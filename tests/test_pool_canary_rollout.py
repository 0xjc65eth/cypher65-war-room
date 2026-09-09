"""Tests for the pure fail-closed pool rollout state machine."""

from dataclasses import FrozenInstanceError, replace

import pytest

from services.pool_intelligence import (
    PoolRolloutPlan,
    PoolRolloutState,
    RolloutError,
    RolloutFailure,
    RolloutOutcome,
    RolloutPhase,
    record_pool_rollout_batch,
    start_pool_rollout,
)


DIGEST = "A1" * 32


def _plan(
    *,
    devices=("device-1", "device-2", "device-3", "device-4", "device-5"),
    canary_size=2,
    batch_size=2,
):
    return PoolRolloutPlan(
        rollout_id="rollout:alpha",
        configuration_hash=DIGEST,
        devices=devices,
        canary_size=canary_size,
        batch_size=batch_size,
    )


def _confirm(state):
    return record_pool_rollout_batch(
        state,
        {device_id: RolloutOutcome.CONFIRMED for device_id in state.active_batch},
    )


def test_plan_is_sanitized_bounded_and_immutable():
    plan = _plan(devices=(f"device-{index}" for index in range(1, 6)))

    assert plan.configuration_hash == DIGEST.lower()
    assert plan.devices == (
        "device-1",
        "device-2",
        "device-3",
        "device-4",
        "device-5",
    )
    with pytest.raises(FrozenInstanceError):
        plan.batch_size = 3


@pytest.mark.parametrize(
    ("operation", "match"),
    [
        (
            lambda: PoolRolloutPlan(123, DIGEST, ("device-1",), 1, 1),
            "must be a string",
        ),
        (
            lambda: PoolRolloutPlan("bad id", DIGEST, ("device-1",), 1, 1),
            "safe identifier",
        ),
        (
            lambda: PoolRolloutPlan("rollout", 123, ("device-1",), 1, 1),
            "configuration_hash must be a string",
        ),
        (
            lambda: PoolRolloutPlan("rollout", "0" * 63, ("device-1",), 1, 1),
            "SHA-256",
        ),
        (
            lambda: _plan(devices="device-1"),
            "iterable of identifiers",
        ),
        (
            lambda: _plan(devices=None),
            "must be iterable",
        ),
        (
            lambda: _plan(devices=()),
            "at least one",
        ),
        (
            lambda: _plan(devices=("device-1", "device-1")),
            "unique",
        ),
        (
            lambda: _plan(devices=("device-1", " bad")),
            "safe identifier",
        ),
        (
            lambda: _plan(devices=(f"device-{index}" for index in range(1_001))),
            "exceeds 1000",
        ),
        (
            lambda: _plan(canary_size=True),
            "canary_size must be an integer",
        ),
        (
            lambda: _plan(canary_size=0),
            "between 1 and 10",
        ),
        (
            lambda: _plan(canary_size=6),
            "cannot exceed",
        ),
        (
            lambda: _plan(batch_size=1.5),
            "batch_size must be an integer",
        ),
        (
            lambda: _plan(batch_size=101),
            "between 1 and 100",
        ),
    ],
)
def test_plan_rejects_unsafe_or_excessive_inputs(operation, match):
    with pytest.raises(RolloutError, match=match):
        operation()


def test_rollout_releases_canary_then_stable_batches_and_completes():
    state = start_pool_rollout(_plan())

    assert state.phase is RolloutPhase.CANARY
    assert state.active_batch == ("device-1", "device-2")
    assert state.reason == "awaiting_canary"

    state = _confirm(state)
    assert state.phase is RolloutPhase.BATCH
    assert state.active_batch == ("device-3", "device-4")
    assert state.confirmed_devices == ("device-1", "device-2")

    state = _confirm(state)
    assert state.phase is RolloutPhase.BATCH
    assert state.active_batch == ("device-5",)

    state = _confirm(state)
    assert state.phase is RolloutPhase.COMPLETE
    assert state.active_batch == ()
    assert state.confirmed_devices == state.plan.devices
    assert state.reason == "rollout_complete"

    with pytest.raises(RolloutError, match="terminal"):
        _confirm(state)


def test_single_device_still_runs_as_a_canary_before_completion():
    state = start_pool_rollout(
        _plan(devices=("only-device",), canary_size=1, batch_size=1)
    )

    assert state.phase is RolloutPhase.CANARY
    assert _confirm(state).phase is RolloutPhase.COMPLETE


