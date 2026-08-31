"""Typed, provenance-aware models for pool intelligence."""

from dataclasses import dataclass
from enum import Enum


class PoolProtocol(str, Enum):
    UNKNOWN = "unknown"
    STRATUM_V1 = "stratum_v1"
    STRATUM_V2 = "stratum_v2"


class CapabilityState(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    ERROR = "error"
    AUTH_REQUIRED = "auth_required"


class Provenance(str, Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    USER_PROVIDED = "user_provided"
    API_REPORTED = "api_reported"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PoolEndpoint:
    scheme: str
    host: str
    port: int
    protocol: PoolProtocol
    tls: bool
    normalized_url: str
    provenance: Provenance = Provenance.USER_PROVIDED
