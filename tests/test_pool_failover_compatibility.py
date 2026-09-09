"""Tests for pool/ASIC compatibility and ordered failover decisions."""

from dataclasses import FrozenInstanceError

import pytest

from services.pool_intelligence import (
    CapabilityAssertion,
    CapabilityState,
    CompatibilityRequirement,
    DeviceCapabilities,
    FailoverCandidate,
    PoolCapabilities,
    Provenance,
    SelectionError,
    build_capability_graph,
    evaluate_pool_compatibility,
    select_failover_candidate,
)


def _graph(states):
    return build_capability_graph(
        [
            CapabilityAssertion(
                name,
                state,
                Provenance.OBSERVED,
                f"probe.{index}",
            )
            for index, (name, state) in enumerate(states.items())
        ]
    )


def _profiles(
    *,
    device_states=None,
    pool_states=None,
    pool_id="pool_primary",
):
    device_states = device_states or {
        "protocol.stratum_v1": CapabilityState.SUPPORTED,
        "transport.tls": CapabilityState.SUPPORTED,
    }
    pool_states = pool_states or {
        "protocol.stratum_v1.subscribe": CapabilityState.SUPPORTED,
        "transport.tls": CapabilityState.SUPPORTED,
    }
    return (
        DeviceCapabilities("device_alpha", _graph(device_states)),
        PoolCapabilities(pool_id, _graph(pool_states)),
    )


def _requirements():
    return (
        CompatibilityRequirement(
            "stratum_v1",
            "protocol.stratum_v1",
            "protocol.stratum_v1.subscribe",
        ),
        CompatibilityRequirement(
            "tls",
            "transport.tls",
            "transport.tls",
        ),
    )


def _compatibility(
    pool_id="pool_primary",
    *,
    state=CapabilityState.SUPPORTED,
):
    device, pool = _profiles(
        pool_id=pool_id,
        pool_states={"protocol.pool": state},
        device_states={"protocol.device": CapabilityState.SUPPORTED},
    )
    return evaluate_pool_compatibility(
        device,
        pool,
        [CompatibilityRequirement("protocol", "protocol.device", "protocol.pool")],
    )


def _candidate(
    pool_id="pool_primary",
    *,
    priority=0,
    health=CapabilityState.SUPPORTED,
    compatibility_state=CapabilityState.SUPPORTED,
    cooldown=0,
):
    return FailoverCandidate(
        pool_id=pool_id,
        priority=priority,
        health_state=health,
        compatibility=_compatibility(pool_id, state=compatibility_state),
        cooldown_seconds=cooldown,
    )


def test_compatibility_requires_supported_device_and_pool_capabilities():
    device, pool = _profiles()

    result = evaluate_pool_compatibility(device, pool, _requirements())

    assert result.device_id == "device_alpha"
    assert result.pool_id == "pool_primary"
    assert result.state is CapabilityState.SUPPORTED
    assert [check.reason for check in result.checks] == ["compatible", "compatible"]
    with pytest.raises(FrozenInstanceError):
        result.state = CapabilityState.ERROR


def test_missing_capability_remains_unknown_instead_of_compatible():
    device, pool = _profiles(
        device_states={"protocol.stratum_v1": CapabilityState.SUPPORTED},
        pool_states={"transport.tls": CapabilityState.SUPPORTED},
    )

    result = evaluate_pool_compatibility(device, pool, _requirements())

    assert result.state is CapabilityState.UNKNOWN
    assert all(check.state is CapabilityState.UNKNOWN for check in result.checks)
    assert all(check.reason == "capability_unknown" for check in result.checks)


