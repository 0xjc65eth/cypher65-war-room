"""Tests for the traction-gated, read-only Postgres readiness controls."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from services.postgres_readiness import (
    PAID_LICENSE_SOURCES,
    ReadinessError,
    TRACTION_PAID_LICENSES,
    fetch_pinned_gist_snapshot,
    readiness_report,
    schema_map,
)
from services.schema import CURRENT_SCHEMA_VERSION


def _database(path, paid: int = 0) -> str:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE schema_version (
            version INTEGER PRIMARY KEY,
            applied_ts INTEGER NOT NULL
        );
        CREATE TABLE pro_licenses (
            key TEXT PRIMARY KEY,
            plan TEXT NOT NULL DEFAULT 'pro',
            email TEXT DEFAULT '',
            source TEXT DEFAULT 'manual',
            created_at TEXT NOT NULL,
            expires_at TEXT,
            revoked_at TEXT
        );
        CREATE TABLE metric_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            metric TEXT NOT NULL,
            value REAL,
            payload BLOB,
            ts INTEGER NOT NULL
        );
        CREATE INDEX idx_metric_samples
            ON metric_samples(device_id, metric, ts);
        """
    )
    conn.execute(
        "INSERT INTO schema_version(version, applied_ts) VALUES (?, 1)",
        (CURRENT_SCHEMA_VERSION,),
    )
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    for index in range(paid):
        conn.execute(
            "INSERT INTO pro_licenses "
            "(key, plan, source, created_at, expires_at) VALUES (?, 'pro', ?, ?, ?)",
            (f"paid-{index}", sorted(PAID_LICENSE_SOURCES)[index % 3], future, future),
        )
    conn.commit()
    conn.close()
    return str(path)


def test_gate_holds_below_paid_traction_and_redacts_configuration(tmp_path):
    db = _database(tmp_path / "source.sqlite", paid=TRACTION_PAID_LICENSES - 1)
    secret = "postgresql://admin:do-not-print@example.invalid/db"
    report = readiness_report(
        db,
        env={
            "POSTGRES_DSN": secret,
            "GITHUB_TOKEN": "also-secret",
            "REMOTE_BACKUP_GIST_ID": "pinned-id",
        },
    )

    assert report["decision"] == "hold"
    assert report["traction"]["current"] == TRACTION_PAID_LICENSES - 1
    assert report["traction"]["met"] is False
    encoded = json.dumps(report)
    assert secret not in encoded
    assert "also-secret" not in encoded
    assert report["cutover_authorized"] is False


