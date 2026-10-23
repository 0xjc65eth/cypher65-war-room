"""Real registry initialization and additive latest-evidence query index."""

import sqlite3

from axe_fleet.registry import DeviceRegistry


def test_registry_energy_index_idempotent_and_serves_latest_query(tmp_path):
    path = tmp_path / "registry.sqlite"

    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    registry = DeviceRegistry(connect)
    registry.ensure_tables()
    registry.ensure_tables()
    conn = connect()
    indexes = conn.execute("PRAGMA index_list(axe_telemetry)").fetchall()
    assert (
        sum(row["name"] == "idx_axe_telemetry_tenant_device_ts" for row in indexes) == 1
    )
    plan = " ".join(
        row["detail"]
        for row in conn.execute(
            "EXPLAIN QUERY PLAN SELECT ts,payload FROM axe_telemetry "
            "WHERE tenant_id=? AND device_id=? ORDER BY ts DESC,id DESC LIMIT 1",
            ("tenant-a", "device-a"),
        )
    )
    assert "idx_axe_telemetry_tenant_device_ts" in plan
    assert "TEMP B-TREE" not in plan
    conn.close()
