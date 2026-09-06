import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from core.models.device import Device, DeviceStatus
from core.models.capability import RiskLevel

log = logging.getLogger("cypher65.safety")


@dataclass
class SafetyResult:
    allowed: bool
    reason: Optional[str] = None
    risk_level: RiskLevel = RiskLevel.LOW
    requires_confirmation: bool = False
    violations: List[str] = field(default_factory=list)


class SafetyEngine:
    """
    Motor de seguranza do CYPHER65.
    Toda acao que modifica estado do device deve passar por aqui.

    Configuracao em camadas (ordem de prioridade):
      1. Padroes globais
      2. Padroes por modelo (model_defaults)
      3. Overrides por device (device.metadata["safety_config"])
    """

    DEFAULTS = {
        "max_temperature": 85.0,
        "min_hashrate": 0.0,
        "max_reject_rate": 5.0,  # %
        "max_stale_rate": 5.0,  # %
        "max_hw_error_rate": 2.0,  # %
        "restart_cooldown_minutes": 5,
    }

    # Safety approval and operator approval are distinct gates.  A healthy
    # device can be technically safe to change while the action still changes
    # its operating state, pool, or frequency and therefore needs an explicit
    # human confirmation in the request controller.
    COMMAND_RISKS = {
        "restart": RiskLevel.MEDIUM,
        "pause": RiskLevel.MEDIUM,
        "resume": RiskLevel.MEDIUM,
        "set_frequency": RiskLevel.HIGH,
        "update_pool": RiskLevel.HIGH,
        "configure": RiskLevel.HIGH,
    }

    # pause is a thermal escape hatch: it must remain available when the
    # miner is already too hot. HIGH mutations still require a fresh sample.
    TELEMETRY_CHECKED_COMMANDS = frozenset(
        {"restart", "identify", "set_frequency", "update_pool", "configure"}
    )
    TELEMETRY_REQUIRED_COMMANDS = frozenset(
        {"set_frequency", "update_pool", "configure"}
    )

    def __init__(self, config: Optional[dict] = None):
        self.config = dict(self.DEFAULTS)
        if config:
            self.config.update(config)
        self._model_defaults: Dict[str, dict] = self.config.get("model_defaults", {})
        self._last_restarts: Dict[str, datetime] = {}

    def _get_limits(self, device: Device) -> dict:
        """Merge global defaults, model defaults, and per-device overrides."""
        limits = dict(self.DEFAULTS)
        limits.update(self.config)

        model = (device.model or "").lower()
        if model in self._model_defaults:
            limits.update(self._model_defaults[model])

        device_config = (device.metadata or {}).get("safety_config", {})
        limits.update(device_config)
        return limits

    @staticmethod
    def _rate(count: float, total: float) -> float:
        """Calculate percentage rate safely."""
        if total and total > 0:
            return (count / total) * 100.0
        return 0.0

    @staticmethod
    def _finite_float(value) -> Optional[float]:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number != number or number in (float("inf"), float("-inf")):
            return None
        return number

    @staticmethod
    def _resolve_hashrate(telemetry: dict) -> Optional[float]:
        """Prefer canonical `hashrate`; fall back to fleet `hashrate_hs`."""
        for key in ("hashrate", "hashrate_hs"):
            resolved = SafetyEngine._finite_float(telemetry.get(key))
            if resolved is not None:
                return resolved
        return None

    def _check_telemetry(self, device: Device, limits: dict) -> List[str]:
        violations = []
        telemetry = device.current_telemetry
        if not telemetry:
            return violations

        temp = self._finite_float(telemetry.get("temperature"))
        if temp is None:
            temp = self._finite_float(telemetry.get("temp_asic"))
        if temp is not None:
            max_temp = limits.get("max_temperature")
            if max_temp is not None and temp > max_temp:
                violations.append(f"Temperature too high: {temp}C (limit {max_temp}C)")

        hashrate = self._resolve_hashrate(telemetry)
        min_hashrate = self._finite_float(limits.get("min_hashrate"))
        # Default min_hashrate 0.0 means "no floor": an idle miner at 0 H/s
        # must still be restartable. A configured floor > 0 is a real gate.
        if (
            hashrate is not None
            and min_hashrate is not None
            and min_hashrate > 0
            and hashrate <= min_hashrate
        ):
            violations.append(f"Hashrate too low: {hashrate} (limit > {min_hashrate})")

        accepted = float(
            telemetry.get("accepted_shares") or telemetry.get("shares_accepted") or 0
        )
        rejected = float(
            telemetry.get("rejected_shares") or telemetry.get("shares_rejected") or 0
        )
        stale = float(
            telemetry.get("stale_shares") or telemetry.get("shares_stale") or 0
        )
        total = accepted + rejected + stale

        if total > 0:
            reject_rate = self._rate(rejected, total)
            max_reject = limits.get("max_reject_rate")
            if max_reject is not None and reject_rate > max_reject:
                violations.append(
                    f"Reject rate too high: {reject_rate:.1f}% (limit {max_reject}%)"
                )

            stale_rate = self._rate(stale, total)
            max_stale = limits.get("max_stale_rate")
            if max_stale is not None and stale_rate > max_stale:
                violations.append(
                    f"Stale rate too high: {stale_rate:.1f}% (limit {max_stale}%)"
                )

        hw_pct = self._finite_float(
            telemetry.get("hw_error_pct") or telemetry.get("hw_error_rate")
        )
        max_hw = self._finite_float(limits.get("max_hw_error_rate"))
        if hw_pct is not None and max_hw is not None and hw_pct > max_hw:
            violations.append(
                f"HW error rate too high: {hw_pct:.1f}% (limit {max_hw}%)"
            )

        return violations

    @staticmethod
    def _db_path() -> str:
        return os.environ.get("DB_PATH", "data/war_room.sqlite")

    def _load_last_restart(self, device_id: str) -> Optional[datetime]:
        cached = self._last_restarts.get(device_id)
        if cached is not None:
            return cached
        try:
            conn = sqlite3.connect(self._db_path(), timeout=3)
            try:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS restart_cooldowns (
                        device_id TEXT PRIMARY KEY,
                        last_restart_at INTEGER NOT NULL
                    )"""
                )
                row = conn.execute(
                    "SELECT last_restart_at FROM restart_cooldowns WHERE device_id=?",
                    (device_id,),
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            log.warning("[safety] cooldown load failed for %s: %s", device_id, exc)
            return None
        if not row:
            return None
        loaded = datetime.fromtimestamp(int(row[0]), tz=timezone.utc)
        self._last_restarts[device_id] = loaded
        return loaded

    def _persist_last_restart(self, device_id: str, when: datetime) -> None:
        epoch = int(when.timestamp())
        try:
            conn = sqlite3.connect(self._db_path(), timeout=3)
            try:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS restart_cooldowns (
                        device_id TEXT PRIMARY KEY,
                        last_restart_at INTEGER NOT NULL
                    )"""
                )
                conn.execute(
                    """INSERT INTO restart_cooldowns (device_id, last_restart_at)
                       VALUES (?, ?)
                       ON CONFLICT(device_id) DO UPDATE SET last_restart_at=excluded.last_restart_at""",
                    (device_id, epoch),
                )
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            log.warning("[safety] cooldown persist failed for %s: %s", device_id, exc)

    def _check_cooldown(self, device: Device, limits: dict) -> List[str]:
        violations = []
        last_restart = self._load_last_restart(device.id)
        cooldown_min = limits.get("restart_cooldown_minutes")
        if last_restart and cooldown_min is not None:
            elapsed = (datetime.now(timezone.utc) - last_restart).total_seconds() / 60.0
            if elapsed < cooldown_min:
                remaining = cooldown_min - elapsed
                violations.append(
                    f"Restart cooldown active: {remaining:.0f} minutes remaining"
                )
        return violations

    def validate_command(
        self, device: Device, command: str, parameters: Optional[dict] = None
    ) -> SafetyResult:
        """
        Valida se um comando pode ser executado com seguranca.
        """
        command_key = str(command or "").strip().lower()
        violations = []
        limits = self._get_limits(device)

        if device.status == DeviceStatus.OFFLINE:
            violations.append("Device is offline")

        if command_key == "restart":
            violations.extend(self._check_cooldown(device, limits))

        if (
            command_key in self.TELEMETRY_REQUIRED_COMMANDS
            and not device.current_telemetry
        ):
            violations.append("Telemetry unavailable for high-risk command")
        elif command_key in self.TELEMETRY_CHECKED_COMMANDS:
            violations.extend(self._check_telemetry(device, limits))

        if violations:
            return SafetyResult(
                allowed=False,
                reason="; ".join(violations),
                risk_level=RiskLevel.HIGH,
                requires_confirmation=True,
                violations=violations,
            )

        risk_level = self.COMMAND_RISKS.get(command_key, RiskLevel.LOW)
        return SafetyResult(
            allowed=True,
            risk_level=risk_level,
            requires_confirmation=command_key in self.COMMAND_RISKS,
        )

    def record_restart(self, device: Device):
        """Register that a restart was just executed for cooldown tracking."""
        when = datetime.now(timezone.utc)
        self._last_restarts[device.id] = when
        self._persist_last_restart(device.id, when)
