"""
CYPHER65 // Seed gating tests (Fase 1 — Honest Telemetry)
==========================================================
Mock/test devices must NEVER be injected into the production fleet.

- DEBUG_MOCK unset/0 → _auto_seed_* are no-ops, POST /api/axe-fleet/test-devices → 403
- DEBUG_MOCK=1        → 4 mock devices created, POST /test-devices → 201 (dev only)
- DEBUG_MOCK off also PURGES leftover rows carrying seed markers
  ("auto-seed" / "test-fleet" groups; core devices with seed_marker metadata)
  so the dashboard never shows invented telemetry.
"""
import os
from unittest.mock import MagicMock, patch

import pytest

import app as _app_module

app = _app_module.app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ══════════════════════════════════════════════════════════════════════════
#  _auto_seed_axe_fleet gating + purge
# ══════════════════════════════════════════════════════════════════════════

class TestAutoSeedAxeFleetGating:
    def test_skipped_when_debug_mock_unset(self, monkeypatch):
        """With DEBUG_MOCK unset, auto-seed must be a no-op."""
        monkeypatch.delenv("DEBUG_MOCK", raising=False)
        registry = MagicMock()
        registry.list_devices.return_value = []
        _app_module._auto_seed_axe_fleet(registry)
        registry._persist_device.assert_not_called()
        registry.save_telemetry.assert_not_called()

    def test_skipped_when_debug_mock_zero(self, monkeypatch):
        """DEBUG_MOCK=0 must also disable seeding."""
        monkeypatch.setenv("DEBUG_MOCK", "0")
        registry = MagicMock()
        registry.list_devices.return_value = []
        _app_module._auto_seed_axe_fleet(registry)
        registry._persist_device.assert_not_called()

    def test_runs_when_debug_mock_one(self, monkeypatch):
        """DEBUG_MOCK=1 seeds exactly 4 mock devices + telemetry."""
        monkeypatch.setenv("DEBUG_MOCK", "1")
        registry = MagicMock()
        registry.list_devices.return_value = []
        result = _app_module._auto_seed_axe_fleet(registry)
        assert result == 4
        assert registry._persist_device.call_count == 4
        assert registry.save_telemetry.call_count >= 10  # ≥10 telemetry points

    def test_skips_when_registry_not_empty(self, monkeypatch):
        """Even with DEBUG_MOCK=1, a non-empty registry is left alone."""
        monkeypatch.setenv("DEBUG_MOCK", "1")
        registry = MagicMock()
        registry.list_devices.return_value = [{"id": "existing"}]
        _app_module._auto_seed_axe_fleet(registry)
        registry._persist_device.assert_not_called()

    def test_purges_seed_marked_rows_when_disabled(self, monkeypatch):
        """DEBUG_MOCK off removes only seed-marker rows, never user devices."""
        monkeypatch.delenv("DEBUG_MOCK", raising=False)
        registry = MagicMock()
        registry.list_devices.return_value = [
            {"id": "d1", "group_id": "auto-seed"},
            {"id": "d2", "group_id": "test-fleet"},
            {"id": "d3", "group_id": "custom-group"},  # user device — kept
            {"id": "d4", "group_id": ""},              # default — kept
        ]
        registry.remove_device.return_value = True
        removed = _app_module._auto_seed_axe_fleet(registry)
        assert removed == 2
        calls = [c.args[0] for c in registry.remove_device.call_args_list]
        assert calls == ["d1", "d2"]

    def test_no_seed_and_no_purge_when_mock_enabled(self, monkeypatch):
        """DEBUG_MOCK=1 never purges (demo data is welcome in dev)."""
        monkeypatch.setenv("DEBUG_MOCK", "1")
        registry = MagicMock()
        registry.list_devices.return_value = [
            {"id": "d1", "group_id": "auto-seed"},
        ]
        _app_module._auto_seed_axe_fleet(registry)
        registry.remove_device.assert_not_called()

    def test_purges_test_prefixed_names_when_disabled(self, monkeypatch):
        """DEBUG_MOCK off removes Test-* / test-* named devices too.
        The RBAC suite (tests/test_rbac_register.py) names its devices with
        the Test- prefix; if those rows ever land in the real DB they must be
        purged at boot — never shown to the user as fleet devices.
        """
        monkeypatch.delenv("DEBUG_MOCK", raising=False)
        registry = MagicMock()
        registry.list_devices.return_value = [
            {"id": "t1", "group_id": "", "name": "Test-rbac-open"},
            {"id": "t2", "group_id": "", "name": "test-rbac-member"},
            {"id": "u1", "group_id": "", "name": "Garage Bitaxe"},   # user — kept
            {"id": "u2", "group_id": "custom-group", "name": "Miner A"},  # user — kept
        ]
        registry.remove_device.return_value = True
        removed = _app_module._auto_seed_axe_fleet(registry)
        assert removed == 2
        calls = [c.args[0] for c in registry.remove_device.call_args_list]
        assert calls == ["t1", "t2"]

    def test_orphaned_telemetry_purged_when_disabled(self, monkeypatch):
        """DEBUG_MOCK off also deletes axe_telemetry rows whose device no
        longer exists (remove_device never cleaned history — long-running
        servers accumulated orphaned telemetry from old seed runs).
        """
        monkeypatch.delenv("DEBUG_MOCK", raising=False)
        registry = MagicMock()
        registry.list_devices.return_value = []  # no devices at all
        conn = MagicMock()
        c = MagicMock()
        c.rowcount = 42
        conn.cursor.return_value = c
        registry._get_db.return_value = conn

        removed = _app_module._auto_seed_axe_fleet(registry)
        assert removed == 0  # no devices purged
        # Orphaned-telemetry DELETE executed against the registry's DB
        sql = c.execute.call_args[0][0]
        assert "DELETE FROM axe_telemetry" in sql
        assert "NOT IN" in sql
        conn.commit.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════