def test_only_active_provider_licenses_count_as_paid_traction(tmp_path):
    db = _database(tmp_path / "source.sqlite", paid=1)
    conn = sqlite3.connect(db)
    now = datetime.now(timezone.utc)
    rows = [
        ("manual", "pro", "manual", None, None),
        ("test", "pro", "test", None, None),
        ("revoked", "pro", "btcpay", None, now.isoformat()),
        (
            "expired",
            "premium",
            "webln",
            (now - timedelta(seconds=1)).isoformat(),
            None,
        ),
        ("free-plan", "free", "btcpay", None, None),
        ("paid-premium", "premium", "lemon_squeezy", None, None),
    ]
    conn.executemany(
        "INSERT INTO pro_licenses "
        "(key, plan, source, created_at, expires_at, revoked_at) "
        "VALUES (?, ?, ?, '2026-01-01T00:00:00+00:00', ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()

    report = readiness_report(db, env={}, now=now)
    assert report["traction"]["current"] == 2


def test_rehearsal_requires_real_source_and_target_credentials(tmp_path):
    db = _database(tmp_path / "source.sqlite", paid=TRACTION_PAID_LICENSES)

    missing = readiness_report(db, env={})
    assert missing["decision"] == "rehearsal-required"

    configured = readiness_report(
        db,
        env={
            "POSTGRES_DSN": "postgresql://redacted.invalid/db",
            "GITHUB_TOKEN": "redacted",
            "REMOTE_BACKUP_GIST_ID": "gist-id",
        },
    )
    assert configured["decision"] == "ready-for-rehearsal"
    assert configured["application_portability"]["ready"] is False
    assert configured["cutover_authorized"] is False


def test_schema_map_is_deterministic_and_maps_sqlite_affinities(tmp_path):
    db = _database(tmp_path / "source.sqlite")
    first = schema_map(db)
    second = schema_map(db)

    assert first["schema_sha256"] == second["schema_sha256"]
    metrics = next(
        item for item in first["tables"] if item["table"] == "metric_samples"
    )
    types = {column["name"]: column["postgres_type"] for column in metrics["columns"]}
    assert types == {
        "id": "BIGINT",
        "device_id": "TEXT",
        "metric": "TEXT",
        "value": "DOUBLE PRECISION",
        "payload": "BYTEA",
        "ts": "BIGINT",
    }
    assert (
        next(column for column in metrics["columns"] if column["name"] == "id")[
            "nullable"
        ]
        is False
    )
    assert metrics["indexes"]
    assert metrics["foreign_keys"] == []


def test_missing_or_wrong_schema_blocks_rehearsal(tmp_path):
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(ReadinessError, match="not found"):
        readiness_report(missing)

    db = _database(tmp_path / "old.sqlite", paid=TRACTION_PAID_LICENSES)
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM schema_version")
    conn.execute(
        "INSERT INTO schema_version VALUES (?, 1)", (CURRENT_SCHEMA_VERSION - 1,)
    )
    conn.commit()
    conn.close()
    report = readiness_report(db, env={})
    assert report["decision"] == "blocked"
    assert report["sqlite"]["schema_compatible"] is False


def test_corrupt_sqlite_surfaces_a_safe_readiness_error(tmp_path):
    corrupt = tmp_path / "corrupt.sqlite"
    corrupt.write_bytes(b"SQLite format 3\x00" + b"corrupt")
    with pytest.raises(ReadinessError, match="SQLite"):
        readiness_report(corrupt)


def test_gist_fetch_rejects_unpinned_or_malformed_identifier_without_network():
    with pytest.raises(ReadinessError, match="required"):
        fetch_pinned_gist_snapshot(env={})
    with pytest.raises(ReadinessError, match="valid Gist identifier"):
        fetch_pinned_gist_snapshot(
            env={
                "GITHUB_TOKEN": "must-not-leak",
                "REMOTE_BACKUP_GIST_ID": "../../attacker",
            }
        )


def test_cli_reports_local_database_without_writing_it(tmp_path):
    db = _database(tmp_path / "source.sqlite")
    before = os.stat(db).st_mtime_ns
    result = subprocess.run(
        [sys.executable, "scripts/postgres_readiness.py", "--db", db],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["source"] == "local-sqlite"
    assert os.stat(db).st_mtime_ns == before


def test_admin_readiness_endpoint_is_gated_and_uses_runtime_database(
    tmp_path, monkeypatch
):
    import app as app_module

    db = _database(tmp_path / "runtime.sqlite")
    monkeypatch.setenv("DB_PATH", db)
    client = app_module.app.test_client()

    denied = client.get(
        "/api/admin/postgres-readiness",
        environ_base={"REMOTE_ADDR": "203.0.113.5"},
    )
    assert denied.status_code == 403

    allowed = client.get("/api/admin/postgres-readiness")
    assert allowed.status_code == 200
    body = allowed.get_json()
    assert body["decision"] == "hold"
    assert body["traction"]["current"] == 0
    assert body["external_prerequisites"]["values_redacted"] is True


def test_admin_readiness_endpoint_surfaces_unreadable_database(tmp_path, monkeypatch):
    import app as app_module

    monkeypatch.setenv("DB_PATH", str(tmp_path / "missing.sqlite"))
    response = app_module.app.test_client().get("/api/admin/postgres-readiness")
    assert response.status_code == 503
    assert response.get_json()["decision"] == "blocked"


def test_read_only_failure_with_pending_wal_never_falls_back_to_stale_snapshot(
    tmp_path, monkeypatch
):
    db = _database(tmp_path / "source.sqlite")
    (tmp_path / "source.sqlite-wal").write_bytes(b"pending")
    real_connect = sqlite3.connect

    def fail_normal_read_only(database, *args, **kwargs):
        if "mode=ro" in str(database) and "immutable=1" not in str(database):
            raise sqlite3.OperationalError("simulated lock probe failure")
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(
        "services.postgres_readiness.sqlite3.connect", fail_normal_read_only
    )
    with pytest.raises(ReadinessError, match="non-empty WAL"):
        readiness_report(db)


@pytest.mark.skipif(
    not (
        os.environ.get("GITHUB_TOKEN")
        and os.environ.get("REMOTE_BACKUP_GIST_ID")
        and os.environ.get("RUN_REAL_GIST_TEST") == "1"
    ),
    reason="requires explicit real private-Gist integration credentials",
)
def test_real_pinned_gist_snapshot_is_current_and_integral(tmp_path):
    raw = fetch_pinned_gist_snapshot()
    assert raw.startswith(b"SQLite format 3\x00")
    snapshot = tmp_path / "real-gist.sqlite"
    snapshot.write_bytes(raw)
    report = readiness_report(snapshot)
    assert report["sqlite"]["integrity"] == "ok"
    assert report["sqlite"]["schema_version"] == CURRENT_SCHEMA_VERSION
