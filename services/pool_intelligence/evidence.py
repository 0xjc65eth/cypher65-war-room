"""Conservative, provenance-aware evidence aggregation for pool intelligence."""

from collections import defaultdict
from dataclasses import dataclass
import re
from typing import Iterable

from .models import CapabilityState, PoolProtocol, Provenance
from .stratum_v1 import StratumV1ProbeResult

MAX_CAPABILITY_ASSERTIONS = 128
MAX_CAPABILITY_DEPENDENCIES = 16
MAX_CAPABILITY_NODES = 256
MAX_IDENTITY_SIGNALS = 64
MIN_IDENTITY_CONFIDENCE_BPS = 8_000

_SAFE_TOKEN = re.compile(r"^[a-z0-9](?:[a-z0-9_.-]{0,62}[a-z0-9])?$")
_TRUSTED_PROVENANCE = frozenset({Provenance.OBSERVED, Provenance.API_REPORTED})


class EvidenceError(ValueError):
    """Evidence is malformed, excessive or internally inconsistent."""


def _normalize_token(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise EvidenceError(f"{label} must be a string")
    normalized = value.strip().lower()
    if not _SAFE_TOKEN.fullmatch(normalized):
        raise EvidenceError(f"{label} must be a safe token")
    return normalized


def _validate_provenance(value: Provenance) -> None:
    if not isinstance(value, Provenance):
        raise EvidenceError("provenance must be a Provenance value")


@dataclass(frozen=True)
class CapabilityAssertion:
    """One sanitized assertion about a capability and its prerequisites."""

    name: str
    state: CapabilityState
    provenance: Provenance
    source: str
    requires: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        name = _normalize_token(self.name, label="capability")
        source = _normalize_token(self.source, label="source")
        if not isinstance(self.state, CapabilityState):
            raise EvidenceError("state must be a CapabilityState value")
        _validate_provenance(self.provenance)
        if not isinstance(self.requires, tuple):
            raise EvidenceError("capability requirements must be a tuple")
        if len(self.requires) > MAX_CAPABILITY_DEPENDENCIES:
            raise EvidenceError("too many capability requirements")
        requirements = tuple(
            sorted(
                {
                    _normalize_token(requirement, label="capability requirement")
                    for requirement in self.requires
                }
            )
        )
        if name in requirements:
            raise EvidenceError("capability cannot require itself")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "requires", requirements)


@dataclass(frozen=True)
class CapabilityNode:
    """Resolved immutable node in the capability dependency graph."""

    name: str
    observed_state: CapabilityState
    effective_state: CapabilityState
    provenances: tuple[Provenance, ...]
    sources: tuple[str, ...]
    requires: tuple[str, ...]
    blocked_by: tuple[str, ...]


@dataclass(frozen=True)
class CapabilityGraph:
    """Immutable capability graph with deterministic lookup."""

    nodes: tuple[CapabilityNode, ...]

    def get(self, name: str) -> CapabilityNode | None:
        normalized = _normalize_token(name, label="capability")
        return next((node for node in self.nodes if node.name == normalized), None)


def _collect_bounded(items: Iterable, *, maximum: int, label: str) -> tuple:
    if isinstance(items, (str, bytes)):
        raise EvidenceError(f"{label} must be an iterable of evidence objects")
    collected = []
    try:
        iterator = iter(items)
    except TypeError as exc:
        raise EvidenceError(f"{label} must be iterable") from exc
    for item in iterator:
        if len(collected) >= maximum:
            raise EvidenceError(f"too many {label}")
        collected.append(item)
    return tuple(collected)


def _resolve_observed_state(
    assertions: tuple[CapabilityAssertion, ...],
) -> CapabilityState:
    states = {
        assertion.state
        for assertion in assertions
        if assertion.provenance in _TRUSTED_PROVENANCE
        and assertion.state is not CapabilityState.UNKNOWN
    }
    if not states:
        return CapabilityState.UNKNOWN
    if len(states) > 1:
        return CapabilityState.ERROR
    return next(iter(states))