#  _auto_seed_core_devices gating + purge (incl. destructive stale-DELETE path)
# ══════════════════════════════════════════════════════════════════════════

class _NoDbRegistry:
    """Minimal registry stand-in WITHOUT db_path.

    Intended contract: if the gated code ever reaches the stale-replacement
    branch of _auto_seed_core_devices it would access `registry.db_path` and
    raise AttributeError — so passing tests prove the gate returns first.
    """

    def __init__(self, devices=None):
        self.devices = dict()
        self.added = []
        self._list = devices or []

    def list_devices(self):
        return list(self._list)

    def add_device(self, device):
        self.added.append(device)
        return device


class _CoreDeviceStub:
    """Minimal Device stand-in with id/name/metadata for purge tests."""

    def __init__(self, device_id, name, metadata=None, telemetry=None):
        self.id = device_id
        self.name = name
        self.metadata = metadata or {}
        self.current_telemetry = telemetry or {}


class TestAutoSeedCoreDevicesGating:
    def test_skipped_when_debug_mock_unset(self, monkeypatch):
        monkeypatch.delenv("DEBUG_MOCK", raising=False)
        registry = _NoDbRegistry()
        _app_module._auto_seed_core_devices(registry)
        assert registry.added == []

    def test_skipped_when_debug_mock_zero(self, monkeypatch):
        monkeypatch.setenv("DEBUG_MOCK", "0")
        registry = _NoDbRegistry()
        _app_module._auto_seed_core_devices(registry)
        assert registry.added == []

    def test_runs_when_debug_mock_one(self, monkeypatch):
        monkeypatch.setenv("DEBUG_MOCK", "1")
        registry = _NoDbRegistry()
        result = _app_module._auto_seed_core_devices(registry)
        assert result == 4
        assert len(registry.added) == 4

    def test_destructive_delete_never_touches_db_when_disabled(self, monkeypatch):
        """The stale-replacement DELETE path must be unreachable with the gate
        off — a stale device would trigger it, but _NoDbRegistry has no
        db_path, so reaching it would raise AttributeError (test would error)."""
        monkeypatch.delenv("DEBUG_MOCK", raising=False)
        stale = MagicMock()
        stale.current_telemetry = {}
        registry = _NoDbRegistry(devices=[stale])
        _app_module._auto_seed_core_devices(registry)
        assert registry.added == []

    def test_purges_seed_marked_rows_when_disabled(self, monkeypatch):
        """DEBUG_MOCK off removes only core devices with seed_marker metadata."""
        monkeypatch.delenv("DEBUG_MOCK", raising=False)
        marked = _CoreDeviceStub("c1", "Garage Bitaxe", metadata={"seed_marker": "auto-seed"})
        real = _CoreDeviceStub("c2", "My Real Miner", metadata={})
        spy = MagicMock()
        spy.list_devices.return_value = [marked, real]
        removed = _app_module._auto_seed_core_devices(spy)
        assert removed == 1
        assert spy.remove_device.call_args.args[0] == "c1"

    def test_no_purge_when_mock_enabled(self, monkeypatch):
        """DEBUG_MOCK=1 keeps core seed devices (dev mode) — seed path runs."""
        monkeypatch.setenv("DEBUG_MOCK", "1")
        # A healthy device (has temperature telemetry) → existing & fresh → seed
        # skips, but nothing is purged. This proves the purge branch is not
        # reached when the flag is on, without hitting the stale-DELETE path.
        healthy = _CoreDeviceStub("c1", "Real Miner", metadata={}, telemetry={"temperature": 60})
        spy = MagicMock()
        spy.list_devices.return_value = [healthy]
        result = _app_module._auto_seed_core_devices(spy)
        spy.remove_device.assert_not_called()
        assert result == 0  # existing fresh devices → no seeding, no purge


# ══════════════════════════════════════════════════════════════════════════
#  POST /api/axe-fleet/test-devices route gating
# ══════════════════════════════════════════════════════════════════════════

class TestSeedDevicesRouteGating:
    ENDPOINT = "/api/axe-fleet/test-devices"

    def test_route_disabled_without_debug_mock(self, client, monkeypatch):
        """Public endpoint must return 403 when DEBUG_MOCK is unset."""
        monkeypatch.delenv("DEBUG_MOCK", raising=False)
        resp = client.post(self.ENDPOINT)
        assert resp.status_code == 403
        assert "disabled" in resp.get_json()["error"]

    def test_route_disabled_with_debug_mock_zero(self, client, monkeypatch):
        monkeypatch.setenv("DEBUG_MOCK", "0")
        resp = client.post(self.ENDPOINT)
        assert resp.status_code == 403

    def test_route_enabled_with_debug_mock_one(self, client, monkeypatch):
        """With DEBUG_MOCK=1 the route seeds 4 devices (201)."""
        monkeypatch.setenv("DEBUG_MOCK", "1")
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = []
        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.post(self.ENDPOINT)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["success"] is True
        assert data["count"] == 4
        assert mock_registry._persist_device.call_count == 4

    def test_route_never_touches_registry_when_disabled(self, client, monkeypatch):
        """Without DEBUG_MOCK the registry is never even consulted."""
        monkeypatch.delenv("DEBUG_MOCK", raising=False)
        mock_registry = MagicMock()
        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.post(self.ENDPOINT)
        assert resp.status_code == 403
        mock_registry.list_devices.assert_not_called()
