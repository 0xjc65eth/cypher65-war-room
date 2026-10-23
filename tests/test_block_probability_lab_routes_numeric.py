"""Hermetic HTTP contracts for Issue #841, without importing app workers."""

import json

import pytest
from flask import Flask

from routes.block_probability_lab_routes import dashboard_bp


@pytest.fixture
def client():
    application = Flask(__name__)
    application.config["TESTING"] = True
    application.register_blueprint(dashboard_bp)
    return application.test_client()


def test_target_route_round_trips_without_network_or_snapshot(client):
    response = client.get(
        "/api/block-probability-lab/target-p1-window?window_seconds=600"
    )
    assert response.status_code == 200
    target = response.get_json()
    assert target["status"] == "SOLVED"
    assert target["user_hashrate_required"] is None
    response = client.get(
        "/api/block-probability-lab/horizon",
        query_string={
            "user_hashrate": target["share_of_network_required"] * 6e20,
            "network_hashrate": 6e20,
            "window_seconds": 600,
        },
    )
    assert response.status_code == 200
    assert response.get_json()["probability_at_least_one"] == pytest.approx(0.10)


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "0", "-1"])
@pytest.mark.parametrize("endpoint", ["target-p1-window", "horizon", "solo"])
def test_http_invalid_window_is_json_safe_and_not_solved(client, bad, endpoint):
    response = client.get(
        f"/api/block-probability-lab/{endpoint}",
        query_string={
            "user_hashrate": 1e12,
            "network_hashrate": 6e20,
            "window_seconds": bad,
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] != "SOLVED"
    json.dumps(payload, allow_nan=False)


def test_route_does_not_invent_missing_network_inputs_for_target_solver(client):
    response = client.get(
        "/api/block-probability-lab/target-solver?target=0.10&window_seconds=600"
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "INSUFFICIENT_INPUTS"
    assert response.get_json()["required_user_hashrate"] is None
