"""Pure fail-closed state machine for canary pool rollouts."""

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable, Mapping


MAX_ROLLOUT_DEVICES = 1_000
MAX_CANARY_DEVICES = 10
MAX_BATCH_DEVICES = 100

_SAFE_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.:-]{0,126}[A-Za-z0-9])?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RolloutError(ValueError):
    """A rollout plan, observation or transition is unsafe or malformed."""


class RolloutPhase(str, Enum):
    CANARY = "canary"
    BATCH = "batch"
    COMPLETE = "complete"
    HALTED = "halted"


class RolloutOutcome(str, Enum):
    CONFIRMED = "confirmed"
    FAILED = "failed"
    UNKNOWN = "unknown"


def _safe_id(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise RolloutError(f"{label} must be a string")
    if value != value.strip() or not _SAFE_ID.fullmatch(value):
        raise RolloutError(f"{label} must be a safe identifier")
    return value


def _bounded_devices(devices: Iterable[str]) -> tuple[str, ...]:
    if isinstance(devices, (str, bytes)):
        raise RolloutError("devices must be an iterable of identifiers")
    try:
        iterator = iter(devices)
    except TypeError as exc:
        raise RolloutError("devices must be iterable") from exc
    collected = []
    for device_id in iterator:
        if len(collected) >= MAX_ROLLOUT_DEVICES:
            raise RolloutError("rollout exceeds 1000 devices")
        collected.append(_safe_id(device_id, label="device_id"))
    if not collected:
        raise RolloutError("rollout requires at least one device")
    if len(collected) != len(set(collected)):
        raise RolloutError("rollout device identifiers must be unique")
    return tuple(collected)


def _bounded_size(value: int, *, label: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RolloutError(f"{label} must be an integer")
    if not 1 <= value <= maximum:
        raise RolloutError(f"{label} must be between 1 and {maximum}")
    return value


@dataclass(frozen=True)
class PoolRolloutPlan:
    """Sanitized rollout inputs with no endpoint, worker or credential."""

    rollout_id: str
    configuration_hash: str
    devices: tuple[str, ...]
    canary_size: int
    batch_size: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "rollout_id", _safe_id(self.rollout_id, label="rollout_id")
        )
        if not isinstance(self.configuration_hash, str):
            raise RolloutError("configuration_hash must be a string")
        configuration_hash = self.configuration_hash.lower()
        if not _SHA256.fullmatch(configuration_hash):
            raise RolloutError("configuration_hash must be a SHA-256 digest")
        object.__setattr__(self, "configuration_hash", configuration_hash)
        devices = _bounded_devices(self.devices)
        object.__setattr__(self, "devices", devices)
        canary_size = _bounded_size(
            self.canary_size,
            label="canary_size",
            maximum=MAX_CANARY_DEVICES,
        )
        if canary_size > len(devices):
            raise RolloutError("canary_size cannot exceed the device count")
        object.__setattr__(self, "canary_size", canary_size)
        object.__setattr__(
            self,
            "batch_size",
            _bounded_size(
                self.batch_size,
                label="batch_size",
                maximum=MAX_BATCH_DEVICES,
            ),
        )


@dataclass(frozen=True)
class RolloutFailure:
    device_id: str
    outcome: RolloutOutcome

    def __post_init__(self) -> None:
        _safe_id(self.device_id, label="device_id")
        if (
            not isinstance(self.outcome, RolloutOutcome)
            or self.outcome is RolloutOutcome.CONFIRMED
        ):
            raise RolloutError("failure outcome must be failed or unknown")


@dataclass(frozen=True)
class PoolRolloutState:
    """One immutable decision state; it grants no execution permission."""

    plan: PoolRolloutPlan
    phase: RolloutPhase
    active_batch: tuple[str, ...]
    confirmed_devices: tuple[str, ...]
    failures: tuple[RolloutFailure, ...]
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.plan, PoolRolloutPlan):
            raise RolloutError("state plan must be a PoolRolloutPlan")
        if not isinstance(self.phase, RolloutPhase):
            raise RolloutError("state phase must be a RolloutPhase")
        if not all(
            isinstance(items, tuple)
            for items in (self.active_batch, self.confirmed_devices, self.failures)
        ) or (
            len(self.active_batch) > MAX_BATCH_DEVICES
            or len(self.confirmed_devices) > MAX_ROLLOUT_DEVICES
            or len(self.failures) > MAX_BATCH_DEVICES
        ):
            raise RolloutError("state collections must be tuples")
        known = set(self.plan.devices)
        active = set(self.active_batch)
        confirmed = set(self.confirmed_devices)
        if (
            len(active) != len(self.active_batch)
            or len(confirmed) != len(self.confirmed_devices)
            or not (active | confirmed) <= known
            or active & confirmed
        ):
            raise RolloutError("state device sets are inconsistent")
        if any(not isinstance(item, RolloutFailure) for item in self.failures):
            raise RolloutError("state failures contain an invalid item")
        failed_ids = {item.device_id for item in self.failures}
        if (
            len(failed_ids) != len(self.failures)
            or not failed_ids <= known
            or failed_ids & active
            or failed_ids & confirmed
        ):
            raise RolloutError("state failure sets are inconsistent")
        if self.phase is RolloutPhase.CANARY:
            if (
                self.active_batch != self.plan.devices[: self.plan.canary_size]
                or self.confirmed_devices
                or self.failures
                or self.reason != "awaiting_canary"
            ):
                raise RolloutError("canary state is inconsistent")
        elif self.phase is RolloutPhase.BATCH:
            expected_confirmed = self.plan.devices[: len(self.confirmed_devices)]
            expected_active = self.plan.devices[
                len(self.confirmed_devices) : len(self.confirmed_devices)
                + self.plan.batch_size
            ]
            if (
                len(self.confirmed_devices) < self.plan.canary_size
                or self.confirmed_devices != expected_confirmed
                or not self.active_batch
                or self.active_batch != expected_active
                or self.failures
                or self.reason != "awaiting_batch"
            ):
                raise RolloutError("batch state is inconsistent")
        elif self.phase is RolloutPhase.COMPLETE:
            if (
                self.active_batch
                or self.confirmed_devices != self.plan.devices
                or self.failures
                or self.reason != "rollout_complete"
            ):
                raise RolloutError("complete state is inconsistent")
        else:
            processed_count = len(self.confirmed_devices) + len(self.failures)
            processed = self.plan.devices[:processed_count]
            expected_confirmed = tuple(
                device_id for device_id in processed if device_id not in failed_ids
            )
            expected_failures = tuple(
                failure
                for device_id in processed
                for failure in self.failures
                if failure.device_id == device_id
            )
            expected_reason = (
                "canary_not_confirmed"
                if processed_count == self.plan.canary_size
                else "batch_not_confirmed"
            )
            if (
                self.active_batch
                or not self.failures
                or self.confirmed_devices != expected_confirmed
                or self.failures != expected_failures
                or self.reason != expected_reason
            ):
                raise RolloutError("halted state is inconsistent")