def build_capability_graph(
    assertions: Iterable[CapabilityAssertion],
) -> CapabilityGraph:
    """Resolve bounded assertions and fail closed on conflicts or cycles.

    User-provided and inferred assertions remain visible as provenance but do
    not establish an observed state. Missing dependencies become explicit
    UNKNOWN nodes instead of disappearing from the graph.
    """

    collected = _collect_bounded(
        assertions,
        maximum=MAX_CAPABILITY_ASSERTIONS,
        label="capability assertions",
    )
    if any(not isinstance(item, CapabilityAssertion) for item in collected):
        raise EvidenceError("capability assertions contain an invalid item")

    grouped: dict[str, list[CapabilityAssertion]] = defaultdict(list)
    requirements: dict[str, set[str]] = defaultdict(set)
    for assertion in collected:
        grouped[assertion.name].append(assertion)
        if assertion.provenance in _TRUSTED_PROVENANCE:
            requirements[assertion.name].update(assertion.requires)
    required_names = {
        name for dependency_set in requirements.values() for name in dependency_set
    }
    if len(set(grouped) | required_names) > MAX_CAPABILITY_NODES:
        raise EvidenceError("too many capability nodes")
    for required_name in required_names:
        grouped.setdefault(required_name, [])
        requirements.setdefault(required_name, set())

    observed = {
        name: _resolve_observed_state(tuple(items)) for name, items in grouped.items()
    }
    visiting: set[str] = set()
    effective: dict[str, CapabilityState] = {}
    blocked: dict[str, tuple[str, ...]] = {}

    def resolve(name: str) -> CapabilityState:
        if name in effective:
            return effective[name]
        if name in visiting:
            raise EvidenceError("capability graph contains a dependency cycle")
        visiting.add(name)
        dependency_states = {
            dependency: resolve(dependency) for dependency in sorted(requirements[name])
        }
        visiting.remove(name)

        direct_state = observed[name]
        blocked_names = tuple(
            dependency
            for dependency, state in dependency_states.items()
            if state is not CapabilityState.SUPPORTED
        )
        state = direct_state
        if direct_state is CapabilityState.SUPPORTED and blocked_names:
            states = {dependency_states[dependency] for dependency in blocked_names}
            if CapabilityState.ERROR in states or CapabilityState.UNSUPPORTED in states:
                state = CapabilityState.ERROR
            elif CapabilityState.AUTH_REQUIRED in states:
                state = CapabilityState.AUTH_REQUIRED
            else:
                state = CapabilityState.UNKNOWN
        effective[name] = state
        blocked[name] = blocked_names
        return state

    for capability_name in sorted(grouped):
        resolve(capability_name)

    nodes = []
    for name in sorted(grouped):
        items = grouped[name]
        nodes.append(
            CapabilityNode(
                name=name,
                observed_state=observed[name],
                effective_state=effective[name],
                provenances=tuple(
                    sorted(
                        {item.provenance for item in items}, key=lambda item: item.value
                    )
                ),
                sources=tuple(sorted({item.source for item in items})),
                requires=tuple(sorted(requirements[name])),
                blocked_by=blocked[name],
            )
        )
    return CapabilityGraph(nodes=tuple(nodes))


def capability_from_v1_probe(result: StratumV1ProbeResult) -> CapabilityAssertion:
    """Convert a sanitized V1 result into one observed capability assertion."""

    if not isinstance(result, StratumV1ProbeResult):
        raise EvidenceError("result must be a StratumV1ProbeResult")
    state = CapabilityState.ERROR
    if (
        result.healthy
        and result.protocol is PoolProtocol.STRATUM_V1
        and result.capability is CapabilityState.SUPPORTED
    ):
        state = CapabilityState.SUPPORTED
    return CapabilityAssertion(
        name="protocol.stratum_v1.subscribe",
        state=state,
        provenance=Provenance.OBSERVED,
        source="stratum_v1_probe",
    )


