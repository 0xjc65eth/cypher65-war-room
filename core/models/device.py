from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .capability import Capability


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DeviceStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    WARNING = "warning"
    CRITICAL = "critical"
    MAINTENANCE = "maintenance"


# ── Fase 5 · telemetria completa (NOT AVAILABLE explícito) ──────────────
# Campos canônicos que todo device deve expor na telemetria. Quando o
# hardware/firmware não fornece um valor, a serialização preenche com
# NOT_AVAILABLE — a UI nunca adivinha um número.
NOT_AVAILABLE = "NOT AVAILABLE"

TELEMETRY_KEYS = (
    "chip_temp",     # °C temperatura do ASIC/junction
    "vr_temp",       # °C temperatura do voltage regulator
    "temperature",   # °C temperatura da placa
    "hashrate",      # H/s atual
    "hashrate_1m",   # H/s média 1 minuto
    "hashrate_10m",  # H/s média 10 minutos
    "hashrate_1h",   # H/s média 1 hora
    "fan_rpm",
    "voltage",
    "power",
    "pool_status",
)


def normalize_telemetry(telemetry: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Fill missing canonical telemetry keys with the explicit NOT_AVAILABLE
    marker so consumers (API + UI) never see empty/guessed values.

    Returns None when telemetry is None (device offline / no snapshot).
    """
    if telemetry is None:
        return None
    out = dict(telemetry)
    for key in TELEMETRY_KEYS:
        if key not in out or out[key] is None:
            out[key] = NOT_AVAILABLE
    return out


@dataclass
class Device:
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    model: str = ""
    firmware: str = ""
    ip: Optional[str] = None
    hostname: Optional[str] = None
    mac: Optional[str] = None
    status: DeviceStatus = DeviceStatus.OFFLINE
    capabilities: List[Capability] = field(default_factory=list)
    last_seen: Optional[datetime] = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    tenant_id: str = "default"  # Fase 4 · B2: tenant isolation
    current_telemetry: Optional[Dict[str, Any]] = None
    # Health/diagnostic summary (computed on demand; not persisted independently)
    health_score: float = 100.0
    last_diagnostic_at: Optional[int] = None
    active_issues: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "model": self.model,
            "firmware": self.firmware,
            "ip": self.ip,
            "hostname": self.hostname,
            "status": self.status.value,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "metadata": self.metadata,
            "current_telemetry": self.current_telemetry,
            "health_score": self.health_score,
            "last_diagnostic_at": self.last_diagnostic_at,
            "active_issues": list(self.active_issues),
        }

    def has_capability(self, name: str) -> bool:
        return any(c.name == name and c.supported for c in self.capabilities)

    def update_status(self, new_status: DeviceStatus):
        self.status = new_status
        self.updated_at = _utc_now()