def start_pool_rollout(plan: PoolRolloutPlan) -> PoolRolloutState:
    """Release only the mandatory canary batch."""
    if not isinstance(plan, PoolRolloutPlan):
        raise RolloutError("plan must be a PoolRolloutPlan")
    return PoolRolloutState(
        plan=plan,
        phase=RolloutPhase.CANARY,
        active_batch=plan.devices[: plan.canary_size],
        confirmed_devices=(),
        failures=(),
        reason="awaiting_canary",
    )


def record_pool_rollout_batch(
    state: PoolRolloutState,
    outcomes: Mapping[str, RolloutOutcome],
) -> PoolRolloutState:
    """Record one exact batch and either halt, complete or release the next.

    The caller must provide reconciled outcomes for every active device. This
    function performs no command, retry, sleep, network access or mutation.
    """
    if not isinstance(state, PoolRolloutState):
        raise RolloutError("state must be a PoolRolloutState")
    if state.phase in {RolloutPhase.COMPLETE, RolloutPhase.HALTED}:
        raise RolloutError("terminal rollout states cannot transition")
    if not isinstance(outcomes, Mapping):
        raise RolloutError("outcomes must be a mapping")
    if len(outcomes) != len(state.active_batch) or set(outcomes) != set(
        state.active_batch
    ):
        raise RolloutError("outcomes must match the active batch exactly")
    if any(not isinstance(value, RolloutOutcome) for value in outcomes.values()):
        raise RolloutError("outcomes contain an invalid state")

    newly_confirmed = tuple(
        device_id
        for device_id in state.active_batch
        if outcomes[device_id] is RolloutOutcome.CONFIRMED
    )
    confirmed = state.confirmed_devices + newly_confirmed
    failures = tuple(
        RolloutFailure(device_id, outcomes[device_id])
        for device_id in state.active_batch
        if outcomes[device_id] is not RolloutOutcome.CONFIRMED
    )
    if failures:
        reason = (
            "canary_not_confirmed"
            if state.phase is RolloutPhase.CANARY
            else "batch_not_confirmed"
        )
        return PoolRolloutState(
            plan=state.plan,
            phase=RolloutPhase.HALTED,
            active_batch=(),
            confirmed_devices=confirmed,
            failures=failures,
            reason=reason,
        )

    confirmed_set = set(confirmed)
    remaining = tuple(
        device_id for device_id in state.plan.devices if device_id not in confirmed_set
    )
    if not remaining:
        return PoolRolloutState(
            plan=state.plan,
            phase=RolloutPhase.COMPLETE,
            active_batch=(),
            confirmed_devices=confirmed,
            failures=(),
            reason="rollout_complete",
        )
    return PoolRolloutState(
        plan=state.plan,
        phase=RolloutPhase.BATCH,
        active_batch=remaining[: state.plan.batch_size],
        confirmed_devices=confirmed,
        failures=(),
        reason="awaiting_batch",
    )
