"""TEL-002 contract tests for local-agent ASIC telemetry."""

import pytest

from axe_fleet.models import validate_agent_telemetry


@pytest.mark.parametrize(
    ("payload", "field", "reason"),
    [
        ({"temperature": 55}, "hashrate_hs", "required_for_sample"),
        ({"hashrate_hs": "fast"}, "hashrate_hs", "invalid_type"),
        ({"hashrate_hs": True}, "hashrate_hs", "invalid_type"),
        ({"hashrate_hs": -1}, "hashrate_hs", "out_of_range"),
        ({"hashrate_hs": 1e30}, "hashrate_hs", "out_of_range"),
        ({"hashrate_hs": float("nan")}, "hashrate_hs", "not_finite"),
        ({"hashrate_hs": float("inf")}, "hashrate_hs", "not_finite"),
        ({"hashrate_hs": float("-inf")}, "hashrate_hs", "not_finite"),
        ({"hashrate_hs": 1e12, "temperature": 151}, "temperature", "out_of_range"),
        ({"hashrate_hs": 1e12, "fan_speed": 101}, "fan_speed", "out_of_range"),
    ],
)
def test_invalid_telemetry_has_readable_field_reason(payload, field, reason):
    errors = validate_agent_telemetry(payload)

    assert errors
    assert (field, reason) in {(error["field"], error["reason"]) for error in errors}


def test_empty_payload_is_a_valid_liveness_heartbeat():
    assert validate_agent_telemetry({}) == []


def test_optional_sensor_may_be_absent_while_hashrate_is_valid():
    assert validate_agent_telemetry({"hashrate_hs": 0, "temperature": None}) == []


def test_unknown_fields_do_not_override_the_numeric_contract():
    assert (
        validate_agent_telemetry({"hashrate_hs": 1e12, "firmware_extension": "v2"})
        == []
    )
