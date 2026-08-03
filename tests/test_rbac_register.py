"""
CYPHER65 // Fase 4 · B4 — RBAC + /register + CORS regression tests
==================================================================
Locks the self-registration endpoint, role-based access control
(admin > member > viewer), env-gated CORS headers and the idempotent
users.role/password_hash migration.
"""
import json
import os

import pytest

from app import app as _app

from services.tenant import (
    ROLE_PRIORITY,
    auth_configured,
    get_current_role,
    create_user,
    authenticate_user,
    ensure_users_schema,
    provision_tenant_with_admin,
)


@pytest.fixture
def client(monkeypatch):
    """Test client that pins the JWT secret in BOTH app.config and env.

    Handlers verify tokens inside a request context where _get_secret()
    prefers current_app.config["JWT_SECRET_KEY"]; tokens minted at test
    level (no app context) use the env SECRET_KEY fallback. Pinning both to
    the same value keeps create/verify in sync and immune to leftover config
    secrets leaked by other test files (cross-file pollution)."""
    _app.config["TESTING"] = True
    saved = _app.config.get("JWT_SECRET_KEY")
    _app.config["JWT_SECRET_KEY"] = "test-secret-key-123"
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-123")
    c = _app.test_client()
    yield c
    if saved is not None:
        _app.config["JWT_SECRET_KEY"] = saved
    else:
        _app.config.pop("JWT_SECRET_KEY", None)


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ── Helpers: role logic ──────────────────────────────────────────────────

class TestRolePriority:
    def test_priority_ordering(self):
        assert ROLE_PRIORITY["viewer"] < ROLE_PRIORITY["member"] < ROLE_PRIORITY["admin"]


class TestAuthConfigured:
    def test_true_when_api_key_set(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "k")
        assert auth_configured() is True

    def test_true_when_tenant_keys_set(self, monkeypatch):
        monkeypatch.setenv("TENANT_API_KEYS", '{"acme":"k"}')
        assert auth_configured() is True

    def test_false_open_mode(self, monkeypatch):
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("TENANT_API_KEYS", raising=False)
        assert auth_configured() is False


# ── Users table helpers ──────────────────────────────────────────────────

def _seed_users_db(tmp_path):
    """Create a scratch SQLite with the users + tenants tables so create_user /
    provision_tenant_with_admin / authenticate_user run hermetically."""
    import sqlite3
    db_path = tmp_path / "rbac.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            username TEXT NOT NULL,
            password_hash TEXT DEFAULT '',
            role TEXT DEFAULT 'member',
            created_at INTEGER NOT NULL,
            UNIQUE(tenant_id, username)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tenants (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            plan TEXT NOT NULL DEFAULT 'free',
            max_workers INTEGER NOT NULL DEFAULT 5,
            created_at INTEGER NOT NULL
        )"""
    )
    conn.commit()
    conn.close()
    return db_path


class TestCreateAndAuthenticateUser:
    def test_create_and_authenticate(self, tmp_path):
        db_path = _seed_users_db(tmp_path)
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setenv("DB_PATH", str(db_path))

        res = create_user("acme", "alice", "supersecret", role="admin")
        assert res.get("ok") is True

        # Scoped lookup (explicit tenant)
        user = authenticate_user("alice", "supersecret", tenant_id="acme")
        assert user is not None
        assert user["role"] == "admin"
        assert user["tenant_id"] == "acme"

        # Global lookup (open mode, tenant="default" → across all tenants)
        user_global = authenticate_user("alice", "supersecret")
        assert user_global is not None
        assert user_global["tenant_id"] == "acme"

        # wrong password → None
        assert authenticate_user("alice", "wrongpass", tenant_id="acme") is None
        # unknown user → None
        assert authenticate_user("nobody", "supersecret", tenant_id="acme") is None
        monkeypatch.undo()

    def test_duplicate_username_rejected(self, tmp_path):
        db_path = _seed_users_db(tmp_path)
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setenv("DB_PATH", str(db_path))

        assert create_user("acme", "bob", "password123")["ok"] is True
        dup = create_user("acme", "bob", "password123")
        assert "error" in dup
        monkeypatch.undo()

    def test_provision_tenant_with_admin_creates_fresh_tenant(self, tmp_path):
        """Each signup gets its own tenant — never the operator's 'default'."""
        db_path = _seed_users_db(tmp_path)
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setenv("DB_PATH", str(db_path))

        created = provision_tenant_with_admin("carol", "supersecret", tenant_name="carol")
        assert created.get("ok") is True
        assert created["role"] == "admin"
        assert created["tenant_id"] != "default"
        assert len(created["tenant_id"]) == 16

        # The registered user can authenticate globally (open mode).
        user = authenticate_user("carol", "supersecret")
        assert user is not None
        assert user["tenant_id"] == created["tenant_id"]
        monkeypatch.undo()