@pytest.mark.parametrize(
    ("device_state", "pool_state", "expected_state", "expected_reason"),
    [
        (
            CapabilityState.ERROR,
            CapabilityState.UNSUPPORTED,
            CapabilityState.ERROR,
            "capability_error",
        ),
        (
            CapabilityState.SUPPORTED,
            CapabilityState.UNSUPPORTED,
            CapabilityState.UNSUPPORTED,
            "capability_unsupported",
        ),
        (
            CapabilityState.AUTH_REQUIRED,
            CapabilityState.SUPPORTED,
            CapabilityState.AUTH_REQUIRED,
            "capability_auth_required",
        ),
        (
            CapabilityState.UNKNOWN,
            CapabilityState.SUPPORTED,
            CapabilityState.UNKNOWN,
            "capability_unknown",
        ),
    ],
)
def test_compatibility_states_use_fail_closed_precedence(
    device_state,
    pool_state,
    expected_state,
    expected_reason,
):
    device, pool = _profiles(
        device_states={"protocol.device": device_state},
        pool_states={"protocol.pool": pool_state},
    )

    result = evaluate_pool_compatibility(
        device,
        pool,
        [CompatibilityRequirement("protocol", "protocol.device", "protocol.pool")],
    )

    assert result.state is expected_state
    assert result.checks[0].reason == expected_reason


def test_multiple_checks_keep_highest_risk_result():
    device, pool = _profiles(
        device_states={
            "capability.ok": CapabilityState.SUPPORTED,
            "capability.auth": CapabilityState.AUTH_REQUIRED,
            "capability.error": CapabilityState.ERROR,
        },
        pool_states={
            "capability.ok": CapabilityState.SUPPORTED,
            "capability.auth": CapabilityState.SUPPORTED,
            "capability.error": CapabilityState.SUPPORTED,
        },
    )
    requirements = [
        CompatibilityRequirement(name, f"capability.{name}", f"capability.{name}")
        for name in ("ok", "auth", "error")
    ]

    result = evaluate_pool_compatibility(device, pool, requirements)

    assert result.state is CapabilityState.ERROR


@pytest.mark.parametrize(
    "operation,match",
    [
        (lambda: DeviceCapabilities(123, _graph({})), "must be a string"),
        (lambda: DeviceCapabilities("bad id", _graph({})), "safe token"),
        (lambda: DeviceCapabilities("device", object()), "CapabilityGraph"),
        (lambda: PoolCapabilities("pool", object()), "CapabilityGraph"),
        (
            lambda: CompatibilityRequirement("bad name", "device.cap", "pool.cap"),
            "safe token",
        ),
        (
            lambda: evaluate_pool_compatibility(
                object(), *_profiles()[1:], _requirements()
            ),
            "DeviceCapabilities",
        ),
        (
            lambda: evaluate_pool_compatibility(
                _profiles()[0], object(), _requirements()
            ),
            "PoolCapabilities",
        ),
        (
            lambda: evaluate_pool_compatibility(*_profiles(), []),
            "at least one",
        ),
        (
            lambda: evaluate_pool_compatibility(*_profiles(), "requirements"),
            "iterable of typed",
        ),
        (
            lambda: evaluate_pool_compatibility(*_profiles(), None),
            "must be iterable",
        ),
        (
            lambda: evaluate_pool_compatibility(*_profiles(), [object()]),
            "invalid item",
        ),
    ],
)
def test_compatibility_boundaries_reject_invalid_inputs(operation, match):
    with pytest.raises(SelectionError, match=match):
        operation()


def test_compatibility_requirements_are_unique_and_bounded():
    device, pool = _profiles()
    requirement = _requirements()[0]

    with pytest.raises(SelectionError, match="unique"):
        evaluate_pool_compatibility(device, pool, [requirement, requirement])
    with pytest.raises(SelectionError, match="too many"):
        evaluate_pool_compatibility(device, pool, [requirement] * 33)


def test_failover_keeps_an_eligible_active_pool_even_if_backup_priority_is_lower():
    active = _candidate("pool_active", priority=10)
    backup = _candidate("pool_backup", priority=0)

    decision = select_failover_candidate([active, backup], active_pool_id="POOL_ACTIVE")

    assert decision.selected_pool_id == "pool_active"
    assert decision.changed is False
    assert decision.reason == "active_eligible"
    assert decision.skipped == ()


