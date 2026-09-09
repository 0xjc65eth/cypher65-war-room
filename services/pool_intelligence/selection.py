"""Fail-closed ASIC compatibility and ordered pool failover decisions."""

from dataclasses import dataclass
import re
from typing import Iterable

from .evidence import CapabilityGraph
from .models import CapabilityState

MAX_COMPATIBILITY_REQUIREMENTS = 32
MAX_FAILOVER_CANDIDATES = 16
MAX_FAILOVER_PRIORITY = 255
MAX_COOLDOWN_SECONDS = 86_400

_SAFE_TOKEN = re.compile(r"^[a-z0-9](?:[a-z0-9_.-]{0,62}[a-z0-9])?$")
_STATE_PRECEDENCE = (
    CapabilityState.ERROR,
    CapabilityState.UNSUPPORTED,
    CapabilityState.AUTH_REQUIRED,
    CapabilityState.UNKNOWN,
    CapabilityState.SUPPORTED,
)


class SelectionError(ValueError):
    """Compatibility or failover input is malformed or excessive."""


def _normalize_token(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise SelectionError(f"{label} must be a string")
    normalized = value.strip().lower()
    if not _SAFE_TOKEN.fullmatch(normalized):
        raise SelectionError(f"{label} must be a safe token")
    return normalized


def _collect_bounded(items: Iterable, *, maximum: int, label: str) -> tuple:
    if isinstance(items, (str, bytes)):
        raise SelectionError(f"{label} must be an iterable of typed values")
    try:
        iterator = iter(items)
    except TypeError as exc:
        raise SelectionError(f"{label} must be iterable") from exc
    collected = []
    for item in iterator:
        if len(collected) >= maximum:
            raise SelectionError(f"too many {label}")
        collected.append(item)
    return tuple(collected)


@dataclass(frozen=True)
class DeviceCapabilities:
    """Sanitized capability graph for one device or firmware profile."""

    device_id: str
    graph: CapabilityGraph

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "device_id", _normalize_token(self.device_id, label="device_id")
        )
        if not isinstance(self.graph, CapabilityGraph):
            raise SelectionError("device graph must be a CapabilityGraph")


@dataclass(frozen=True)
class PoolCapabilities:
    """Sanitized capability graph for one pool endpoint profile."""

    pool_id: str
    graph: CapabilityGraph

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "pool_id", _normalize_token(self.pool_id, label="pool_id")
        )
        if not isinstance(self.graph, CapabilityGraph):
            raise SelectionError("pool graph must be a CapabilityGraph")


@dataclass(frozen=True)
class CompatibilityRequirement:
    """Pair of device/pool capabilities required for one behavior."""

    name: str
    device_capability: str
    pool_capability: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _normalize_token(self.name, label="name"))
        object.__setattr__(
            self,
            "device_capability",
            _normalize_token(self.device_capability, label="device_capability"),
        )
        object.__setattr__(
            self,
            "pool_capability",
            _normalize_token(self.pool_capability, label="pool_capability"),
        )


@dataclass(frozen=True)
class CompatibilityCheck:
    requirement: str
    device_state: CapabilityState
    pool_state: CapabilityState
    state: CapabilityState
    reason: str


@dataclass(frozen=True)
class CompatibilityResult:
    device_id: str
    pool_id: str
    state: CapabilityState
    checks: tuple[CompatibilityCheck, ...]


def _combine_capability_states(
    device_state: CapabilityState,
    pool_state: CapabilityState,
) -> tuple[CapabilityState, str]:
    states = {device_state, pool_state}
    if CapabilityState.ERROR in states:
        return CapabilityState.ERROR, "capability_error"
    if CapabilityState.UNSUPPORTED in states:
        return CapabilityState.UNSUPPORTED, "capability_unsupported"
    if CapabilityState.AUTH_REQUIRED in states:
        return CapabilityState.AUTH_REQUIRED, "capability_auth_required"
    if CapabilityState.UNKNOWN in states:
        return CapabilityState.UNKNOWN, "capability_unknown"
    return CapabilityState.SUPPORTED, "compatible"