class TestEnsureUsersSchema:
    def test_idempotent_migration(self, tmp_path):
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setenv("DB_PATH", str(tmp_path / "legacy.sqlite"))
        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "legacy.sqlite"))
        conn.execute(
            """CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                username TEXT NOT NULL,
                api_key TEXT DEFAULT '',
                created_at INTEGER NOT NULL
            )"""
        )
        conn.commit()
        conn.close()

        ensure_users_schema()  # adds role + password_hash
        conn = sqlite3.connect(str(tmp_path / "legacy.sqlite"))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
        conn.close()
        assert "role" in cols
        assert "password_hash" in cols

        ensure_users_schema()  # idempotent — must not raise
        monkeypatch.undo()


# ── /api/auth/register ───────────────────────────────────────────────────

class TestApiRegister:
    """Self-registration + login by username/password.

    DB_PATH is monkeypatched to a scratch SQLite (seeded with tenants + users
    tables) so these tests never write real rows into data/war_room.sqlite.
    """

    @pytest.fixture(autouse=True)
    def _scratch_db(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(_seed_users_db(tmp_path)))
        monkeypatch.setenv("SECRET_KEY", "test-secret-key-123")

    def test_register_returns_tokens_and_role(self, client):
        res = client.post("/api/auth/register", json={
            "username": "alice", "password": "supersecret",
        })
        assert res.status_code == 201
        data = res.get_json()
        assert data["success"] is True
        assert data["access_token"]
        assert data["refresh_token"]
        assert data["role"] == "admin"
        assert data["tenant_id"] != "default"  # fresh tenant, not operator's

    def test_register_validates_username(self, client):
        res = client.post("/api/auth/register", json={
            "username": "a", "password": "supersecret",
        })
        assert res.status_code == 400

    def test_register_validates_password(self, client):
        res = client.post("/api/auth/register", json={
            "username": "alice", "password": "short",
        })
        assert res.status_code == 400

    def test_login_by_username_password(self, client):
        # register first, then log in with username/password (global lookup
        # finds the user in their provisioned tenant)
        client.post("/api/auth/register", json={
            "username": "alice", "password": "supersecret",
        })
        res = client.post("/api/auth/login", json={
            "username": "alice", "password": "supersecret",
        })
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert data["access_token"]
        assert data["role"] == "admin"

    def test_login_wrong_password_401(self, client):
        client.post("/api/auth/register", json={
            "username": "alice", "password": "supersecret",
        })
        res = client.post("/api/auth/login", json={
            "username": "alice", "password": "nope",
        })
        assert res.status_code == 401

    def test_duplicate_username_register_409(self, client):
        """Global username uniqueness: a second signup with the same username
        must fail (409), never create a second ambiguous account."""
        body = {"username": "dave", "password": "supersecret"}
        assert client.post("/api/auth/register", json=body).status_code == 201
        res = client.post("/api/auth/register", json=body)
        assert res.status_code == 409
        assert "username" in res.get_json().get("error", "")

    def test_refresh_preserves_role(self, client):
        """Privilege-escalation guard: after /api/auth/refresh the new access
        token must carry the SAME role (viewer stays viewer — never admin)."""
        client.post("/api/auth/register", json={
            "username": "erin", "password": "supersecret",
        })
        login = client.post("/api/auth/login", json={
            "username": "erin", "password": "supersecret",
        }).get_json()
        assert login["role"] == "admin"

        # Downgrade a login token to viewer by minting a viewer-role refresh
        # token directly (simulates a viewer session refreshing).
        from services.auth import create_refresh_token, verify_token
        viewer_refresh, _ = create_refresh_token(
            subject=login["tenant_id"], extra_claims={"role": "viewer"}
        )
        res = client.post("/api/auth/refresh", json={"refresh_token": viewer_refresh})
        assert res.status_code == 200
        data = res.get_json()
        assert data["role"] == "viewer"  # never escalated to admin
        payload = verify_token(data["access_token"])
        assert payload["role"] == "viewer"

    def test_refresh_legacy_token_defaults_viewer(self, client):
        """Legacy refresh tokens (no role claim) must NOT escalate to admin —
        they default to the least privilege (viewer)."""
        from services.auth import create_refresh_token, verify_token
        legacy_refresh, _ = create_refresh_token(subject="some-tenant")
        res = client.post("/api/auth/refresh", json={"refresh_token": legacy_refresh})
        assert res.status_code == 200
        data = res.get_json()
        assert data["role"] == "viewer"
        payload = verify_token(data["access_token"])
        assert payload["role"] == "viewer"