def test_failover_selects_lowest_priority_eligible_candidate_stably():
    active = _candidate(
        "pool_active",
        priority=0,
        health=CapabilityState.ERROR,
    )
    first_tie = _candidate("pool_first", priority=5)
    second_tie = _candidate("pool_second", priority=5)

    decision = select_failover_candidate(
        [active, first_tie, second_tie], active_pool_id="pool_active"
    )

    assert decision.selected_pool_id == "pool_first"
    assert decision.changed is True
    assert decision.reason == "failover_selected"
    assert decision.skipped[0].pool_id == "pool_active"
    assert decision.skipped[0].reason == "health_error"


def test_initial_selection_is_not_reported_as_a_failover():
    decision = select_failover_candidate(
        [_candidate("pool_secondary", priority=2), _candidate(priority=1)]
    )

    assert decision.selected_pool_id == "pool_primary"
    assert decision.changed is False
    assert decision.reason == "initial_selection"


def test_failover_rejects_cooldown_unhealthy_and_incompatible_candidates():
    candidates = [
        _candidate("pool_cooldown", cooldown=60),
        _candidate("pool_unknown", health=CapabilityState.UNKNOWN),
        _candidate(
            "pool_incompatible",
            compatibility_state=CapabilityState.UNSUPPORTED,
        ),
    ]

    decision = select_failover_candidate(candidates)

    assert decision.selected_pool_id is None
    assert decision.reason == "no_eligible_candidate"
    assert decision.changed is False
    assert [(skip.pool_id, skip.reason) for skip in decision.skipped] == [
        ("pool_cooldown", "cooldown_active"),
        ("pool_unknown", "health_unknown"),
        ("pool_incompatible", "compatibility_unsupported"),
    ]


@pytest.mark.parametrize(
    "operation,match",
    [
        (
            lambda: FailoverCandidate(
                "pool",
                True,
                CapabilityState.SUPPORTED,
                _compatibility("pool"),
            ),
            "priority",
        ),
        (
            lambda: FailoverCandidate(
                "pool",
                0,
                "supported",
                _compatibility("pool"),
            ),
            "health_state",
        ),
        (
            lambda: FailoverCandidate("pool", 0, CapabilityState.SUPPORTED, object()),
            "CompatibilityResult",
        ),
        (
            lambda: FailoverCandidate(
                "pool_a",
                0,
                CapabilityState.SUPPORTED,
                _compatibility("pool_b"),
            ),
            "pool_id must match",
        ),
        (
            lambda: FailoverCandidate(
                "pool",
                0,
                CapabilityState.SUPPORTED,
                _compatibility("pool"),
                cooldown_seconds=True,
            ),
            "cooldown",
        ),
    ],
)
def test_failover_candidate_rejects_invalid_fields(operation, match):
    with pytest.raises(SelectionError, match=match):
        operation()


def test_failover_collection_rejects_invalid_duplicate_and_missing_active():
    candidate = _candidate()

    with pytest.raises(SelectionError, match="typed values"):
        select_failover_candidate("candidates")
    with pytest.raises(SelectionError, match="must be iterable"):
        select_failover_candidate(None)
    with pytest.raises(SelectionError, match="invalid item"):
        select_failover_candidate([object()])
    with pytest.raises(SelectionError, match="unique"):
        select_failover_candidate([candidate, candidate])
    with pytest.raises(SelectionError, match="present"):
        select_failover_candidate([candidate], active_pool_id="pool_missing")
    with pytest.raises(SelectionError, match="too many"):
        select_failover_candidate([candidate] * 17)


def test_empty_failover_set_returns_explicit_no_candidate_decision():
    decision = select_failover_candidate([])

    assert decision.selected_pool_id is None
    assert decision.changed is False
    assert decision.reason == "no_eligible_candidate"
    assert decision.skipped == ()