def evaluate_pool_compatibility(
    device: DeviceCapabilities,
    pool: PoolCapabilities,
    requirements: Iterable[CompatibilityRequirement],
) -> CompatibilityResult:
    """Evaluate only observed/effective capability graph states.

    No model, firmware or provider-name heuristic is accepted by this API.
    Missing graph nodes remain UNKNOWN and therefore never become a positive
    compatibility claim.
    """

    if not isinstance(device, DeviceCapabilities):
        raise SelectionError("device must be a DeviceCapabilities value")
    if not isinstance(pool, PoolCapabilities):
        raise SelectionError("pool must be a PoolCapabilities value")
    collected = _collect_bounded(
        requirements,
        maximum=MAX_COMPATIBILITY_REQUIREMENTS,
        label="compatibility requirements",
    )
    if not collected:
        raise SelectionError("at least one compatibility requirement is required")
    if any(not isinstance(item, CompatibilityRequirement) for item in collected):
        raise SelectionError("compatibility requirements contain an invalid item")
    names = [item.name for item in collected]
    if len(names) != len(set(names)):
        raise SelectionError("compatibility requirement names must be unique")

    checks = []
    for requirement in collected:
        device_node = device.graph.get(requirement.device_capability)
        pool_node = pool.graph.get(requirement.pool_capability)
        device_state = (
            device_node.effective_state
            if device_node is not None
            else CapabilityState.UNKNOWN
        )
        pool_state = (
            pool_node.effective_state
            if pool_node is not None
            else CapabilityState.UNKNOWN
        )
        state, reason = _combine_capability_states(device_state, pool_state)
        checks.append(
            CompatibilityCheck(
                requirement=requirement.name,
                device_state=device_state,
                pool_state=pool_state,
                state=state,
                reason=reason,
            )
        )

    result_state = next(
        state
        for state in _STATE_PRECEDENCE
        if any(check.state is state for check in checks)
    )
    return CompatibilityResult(
        device_id=device.device_id,
        pool_id=pool.pool_id,
        state=result_state,
        checks=tuple(checks),
    )


@dataclass(frozen=True)
class FailoverCandidate:
    """One pre-evaluated pool candidate; it contains no endpoint or secret."""

    pool_id: str
    priority: int
    health_state: CapabilityState
    compatibility: CompatibilityResult
    cooldown_seconds: int = 0

    def __post_init__(self) -> None:
        pool_id = _normalize_token(self.pool_id, label="pool_id")
        object.__setattr__(self, "pool_id", pool_id)
        if (
            isinstance(self.priority, bool)
            or not isinstance(self.priority, int)
            or not 0 <= self.priority <= MAX_FAILOVER_PRIORITY
        ):
            raise SelectionError("priority must be an integer between 0 and 255")
        if not isinstance(self.health_state, CapabilityState):
            raise SelectionError("health_state must be a CapabilityState value")
        if not isinstance(self.compatibility, CompatibilityResult):
            raise SelectionError("compatibility must be a CompatibilityResult")
        if self.compatibility.pool_id != pool_id:
            raise SelectionError("candidate and compatibility pool_id must match")
        if (
            isinstance(self.cooldown_seconds, bool)
            or not isinstance(self.cooldown_seconds, int)
            or not 0 <= self.cooldown_seconds <= MAX_COOLDOWN_SECONDS
        ):
            raise SelectionError("cooldown must be an integer between 0 and 86400")


@dataclass(frozen=True)
class FailoverSkip:
    pool_id: str
    reason: str


@dataclass(frozen=True)
class FailoverDecision:
    selected_pool_id: str | None
    changed: bool
    reason: str
    skipped: tuple[FailoverSkip, ...]


def _ineligible_reason(candidate: FailoverCandidate) -> str | None:
    if candidate.cooldown_seconds:
        return "cooldown_active"
    if candidate.health_state is not CapabilityState.SUPPORTED:
        return f"health_{candidate.health_state.value}"
    if candidate.compatibility.state is not CapabilityState.SUPPORTED:
        return f"compatibility_{candidate.compatibility.state.value}"
    return None


def select_failover_candidate(
    candidates: Iterable[FailoverCandidate],
    *,
    active_pool_id: str | None = None,
) -> FailoverDecision:
    """Keep an eligible active pool or select the lowest numeric priority.

    This function does not retry, sleep, resolve DNS or mutate a device. The
    caller must run probes and compatibility evaluation before invoking it.
    Equal priorities preserve caller order for deterministic behavior.
    """

    collected = _collect_bounded(
        candidates,
        maximum=MAX_FAILOVER_CANDIDATES,
        label="failover candidates",
    )
    if any(not isinstance(item, FailoverCandidate) for item in collected):
        raise SelectionError("failover candidates contain an invalid item")
    pool_ids = [candidate.pool_id for candidate in collected]
    if len(pool_ids) != len(set(pool_ids)):
        raise SelectionError("failover candidate pool_ids must be unique")

    active = None
    if active_pool_id is not None:
        active = _normalize_token(active_pool_id, label="active_pool_id")
        if active not in pool_ids:
            raise SelectionError("active pool must be present in candidates")

    reasons = {
        candidate.pool_id: _ineligible_reason(candidate) for candidate in collected
    }
    skipped = tuple(
        FailoverSkip(candidate.pool_id, reasons[candidate.pool_id])
        for candidate in collected
        if reasons[candidate.pool_id] is not None
    )

    if active is not None and reasons[active] is None:
        return FailoverDecision(active, False, "active_eligible", skipped)

    eligible = [
        (candidate.priority, index, candidate)
        for index, candidate in enumerate(collected)
        if reasons[candidate.pool_id] is None
    ]
    if not eligible:
        return FailoverDecision(None, False, "no_eligible_candidate", skipped)
    selected = min(eligible, key=lambda item: (item[0], item[1]))[2]
    if active is None:
        return FailoverDecision(selected.pool_id, False, "initial_selection", skipped)
    return FailoverDecision(selected.pool_id, True, "failover_selected", skipped)
