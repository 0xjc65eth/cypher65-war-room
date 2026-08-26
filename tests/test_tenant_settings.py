"""
Tests for PER-TENANT settings + provider credentials.

Multi-user deployments (1000+ users): every tenant has its OWN settings and
Braiins/MRR credentials. The critical guarantees pinned here:

  1. A named tenant's settings live in `tenant_settings`, never the global
     `settings` table — and vice-versa (no cross-tenant writes).
  2. A named tenant's credential resolution NEVER falls through to the
     operator's env vars or global settings (no key leakage).
  3. The RENTALS + Settings routes resolve the caller's tenant from the
     Bearer token and thread tenant_id through to the fetchers.
"""

import pytest

import app as _app_module
from services import settings as _settings_mod
from services.db import get_db
from agents.solo_mining_advisor import tools as _tools_mod


@pytest.fixture(autouse=True)
def _clean_state():
    """Fresh caches + clean settings tables before EVERY test (the scratch DB
    persists across tests in a session, so rows from one test must not leak
    into the next)."""
    _settings_mod.invalidate_cache()
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM settings")
        c.execute("DELETE FROM tenant_settings")
        conn.commit()
        conn.close()
    except Exception:
        pass
    yield
    _settings_mod.invalidate_cache()


@pytest.fixture
def rclient():
    _app_module.app.config["TESTING"] = True
    _app_module.app.config["JWT_SECRET_KEY"] = "cypher65-test-secret-key-0123456789"
    with _app_module.app.test_client() as c:
        yield c


def _token(tenant_id: str, role: str = "admin") -> str:
    """Mint a JWT access token for a tenant (mimics the login flow)."""
    from services.auth import create_token

    with _app_module.app.app_context():
        return create_token(subject=tenant_id, extra_claims={"role": role})


def _mrr_result(tenant_id, seen):
    seen["mrr"] = tenant_id
    return {"success": True, "needs_auth": False, "rentals": [], "total": 0}


def _braiins_result(tenant_id, seen):
    seen["braiins"] = tenant_id
    return {"success": True, "needs_auth": False, "contracts": []}


# ── services.settings: per-tenant storage isolation ────────────────────────


def test_tenant_settings_isolated_from_global():
    """save/load for a named tenant touches ONLY tenant_settings."""
    _settings_mod.save_setting("braiins_api_key", "t1-key", tenant_id="tenant-aaa")
    _settings_mod.save_setting("cost_mode", "power", tenant_id="tenant-aaa")

    s1 = _settings_mod.load_settings("tenant-aaa")
    assert s1["braiins_api_key"] == "t1-key"
    assert s1["cost_mode"] == "power"

    # Another tenant + the operator's global settings are untouched.
    s2 = _settings_mod.load_settings("tenant-bbb")
    assert s2["braiins_api_key"] == ""
    assert s2["cost_mode"] == "none"
    g = _settings_mod.load_settings()  # default (operator)
    assert g["braiins_api_key"] == ""
    assert g["cost_mode"] == "none"


def test_global_settings_untouched_by_tenant_writes():
    """A named tenant can NEVER write into the operator's global table."""
    _settings_mod.save_setting("webhook_url", "https://operator.example/hook")
    _settings_mod.save_setting(
        "webhook_url", "https://evil.example/hook", tenant_id="tenant-aaa"
    )
    assert (
        _settings_mod.load_settings()["webhook_url"] == "https://operator.example/hook"
    )
    assert (
        _settings_mod.load_settings("tenant-aaa")["webhook_url"]
        == "https://evil.example/hook"
    )


# ── Credential resolvers: tenant NEVER inherits env/global ─────────────────


def test_braiins_credentials_tenant_uses_own_key(monkeypatch):
    """Env key + global key set, but the tenant has its own → tenant wins."""
    monkeypatch.setenv("BRAIINS_API_KEY", "env-key")
    _settings_mod.save_setting("braiins_api_key", "global-key")  # operator table
    _settings_mod.save_setting("braiins_api_key", "tenant-key", tenant_id="tenant-aaa")

    assert (
        _tools_mod.braiins_credentials(tenant_id="tenant-aaa")["api_key"]
        == "tenant-key"
    )
    # Default tenant keeps the legacy env-first behavior.
    assert _tools_mod.braiins_credentials()["api_key"] == "env-key"


