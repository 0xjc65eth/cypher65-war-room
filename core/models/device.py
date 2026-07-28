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