@pytest.mark.parametrize("outcome", [RolloutOutcome.FAILED, RolloutOutcome.UNKNOWN])
def test_any_non_confirmed_canary_result_halts_without_releasing_a_batch(outcome):
    state = start_pool_rollout(_plan())

    halted = record_pool_rollout_batch(
        state,
        {
            "device-1": RolloutOutcome.CONFIRMED,
            "device-2": outcome,
        },
    )

    assert halted.phase is RolloutPhase.HALTED
    assert halted.active_batch == ()
    assert halted.confirmed_devices == ("device-1",)
    assert halted.failures == (RolloutFailure("device-2", outcome),)
    assert halted.reason == "canary_not_confirmed"
    with pytest.raises(RolloutError, match="terminal"):
        record_pool_rollout_batch(halted, {})


def test_non_confirmed_regular_batch_halts_with_batch_reason():
    state = _confirm(start_pool_rollout(_plan()))

    halted = record_pool_rollout_batch(
        state,
        {
            "device-3": RolloutOutcome.UNKNOWN,
            "device-4": RolloutOutcome.FAILED,
        },
    )

    assert halted.phase is RolloutPhase.HALTED
    assert halted.confirmed_devices == ("device-1", "device-2")
    assert [failure.device_id for failure in halted.failures] == [
        "device-3",
        "device-4",
    ]
    assert halted.reason == "batch_not_confirmed"


@pytest.mark.parametrize(
    ("operation", "match"),
    [
        (lambda: start_pool_rollout(object()), "plan must"),
        (lambda: record_pool_rollout_batch(object(), {}), "state must"),
        (
            lambda: record_pool_rollout_batch(start_pool_rollout(_plan()), []),
            "must be a mapping",
        ),
        (
            lambda: record_pool_rollout_batch(
                start_pool_rollout(_plan()),
                {"device-1": RolloutOutcome.CONFIRMED},
            ),
            "match the active batch",
        ),
        (
            lambda: record_pool_rollout_batch(
                start_pool_rollout(_plan()),
                {"device-1": "confirmed", "device-2": RolloutOutcome.CONFIRMED},
            ),
            "invalid state",
        ),
        (
            lambda: RolloutFailure("device-1", RolloutOutcome.CONFIRMED),
            "failed or unknown",
        ),
        (
            lambda: RolloutFailure("device-1", []),
            "failed or unknown",
        ),
    ],
)
def test_transition_boundary_rejects_invalid_inputs(operation, match):
    with pytest.raises(RolloutError, match=match):
        operation()


def test_state_constructor_rejects_forged_or_inconsistent_states():
    canary = start_pool_rollout(_plan())
    batch = _confirm(canary)
    complete = _confirm(_confirm(batch))
    halted = record_pool_rollout_batch(
        canary,
        {
            "device-1": RolloutOutcome.FAILED,
            "device-2": RolloutOutcome.UNKNOWN,
        },
    )

    invalid_states = [
        lambda: replace(canary, plan=object()),
        lambda: replace(canary, phase="canary"),
        lambda: replace(canary, active_batch=list(canary.active_batch)),
        lambda: replace(canary, active_batch=("device-1", "device-1")),
        lambda: replace(canary, active_batch=("missing",)),
        lambda: replace(canary, confirmed_devices=("device-1",)),
        lambda: replace(canary, failures=(object(),)),
        lambda: replace(
            batch,
            failures=(
                RolloutFailure("device-1", RolloutOutcome.FAILED),
                RolloutFailure("device-1", RolloutOutcome.UNKNOWN),
            ),
        ),
        lambda: replace(canary, reason="awaiting_batch"),
        lambda: replace(batch, confirmed_devices=()),
        lambda: replace(complete, reason="awaiting_batch"),
        lambda: replace(halted, active_batch=("device-5",)),
    ]

    for operation in invalid_states:
        with pytest.raises(RolloutError):
            operation()


def test_state_and_failure_objects_are_immutable():
    state = start_pool_rollout(_plan())
    failure = RolloutFailure("device-1", RolloutOutcome.UNKNOWN)

    with pytest.raises(FrozenInstanceError):
        state.reason = "changed"
    with pytest.raises(FrozenInstanceError):
        failure.outcome = RolloutOutcome.FAILED
