"""Issue #787: retained observations and coherent time determine evidence."""

import json
import math
from decimal import Decimal

import pytest

from services.block_probability_lab import share_statistics


NOW = 10000
ENDPOINT = "/api/block-probability-lab/session-evidence"


def _history(count=100, *, timed=True):
    return [
        dict(share_diff_raw=index + 1, **({"ts": 9801 + index} if timed else {}))
        for index in range(count)
    ]


def _statistics(history, *, cumulative=100, age=None, user_hr=100, network_hr=1000):
    return share_statistics(
        cumulative,
        history,
        user_hashrate=user_hr,
        network_hashrate=network_hr,
        age_seconds=age,
        observed_now=NOW,
    )


def test_boolean_difficulties_are_not_observed_shares():
    result = _statistics(
        [
            {"share_diff_raw": True},
            {"share_diff_raw": False},
            {"share_diff_raw": math.inf},
            {"share_diff_raw": math.nan},
            {"share_diff_raw": 0},
            {"share_diff_raw": -1},
            {"share_diff_raw": 2},
            {"share_diff_raw": 4},
        ],
        age=0,
    )
    assert result["sample_count"] == result["valid_modeled_shares"] == 2
    assert result["p50"] == result["avg_share_difficulty"] == 3
    assert result["evidence_state"] == "PARTIAL"


@pytest.mark.parametrize("cumulative", [0, 2, 100, 1000000])
def test_fresh_coverage_uses_retained_valid_observations(cumulative):
    result = _statistics(_history(), cumulative=cumulative)
    assert result["evidence_state"] == "GOOD COVERAGE"
    assert result["valid_modeled_shares"] == 100
    assert result["last_share_age_seconds"] == 100
    assert result["observed_window_seconds"] == 99


@pytest.mark.parametrize(
    "count,expected", [(0, "INSUFFICIENT"), (1, "PARTIAL"), (99, "PARTIAL")]
)
def test_large_cumulative_count_cannot_promote_missing_retained_evidence(
    count, expected
):
    result = _statistics(_history(count), cumulative=1000000, age=0)
    assert result["evidence_state"] == expected
    assert result["valid_modeled_shares"] == count
    if count == 0:
        assert result["last_share_age_seconds"] is None
        assert result["observed_window_seconds"] is None


def test_unknown_age_is_partial_even_with_one_hundred_valid_shares():
    result = _statistics(_history(timed=False))
    assert result["evidence_state"] == "PARTIAL"
    assert result["last_share_age_seconds"] is None
    assert result["observed_window_seconds"] is None


@pytest.mark.parametrize(
    "user_hr,network_hr,count,expected",
    [
        (None, None, 0, "NO DATA"),
        (0, 1000, 0, "NO DATA"),
        (None, 1000, 100, "INSUFFICIENT"),
        (100, None, 100, "INSUFFICIENT"),
    ],
)
def test_missing_hashrate_does_not_claim_coverage(user_hr, network_hr, count, expected):
    assert (
        _statistics(_history(count), user_hr=user_hr, network_hr=network_hr)[
            "evidence_state"
        ]
        == expected
    )


@pytest.mark.parametrize(
    "history",
    [
        [{"ts": 9000, "share_diff_raw": 1}, {"ts": 8999, "share_diff_raw": 2}],
        [{"ts": 9000, "share_diff_raw": 1}, {"ts": NOW + 1, "share_diff_raw": 2}],
        [{"share_diff_raw": 1}, {"ts": 9000, "share_diff_raw": 2}],
        [{"ts": 9000, "share_diff_raw": 1}, {"share_diff_raw": 2}],
    ],
    ids=["reversed", "future", "missing-first", "missing-last"],
)
def test_incoherent_history_cannot_borrow_explicit_freshness(history):
    result = _statistics(history, age=0)
    assert result["last_share_age_seconds"] is None
    assert result["last_share_age"] is None
    assert result["observed_window_seconds"] is None
    assert result["observed_window"] is None
    assert result["evidence_state"] == "PARTIAL"


