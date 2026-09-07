"""Issue #423 — tenant isolation for the Auto-Pilot 7-day peak.

The production schema migration and both consumers must fail closed: a tenant
without history gets zero and can never inherit another tenant's hashrate peak.
"""

import sqlite3
import time

import app as app_module
from services import auto_pilot
from services import snapshot_enrichment


def _create_proximity_table(conn, *, tenant_aware: bool) -> None:
    tenant_column = "tenant_id TEXT NOT NULL DEFAULT 'default'," if tenant_aware else ""
    conn.execute(
        f"""CREATE TABLE proximity_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            {tenant_column}
            best_diff REAL,
            best_diff_str TEXT,
            all_time_best_diff REAL,
            network_difficulty REAL,
            worker_hashrate REAL,
            pct_of_network REAL,
            hot_streak INTEGER DEFAULT 0
        )"""
    )


def _seed_tenant_peaks(db_path, now: int) -> None:
    conn = sqlite3.connect(db_path)
    _create_proximity_table(conn, tenant_aware=True)
    conn.executemany(
        "INSERT INTO proximity_history (ts, tenant_id, worker_hashrate) "
        "VALUES (?, ?, ?)",
        [
            (now - 60, "tenant-a", 100.0),
            (now - 30, "tenant-b", 900.0),
            (now - 8 * 86400, "tenant-a", 5_000.0),
        ],
    )
    conn.commit()
    conn.close()


def test_init_db_migrates_legacy_rows_to_default_tenant(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(db_path)
    _create_proximity_table(conn, tenant_aware=False)
    conn.execute(
        "INSERT INTO proximity_history (ts, worker_hashrate) VALUES (?, ?)",
        (int(time.time()), 65.0),
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("DB_PATH", str(db_path))
    app_module.init_db()

    conn = sqlite3.connect(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(proximity_history)")}
    migrated_tenant = conn.execute(
        "SELECT tenant_id FROM proximity_history"
    ).fetchone()[0]
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(proximity_history)")}
    conn.close()

    assert "tenant_id" in columns
    assert migrated_tenant == "default"
    assert "idx_proximity_history_tenant_ts" in indexes


def test_collect_peak_7d_never_reads_another_tenant(tmp_path, monkeypatch):
    db_path = tmp_path / "peaks.sqlite"
    now = int(time.time())
    _seed_tenant_peaks(db_path, now)
    monkeypatch.setenv("DB_PATH", str(db_path))

    assert auto_pilot._collect_peak_7d("tenant-a") == 100.0
    assert auto_pilot._collect_peak_7d("tenant-b") == 900.0
    assert auto_pilot._collect_peak_7d("tenant-without-history") == 0.0


def test_collect_peak_7d_closes_connection_after_query_error(monkeypatch):
    closed = []

    class BrokenConnection:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("schema unavailable")

        def close(self):
            closed.append(True)

    monkeypatch.setattr("services.db.get_db", lambda: BrokenConnection())

    assert auto_pilot._collect_peak_7d("tenant-a") == 0.0
    assert closed == [True]


def test_snapshot_context_queries_only_resolved_tenant(tmp_path, monkeypatch):
    db_path = tmp_path / "snapshot.sqlite"
    _seed_tenant_peaks(db_path, int(time.time()))
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setattr("services.tenant.get_tenant_id", lambda: "tenant-a")
    monkeypatch.setattr(snapshot_enrichment, "_auto_pilot_engine", None)
    monkeypatch.setattr(snapshot_enrichment, "_auto_pilot_registry", None)

    context = snapshot_enrichment.build_auto_pilot_context()

    assert context["peak_hashrate_7d"] == 100.0
