"""Security-first primitives for SHA-256 mining-pool discovery.

Network access is limited to explicit resolver and probe stages. Connectors
consume validated numeric destinations and never resolve a hostname again.
"""

from .endpoint import EndpointError, parse_pool_endpoint
from .configuration import (
    PoolConfigurationError,
    ValidatedPoolConfiguration,
    validate_pool_configuration,
)
from .models import CapabilityState, PoolEndpoint, PoolProtocol, Provenance
from .policy import DestinationPolicy, PolicyError, ValidatedDestination
from .resolver import PoolResolution, ResolutionError, resolve_pool_destination
from .stratum_v1 import (
    StratumV1ProbeError,
    StratumV1ProbeResult,
    probe_stratum_v1,
)

__all__ = [
    "CapabilityState",
    "DestinationPolicy",
    "EndpointError",
    "PolicyError",
    "PoolConfigurationError",
    "PoolEndpoint",
    "PoolProtocol",
    "PoolResolution",
    "Provenance",
    "ResolutionError",
    "StratumV1ProbeError",
    "StratumV1ProbeResult",
    "ValidatedDestination",
    "ValidatedPoolConfiguration",
    "parse_pool_endpoint",
    "probe_stratum_v1",
    "resolve_pool_destination",
    "validate_pool_configuration",
]
