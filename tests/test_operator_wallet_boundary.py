"""Issue #856: exercise legacy wallet routes against a real isolated database."""

import json
import sqlite3
import socket

import pytest

import app as app_module
from services.auth import create_refresh_token, create_token, revoke_token

OLD_ADDRESS = "operator-fixture-wallet"
NEW_ADDRESS = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
SECRET = "operator-wallet-test-secret-0123456789-0123456789"
PATHS = ("/api/set-address", "/api/wallet/history")


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """Use actual handlers, synthetic identities and SQLite; deny all networking."""
    db_path = tmp_path / "wallet.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        "CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT,updated_ts INTEGER);"
        "CREATE TABLE wallet_address_history(id INTEGER PRIMARY KEY,address TEXT,"
        "worker TEXT,connected_at INTEGER,label TEXT);"
        "CREATE TABLE snapshots(id INTEGER PRIMARY KEY,fixture TEXT);"
        "CREATE TABLE proximity_history(id INTEGER PRIMARY KEY,fixture TEXT);"
        "CREATE TABLE share_timeline(id INTEGER PRIMARY KEY,fixture TEXT);"
    )
    conn.execute("INSERT INTO settings VALUES('_wallet_address',?,1)", (OLD_ADDRESS,))
    conn.execute(
        "INSERT INTO wallet_address_history VALUES(1,?,'private-worker',1,'private')",
        (OLD_ADDRESS,),
    )
    for table in ("snapshots", "proximity_history", "share_timeline"):
        conn.execute(f"INSERT INTO {table} VALUES(1,'operator-only')")
    conn.commit()
    conn.close()
    calls = {"db": 0, "reset": 0, "threads": 0, "network": 0}

    def database():
        calls["db"] += 1
        result = sqlite3.connect(db_path)
        result.row_factory = sqlite3.Row
        return result

    def deny_network(*args, **kwargs):
        calls["network"] += 1
        raise AssertionError("Network forbidden in wallet boundary tests")

    def reset():
        calls["reset"] += 1

    def thread_start(self):
        calls["threads"] += 1

    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("SECRET_KEY", SECRET)
    monkeypatch.setenv("API_KEY", "operator-fixture-key")
    monkeypatch.setenv("TENANT_API_KEYS", json.dumps({"tenant-a": "tenant-a-key"}))
    monkeypatch.setitem(app_module.app.config, "TESTING", True)
    monkeypatch.setitem(app_module.app.config, "JWT_SECRET_KEY", SECRET)
    monkeypatch.setitem(app_module.app.config, "SECRET_KEY", SECRET)
    monkeypatch.setattr(app_module, "get_db", database)
    monkeypatch.setattr(app_module, "BTC_ADDRESS", OLD_ADDRESS)
    monkeypatch.setattr(app_module, "WORKER_NAME", "operator-worker")
    monkeypatch.setattr(app_module, "_reset_session_state", reset)
    monkeypatch.setattr(app_module, "memory_critical_alerts", [])
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr("requests.sessions.Session.request", deny_network)
    monkeypatch.setattr(app_module.threading.Thread, "start", thread_start)
    yield app_module.app.test_client(), db_path, calls


def bearer(tenant="default", role="admin", *, refresh=False, extra=None):
    """Mint only fixture credentials with the current test app configuration."""
    claims = {} if role is None else {"role": role}
    claims.update(extra or {})
    with app_module.app.app_context():
        if refresh:
            token, _ = create_refresh_token(tenant, extra_claims=claims)
        else:
            token = create_token(tenant, extra_claims=claims)
    return {"Authorization": "Bearer " + token}


def send(client, path, headers=None, *, local=False):
    environ = {"REMOTE_ADDR": "127.0.0.1" if local else "198.51.100.50"}
    if path == "/api/set-address":
        return client.post(
            path,
            json={"address": NEW_ADDRESS, "worker": "new-worker"},
            headers=headers or {},
            environ_overrides=environ,
        )
    return client.get(path, headers=headers or {}, environ_overrides=environ)


