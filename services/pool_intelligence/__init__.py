"""Security-first primitives for SHA-256 mining-pool discovery.

Network access is limited to explicit resolver and probe stages. Connectors
consume validated numeric destinations and never resolve a hostname again.
"""

from .endpoint import EndpointError, parse_pool_endpoint
from .evidence import (
    CapabilityAssertion,
    CapabilityGraph,
    CapabilityNode,
    ChainClassification,
    ChainSignal,
    EvidenceError,
    ProviderFingerprint,
    ProviderSignal,
    build_capability_graph,
    capability_from_v1_probe,
    classify_chain,
    fingerprint_provider,
)
from .configuration import (
    PoolConfigurationError,
    ValidatedPoolConfiguration,
    validate_pool_configuration,
)
from .models import CapabilityState, PoolEndpoint, PoolProtocol, Provenance
from .policy import DestinationPolicy, PolicyError, ValidatedDestination
from .resolver import PoolResolution, ResolutionError, resolve_pool_destination
from .selection import (
    CompatibilityCheck,
    CompatibilityRequirement,
    CompatibilityResult,
    DeviceCapabilities,
    FailoverCandidate,
    FailoverDecision,
    FailoverSkip,
    PoolCapabilities,
    SelectionError,
    evaluate_pool_compatibility,
    select_failover_candidate,
)
from .stratum_v1 import (
    StratumV1ProbeError,
    StratumV1ProbeResult,
    probe_stratum_v1,
)

__all__ = [
    "CapabilityAssertion",
    "CapabilityGraph",
    "CapabilityNode",
    "CapabilityState",
    "ChainClassification",
    "ChainSignal",
    "CompatibilityCheck",
    "CompatibilityRequirement",
    "CompatibilityResult",
    "DeviceCapabilities",
    "DestinationPolicy",
    "EndpointError",
    "EvidenceError",
    "FailoverCandidate",
    "FailoverDecision",
    "FailoverSkip",
    "PolicyError",
    "PoolConfigurationError",
    "PoolCapabilities",
    "PoolEndpoint",
    "PoolProtocol",
    "PoolResolution",
    "ProviderFingerprint",
    "ProviderSignal",
    "Provenance",
    "ResolutionError",
    "SelectionError",
    "StratumV1ProbeError",
    "StratumV1ProbeResult",
    "ValidatedDestination",
    "ValidatedPoolConfiguration",
    "build_capability_graph",
    "capability_from_v1_probe",
    "classify_chain",
    "evaluate_pool_compatibility",
    "fingerprint_provider",
    "parse_pool_endpoint",
    "probe_stratum_v1",
    "resolve_pool_destination",
    "select_failover_candidate",
    "validate_pool_configuration",
]
