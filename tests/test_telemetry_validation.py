"""TEL-002 contract tests for local-agent ASIC telemetry."""

import pytest

from axe_fleet.models import validate_agent_telemetry

pytestmark = pytest.mark.covers("TEL-002")


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


def test_agent_source_error_survives_optional_sensor_normalization():
    errors = validate_agent_telemetry(
        {"hashrate_hs": 5e12, "temperature": None, "_invalid_fields": ["temperature"]}
    )

    assert ("temperature", "invalid_source_value") in {
        (error["field"], error["reason"]) for error in errors
    }


@pytest.mark.parametrize("payload", [None, [], "not telemetry"])
def test_telemetry_payload_must_be_an_object(payload):
    assert validate_agent_telemetry(payload) == [
        {"field": "telemetry", "reason": "must_be_object"}
    ]


@pytest.mark.parametrize(
    "metadata",
    ["temperature", ["temperature"] * 33, ["temperature", "", None]],
)
def test_invalid_source_metadata_is_bounded_and_typed(metadata):
    errors = validate_agent_telemetry(
        {"hashrate_hs": 1e12, "_invalid_fields": metadata}
    )

    assert ("telemetry", "invalid_source_metadata") in {
        (error["field"], error["reason"]) for error in errors
    }


def test_source_metadata_field_names_are_sanitized_before_logging():
    errors = validate_agent_telemetry(
        {"hashrate_hs": 1e12, "_invalid_fields": ["sensor\nsecret"]}
    )

    assert errors == [{"field": "sensor_secret", "reason": "invalid_source_value"}]


@pytest.mark.parametrize(
    ("payload", "field", "reason"),
    [
        ({"hashrate_hs": 1e12, "ts": None}, "ts", "invalid_type"),
        (
            {"hashrate_hs": 1e12, "shares_accepted": 1.5},
            "shares_accepted",
            "must_be_integer",
        ),
        (
            {"hashrate_hs": 1e12, "shares_accepted": 10**1000},
            "shares_accepted",
            "not_finite",
        ),
        ({"hashrate_hs": 1e12, "pool_diff": []}, "pool_diff", "invalid_type"),
        (
            {"hashrate_hs": 1e12, "last_share_ts": float("nan")},
            "last_share_ts",
            "not_finite",
        ),
        ({"hashrate_hs": 1e12, "pool_diff": -1}, "pool_diff", "out_of_range"),
        ({"hashrate_hs": 1e12, "pool_url": None}, "pool_url", "invalid_type"),
        (
            {"hashrate_hs": 1e12, "mining_paused": "false"},
            "mining_paused",
            "invalid_type",
        ),
    ],
)
def test_edge_types_and_ranges_are_rejected(payload, field, reason):
    errors = validate_agent_telemetry(payload)

    assert (field, reason) in {(error["field"], error["reason"]) for error in errors}


def test_nested_non_finite_values_report_a_sanitized_path():
    errors = validate_agent_telemetry(
        {"hashrate_hs": 1e12, "extension\nfield": [{"reading": float("inf")}]}
    )

    assert ("extension_field[0].reading", "not_finite") in {
        (error["field"], error["reason"]) for error in errors
    }


def test_flexible_source_strings_keep_documented_formats():
    assert validate_agent_telemetry(
        {
            "hashrate_hs": 1e12,
            "pool_diff": "256M",
            "last_share_ts": "2026-09-30T12:00:00Z",
        }
    ) == []


@pytest.mark.parametrize("field", ["pool_diff", "last_share_ts"])
def test_optional_flexible_fields_may_be_absent(field):
    assert validate_agent_telemetry({"hashrate_hs": 1e12, field: None}) == []
