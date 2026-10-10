"""Recovery #799: real scratch SQLite identity primitives and restore guards."""

import sqlite3
from unittest.mock import patch

from flask import Flask
import pytest

from axe_fleet.registry import (
    DeviceIdentityConflict,
    DeviceRegistry,
    normalize_device_mac,
)
from axe_fleet.routes import axe_fleet_bp


@pytest.mark.parametrize(
    "value",
    ["02:aB:01:23:45:67", "02-AB-01-23-45-67", "02ab01234567", " 02:AB:01:23:45:67 "],
)
def test_valid_mac_formats_converge(value):
    assert normalize_device_mac(value) == "02:AB:01:23:45:67"


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "unknown",
        "00:00:00:00:00:00",
        "FF:FF:FF:FF:FF:FF",
        "01:00:5E:00:00:01",
        "02:AB:01:23:45",
        "02-AB:01:23:45:67",
        "020AB01234567",
        "02:AB:01:23:45:GG",
        True,
        123456789012,
        {},
        [],
    ],
)
def test_invalid_mac_is_unknown(value):
    assert normalize_device_mac(value) is None


@pytest.fixture
def registry(tmp_path):
    path = tmp_path / "identity.sqlite"

    def get_db():
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        return connection

    instance = DeviceRegistry(get_db)
    instance.ensure_tables()
    return instance


def tombstone(registry, mac="02:AB:01:23:45:67", tenant="default"):
    device = registry.upsert_agent_device(
        "192.0.2.7", tenant_id=tenant, info={"mac": mac}
    )
    registry.save_telemetry(device["id"], {"hashrate_hs": 0}, tenant_id=tenant)
    assert registry.remove_device(device["id"], tenant_id=tenant)
    return device


def snapshot(registry):
    with registry._get_db() as connection:
        return {
            table: [tuple(row) for row in connection.execute("SELECT * FROM " + table)]
            for table in (
                "axe_devices",
                "axe_device_identity_aliases",
                "axe_telemetry",
                "axe_agent_commands",
            )
        }


@pytest.mark.parametrize(
    "mac", [None, "", "unknown", "00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"]
)
def test_restore_without_valid_evidence_never_mutates(registry, mac):
    device = tombstone(registry)
    before = snapshot(registry)
    assert (
        registry.clear_tombstone(
            device["ip_address"], tenant_id="default", mac_address=mac
        )
        == {}
    )
    assert snapshot(registry) == before


def test_restore_mismatch_fails_in_transaction(registry):
    device = tombstone(registry)
    before = snapshot(registry)
    with pytest.raises(DeviceIdentityConflict):
        registry.clear_tombstone(
            device["ip_address"], tenant_id="default", mac_address="02:AB:01:23:45:68"
        )
    assert snapshot(registry) == before


def test_restore_preserves_device_and_history(registry):
    device = tombstone(registry)
    before = snapshot(registry)
    restored = registry.clear_tombstone(
        device["ip_address"], tenant_id="default", mac_address="02-ab-01-23-45-67"
    )
    assert restored["id"] == device["id"]
    assert registry.get_device(device["id"], tenant_id="default")["removed_at"] == 0
    after = snapshot(registry)
    for table in ("axe_device_identity_aliases", "axe_telemetry", "axe_agent_commands"):
        assert after[table] == before[table]
    assert len(after["axe_devices"]) == 1


def test_restore_is_tenant_scoped(registry):
    device = tombstone(registry, tenant="acme")
    before = snapshot(registry)
    assert (
        registry.clear_tombstone(
            device["ip_address"], tenant_id="other", mac_address=device["mac_address"]
        )
        == {}
    )
    assert snapshot(registry) == before


@pytest.mark.parametrize(
    "stored, supplied, status",
    [
        ("unknown", "unknown", 400),
        ("unknown", "02:AB:01:23:45:67", 409),
        ("02:AB:01:23:45:67", "unknown", 400),
        ("02:AB:01:23:45:67", "02:AB:01:23:45:68", 409),
        ("02:AB:01:23:45:67", "02-ab-01-23-45-67", 200),
    ],
)
def test_restore_route_validates_both_sides(
    registry, monkeypatch, stored, supplied, status
):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("TENANT_API_KEYS", raising=False)
    tombstone(registry)
    with registry._get_db() as connection:
        connection.execute("UPDATE axe_devices SET mac_address=?", (stored,))
    before = snapshot(registry)
    app = Flask(__name__)
    app.secret_key = "identity-recovery-test-secret-0123456789"
    app.register_blueprint(axe_fleet_bp, url_prefix="/api/axe-fleet")
    with patch("axe_fleet.routes._registry", registry), patch(
        "axe_fleet.routes._log_audit"
    ):
        response = app.test_client().post(
            "/api/axe-fleet/devices/restore",
            json={"ip_address": "192.0.2.7", "mac": supplied},
        )
    assert response.status_code == status, response.get_json()
    if status != 200:
        assert snapshot(registry) == before
    else:
        assert response.get_json()["device_id"] == before["axe_devices"][0][0]


def test_active_only_update_cannot_reanimate_removed_row(registry):
    device = tombstone(registry)
    before = snapshot(registry)
    assert (
        registry.update_device(
            device["id"], {"status": "ONLINE"}, tenant_id="default", active_only=True
        )
        is False
    )
    assert snapshot(registry) == before


def test_manual_add_never_deletes_removed_identity(registry):
    device = tombstone(registry)
    before = snapshot(registry)
    with patch("axe_fleet.registry.AxeOSConnector") as connector:
        assert registry.add_device(device["ip_address"]) == {}
    connector.assert_not_called()
    assert snapshot(registry) == before


def test_manual_add_new_ip_cannot_restore_removed_mac(registry):
    from axe_fleet.axeos_contract import official_esp_miner_info

    tombstone(registry)
    before = snapshot(registry)
    with patch("axe_fleet.registry.AxeOSConnector") as connector:
        connector.return_value.fetch_info.return_value = official_esp_miner_info(
            macAddr="02:AB:01:23:45:67"
        )
        connector.return_value.detect_capabilities.return_value = {}
        assert registry.add_device("192.0.2.8") == {}
    assert snapshot(registry) == before


def test_cloud_add_removed_device_does_not_queue_or_restore(registry, monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("TENANT_API_KEYS", raising=False)
    device = tombstone(registry)
    before = snapshot(registry)
    app = Flask(__name__)
    app.secret_key = "identity-recovery-test-secret-0123456789"
    app.register_blueprint(axe_fleet_bp, url_prefix="/api/axe-fleet")
    with patch("axe_fleet.routes._registry", registry), patch(
        "config.is_cloud_deploy", return_value=True
    ), patch("axe_fleet.registry.AxeOSConnector") as connector:
        response = app.test_client().post(
            "/api/axe-fleet/devices", json={"ip_address": device["ip_address"]}
        )
    assert response.status_code == 409
    assert response.get_json()["code"] == "DEVICE_REMOVED"
    connector.assert_not_called()
    assert snapshot(registry) == before