# ── RBAC enforcement on axe_fleet write endpoints ────────────────────────

class TestRbacEnforcement:
    """RBAC on axe_fleet write endpoints.

    Hermetic by construction: DB_PATH is monkeypatched to a scratch SQLite
    (users + tenants + axe_fleet tables) so the POST /api/axe-fleet/devices
    calls never write rows into data/war_room.sqlite. As a second line of
    defense, device names keep the Test- prefix so the boot purge
    (_purge_seed_marked_devices / _purge_test_devices) removes any leftovers.
    """

    @pytest.fixture(autouse=True)
    def _scratch_db(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(_seed_users_db(tmp_path)))
        monkeypatch.setenv("SECRET_KEY", "test-secret-key-123")
        # Create the axe_fleet tables in the scratch DB so the real add path
        # (registry → get_db → env DB_PATH) persists into the scratch file.
        from app import _axe_registry
        _axe_registry.ensure_tables()

    def test_open_mode_never_blocks_selfhost(self, client, monkeypatch):
        # No API_KEY / TENANT_API_KEYS → operator is admin, writes pass RBAC.
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("TENANT_API_KEYS", raising=False)
        monkeypatch.setenv("SECRET_KEY", "test-secret-key-123")
        res = client.post("/api/axe-fleet/devices", json={
            "ip_address": "192.168.1.250", "name": "Test-rbac-open",
        })
        # Registry exists; open mode passes RBAC. (May 400/500 on real add,
        # but must NOT be the RBAC 403 shape.)
        assert res.status_code != 403
        assert res.get_json().get("error") != "permission denied"

    def test_viewer_role_blocked_from_write(self, client, monkeypatch):
        monkeypatch.setenv("API_KEY", "master-key")
        monkeypatch.setenv("SECRET_KEY", "test-secret-key-123")
        from services.auth import create_token
        viewer_token = create_token(subject="default", extra_claims={"role": "viewer"})
        res = client.post(
            "/api/axe-fleet/devices",
            json={"ip_address": "192.168.1.251", "name": "Test-rbac-viewer"},
            headers=_auth_headers(viewer_token),
        )
        assert res.status_code == 403
        body = res.get_json()
        assert body["required_role"] == "member"

    def test_member_role_allowed(self, client, monkeypatch):
        monkeypatch.setenv("API_KEY", "master-key")
        monkeypatch.setenv("SECRET_KEY", "test-secret-key-123")
        from services.auth import create_token
        member_token = create_token(subject="default", extra_claims={"role": "member"})
        res = client.post(
            "/api/axe-fleet/devices",
            json={"ip_address": "192.168.1.252", "name": "Test-rbac-member"},
            headers=_auth_headers(member_token),
        )
        # RBAC passes for member → real add path (201 or 409 dup / 500 reg error),
        # never the RBAC 403.
        assert res.status_code != 403
        assert res.get_json().get("error") != "permission denied"


# ── RBAC on read routes (login required even for reads) ──────────────────

