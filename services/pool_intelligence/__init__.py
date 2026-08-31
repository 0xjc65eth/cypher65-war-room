"""Security-first primitives for SHA-256 mining-pool discovery.

This package intentionally performs no network I/O.  Endpoint resolution and
protocol probes are later stages and must consume a validated policy result.
"""

from .endpoint import EndpointError, parse_pool_endpoint
from .models import CapabilityState, PoolEndpoint, PoolProtocol, Provenance
from .policy import DestinationPolicy, PolicyError, ValidatedDestination

__all__ = [
    "CapabilityState",
    "DestinationPolicy",
    "EndpointError",
    "PolicyError",
    "PoolEndpoint",
    "PoolProtocol",
    "Provenance",
    "ValidatedDestination",
    "parse_pool_endpoint",
]