@pytest.mark.parametrize(
    "timestamp", [True, False, None, "bad", -1, 0, math.inf, math.nan]
)
def test_present_invalid_timestamp_is_unknown_not_explicit_age(timestamp):
    result = _statistics([{"share_diff_raw": 1, "ts": timestamp}], age=0)
    assert result["last_share_age_seconds"] is None
    assert result["observed_window_seconds"] is None
    assert result["evidence_state"] == "PARTIAL"


@pytest.mark.parametrize("age", [0, 30, 7200])
def test_explicit_age_is_allowed_only_without_history_timestamps(age):
    result = _statistics(_history(timed=False), age=age)
    assert result["last_share_age_seconds"] == age
    assert result["observed_window_seconds"] is None
    assert result["evidence_state"] == ("STALE" if age > 3600 else "GOOD COVERAGE")


def test_display_and_classification_use_same_stale_observation_age():
    result = _statistics(
        [
            {"ts": 1, "share_diff_raw": 10},
            {"ts": 2, "share_diff_raw": 20},
        ],
        age=0,
    )
    assert result["last_share_age_seconds"] == 9998
    assert result["last_share_age"] == "166m"
    assert result["evidence_state"] == result["evidence_state_label"] == "STALE"


def test_trend_retains_input_order_even_if_timestamps_are_incoherent():
    history = [{"ts": NOW - index, "share_diff_raw": 20 - index} for index in range(20)]
    result = _statistics(history, age=0)
    assert result["share_diff_trend"] == "DECREASING"
    assert result["p50"] == 10.5
    assert result["last_share_age_seconds"] is None
    assert result["observed_window_seconds"] is None


@pytest.fixture
def client(monkeypatch):
    import app as app_module
    import routes.block_probability_lab_routes as routes
    import services.state as state

    monkeypatch.setitem(app_module.app.config, "TESTING", True)
    monkeypatch.setattr(
        state,
        "latest_snapshot",
        {
            "worker": {"hashrate": 100},
            "network": {"hashrate": 1000},
        },
    )
    monkeypatch.setattr(
        state,
        "timeline_state",
        {
            "session_share_count": 1000000,
            "last_submit_ts": NOW,
            "share_calc_history": _history(),
        },
    )
    monkeypatch.setattr(routes.time, "time", lambda: NOW)
    return app_module.app.test_client()


INVALID_INPUTS = [
    ("session_share_count", value)
    for value in [
        True,
        False,
        -1,
        0.5,
        "1.5",
        math.inf,
        -math.inf,
        math.nan,
        "Infinity",
    ]
] + [
    (field, value)
    for field in ["age_seconds", "user_hashrate", "network_hashrate"]
    for value in [True, False, -1, math.inf, -math.inf, math.nan]
]


@pytest.mark.parametrize("field,value", INVALID_INPUTS)
@pytest.mark.parametrize("method", ["post", "get"])
def test_endpoint_rejects_invalid_numeric_inputs_as_json_400(
    client, field, value, method
):
    if method == "post":
        response = client.post(ENDPOINT, json={field: value})
    else:
        response = client.get(ENDPOINT, query_string={field: value})
    assert response.status_code == 400
    assert response.is_json
    assert response.get_json().get("error")


@pytest.mark.parametrize("body", [[], False])
def test_endpoint_rejects_falsey_non_object_bodies(client, body):
    response = client.post(ENDPOINT, json=body)
    assert response.status_code == 400
    assert response.is_json
    assert response.get_json().get("error")


@pytest.mark.parametrize(
    "history",
    [
        _history(timed=False),
        [{"ts": NOW + 1, "share_diff_raw": 1}],
        [{"ts": 9000, "share_diff_raw": 1}, {"share_diff_raw": 2}],
    ],
    ids=["untimed", "future", "mixed-missing"],
)
def test_supplied_history_never_borrows_live_session_clock(client, history):
    response = client.post(ENDPOINT, json={"share_calc_history": history})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["evidence_state"] == "PARTIAL"
    assert payload["session_evidence"]["last_share_age_seconds"] is None
    assert payload["session_evidence"]["observed_window_seconds"] is None


