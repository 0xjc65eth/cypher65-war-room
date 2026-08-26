"""
CYPHER65 // FLEET TENANT SCOPE — isolation regression suite
============================================================
Locks the multi-tenant fleet audit fixes:

1. GET /api/axe-fleet/devices is scoped per tenant (Worker A added by User 1
   must NEVER appear on User 2's dashboard).
2. /api/snapshot['axe_fleet'] is scoped per tenant (the deployment-wide poll
   cache is filtered at serve time).
3. Read routes require at least the "viewer" role → anonymous REMOTE callers
   (auth configured) get 403 instead of silently reading the "default"
   operator fleet.
4. /api/axe-fleet/diagnose/<ip> (SSRF surface) requires auth.
5. /api/axe-fleet/remote/* endpoints are tenant-scoped.
6. /api/axe-fleet/test-devices seeds only into the caller's tenant.

Strategy (hermetic): real DeviceRegistry on the scratch DB (conftest
redirects DB_PATH), Flask test_client with Bearer tokens (sub=tenant_id),
and the connector monkeypatched to fail fast (no network). Anonymous tests
use environ_overrides REMOTE_ADDR so the "localhost = admin" rule does not
mask the gate.
"""
import pytest

from services.auth import create_token
from services import state as _shared_state

import app as _app_module

app = _app_module.app
_axe_registry = _app_module._axe_registry


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """Clean fleet state + fixed JWT secret + auth CONFIGURED (so the
    role gates are active — open self-host mode would bypass them)."""
    app.config["TESTING"] = True
    saved = app.config.get("JWT_SECRET_KEY")
    app.config["JWT_SECRET_KEY"] = "fleet-scope-secret-0123456789abcdef"
    monkeypatch.setenv("SECRET_KEY", "fleet-scope-secret-0123456789abcdef")
    monkeypatch.setenv("API_KEY", "fleet-scope-test-key")
    for d in _axe_registry.list_devices():
        _axe_registry.remove_device(d["id"], tenant_id=d.get("tenant_id") or "default")
    _shared_state.axe_telemetry_cache.clear()
    _app_module.latest_snapshot.pop("axe_fleet", None)
    yield
    for d in _axe_registry.list_devices():
        _axe_registry.remove_device(d["id"], tenant_id=d.get("tenant_id") or "default")
    _shared_state.axe_telemetry_cache.clear()
    _app_module.latest_snapshot.pop("axe_fleet", None)
    if saved is not None:
        app.config["JWT_SECRET_KEY"] = saved
    else:
        app.config.pop("JWT_SECRET_KEY", None)


@pytest.fixture
def client():
    with app.test_client() as c:
        yield c


@pytest.fixture
def no_connect(monkeypatch):
    """Make AxeOSConnector fail instantly (hermetic: no network, no 5s waits)."""
    import axe_fleet.registry as _reg
    from axe_fleet.connector import AxeOSConnectorError

    class _NoConn:
        def __init__(self, *a, **k):
            raise AxeOSConnectorError("no network in tests")

    monkeypatch.setattr(_reg, "AxeOSConnector", _NoConn)


def _bearer(tenant_id: str) -> dict:
    with app.app_context():
        token = create_token(subject=tenant_id)
    return {"Authorization": f"Bearer {token}"}


def _remote_get(client, path, **kw):
    """GET as an anonymous REMOTE caller (not localhost) — the localhost
    admin exemption must not mask the role gate."""
    return client.get(path, environ_overrides={"REMOTE_ADDR": "203.0.113.5"}, **kw)


class TestFleetListTenantScope:
    def test_tenant_b_cannot_see_tenant_a_devices(self, client, no_connect):
        _axe_registry.add_device("10.0.0.1", "A-miner", tenant_id="tenantA")
        _axe_registry.add_device("10.0.0.2", "B-miner", tenant_id="tenantB")

        r = client.get("/api/axe-fleet/devices", headers=_bearer("tenantA"))
        assert r.status_code == 200
        names = [d["name"] for d in r.get_json()["devices"]]
        assert "A-miner" in names
        assert "B-miner" not in names

        r = client.get("/api/axe-fleet/devices", headers=_bearer("tenantB"))
        assert r.status_code == 200
        names = [d["name"] for d in r.get_json()["devices"]]
        assert "B-miner" in names
        assert "A-miner" not in names

    def test_anonymous_remote_cannot_list(self, client, no_connect):
        """With auth configured, an anonymous remote caller must NOT fall
        back to reading the operator's 'default' fleet."""
        _axe_registry.add_device("10.0.0.1", "A-miner", tenant_id="tenantA")
        r = _remote_get(client, "/api/axe-fleet/devices")
        assert r.status_code in (401, 403)

    def test_tenant_cannot_get_other_tenant_device(self, client, no_connect):
        da = _axe_registry.add_device("10.0.0.1", "A-miner", tenant_id="tenantA")
        r = client.get(f"/api/axe-fleet/devices/{da['id']}", headers=_bearer("tenantB"))
        assert r.status_code == 404
        r = client.get(f"/api/axe-fleet/devices/{da['id']}", headers=_bearer("tenantA"))
        assert r.status_code == 200