def _validate_confidence(value: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= 10_000
    ):
        raise EvidenceError("confidence_bps must be an integer between 0 and 10000")


@dataclass(frozen=True)
class ProviderSignal:
    provider: str
    feature: str
    confidence_bps: int
    provenance: Provenance
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider", _normalize_token(self.provider, label="provider")
        )
        object.__setattr__(
            self, "feature", _normalize_token(self.feature, label="feature")
        )
        object.__setattr__(
            self, "source", _normalize_token(self.source, label="source")
        )
        _validate_confidence(self.confidence_bps)
        _validate_provenance(self.provenance)


@dataclass(frozen=True)
class ChainSignal:
    chain: str
    feature: str
    confidence_bps: int
    provenance: Provenance
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "chain", _normalize_token(self.chain, label="chain"))
        object.__setattr__(
            self, "feature", _normalize_token(self.feature, label="feature")
        )
        object.__setattr__(
            self, "source", _normalize_token(self.source, label="source")
        )
        _validate_confidence(self.confidence_bps)
        _validate_provenance(self.provenance)


@dataclass(frozen=True)
class ProviderFingerprint:
    provider: str | None
    confidence_bps: int
    evidence_count: int
    conflicted: bool
    reason: str


@dataclass(frozen=True)
class ChainClassification:
    chain: str | None
    confidence_bps: int
    evidence_count: int
    conflicted: bool
    reason: str


def _classify_identity(signals: Iterable, *, candidate_field: str) -> tuple:
    collected = _collect_bounded(
        signals,
        maximum=MAX_IDENTITY_SIGNALS,
        label="identity signals",
    )
    expected_type = ProviderSignal if candidate_field == "provider" else ChainSignal
    if any(not isinstance(item, expected_type) for item in collected):
        raise EvidenceError("identity signals contain an invalid item")

    by_candidate: dict[str, dict[tuple[str, str], int]] = defaultdict(dict)
    for signal in collected:
        if signal.provenance not in _TRUSTED_PROVENANCE:
            continue
        candidate = getattr(signal, candidate_field)
        key = (signal.source, signal.feature)
        by_candidate[candidate][key] = max(
            signal.confidence_bps,
            by_candidate[candidate].get(key, 0),
        )

    decisive_sources: dict[str, dict[str, int]] = {}
    for candidate, evidence in by_candidate.items():
        sources: dict[str, int] = {}
        for (source, _feature), confidence in evidence.items():
            if confidence >= MIN_IDENTITY_CONFIDENCE_BPS:
                sources[source] = max(confidence, sources.get(source, 0))
        if sources:
            decisive_sources[candidate] = sources

    if len(decisive_sources) > 1:
        return (
            None,
            0,
            sum(len(items) for items in by_candidate.values()),
            True,
            ("conflicting_evidence"),
        )
    if not decisive_sources:
        return (
            None,
            0,
            sum(len(items) for items in by_candidate.values()),
            False,
            "insufficient_evidence",
        )

    candidate, sources = next(iter(decisive_sources.items()))
    if len(sources) < 2:
        return None, 0, len(by_candidate[candidate]), False, "insufficient_evidence"
    strongest = sorted(sources.values(), reverse=True)
    confidence = min(strongest[:2])
    return candidate, confidence, len(by_candidate[candidate]), False, "identified"


def fingerprint_provider(signals: Iterable[ProviderSignal]) -> ProviderFingerprint:
    """Identify a provider only with two independent, trusted strong signals."""

    provider, confidence, count, conflicted, reason = _classify_identity(
        signals, candidate_field="provider"
    )
    return ProviderFingerprint(provider, confidence, count, conflicted, reason)


def classify_chain(signals: Iterable[ChainSignal]) -> ChainClassification:
    """Classify a chain without accepting endpoint or provider heuristics."""

    chain, confidence, count, conflicted, reason = _classify_identity(
        signals, candidate_field="chain"
    )
    return ChainClassification(chain, confidence, count, conflicted, reason)
