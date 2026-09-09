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
from .dry_run import (
    PoolDryRunError,
    PoolDryRunResult,
    PoolDryRunStage,
    run_pool_dry_run,
)
from .models import CapabilityState, PoolEndpoint, PoolProtocol, Provenance
from .policy import DestinationPolicy, PolicyError, ValidatedDestination
from .resolver import PoolResolution, ResolutionError, resolve_pool_destination
from .rollback import (
    PoolRollbackError,
    PoolRollbackTarget,
    claim_pool_rollback_target,
    load_pool_rollback_target,
    rollback_encryption_ready,
    store_pool_rollback_target,
)
from .rollout import (
    PoolRolloutPlan,
    PoolRolloutState,
    RolloutError,
    RolloutFailure,
    RolloutOutcome,
    RolloutPhase,
    record_pool_rollout_batch,
    start_pool_rollout,
)
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
    StratumV1ResponseError,
    probe_stratum_v1,
    validate_stratum_v1_subscribe_response,
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
    "PoolDryRunError",
    "PoolDryRunResult",
    "PoolDryRunStage",
    "PoolCapabilities",
    "PoolEndpoint",
    "PoolProtocol",
    "PoolResolution",
    "PoolRollbackError",
    "PoolRollbackTarget",
    "PoolRolloutPlan",
    "PoolRolloutState",
    "ProviderFingerprint",
    "ProviderSignal",
    "Provenance",
    "ResolutionError",
    "RolloutError",
    "RolloutFailure",
    "RolloutOutcome",
    "RolloutPhase",
    "SelectionError",
    "StratumV1ProbeError",
    "StratumV1ProbeResult",
    "StratumV1ResponseError",
    "ValidatedDestination",
    "ValidatedPoolConfiguration",
    "build_capability_graph",
    "capability_from_v1_probe",
    "claim_pool_rollback_target",
    "classify_chain",
    "evaluate_pool_compatibility",
    "fingerprint_provider",
    "load_pool_rollback_target",
    "parse_pool_endpoint",
    "probe_stratum_v1",
    "record_pool_rollout_batch",
    "resolve_pool_destination",
    "rollback_encryption_ready",
    "run_pool_dry_run",
    "select_failover_candidate",
    "start_pool_rollout",
    "store_pool_rollback_target",
    "validate_pool_configuration",
    "validate_stratum_v1_subscribe_response",
]