def test_endpoint_stale_supplied_history_overrides_explicit_fresh_age(client):
    response = client.post(
        ENDPOINT,
        json={
            "share_calc_history": [
                {"ts": 1, "share_diff_raw": 10},
                {"ts": 2, "share_diff_raw": 20},
            ],
            "age_seconds": 0,
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert (
        payload["evidence_state"]
        == payload["session_evidence"]["evidence_state"]
        == "STALE"
    )
    assert (
        payload["last_share_age_seconds"]
        == payload["session_evidence"]["last_share_age_seconds"]
        == 9998
    )
    assert payload["session_evidence"]["last_share_age"] == "166m"


def test_endpoint_cumulative_count_without_samples_is_insufficient(client):
    response = client.post(
        ENDPOINT,
        json={"share_calc_history": [], "session_share_count": 100, "age_seconds": 0},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["evidence_state"] == "INSUFFICIENT"
    assert payload["session_evidence"]["valid_modeled_shares"] == 0
    assert payload["session_evidence"]["last_share_age_seconds"] is None


def test_endpoint_one_hundred_fresh_observations_have_good_coverage(client):
    response = client.post(
        ENDPOINT, json={"share_calc_history": _history(), "session_share_count": 0}
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["evidence_state"] == "GOOD COVERAGE"
    assert payload["session_evidence"]["valid_modeled_shares"] == 100
    assert payload["session_evidence"]["last_share_age_seconds"] == 100


@pytest.mark.parametrize("body", ["{broken", "null", "", "[]", "false"])
def test_endpoint_json_body_errors_are_explicit(client, body):
    response = client.post(ENDPOINT, data=body, content_type="application/json")
    # An absent body is the documented live-session request; supplied malformed
    # or non-object JSON must never silently fall back to that session.
    if body == "":
        assert response.status_code == 200
    else:
        assert response.status_code == 400
        assert response.get_json().get("error")


@pytest.mark.parametrize("window", [None, "", 0, False])
def test_endpoint_invalid_window_returns_json_400(client, window):
    response = client.post(ENDPOINT, json={"window_seconds": window})
    assert response.status_code == 400
    assert response.is_json
    assert response.get_json().get("error")


def _public_proximity(monkeypatch, history, last_submit, *, return_payload=False):
    import services.state as state
    from services import proximity

    monkeypatch.setattr(
        state,
        "timeline_state",
        {
            "session_share_count": 1000000,
            "last_submit_ts": last_submit,
            "share_calc_history": history,
            "all_time_best_diff_raw": 100,
        },
    )
    # Exercise the public computation without app's persistence injection.
    monkeypatch.setattr(proximity, "_get_db", None)
    result = proximity.compute_proximity(
        {"hashrate": 100, "bestDifficulty": "100"},
        10000,
        1000,
        NOW,
    )
    assert not result.get("insufficient_data")
    return result if return_payload else result["session_evidence"]


@pytest.mark.parametrize(
    "last_submit",
    [
        NOW + 1,
        True,
        False,
        math.inf,
        -math.inf,
        math.nan,
        "malformed",
        None,
        0,
        -1,
    ],
)
def test_public_proximity_invalid_submit_clock_keeps_untimed_age_unknown(
    monkeypatch,
    last_submit,
):
    evidence = _public_proximity(monkeypatch, _history(timed=False), last_submit)
    assert evidence["valid_modeled_shares"] == 100
    assert evidence["last_share_age_seconds"] is None
    assert evidence["observed_window_seconds"] is None
    assert evidence["evidence_state"] == "PARTIAL"


@pytest.mark.parametrize("last_submit", [NOW, NOW + 1, True, math.inf, "malformed", 1])
def test_public_proximity_retained_stale_history_cannot_be_masked_by_submit_clock(
    monkeypatch,
    last_submit,
):
    evidence = _public_proximity(
        monkeypatch,
        [
            {"ts": 1, "share_diff_raw": 10},
            {"ts": 2, "share_diff_raw": 20},
        ],
        last_submit,
    )
    assert evidence["last_share_age_seconds"] == 9998
    assert evidence["last_share_age"] == "166m"
    assert evidence["observed_window_seconds"] == 1
    assert evidence["evidence_state"] == "STALE"


def test_public_proximity_old_submit_clock_only_supplies_untimed_history_age(
    monkeypatch,
):
    evidence = _public_proximity(monkeypatch, _history(timed=False), 1)
    assert evidence["last_share_age_seconds"] == 9999
    assert evidence["observed_window_seconds"] is None
    assert evidence["evidence_state"] == "STALE"


def _overflow_difficulty_history():
    return [{"share_diff_raw": 10**400}, {"share_diff_raw": 2}, {"share_diff_raw": 4}]


def _strict_json(response):
    def reject_constant(value):
        raise AssertionError(f"Non-finite JSON constant: {value}")

    return json.loads(response.get_data(as_text=True), parse_constant=reject_constant)


def test_service_ignores_unrepresentable_difficulty_without_raising():
    result = _statistics(_overflow_difficulty_history(), age=0)
    assert result["valid_modeled_shares"] == 2
    assert result["avg_share_difficulty"] == result["p50"] == 3


def test_endpoint_ignores_unrepresentable_difficulty_and_returns_strict_json(client):
    response = client.post(
        ENDPOINT,
        json={
            "share_calc_history": _overflow_difficulty_history(),
            "age_seconds": 0,
        },
    )
    assert response.status_code == 200
    payload = _strict_json(response)
    assert payload["valid_modeled_shares"] == 2
    assert payload["avg_share_difficulty"] == 3


def test_public_proximity_handles_unrepresentable_difficulty(monkeypatch):
    evidence = _public_proximity(monkeypatch, _overflow_difficulty_history(), NOW)
    assert evidence["valid_modeled_shares"] == 2
    assert evidence["avg_share_difficulty"] == 3
    assert evidence["evidence_state"] == "PARTIAL"


def test_service_large_finite_difficulties_have_finite_mean_and_trend():
    result = _statistics([{"share_diff_raw": 1e308} for _ in range(100)], age=0)
    assert result["valid_modeled_shares"] == 100
    assert math.isfinite(result["avg_share_difficulty"])
    assert result["avg_share_difficulty"] == pytest.approx(1e308)
    assert result["share_diff_trend"] == "STABLE"
    assert result["evidence_state"] == "GOOD COVERAGE"


def test_endpoint_large_finite_difficulties_never_emit_nonfinite_json(client):
    response = client.post(
        ENDPOINT,
        json={
            "share_calc_history": [{"share_diff_raw": 1e308} for _ in range(100)],
            "age_seconds": 0,
        },
    )
    assert response.status_code == 200
    payload = _strict_json(response)
    assert payload["avg_share_difficulty"] == pytest.approx(1e308)
    assert payload["session_evidence"]["avg_share_difficulty"] == pytest.approx(1e308)
    assert payload["session_evidence"]["share_difficulty_trend"] == "STABLE"


@pytest.mark.parametrize(
    "method,count",
    [
        ("post", 9007199254740993),
        ("post", "9007199254740993"),
        ("get", "9007199254740993"),
    ],
    ids=["json-integer", "json-string", "query-string"],
)
def test_endpoint_preserves_integer_count_above_float_precision(client, method, count):
    if method == "post":
        response = client.post(ENDPOINT, json={"session_share_count": count})
    else:
        response = client.get(ENDPOINT, query_string={"session_share_count": count})
    assert response.status_code == 200
    payload = _strict_json(response)
    assert payload["session_share_count"] == 9007199254740993
    assert payload["session_evidence"]["session_shares"] == 9007199254740993


def test_endpoint_rejects_fractional_count_hidden_by_float_string_rounding(client):
    response = client.post(
        ENDPOINT, json={"session_share_count": "100.0000000000000000001"}
    )
    assert response.status_code == 400
    assert _strict_json(response).get("error")


def test_endpoint_rejects_raw_fractional_json_count_beyond_float_precision(client):
    response = client.post(
        ENDPOINT,
        data='{"session_share_count":100.0000000000000000001}',
        content_type="application/json",
    )
    assert response.status_code == 400
    assert _strict_json(response).get("error")


@pytest.mark.parametrize("field", ["user_hr", "network_hr"])
def test_pure_service_huge_hashrate_is_insufficient_not_fresh_coverage(field):
    result = _statistics(_history(), **{field: 10**400})
    assert result["evidence_state"] == "INSUFFICIENT"
    assert result["valid_modeled_shares"] == 100


@pytest.mark.parametrize("age", ["-1e-9999", Decimal("-1e-9999")])
def test_service_tiny_negative_age_is_unknown_not_rounded_fresh(age):
    result = _statistics(_history(timed=False), age=age)
    assert result["last_share_age_seconds"] is None
    assert result["last_share_age"] is None
    assert result["observed_window_seconds"] is None
    assert result["evidence_state"] == "PARTIAL"


@pytest.mark.parametrize("raw_json", [False, True], ids=["string", "raw-number"])
def test_endpoint_tiny_negative_age_is_json_400(client, raw_json):
    if raw_json:
        response = client.post(
            ENDPOINT,
            data='{"age_seconds":-1e-9999}',
            content_type="application/json",
        )
    else:
        response = client.post(ENDPOINT, json={"age_seconds": "-1e-9999"})
    assert response.status_code == 400
    assert response.is_json
    assert _strict_json(response).get("error")


@pytest.mark.parametrize("field", ["age_seconds", "session_share_count"])
def test_endpoint_unrepresentable_json_exponent_is_json_400(client, field):
    response = client.post(
        ENDPOINT,
        data='{"' + field + '":1e9999999999999999999999999}',
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.is_json
    assert _strict_json(response).get("error")


def test_public_proximity_filters_boolean_difficulties_without_mutating_history(
    monkeypatch,
):
    import services.state as state

    history = [
        {"share_diff_raw": True},
        {"share_diff_raw": False},
        {"share_diff_raw": 10**400},
        {"share_diff_raw": 0},
        {"share_diff_raw": 2},
        {"share_diff_raw": 4},
    ]
    payload = _public_proximity(monkeypatch, history, NOW, return_payload=True)
    evidence = payload["session_evidence"]
    assert evidence["valid_modeled_shares"] == 2
    assert evidence["avg_share_difficulty"] == 3
    assert evidence["evidence_state"] == "PARTIAL"
    assert history[0]["share_diff_raw"] is True
    assert history[1]["share_diff_raw"] is False
    assert history[2]["share_diff_raw"] == 10**400
    assert history[3]["share_diff_raw"] == 0
    assert history[4:] == [{"share_diff_raw": 2}, {"share_diff_raw": 4}]
    assert len(history) == 6
    assert state.timeline_state["share_calc_history"] is history
    assert state.timeline_state["session_share_count"] == 1000000
    assert payload["live_calc"]["session_totals"]["shares_in_ticker"] == 2
    assert payload["live_calc"]["session_totals"]["avg_share_diff_raw"] == 3
    assert len(payload["live_calc"]["ticker"]) == 2


@pytest.mark.parametrize(
    "timestamp", [None, "bad", True, False, math.nan, NOW + 1, 9800]
)
def test_public_proximity_mixed_invalid_timestamps_remain_unknown_without_degradation(
    monkeypatch,
    timestamp,
):
    evidence = _public_proximity(
        monkeypatch,
        [
            {"ts": 9900, "share_diff_raw": 2},
            {"ts": timestamp, "share_diff_raw": 4},
        ],
        NOW,
    )
    assert evidence["valid_modeled_shares"] == 2
    assert evidence["last_share_age_seconds"] is None
    assert evidence["observed_window_seconds"] is None
    assert evidence["evidence_state"] == "PARTIAL"


def test_public_proximity_mixed_missing_timestamp_does_not_borrow_live_age(monkeypatch):
    evidence = _public_proximity(
        monkeypatch,
        [
            {"ts": 9900, "share_diff_raw": 2},
            {"share_diff_raw": 4},
        ],
        NOW,
    )
    assert evidence["last_share_age_seconds"] is None
    assert evidence["observed_window_seconds"] is None
    assert evidence["evidence_state"] == "PARTIAL"