class TestRbacReadRoutes:
    """Read routes (export, backup, wallet/history, donations) now require
    login when auth is configured — anonymous remote callers get 403, while
    viewer+ tokens pass and open self-host mode stays unaffected.

    Requests are made with a non-localhost REMOTE_ADDR because
    get_current_role() maps localhost to admin by design (the deployment
    operator) — the anonymous 403 path must be exercised from a remote
    address to prove the "login even for reads" rule.
    """

    @pytest.fixture(autouse=True)
    def _scratch_db(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(_seed_users_db(tmp_path)))
        monkeypatch.setenv("SECRET_KEY", "test-secret-key-123")
        # Seed the read-route tables so viewer/member/open-mode requests that
        # PASS the RBAC gate reach the handler without crashing (api_export has
        # no try/except, so a missing snapshots table would raise in-test).
        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "rbac.sqlite"))
        conn.execute("CREATE TABLE IF NOT EXISTS snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT, updated_ts INTEGER)")
        conn.execute("CREATE TABLE IF NOT EXISTS wallet_address_history (id INTEGER PRIMARY KEY AUTOINCREMENT, address TEXT NOT NULL, worker TEXT DEFAULT '', connected_at INTEGER NOT NULL, label TEXT DEFAULT '')")
        conn.execute("CREATE TABLE IF NOT EXISTS donations (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, method TEXT DEFAULT 'lightning', amount_sat INTEGER, txid TEXT DEFAULT '', preimage TEXT DEFAULT '', note TEXT DEFAULT '', source TEXT DEFAULT 'webln')")
        conn.commit()
        conn.close()

    READ_ROUTES = [
        "/api/export/snapshots.csv",
        "/api/config/backup",
        "/api/wallet/history",
        "/api/donations",
    ]

    def test_donation_post_stays_open_to_anonymous(self, client, monkeypatch):
        """The public WebLN/manual donation-record POST must NOT be RBAC-gated
        (anonymous donors report proof of payment) — only tenant resolution."""
        monkeypatch.setenv("API_KEY", "master-key")
        res = client.post("/api/donations", json={"txid": "anon-tx-123", "amount_sat": 5000},
                          environ_base={"REMOTE_ADDR": "203.0.113.7"})
        # Not 403: anonymous donation recording must keep working.
        assert res.status_code in (201, 409)

    def _get_remote(self, client, path, headers=None):
        """GET as a non-localhost remote caller (bypasses localhost→admin)."""
        return client.get(path, headers=headers or {},
                          environ_base={"REMOTE_ADDR": "203.0.113.7"})

    def test_anonymous_remote_blocked_from_reads(self, client, monkeypatch):
        monkeypatch.setenv("API_KEY", "master-key")
        for route in self.READ_ROUTES:
            res = self._get_remote(client, route)
            assert res.status_code == 403, f"{route}: expected 403, got {res.status_code}"
            body = res.get_json()
            assert body.get("required_role") == "viewer"

    def test_viewer_token_allowed_on_reads(self, client, monkeypatch):
        monkeypatch.setenv("API_KEY", "master-key")
        from services.auth import create_token
        viewer_token = create_token(subject="default", extra_claims={"role": "viewer"})
        for route in self.READ_ROUTES:
            res = self._get_remote(client, route, headers=_auth_headers(viewer_token))
            # RBAC must pass (never the 403 shape) — the route itself may
            # 200/400/500 depending on scratch-DB tables; that's out of scope.
            # Note: /api/export/snapshots.csv returns CSV text, so use
            # get_json(silent=True) (None for non-JSON bodies).
            assert res.status_code != 403, f"{route}: viewer should not be blocked"
            data = res.get_json(silent=True) or {}
            assert data.get("error") != "permission denied"

    def test_member_and_admin_tokens_allowed_on_reads(self, client, monkeypatch):
        monkeypatch.setenv("API_KEY", "master-key")
        from services.auth import create_token
        for role in ("member", "admin"):
            token = create_token(subject="default", extra_claims={"role": role})
            for route in self.READ_ROUTES:
                res = self._get_remote(client, route, headers=_auth_headers(token))
                assert res.status_code != 403, f"{route}: {role} should not be blocked"

    def test_open_mode_reads_unaffected(self, client, monkeypatch):
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("TENANT_API_KEYS", raising=False)
        for route in self.READ_ROUTES:
            res = self._get_remote(client, route)
            assert res.status_code != 403, f"{route}: open mode must not block"


# ── CORS (env-gated) ─────────────────────────────────────────────────────

class TestCorsHeaders:
    def _get_snapshot(self, client, monkeypatch, headers=None):
        """Hit /api/snapshot without triggering live provider fetches
        (monkeypatch _get_hashrate_market_offers to a no-op) so the header
        assertions never depend on the network."""
        monkeypatch.setattr("app._get_hashrate_market_offers", lambda: None)
        return client.get("/api/snapshot", headers=headers or {})

    def test_no_cors_when_unset(self, client, monkeypatch):
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        res = self._get_snapshot(client, monkeypatch)
        assert res.headers.get("Access-Control-Allow-Origin") is None

    def test_cors_wildcard(self, client, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", "*")
        res = self._get_snapshot(client, monkeypatch, {"Origin": "https://app.example.com"})
        assert res.headers.get("Access-Control-Allow-Origin") == "*"
        assert "GET" in res.headers.get("Access-Control-Allow-Methods", "")

    def test_cors_allowlist(self, client, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com,https://x.io")
        res = self._get_snapshot(client, monkeypatch, {"Origin": "https://app.example.com"})
        assert res.headers.get("Access-Control-Allow-Origin") == "https://app.example.com"
        # non-listed origin → no CORS header
        res2 = self._get_snapshot(client, monkeypatch, {"Origin": "https://evil.io"})
        assert res2.headers.get("Access-Control-Allow-Origin") is None