class TestSnapshotFleetScope:
    def test_snapshot_axe_fleet_scoped_to_tenant(self, client, no_connect):
        """The dashboard snapshot's fleet field is served from a GLOBAL poll
        cache — it must be filtered to the caller's tenant."""
        da = _axe_registry.add_device("10.0.0.1", "A-miner", tenant_id="tenantA")
        db = _axe_registry.add_device("10.0.0.2", "B-miner", tenant_id="tenantB")
        _shared_state.axe_telemetry_cache[da["id"]] = {"device_id": da["id"], "hashrate_hs": 1}
        _shared_state.axe_telemetry_cache[db["id"]] = {"device_id": db["id"], "hashrate_hs": 2}
        # Simulate what _do_poll does: sync the snapshot's fleet field from
        # the (global) telemetry cache.
        _app_module.latest_snapshot["axe_fleet"] = list(_shared_state.axe_telemetry_cache.values())

        r = client.get("/api/snapshot", headers=_bearer("tenantA"))
        assert r.status_code == 200
        fleet = r.get_json().get("axe_fleet") or []
        ids = {t.get("device_id") for t in fleet}
        assert da["id"] in ids
        assert db["id"] not in ids

        r = client.get("/api/snapshot", headers=_bearer("tenantB"))
        fleet = r.get_json().get("axe_fleet") or []
        ids = {t.get("device_id") for t in fleet}
        assert db["id"] in ids
        assert da["id"] not in ids


class TestDiagnoseSsfrGate:
    def test_anonymous_remote_cannot_diagnose(self, client, no_connect):
        """diagnose/<ip> is an SSRF surface — must require auth."""
        r = _remote_get(client, "/api/axe-fleet/diagnose/10.0.0.99")
        assert r.status_code in (401, 403)

    def test_authenticated_local_can_diagnose(self, client, no_connect):
        # Localhost (default test REMOTE_ADDR) is the operator → allowed.
        r = client.get("/api/axe-fleet/diagnose/10.0.0.99")
        assert r.status_code == 200
        # diagnose_host() unified contract (AxeOS :80 + cgminer :4028)
        data = r.get_json()
        assert data.get("bitaxe_http") is not None
        assert data.get("cgminer_tcp") is not None
        assert data.get("reachable") is not None


class TestRemoteEndpointsScoped:
    def test_remote_devices_scoped_to_tenant(self, client, no_connect, monkeypatch):
        da = _axe_registry.add_device("10.0.0.1", "A-miner", tenant_id="tenantA")
        _axe_registry.add_device("10.0.0.2", "B-miner", tenant_id="tenantB")
        monkeypatch.setattr(
            "services.tailscale_adapter.get_local_status",
            lambda: {"connected": True, "ip": "100.64.0.1", "hostname": "test"},
        )
        monkeypatch.setattr(
            "services.tailscale_adapter.diagnose_connection",
            lambda *a, **k: {"reachable": True, "elapsed_ms": 5},
        )
        r = client.get("/api/axe-fleet/remote/devices", headers=_bearer("tenantA"))
        assert r.status_code == 200
        payload = r.get_json()
        assert payload["count"] == 1
        assert payload["devices"][0]["id"] == da["id"]

    def test_remote_devices_anonymous_blocked(self, client, no_connect):
        _axe_registry.add_device("10.0.0.1", "A-miner", tenant_id="tenantA")
        r = _remote_get(client, "/api/axe-fleet/remote/devices")
        assert r.status_code in (401, 403)


class TestSeedScoped:
    def test_seed_lands_only_in_caller_tenant(self, client, no_connect, monkeypatch):
        monkeypatch.setenv("DEBUG_MOCK", "1")
        r = client.post("/api/axe-fleet/test-devices", headers=_bearer("tenantA"))
        assert r.status_code == 201
        assert len(_axe_registry.list_devices(tenant_id="tenantA")) == 4
        assert _axe_registry.list_devices(tenant_id="tenantB") == []


class TestNo500Regression:
    """@require_tenant injects the tenant_id kwarg UNCONDITIONALLY — every
    handler it decorates MUST accept it or the route 500s (TypeError).
    Smoke-test the routes that historically missed the parameter so a
    future decorator/signature drift is caught immediately."""

    def test_list_power_plugs_accepts_tenant_kwarg(self, client):
        r = client.get("/api/axe-fleet/power-plugs", headers=_bearer("tenantA"))
        assert r.status_code == 200

    def test_power_plug_status_accepts_tenant_kwarg(self, client):
        r = client.get("/api/axe-fleet/power-plugs/x/status", headers=_bearer("tenantA"))
        assert r.status_code == 200  # no TypeError; Tuya not configured → 200 error body

    def test_power_cycle_status_accepts_tenant_kwarg(self, client):
        r = client.get("/api/axe-fleet/power-cycle/status/nonexistent",
                       headers=_bearer("tenantA"))
        assert r.status_code == 404  # no TypeError

    def test_remote_onboarding_accepts_tenant_kwarg(self, client, monkeypatch):
        monkeypatch.setattr(
            "services.tailscale_adapter.get_local_status",
            lambda: {"connected": False, "tailscale_installed": False,
                     "ip": "", "hostname": "", "error": "not installed"},
        )
        r = client.get("/api/axe-fleet/remote/onboarding", headers=_bearer("tenantA"))
        assert r.status_code == 200