def test_mrr_credentials_tenant_never_leaks_env(monkeypatch):
    monkeypatch.setenv("MRR_API_KEY", "env-key")
    monkeypatch.setenv("MRR_API_SECRET", "env-secret")
    _settings_mod.save_setting("mrr_api_key", "t1-key", tenant_id="tenant-aaa")
    _settings_mod.save_setting("mrr_api_secret", "t1-secret", tenant_id="tenant-aaa")

    creds = _tools_mod.mrr_credentials(tenant_id="tenant-aaa")
    assert creds["api_key"] == "t1-key"
    assert creds["api_secret"] == "t1-secret"
    # Default tenant still resolves the env creds.
    assert _tools_mod.mrr_credentials()["api_key"] == "env-key"


def test_named_tenant_without_own_key_never_inherits_env(monkeypatch):
    """The per-user rule (Issue #189): a named tenant with NO credential rows
    must NEVER inherit the operator's env/global keys. Env vars set + no
    tenant rows → the resolvers return EMPTY, never the operator's key."""
    monkeypatch.setenv("MRR_API_KEY", "env-key")
    monkeypatch.setenv("MRR_API_SECRET", "env-secret")
    monkeypatch.setenv("BRAIINS_API_KEY", "env-token")

    assert _tools_mod.mrr_credentials(tenant_id="tenant-nokeys") == {
        "api_key": "",
        "api_secret": "",
    }
    assert _tools_mod.braiins_credentials(tenant_id="tenant-nokeys") == {"api_key": ""}
    # The default tenant (operator self-host) legitimately keeps env fallback.
    assert _tools_mod.mrr_credentials()["api_key"] == "env-key"
    assert _tools_mod.braiins_credentials()["api_key"] == "env-token"


def test_tuya_credentials_are_encrypted_and_tenant_isolated(monkeypatch):
    """A named tenant never inherits the operator's Tuya plug credentials."""
    from axe_fleet.routes import _get_tuya_credentials

    monkeypatch.setenv("SECRET_KEY", "tuya-settings-test-secret-0123456789")
    monkeypatch.setenv("TUYA_ACCESS_ID", "operator-id")
    monkeypatch.setenv("TUYA_ACCESS_SECRET", "operator-secret")
    _settings_mod.save_setting("tuya_access_id", "tenant-id", tenant_id="tenant-aaa")
    _settings_mod.save_setting(
        "tuya_access_secret", "tenant-secret", tenant_id="tenant-aaa"
    )
    _settings_mod.save_setting("tuya_region", "eu", tenant_id="tenant-aaa")

    creds = _get_tuya_credentials("tenant-aaa")
    assert creds["access_id"] == "tenant-id"
    assert creds["access_secret"] == "tenant-secret"
    assert creds["region"] == "eu"
    assert _get_tuya_credentials("tenant-empty")["access_id"] == ""

    conn = get_db()
    row = conn.execute(
        "SELECT value FROM tenant_settings WHERE tenant_id=? AND key=?",
        ("tenant-aaa", "tuya_access_secret"),
    ).fetchone()
    conn.close()
    assert row["value"].startswith("enc:v1:")


def test_boot_guard_warns_on_provider_env_keys_in_multitenant():
    """Boot guard (Issue #189): a multi-tenant deployment must NOT carry
    operator provider keys at env level — they only apply to the default
    tenant and would look like shared credentials."""
    warn = _app_module.provider_keys_env_warning
    assert warn({"t1": "k"}, {"MRR_API_KEY": "x"})
    assert warn({"t1": "k"}, {"BRAIINS_API_KEY": "x"})
    # No TENANT_API_KEYS (self-host) → no warning (legacy env fallback ok).
    assert not warn({}, {"MRR_API_KEY": "x"})
    # Multi-tenant but no provider env keys → no warning.
    assert not warn({"t1": "k"}, {})


def test_rental_perf_threads_tenant():
    """services.rental_performance passes tenant_id to the resolvers."""
    import services.rental_performance as rp

    _settings_mod.save_setting("braiins_api_key", "t1-key", tenant_id="tenant-aaa")
    assert rp._braiins_key(tenant_id="tenant-aaa") == "t1-key"
    assert rp._braiins_key() == ""  # no env/global → empty


# ── Routes: tenant resolved from Bearer token ──────────────────────────────


def test_rentals_route_threads_tenant_id(rclient, monkeypatch):
    """GET /api/rentals passes the caller's tenant_id into the fetchers."""
    seen = {}
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_mrr_rentals",
        lambda rtype, history, limit, tenant_id="": _mrr_result(tenant_id, seen),
    )
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_braiins_contracts",
        lambda tenant_id="": _braiins_result(tenant_id, seen),
    )

    resp = rclient.get(
        "/api/rentals", headers={"Authorization": "Bearer " + _token("tenant-aaa")}
    )
    assert resp.status_code == 200
    assert seen["mrr"] == "tenant-aaa"
    assert seen["braiins"] == "tenant-aaa"


