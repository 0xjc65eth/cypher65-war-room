"""Regression coverage for evidence derived from retained mining shares."""

import math

import pytest

from services.block_probability_lab import share_statistics


def test_percentiles_and_valid_sample_count_ignore_invalid_history():
    result = share_statistics(12, [
        {"share_diff_raw": 1},
        {"share_diff_raw": None},
        None,
        {"share_diff_raw": math.inf},
        {"share_diff_raw": 3},
    ])
    assert result["sample_count"] == 2
    assert result["valid_modeled_shares"] == 2
    assert result["p50"] == 2
    assert result["max"] == 3
    assert result["data_gaps"] is None
    assert result["observed_window"] is None
    assert result["last_share_age"] is None


def test_trend_compares_chronological_history_not_sorted_values():
    rising = [{"share_diff_raw": 1 + i} for i in range(20)]
    falling = list(reversed(rising))
    assert share_statistics(20, rising)["share_diff_trend"] == "INCREASING"
    assert share_statistics(20, falling)["share_diff_trend"] == "DECREASING"


def test_timestamps_produce_observation_window_and_last_age():
    history = [
        {"share_diff_raw": 4, "timestamp": 1000},
        {"share_diff_raw": 8, "ts": 1120},
    ]
    result = share_statistics(2, history, observed_now=1180)
    assert result["observed_window_seconds"] == 120
    assert result["last_share_age_seconds"] == 60
    assert result["last_share_age"] == "60s"


def test_sample_count_mismatch_no_longer_breaks_quantiles():
    result = share_statistics(100, [{"share_diff_raw": 7}, {}, {"share_diff_raw": 9}])
    assert result["sample_count"] == 2
    assert result["p99"] == pytest.approx(8.98)


@pytest.fixture
def client(monkeypatch):
    import app as app_module
    import services.state as state

    monkeypatch.setattr(state, "latest_snapshot", {
        "worker": {"hashrate": 100, "bestDifficulty": "1"},
        "network": {"hashrate": 1000},
    })
    monkeypatch.setattr(state, "timeline_state", {
        "session_share_count": 20,
        "last_submit_ts": 1120,
        "share_calc_history": [
            {"ts": 1000, "share_diff_raw": 1},
            {"ts": 1120, "share_diff_raw": 2},
        ],
    })
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_session_evidence_endpoint_uses_live_snapshot_and_history(client, monkeypatch):
    import routes.block_probability_lab_routes as routes

    monkeypatch.setattr(routes.time, "time", lambda: 1180)
    response = client.get("/api/block-probability-lab/session-evidence")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["evidence_state"] == "PARTIAL"
    assert payload["session_evidence"]["session_shares"] == 20
    assert payload["session_evidence"]["valid_modeled_shares"] == 2
    assert payload["session_evidence"]["observed_window_seconds"] == 120
    assert payload["session_evidence"]["last_share_age_seconds"] == 60
    assert payload["session_evidence"]["data_gaps"] is None


def test_session_evidence_rejects_non_object_history(client):
    response = client.post(
        "/api/block-probability-lab/session-evidence",
        json={"share_calc_history": "not,a,number"},
    )
    assert response.status_code == 400
