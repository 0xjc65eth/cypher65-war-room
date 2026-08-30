"""Unit tests for the fail-closed production safety policy."""

from __future__ import annotations

import json

import pytest

from services.safety_policy import (
    ENABLE_AUTONOMOUS_COMMANDS,
    ENABLE_PHYSICAL_COMMANDS,
    ENABLE_REAL_HASHRATE_PURCHASES,
    ENABLE_REAL_PAYMENTS,
    can_execute_autonomous_command,
    can_execute_physical_command,
    can_process_real_payment,
    can_purchase_hashrate,
    safety_policy_status,
)


GATES = (
    (ENABLE_PHYSICAL_COMMANDS, can_execute_physical_command),
    (ENABLE_AUTONOMOUS_COMMANDS, can_execute_autonomous_command),
    (ENABLE_REAL_HASHRATE_PURCHASES, can_purchase_hashrate),
    (ENABLE_REAL_PAYMENTS, can_process_real_payment),
)


@pytest.mark.parametrize(("_name", "gate"), GATES)
def test_gate_defaults_to_disabled_when_environment_is_absent(_name, gate):
    assert gate({}) is False


@pytest.mark.parametrize(("_name", "gate"), GATES)
@pytest.mark.parametrize("value", ["", " ", "0", "false", "no", "off"])
def test_gate_is_disabled_for_empty_and_explicit_false_values(_name, gate, value):
    assert gate({_name: value}) is False


@pytest.mark.parametrize(("_name", "gate"), GATES)
@pytest.mark.parametrize(
    "value", ["enable", "enabled", "TRUE!", "2", "-1", "y", "t", "null"]
)
def test_gate_fails_closed_for_unrecognized_values(_name, gate, value):
    assert gate({_name: value}) is False


@pytest.mark.parametrize(("_name", "gate"), GATES)
@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "On"])
def test_gate_accepts_only_explicit_safe_true_values(_name, gate, value):
    assert gate({_name: value}) is True


@pytest.mark.parametrize(("_name", "gate"), GATES)
@pytest.mark.parametrize("value", [None, True, 1, object()])
def test_gate_fails_closed_for_non_string_values(_name, gate, value):
    assert gate({_name: value}) is False


def test_gates_are_independent():
    env = {ENABLE_PHYSICAL_COMMANDS: "true"}

    assert can_execute_physical_command(env) is True
    assert can_execute_autonomous_command(env) is False
    assert can_purchase_hashrate(env) is False
    assert can_process_real_payment(env) is False


def test_default_environment_is_read_at_call_time(monkeypatch):
    monkeypatch.delenv(ENABLE_REAL_PAYMENTS, raising=False)
    assert can_process_real_payment() is False

    monkeypatch.setenv(ENABLE_REAL_PAYMENTS, "true")
    assert can_process_real_payment() is True

    monkeypatch.setenv(ENABLE_REAL_PAYMENTS, "invalid")
    assert can_process_real_payment() is False


def test_status_is_sanitized_and_contains_only_policy_results():
    secret_like_invalid_value = "do-not-log-this-value"
    status = safety_policy_status(
        {
            ENABLE_PHYSICAL_COMMANDS: "true",
            ENABLE_AUTONOMOUS_COMMANDS: secret_like_invalid_value,
            ENABLE_REAL_HASHRATE_PURCHASES: "on",
            ENABLE_REAL_PAYMENTS: "false",
            "UNRELATED_SECRET": "also-do-not-log",
        }
    )

    assert status == {
        "default": "deny",
        "physical_commands": True,
        "autonomous_commands": False,
        "real_hashrate_purchases": True,
        "real_payments": False,
    }
    serialized = json.dumps(status)
    assert secret_like_invalid_value not in serialized
    assert "also-do-not-log" not in serialized