def test_rentals_route_anonymous_uses_default(rclient, monkeypatch):
    """No token (open self-host mode) → operator's default tenant."""
    seen = {}
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_braiins_contracts",
        lambda tenant_id="": _braiins_result(tenant_id, seen),
    )
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_mrr_rentals",
        lambda rtype, history, limit, tenant_id="": _mrr_result(tenant_id, seen),
    )

    resp = rclient.get("/api/rentals")
    assert resp.status_code == 200
    assert seen["braiins"] == "default"


def test_settings_post_writes_tenant_row(rclient):
    """POST /api/settings as a named tenant stores creds in THEIR row only."""
    resp = rclient.post(
        "/api/settings",
        headers={"Authorization": "Bearer " + _token("tenant-aaa")},
        json={"braiins_api_key": "t1-key", "cost_mode": "power"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["rejected"] == []

    assert _settings_mod.load_settings("tenant-aaa")["braiins_api_key"] == "t1-key"
    assert _settings_mod.load_settings("tenant-aaa")["cost_mode"] == "power"
    # Operator's global table untouched.
    assert _settings_mod.load_settings()["braiins_api_key"] == ""
    assert _settings_mod.load_settings()["cost_mode"] == "none"


def test_settings_get_tenant_values_no_env_override(rclient, monkeypatch):
    """A named tenant sees THEIR own values; env vars never override for them."""
    monkeypatch.setenv("BRAIINS_API_KEY", "env-key")
    _settings_mod.save_setting("braiins_api_key", "t1-key", tenant_id="tenant-aaa")

    resp = rclient.get(
        "/api/settings", headers={"Authorization": "Bearer " + _token("tenant-aaa")}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    by_key = {s["key"]: s["value"] for s in data["settings"]}
    assert by_key["braiins_api_key"] == "t1-key"
    # env override only applies to the operator's default tenant.
    assert data["env_overrides"]["braiins_api_key"] is False
    assert data["tenant_id"] == "tenant-aaa"


def test_settings_get_default_env_override_shows(rclient, monkeypatch):
    """Default tenant keeps the env-override warning (operator self-host)."""
    monkeypatch.setenv("BRAIINS_API_KEY", "env-key")
    resp = rclient.get("/api/settings")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["env_overrides"]["braiins_api_key"] is True
    assert data["tenant_id"] == "default"


def test_config_backup_is_tenant_scoped(rclient, monkeypatch):
    """A named tenant's config backup must NEVER include the operator's
    global settings (which can hold the operator's provider keys)."""
    _settings_mod.save_setting("braiins_api_key", "OPERATOR-SECRET-KEY")
    _settings_mod.save_setting("cost_mode", "power", tenant_id="tenant-aaa")

    resp = rclient.get(
        "/api/config/backup",
        headers={"Authorization": "Bearer " + _token("tenant-aaa")},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    # Tenant's own value, NOT the operator's global secret.
    assert data["settings"]["braiins_api_key"] == ""
    assert data["settings"]["cost_mode"] == "power"


def test_config_restore_writes_tenant_row(rclient):
    """A named tenant restoring a config writes ONLY into their own
    tenant_settings rows — never the operator's global table."""
    _settings_mod.save_setting("braiins_api_key", "OPERATOR-KEY")
    resp = rclient.post(
        "/api/config/restore",
        headers={"Authorization": "Bearer " + _token("tenant-aaa")},
        json={"settings": {"braiins_api_key": "t1-key", "cost_mode": "none"}},
    )
    assert resp.status_code == 200
    assert resp.get_json()["rejected"] == []

    assert _settings_mod.load_settings("tenant-aaa")["braiins_api_key"] == "t1-key"
    # Operator's global table untouched (still the original key).
    assert _settings_mod.load_settings()["braiins_api_key"] == "OPERATOR-KEY"


def test_test_braiins_route_uses_tenant_key(rclient, monkeypatch):
    """POST /api/settings/test-braiins probes the CALLER's key."""
    _settings_mod.save_setting("braiins_api_key", "t1-key", tenant_id="tenant-aaa")
    calls = {}

    def _capture(tenant_id=""):
        calls["tenant_id"] = tenant_id
        return {"success": True, "needs_auth": False, "contracts": []}

    monkeypatch.setattr(_app_module._rental_perf, "fetch_braiins_contracts", _capture)

    resp = rclient.post(
        "/api/settings/test-braiins",
        headers={"Authorization": "Bearer " + _token("tenant-aaa")},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert calls["tenant_id"] == "tenant-aaa"
    assert data["success"] is True
    assert data["env_override"] is False
