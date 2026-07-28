"""core/diagnostics/diagnostics_engine.py

Simple diagnostics engine for CYPHER65 devices.
Analyzes a Device's current telemetry and metadata and returns a list of
operational issues (diagnostics).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from core.models.device import Device, DeviceStatus


class DiagnosticSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Diagnostic:
    category: str
    severity: DiagnosticSeverity
    message: str
    timestamp: int
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity.value,
            "message": self.message,
            "timestamp": self.timestamp,
            "details": self.details,
        }


class DiagnosticsEngine:
    """Analyze a device and return a list of operational diagnostics."""

    DEFAULTS = {
        "max_temperature": 85.0,
        "expected_hashrate": None,  # optional override in device metadata
        "hashrate_drop_pct": 20.0,  # flag if current hashrate < expected * (1 - drop)
        "max_reject_rate": 5.0,
        "max_stale_rate": 5.0,
        "max_reconnect_count": 3,
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = dict(self.DEFAULTS)
        if config:
            self.config.update(config)

    def _get_limits(self, device: Device) -> Dict[str, Any]:
        limits = dict(self.config)
        model_defaults = (device.metadata or {}).get("diagnostics_config", {})
        limits.update(model_defaults)
        device_config = (device.metadata or {}).get("safety_config", {})
        limits.update(device_config)
        return limits

    @staticmethod
    def _rate(count: float, total: float) -> float:
        if total and total > 0:
            return (count / total) * 100.0
        return 0.0

    def analyze(self, device: Device) -> List[Diagnostic]:
        diagnostics: List[Diagnostic] = []
        telemetry = device.current_telemetry or {}
        limits = self._get_limits(device)
        now = int(datetime.now(timezone.utc).timestamp())

        # --- Temperature ---------------------------------------------------
        temperature = telemetry.get("temperature")
        max_temp = limits.get("max_temperature")
        if temperature is not None and max_temp is not None:
            if temperature > max_temp:
                diagnostics.append(
                    Diagnostic(
                        category="temperature",
                        severity=DiagnosticSeverity.CRITICAL,
                        message=f"Temperature {temperature}°C exceeds limit {max_temp}°C",
                        timestamp=now,
                        details={"temperature": temperature, "limit": max_temp},
                    )
            )

        # --- Hashrate ------------------------------------------------------
        hashrate = telemetry.get("hashrate")
        expected_hashrate = limits.get("expected_hashrate")
        if expected_hashrate is None and device.metadata:
            expected_hashrate = device.metadata.get("expected_hashrate")
        if hashrate is not None and expected_hashrate:
            drop_pct = limits.get("hashrate_drop_pct", 20.0)
            threshold = float(expected_hashrate) * (1 - drop_pct / 100.0)
            if float(hashrate) < threshold:
                diagnostics.append(
                    Diagnostic(
                        category="hashrate",
                        severity=DiagnosticSeverity.WARNING,
                        message=(
                            f"Hashrate {hashrate} H/s is below threshold "
                            f"{threshold:.0f} H/s (expected {expected_hashrate} H/s, drop {drop_pct}%)"
                        ),
                        timestamp=now,
                        details={
                            "hashrate": hashrate,
                            "expected_hashrate": expected_hashrate,
                            "threshold": threshold,
                            "drop_pct": drop_pct,
                        },
                    )
            )

        # --- Reject / Stale rates ------------------------------------------
        accepted = float(telemetry.get("accepted_shares") or 0)
        rejected = float(telemetry.get("rejected_shares") or 0)
        stale = float(telemetry.get("stale_shares") or 0)
        total = accepted + rejected + stale
        if total > 0:
            reject_rate = self._rate(rejected, total)
            max_reject = limits.get("max_reject_rate", 5.0)
            if reject_rate > max_reject:
                diagnostics.append(
                    Diagnostic(
                        category="shares",
                        severity=DiagnosticSeverity.WARNING,
                        message=f"Reject rate {reject_rate:.1f}% exceeds limit {max_reject}%",
                        timestamp=now,
                        details={
                            "reject_rate": reject_rate,
                            "limit": max_reject,
                            "accepted": accepted,
                            "rejected": rejected,
                        },
                    )
                )

            stale_rate = self._rate(stale, total)
            max_stale = limits.get("max_stale_rate", 5.0)
            if stale_rate > max_stale:
                diagnostics.append(
                    Diagnostic(
                        category="shares",
                        severity=DiagnosticSeverity.WARNING,
                        message=f"Stale rate {stale_rate:.1f}% exceeds limit {max_stale}%",
                        timestamp=now,
                        details={
                            "stale_rate": stale_rate,
                            "limit": max_stale,
                            "accepted": accepted,
                            "stale": stale,
                        },
                    )
                )

        # --- Instability / reconnects ----------------------------------------
        reconnect_count = (device.metadata or {}).get("reconnect_count", 0)
        max_reconnect = limits.get("max_reconnect_count", 3)
        if reconnect_count > max_reconnect:
            diagnostics.append(
                Diagnostic(
                    category="instability",
                    severity=DiagnosticSeverity.WARNING,
                    message=f"Device has {reconnect_count} reconnects (limit {max_reconnect})",
                    timestamp=now,
                    details={
                        "reconnect_count": reconnect_count,
                        "limit": max_reconnect,
                    },
                )
            )

        # --- Offline status ------------------------------------------------
        if device.status == DeviceStatus.OFFLINE:
            diagnostics.append(
                Diagnostic(
                    category="connectivity",
                    severity=DiagnosticSeverity.INFO,
                    message="Device is currently offline",
                    timestamp=now,
                    details={"status": device.status.value},
                )
            )

        return diagnostics
