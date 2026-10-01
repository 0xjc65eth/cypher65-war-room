"""Security contract tests for persisted command audit records (AUD-001)."""

import json
import sqlite3
from datetime import UTC, datetime

import pytest
from flask import g

import app as app_module


@pytest.fixture
def audit_db(tmp_path, monkeypatch):
    """Initialize the real schema against an isolated SQLite database."""
    db_path = tmp_path / "audit.sqlite"
    monkeypatch.setenv("DB_PATH", str(db_path))

    from services.bootstrap import init_db

    init_db()
    yield db_path


@pytest.mark.parametrize(
    ("result", "expected_success"),
    [
        ({"success": True, "operation_id": "op-success"}, True),
        (
            {
                "success": False,
                "reason": "safety_blocked",
                "error": "command blocked by policy",
            },
            False,
        ),
        (
            {
                "success": False,
                "reason": "adapter_error",
                "error": "device rejected token audit-test-token",
            },
            False,
        ),
    ],
    ids=("success", "blocked", "error"),
)
def test_command_audit_persists_actor_scope_outcome_and_utc(
    audit_db, monkeypatch, result, expected_success
):
    """Persist successful, blocked, and failed attempts without credentials."""
    import services.tenant as tenant

    tenant_id = "audit-tenant"
    actor = "operator-17"
    device_id = "device-audit-42"
    event_time = datetime(2026, 10, 1, 9, 30, tzinfo=UTC)
    epoch = int(event_time.timestamp())
    monkeypatch.setattr(tenant, "get_tenant_id", lambda: tenant_id)
    monkeypatch.setattr("time.time", lambda: epoch)

    parameters = {
        "frequency": 525,
        "password": "audit-test-password",
        "secret": "audit-test-secret",
        "token": "audit-test-token",
        "private_key": "audit-test-private-key",
        "authorization": "Bearer audit-test-authorization",
    }
    with app_module.app.test_request_context("/api/devices/device/command"):
        g.auth_payload = {"username": actor}
        app_module._record_command(device_id, "set_frequency", parameters, result)

    from services.tenant import recent_audit_logs

    rows = recent_audit_logs(tenant_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["user_id"] == actor
    assert row["tenant_id"] == tenant_id
    assert row["target"] == device_id
    assert row["action"] == "device.command"
    assert row["ts"] == epoch
    assert datetime.fromtimestamp(row["ts"], UTC) == event_time
    assert row["details"]["command"] == "set_frequency"
    assert row["details"]["success"] is expected_success
    expected_reason = "command_failed" if result.get("reason") else None
    assert row["details"]["reason"] == expected_reason
    assert row["details"]["parameters"]["frequency"] == 525

    serialized = json.dumps(row, sort_keys=True)
    for credential in parameters.values():
        if isinstance(credential, str):
            assert credential not in serialized
    assert "audit-test-token" not in serialized
    history = app_module._command_history[(tenant_id, device_id)][-1]
    assert "audit-test-token" not in json.dumps(history, sort_keys=True)
    if result.get("error"):
        assert row["details"]["error"] == "command_failed"
    for key in ("password", "secret", "token", "private_key", "authorization"):
        assert row["details"]["parameters"][key] == "[REDACTED]"


def test_audit_rows_reject_updates_and_deletes(audit_db):
    """Persisted audit evidence is immutable at the database boundary."""
    from services.tenant import log_audit, recent_audit_logs

    row_id = log_audit("audit-tenant", "device.command", "device-1")
    assert row_id is not None

    conn = sqlite3.connect(audit_db)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE audit_logs SET action=? WHERE id=?",
                ("tampered", row_id),
            )
        conn.rollback()

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM audit_logs WHERE id=?", (row_id,))
        conn.rollback()

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                """INSERT OR REPLACE INTO audit_logs
                   (id, ts, tenant_id, user_id, action, target, details)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    row_id,
                    1_800_000_000,
                    "audit-tenant",
                    "attacker",
                    "tampered",
                    "device-1",
                    "{}",
                ),
            )
        conn.rollback()
    finally:
        conn.close()

    rows = recent_audit_logs("audit-tenant")
    assert len(rows) == 1
    assert rows[0]["id"] == row_id
    assert rows[0]["action"] == "device.command"


def test_audit_history_orders_same_second_by_newest_id(audit_db, monkeypatch):
    """Tied timestamps have a deterministic newest-first ordering."""
    import services.tenant as tenant

    monkeypatch.setattr(tenant.time, "time", lambda: 1_798_000_000)
    first_id = tenant.log_audit("audit-tenant", "test.first")
    second_id = tenant.log_audit("audit-tenant", "test.second")

    rows = tenant.recent_audit_logs("audit-tenant")
    assert [row["id"] for row in rows] == [second_id, first_id]
    assert [row["action"] for row in rows] == ["test.second", "test.first"]
    assert rows[0]["ts"] == rows[1]["ts"] == 1_798_000_000
