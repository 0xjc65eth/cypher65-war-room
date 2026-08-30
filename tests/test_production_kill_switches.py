"""Integration tests for deployment-level, default-off side-effect gates."""

from unittest.mock import MagicMock

import pytest

import app as app_module
import axe_fleet.routes as fleet_routes
import routes.device_control as device_control
from services import auto_pilot, btcpay, payments, rental_performance
from services.safety_policy import (
    ENABLE_AUTONOMOUS_COMMANDS,
    ENABLE_PHYSICAL_COMMANDS,
    ENABLE_REAL_HASHRATE_PURCHASES,
    ENABLE_REAL_PAYMENTS,
)


FLAGS = (
    ENABLE_PHYSICAL_COMMANDS,
    ENABLE_AUTONOMOUS_COMMANDS,
    ENABLE_REAL_HASHRATE_PURCHASES,
    ENABLE_REAL_PAYMENTS,
)


@pytest.fixture(autouse=True)
def disabled_policy(monkeypatch):
    for name in FLAGS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_unified_device_route_keeps_dry_run_but_blocks_execution(client, monkeypatch):
    registry = MagicMock()
    registry.get_device.return_value = {
        "id": "miner-1",
        "name": "Miner 1",
        "status": "ONLINE",
        "firmware": "AxeOS",
        "ip_address": "192.0.2.10",
        "capabilities": {"restart": True},
        "current_telemetry": {},
    }
    monkeypatch.setattr(device_control, "_registry", registry)
    monkeypatch.setattr(device_control, "_safety", None)
    audit = MagicMock()
    monkeypatch.setattr(device_control, "_record_cb", audit)
    adapter = MagicMock()
    monkeypatch.setattr(device_control, "_build_adapter", adapter)

    preview = client.post(
        "/api/devices/miner-1/command",
        json={"command": "restart"},
    )
    blocked = client.post(
        "/api/devices/miner-1/command",
        json={"command": "restart", "dry_run": False},
    )

    assert preview.status_code == 200
    assert preview.get_json()["dry_run"] is True
    assert blocked.status_code == 503
    assert blocked.get_json()["reason"] == "deployment_policy_disabled"
    adapter.assert_not_called()


def test_internal_fleet_executor_cannot_bypass_physical_gate(monkeypatch):
    registry = MagicMock()
    registry.get_device.return_value = {
        "id": "miner-1",
        "ip_address": "192.0.2.10",
        "capabilities": {"restart": True},
        "agent_managed": 0,
    }
    monkeypatch.setattr(fleet_routes, "_registry", registry)
    connector = MagicMock()
    monkeypatch.setattr(fleet_routes, "AxeOSConnector", connector)
    monkeypatch.setattr(fleet_routes, "_log_audit", MagicMock())

    with app_module.app.test_request_context("/"):
        response, status = fleet_routes._execute_device_command(
            "miner-1", "restart", tenant_id="default"
        )

    assert status == 503
    assert response.get_json()["code"] == "PHYSICAL_COMMANDS_DISABLED"
    connector.assert_not_called()
    registry.enqueue_agent_command.assert_not_called()


def test_auto_pilot_pro_admin_state_cannot_bypass_deployment_gate(monkeypatch):
    execute = MagicMock(return_value={"ok": True})
    engine = MagicMock()
    engine.is_armed.return_value = True
    monkeypatch.setattr(auto_pilot, "is_autonomous_enabled", lambda _tid: True)

    result = auto_pilot.execute_autonomous_actions(
        tenant_id="default",
        engine=engine,
        execute_fn=execute,
        recs=[],
        fleet=[],
        now=123,
    )

    assert result == [
        {"status": "skipped", "reason": "autonomous_commands_disabled", "ts": 123}
    ]
    execute.assert_not_called()
    engine.is_armed.assert_not_called()


def test_braiins_http_bypass_never_contacts_provider(client, monkeypatch):
    provider = MagicMock(return_value={"success": True, "bid": {"id": "unsafe"}})
    monkeypatch.setattr(app_module._rental_perf, "create_braiins_bid", provider)

    response = client.post(
        "/api/rentals/braiins/bid",
        json={
            "dry_run": False,
            "speed_limit_th": 1000,
            "amount_sat": 500000,
            "price_sat": 123456,
            "upstream_url": "stratum+tcp://pool.invalid:3333",
            "upstream_identity": "worker",
        },
    )

    assert response.status_code == 503
    assert response.get_json()["code"] == "REAL_HASHRATE_PURCHASES_DISABLED"
    provider.assert_not_called()


def test_braiins_service_call_cannot_bypass_gate(monkeypatch):
    key_lookup = MagicMock(return_value="configured")
    monkeypatch.setattr(rental_performance, "_braiins_key", key_lookup)

    result = rental_performance.create_braiins_bid(
        1.0,
        500000,
        123456,
        "stratum+tcp://pool.invalid:3333",
        "worker",
    )

    assert result["policy_disabled"] is True
    key_lookup.assert_not_called()


def test_payment_checkout_flag_overrides_provider_configuration(client, monkeypatch):
    monkeypatch.setattr(app_module._btcpay, "btcpay_configured", lambda: True)
    create_invoice = MagicMock(return_value={"id": "unsafe"})
    monkeypatch.setattr(app_module._btcpay, "create_invoice", create_invoice)

    status = client.get("/api/license-status").get_json()
    response = client.post(
        "/api/upgrade/checkout", json={"method": "btc", "plan": "pro"}
    )

    assert status["btcpay"] is False
    assert status["checkout_state"] == "unavailable"
    assert status["checkout_unavailable_reason"] == "deployment_policy_disabled"
    assert response.status_code == 503
    assert response.get_json()["code"] == "REAL_PAYMENTS_DISABLED"
    create_invoice.assert_not_called()


def test_payment_service_fulfillment_cannot_bypass_gate(monkeypatch):
    issue_license = MagicMock(return_value="unsafe-license")
    monkeypatch.setattr(btcpay.licensing, "issue_license", issue_license)

    assert (
        btcpay.handle_invoice_webhook(
            {"invoiceId": "attacker", "type": "InvoiceSettled"}
        )
        is None
    )
    issue_license.assert_not_called()


def test_card_checkout_service_cannot_bypass_gate(monkeypatch):
    configured = MagicMock(return_value=True)
    provider_post = MagicMock()
    monkeypatch.setattr(payments, "payments_configured", configured)
    monkeypatch.setattr(payments.requests, "post", provider_post)

    result = payments.create_checkout(plan="pro", email="operator@example.invalid")

    assert result is None
    configured.assert_not_called()
    provider_post.assert_not_called()


def test_card_webhook_service_cannot_issue_license_when_disabled(monkeypatch):
    issue_license = MagicMock(return_value="unsafe-license")
    monkeypatch.setattr(payments.licensing, "issue_license", issue_license)

    result = payments.handle_webhook(
        {
            "meta": {"event_name": "order_created"},
            "data": {"id": "attacker", "attributes": {}},
        }
    )

    assert result is None
    issue_license.assert_not_called()
