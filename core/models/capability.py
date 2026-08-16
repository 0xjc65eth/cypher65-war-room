from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Capability:
    name: str
    supported: bool
    requires_confirmation: bool = False
    risk_level: RiskLevel = RiskLevel.LOW
    constraints: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "supported": self.supported,
            "requires_confirmation": self.requires_confirmation,
            "risk_level": self.risk_level.value,
            "constraints": self.constraints,
        }


# Common capabilities used across devices
COMMON_CAPABILITIES = [
    "telemetry",
    "restart",
    "identify",
    "logs",
    "config_read",
]
