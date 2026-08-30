"""Critical flow tests for Braiins confirmation and idempotent execution."""

from unittest.mock import MagicMock

import pytest

import app as app_module


BASE = {
    "speed_limit_th": 100,
    "amount_sat": 50000,
    "price_sat": 123456,
    "upstream_url": "stratum+tcp://pool.invalid:3333",
    "upstream_identity": "wallet.worker",
    "memo": "validation",
}


@pytest.fixture(autouse=True)
def _enable_purchase_boundary(monkeypatch):
    monkeypatch.setenv("ENABLE_REAL_HASHRATE_PURCHASES", "true")
    app_module._braiins_bid_store.clear()


@pytest.fixture()
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _prepare(client, provider, key):
    payload = {**BASE, "cl_order_id": key, "dry_run": True}
    response = client.post("/api/rentals/braiins/bid", json=payload)
    assert response.status_code == 200, response.get_json()
    return payload, response.get_json()["confirmation_token"]


def _provider_success(**kwargs):
    if kwargs.get("dry_run"):
        return {"success": True, "dry_run": True, "validated": True}
    return {"success": True, "bid": {"id": "provider-bid-1"}}


def test_dry_run_is_default_and_does_not_require_enabled_flag(client, monkeypatch):
    monkeypatch.delenv("ENABLE_REAL_HASHRATE_PURCHASES", raising=False)
    provider = MagicMock(side_effect=_provider_success)
    monkeypatch.setattr(app_module._rental_perf, "create_braiins_bid", provider)

    response = client.post(
        "/api/rentals/braiins/bid",
        json={**BASE, "cl_order_id": "dry-default-1"},
    )

    assert response.status_code == 200
    assert response.get_json()["dry_run"] is True
    assert response.get_json()["requires_confirmation"] is True
    assert provider.call_args.kwargs["dry_run"] is True


def test_replay_with_same_key_never_posts_twice(client, monkeypatch):
    provider = MagicMock(side_effect=_provider_success)
    monkeypatch.setattr(app_module._rental_perf, "create_braiins_bid", provider)
    monkeypatch.setattr(
        app_module._rental_perf,
        "reconcile_braiins_bid",
        lambda **_kwargs: {"reconciled": True, "bid_id": "provider-bid-1"},
    )
    payload, token = _prepare(client, provider, "idempotent-1")
    execution = {
        **payload,
        "dry_run": False,
        "confirmation_token": token,
    }

    first = client.post(
        "/api/rentals/braiins/bid",
        json=execution,
        headers={"Idempotency-Key": "idempotent-1"},
    )
    replay = client.post(
        "/api/rentals/braiins/bid",
        json=execution,
        headers={"Idempotency-Key": "idempotent-1"},
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.get_json()["replayed"] is True
    assert (
        sum(
            1 for call in provider.call_args_list if call.kwargs.get("dry_run") is False
        )
        == 1
    )


def test_same_key_with_changed_payload_is_rejected(client, monkeypatch):
    provider = MagicMock(side_effect=_provider_success)
    monkeypatch.setattr(app_module._rental_perf, "create_braiins_bid", provider)
    monkeypatch.setattr(
        app_module._rental_perf,
        "reconcile_braiins_bid",
        lambda **_kwargs: {"reconciled": True, "bid_id": "provider-bid-1"},
    )
    payload, token = _prepare(client, provider, "payload-bind-1")
    first = client.post(
        "/api/rentals/braiins/bid",
        json={**payload, "dry_run": False, "confirmation_token": token},
        headers={"Idempotency-Key": "payload-bind-1"},
    )
    changed = client.post(
        "/api/rentals/braiins/bid",
        json={
            **payload,
            "amount_sat": 50001,
            "dry_run": False,
            "confirmation_token": token,
        },
        headers={"Idempotency-Key": "payload-bind-1"},
    )

    assert first.status_code == 200
    assert changed.status_code == 409
    assert changed.get_json()["code"] == "IDEMPOTENCY_PAYLOAD_MISMATCH"


def test_invalid_confirmation_never_reaches_actual_provider_call(client, monkeypatch):
    provider = MagicMock(side_effect=_provider_success)
    monkeypatch.setattr(app_module._rental_perf, "create_braiins_bid", provider)

    response = client.post(
        "/api/rentals/braiins/bid",
        json={
            **BASE,
            "cl_order_id": "confirm-required-1",
            "dry_run": False,
            "confirmation_token": "invalid",
        },
        headers={"Idempotency-Key": "confirm-required-1"},
    )

    assert response.status_code == 403
    assert not any(
        call.kwargs.get("dry_run") is False for call in provider.call_args_list
    )


def test_idempotency_header_must_match_provider_correlation_id(client, monkeypatch):
    provider = MagicMock(side_effect=_provider_success)
    monkeypatch.setattr(app_module._rental_perf, "create_braiins_bid", provider)
    payload, token = _prepare(client, provider, "correlation-1")

    response = client.post(
        "/api/rentals/braiins/bid",
        json={**payload, "dry_run": False, "confirmation_token": token},
        headers={"Idempotency-Key": "different-key-1"},
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "IDEMPOTENCY_CORRELATION_MISMATCH"
    assert not any(
        call.kwargs.get("dry_run") is False for call in provider.call_args_list
    )


def test_ambiguous_timeout_is_persisted_and_replay_does_not_retry(client, monkeypatch):
    def ambiguous(**kwargs):
        if kwargs.get("dry_run"):
            return {"success": True, "dry_run": True, "validated": True}
        return {
            "success": False,
            "ambiguous": True,
            "error": "provider timeout — outcome unknown",
        }

    provider = MagicMock(side_effect=ambiguous)
    monkeypatch.setattr(app_module._rental_perf, "create_braiins_bid", provider)
    payload, token = _prepare(client, provider, "timeout-safe-1")
    execution = {**payload, "dry_run": False, "confirmation_token": token}

    first = client.post(
        "/api/rentals/braiins/bid",
        json=execution,
        headers={"Idempotency-Key": "timeout-safe-1"},
    )
    replay = client.post(
        "/api/rentals/braiins/bid",
        json=execution,
        headers={"Idempotency-Key": "timeout-safe-1"},
    )

    assert first.status_code == 202
    assert first.get_json()["state"] == "unknown"
    assert first.get_json()["retry_allowed"] is False
    assert replay.status_code == 202
    assert replay.get_json()["replayed"] is True
    assert (
        sum(
            1 for call in provider.call_args_list if call.kwargs.get("dry_run") is False
        )
        == 1
    )