def assert_untouched(harness, response):
    """A rejection must happen before any operator read, mutation or background work."""
    _, db_path, calls = harness
    assert calls == {"db": 0, "reset": 0, "threads": 0, "network": 0}
    assert app_module.BTC_ADDRESS == OLD_ADDRESS
    assert app_module.WORKER_NAME == "operator-worker"
    assert OLD_ADDRESS not in response.get_data(as_text=True)
    assert "private-worker" not in response.get_data(as_text=True)
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT value FROM settings").fetchone()[0] == OLD_ADDRESS
        for table in ("snapshots", "proximity_history", "share_timeline"):
            assert conn.execute(f"SELECT fixture FROM {table}").fetchall() == [
                ("operator-only",)
            ]
        assert (
            conn.execute("SELECT COUNT(*) FROM wallet_address_history").fetchone()[0]
            == 1
        )
    finally:
        conn.close()


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("tenant", ("tenant-a", "tenant-b"))
@pytest.mark.parametrize("role", ("viewer", "member", "admin"))
def test_named_tenant_never_reads_or_changes_operator_wallet(
    harness, path, tenant, role
):
    response = send(harness[0], path, bearer(tenant, role))
    assert response.status_code == 403
    assert response.json["code"] == "OPERATOR_SCOPED_DATA"
    assert_untouched(harness, response)


@pytest.mark.parametrize("role", ("viewer", "member", "unknown"))
@pytest.mark.parametrize("local", (False, True))
def test_default_tenant_does_not_imply_mutation_authority(harness, role, local):
    response = send(harness[0], PATHS[0], bearer(role=role), local=local)
    assert response.status_code == 403
    assert_untouched(harness, response)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("open_mode", (False, True))
@pytest.mark.parametrize(
    "headers",
    (
        {"Authorization": "Bearer invalid"},
        {"Authorization": "Basic invalid"},
        {"Authorization": ""},
        {"X-API-Key": "invalid"},
        {"X-API-Key": ""},
        {"X-API-Key": "\N{LATIN SMALL LETTER E WITH ACUTE}"},
    ),
)
def test_explicit_invalid_credentials_never_fall_back(
    harness, monkeypatch, path, open_mode, headers
):
    if open_mode:
        monkeypatch.delenv("API_KEY")
        monkeypatch.delenv("TENANT_API_KEYS")
    response = send(harness[0], path, headers, local=True)
    assert response.status_code == 401
    assert_untouched(harness, response)


@pytest.mark.parametrize("path", PATHS)
def test_conflicting_valid_credentials_rejected(harness, path):
    headers = {**bearer(), "X-API-Key": "tenant-a-key"}
    response = send(harness[0], path, headers)
    assert response.status_code == 401
    assert_untouched(harness, response)


@pytest.mark.parametrize("path", PATHS)
def test_named_api_key_cannot_reach_operator_resources(harness, path):
    response = send(harness[0], path, {"X-API-Key": "tenant-a-key"})
    assert response.status_code == 403
    assert_untouched(harness, response)


@pytest.mark.parametrize("path", PATHS)
def test_session_cannot_conflict_with_bearer(harness, path):
    with harness[0].session_transaction() as session:
        session.update(authenticated=True, tenant_id="tenant-a", role="admin")
    response = send(harness[0], path, bearer())
    assert response.status_code == 401
    assert_untouched(harness, response)


@pytest.mark.parametrize("path", PATHS)
def test_named_legacy_session_rejected(harness, path):
    with harness[0].session_transaction() as session:
        session.update(authenticated=True, tenant_id="tenant-a", role="admin")
    response = send(harness[0], path)
    assert response.status_code == 403
    assert_untouched(harness, response)


@pytest.mark.parametrize("path", PATHS)
def test_refresh_and_revoked_credentials_rejected(harness, path):
    response = send(harness[0], path, bearer(refresh=True))
    assert response.status_code == 401
    headers = bearer()
    token = headers["Authorization"][7:]
    with app_module.app.app_context():
        revoke_token(token)
    try:
        response = send(harness[0], path, headers)
        assert response.status_code == 401
        assert_untouched(harness, response)
    finally:
        from services.auth import _blacklisted_tokens

        _blacklisted_tokens.pop(token, None)


@pytest.mark.parametrize("path", PATHS)
def test_anonymous_remote_blocked_with_auth_configured(harness, path):
    response = send(harness[0], path)
    assert response.status_code == 403
    assert_untouched(harness, response)


