from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from core.models.device import Device, DeviceStatus
from core.models.capability import RiskLevel


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
        "max_reject_rate": 5.0,       # %
        "max_stale_rate": 5.0,        # %
        "max_hw_error_rate": 2.0,     # %
        "restart_cooldown_minutes": 5,
    }

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

    def _check_telemetry(self, device: Device, limits: dict) -> List[str]:
        violations = []
        telemetry = device.current_telemetry
        if not telemetry:
            return violations

        temp = telemetry.get("temperature")
        if temp is not None:
            max_temp = limits.get("max_temperature")
            if max_temp is not None and temp > max_temp:
                violations.append(f"Temperature too high: {temp}C (limit {max_temp}C)")

        hashrate = telemetry.get("hashrate")
        min_hashrate = limits.get("min_hashrate")
        if hashrate is not None and min_hashrate is not None and hashrate <= min_hashrate:
            violations.append(f"Hashrate too low: {hashrate} (limit > {min_hashrate})")

        accepted = float(telemetry.get("accepted_shares") or 0)
        rejected = float(telemetry.get("rejected_shares") or 0)
        stale = float(telemetry.get("stale_shares") or 0)
        total = accepted + rejected + stale

        if total > 0:
            reject_rate = self._rate(rejected, total)
            max_reject = limits.get("max_reject_rate")
            if max_reject is not None and reject_rate > max_reject:
                violations.append(f"Reject rate too high: {reject_rate:.1f}% (limit {max_reject}%)")

            stale_rate = self._rate(stale, total)
            max_stale = limits.get("max_stale_rate")
            if max_stale is not None and stale_rate > max_stale:
                violations.append(f"Stale rate too high: {stale_rate:.1f}% (limit {max_stale}%)")

        return violations

    def _check_cooldown(self, device: Device, limits: dict) -> List[str]:
        violations = []
        last_restart = self._last_restarts.get(device.id)
        cooldown_min = limits.get("restart_cooldown_minutes")
        if last_restart and cooldown_min is not None:
            elapsed = (datetime.now(timezone.utc) - last_restart).total_seconds() / 60.0
            if elapsed < cooldown_min:
                remaining = cooldown_min - elapsed
                violations.append(f"Restart cooldown active: {remaining:.0f} minutes remaining")
        return violations

    def validate_command(self, device: Device, command: str, parameters: Optional[dict] = None) -> SafetyResult:
        """
        Valida se um comando pode ser executado com seguranca.
        """
        violations = []
        limits = self._get_limits(device)

        if device.status == DeviceStatus.OFFLINE:
            violations.append("Device is offline")

        if command == "restart":
            violations.extend(self._check_cooldown(device, limits))

        if command in ("restart", "identify"):
            violations.extend(self._check_telemetry(device, limits))

        if violations:
            return SafetyResult(
                allowed=False,
                reason="; ".join(violations),
                risk_level=RiskLevel.HIGH,
                requires_confirmation=True,
                violations=violations,
            )

        return SafetyResult(allowed=True)

    def record_restart(self, device: Device):
        """Register that a restart was just executed for cooldown tracking."""
        self._last_restarts[device.id] = datetime.now(timezone.utc)