@pytest.mark.parametrize(
    "mode", ("admin", "api-key", "legacy-token", "session", "localhost", "open")
)
def test_authorized_operator_mutation_preserves_existing_behavior(
    harness, monkeypatch, mode
):
    client, db_path, calls = harness
    headers = bearer()
    if mode == "api-key":
        headers = {"X-API-Key": "operator-fixture-key"}
    elif mode == "legacy-token":
        headers = bearer(role=None)
    elif mode == "session":
        headers = {}
        with client.session_transaction() as session:
            session.update(authenticated=True, tenant_id="default", role="admin")
    elif mode in ("localhost", "open"):
        headers = {}
        if mode == "open":
            monkeypatch.delenv("API_KEY")
            monkeypatch.delenv("TENANT_API_KEYS")
    response = send(client, PATHS[0], headers, local=mode == "localhost")
    assert response.status_code == 200
    assert app_module.BTC_ADDRESS == NEW_ADDRESS
    assert calls["reset"] == calls["threads"] == 1
    assert calls["network"] == 0
    conn = sqlite3.connect(db_path)
    try:
        assert (
            conn.execute(
                "SELECT value FROM settings WHERE key='_wallet_address'"
            ).fetchone()[0]
            == NEW_ADDRESS
        )
        assert conn.execute("SELECT COUNT(*) FROM share_timeline").fetchone()[0] == 0
    finally:
        conn.close()


def test_authorized_default_viewer_can_read_history_but_not_mutate(harness):
    response = send(harness[0], PATHS[1], bearer(role="viewer"))
    assert response.status_code == 200
    assert response.json["history"][0]["address"] == OLD_ADDRESS
    assert harness[2]["reset"] == harness[2]["threads"] == 0


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("subject", ("", "   "))
def test_empty_bearer_subject_rejected(harness, path, subject):
    response = send(harness[0], path, bearer(subject))
    assert response.status_code == 401
    assert_untouched(harness, response)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("tenant", ("", 123))
def test_invalid_authenticated_session_rejected(harness, path, tenant):
    with harness[0].session_transaction() as session:
        session.update(authenticated=True, tenant_id=tenant, role="admin")
    response = send(harness[0], path)
    assert response.status_code == 401
    assert_untouched(harness, response)


@pytest.mark.parametrize("path", PATHS)
def test_named_tenant_still_rejected_when_deployment_auth_is_open(
    harness, monkeypatch, path
):
    monkeypatch.delenv("API_KEY")
    monkeypatch.delenv("TENANT_API_KEYS")
    response = send(harness[0], path, bearer("tenant-a"))
    assert response.status_code == 403
    assert_untouched(harness, response)


def test_valid_operator_key_does_not_upgrade_explicit_viewer(harness):
    headers = {**bearer(role="viewer"), "X-API-Key": "operator-fixture-key"}
    response = send(harness[0], PATHS[0], headers)
    assert response.status_code == 403
    assert_untouched(harness, response)


def test_invalid_decorator_role_is_a_configuration_error():
    from services.operator_wallet import operator_wallet_required

    with pytest.raises(ValueError, match="unknown operator wallet role"):
        operator_wallet_required("anything")


def test_tenant_scoped_wallet_session_flow_remains_available(harness, monkeypatch):
    from services.session_manager import SessionManager

    # Keep the real session store/ownership handlers. Only provider I/O and the
    # polling worker are replaced; timer threads are already denied by fixture.
    manager = SessionManager()
    monkeypatch.setattr(app_module, "_session_manager", manager)
    monkeypatch.setattr(app_module, "_session_workers", {})
    monkeypatch.setattr(app_module, "_resolve_pool_for_address", lambda *args: None)

    class Worker:
        def __init__(self, sid, store, address, name, tenant_id):
            self.sid, self.store = sid, store
            self.value = {"btc_address": address, "tenant_scope": tenant_id}

        def start(self):
            return None

        def poll_now(self):
            self.store.update_snapshot(self.sid, self.value)
            return self.value

    monkeypatch.setattr(app_module, "UserPollingWorker", Worker)
    client = harness[0]
    response = client.post(
        "/api/connect-wallet",
        json={"address": NEW_ADDRESS, "worker": "tenant-worker"},
        headers=bearer("tenant-a", "member"),
        environ_overrides={"REMOTE_ADDR": "198.51.100.50"},
    )
    assert response.status_code == 200
    sid = response.json["session_id"]
    assert manager.get_session(sid).tenant_id == "tenant-a"
    own = client.get(
        "/api/session-snapshot",
        query_string={"session_id": sid},
        headers=bearer("tenant-a"),
    )
    other = client.get(
        "/api/session-snapshot",
        query_string={"session_id": sid},
        headers=bearer("tenant-b"),
    )
    assert own.status_code == 200
    assert own.json["snapshot"]["btc_address"] == NEW_ADDRESS
    assert other.status_code == 404
    assert app_module.BTC_ADDRESS == OLD_ADDRESS
    assert harness[2]["db"] == harness[2]["reset"] == harness[2]["network"] == 0
