"""Actual-SQLite thermal history contracts; no miner or provider connections."""

import json
import sqlite3

from flask import Flask
import pytest

from routes.thermal_timeline import create_thermal_blueprint
from services.thermal_timeline import build_thermal_timeline, list_timeline_devices

NOW = 2_000_000_000


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "thermal.sqlite"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE axe_devices(id TEXT PRIMARY KEY,name TEXT,tenant_id TEXT,
          mac_address TEXT,status TEXT,removed_at INTEGER DEFAULT 0);
        CREATE TABLE axe_telemetry(id INTEGER PRIMARY KEY AUTOINCREMENT,ts INTEGER,
          tenant_id TEXT,device_id TEXT,payload TEXT);
        CREATE INDEX idx_axe_telemetry_tenant_device_ts
          ON axe_telemetry(tenant_id,device_id,ts DESC,id DESC);
        CREATE TABLE devices(id TEXT PRIMARY KEY,tenant_id TEXT,mac TEXT);
        CREATE TABLE maintenance_records(id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts INTEGER,device_id TEXT,type TEXT,tenant_id TEXT,notes TEXT,performed_by TEXT);
        INSERT INTO axe_devices VALUES('axe-a','A','a','aa:bb:cc:dd:ee:02','ONLINE',0);
        INSERT INTO axe_devices VALUES('axe-b','B','b','aa:bb:cc:dd:ee:02','ONLINE',0);
        INSERT INTO axe_devices VALUES('gone','Removed','a','','OFFLINE',1);
        """
    )
    conn.commit()
    yield conn, path
    conn.close()


def insert(conn, payload, ts=NOW - 30, *, tenant="a", device="axe-a"):
    conn.execute(
        "INSERT INTO axe_telemetry(ts,tenant_id,device_id,payload) VALUES(?,?,?,?)",
        (ts, tenant, device, json.dumps(payload)),
    )
    conn.commit()


def timeline(conn, **kwargs):
    return build_thermal_timeline(conn, "a", "axe-a", now=NOW, **kwargs)


def test_allowlist_and_real_zeros(db):
    conn, _ = db
    insert(
        conn,
        {
            "hashrate_hs": 0,
            "temperature": 0,
            "fan_rpm": 0,
            "fan_speed": 35,
            "power_watts": 0,
            "pool_user": "SECRET",
            "ip": "SECRET",
            "mac": "SECRET",
        },
    )
    result = timeline(conn)
    sample = result["samples"][0]
    assert sample["hashrate_hs"] == sample["temperature_c"] == sample["fan_rpm"] == 0
    assert sample["fan_speed"] == 35
    assert sample["frequency_mhz"] is None
    assert sample["window_seconds"] is None
    assert "SECRET" not in json.dumps(result)
    assert result["state"] == "current"
    assert result["stale_after_s"] == 900


@pytest.mark.parametrize(
    "value", [True, "42", -1, float("nan"), float("inf"), 10**1000]
)
def test_invalid_required_hash_is_not_a_measurement(db, value):
    conn, _ = db
    insert(conn, {"hashrate_hs": value, "temperature": 42})
    result = timeline(conn)
    assert result["samples"] == []
    assert result["state"] == "unknown"
    assert result["coverage"]["skipped"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("temperature", -41),
        ("temperature", 151),
        ("temperature", True),
        ("temperature", "30"),
        ("fan_rpm", 100001),
        ("fan_speed", 101),
        ("power_watts", -1),
        ("voltage_mv", float("inf")),
        ("frequency_mhz", 10**1000),
    ],
)
def test_invalid_optional_sensor_is_null_not_zero(db, field, value):
    conn, _ = db
    insert(conn, {"hashrate_hs": 5, field: value})
    sample = timeline(conn)["samples"][0]
    assert sample["temperature_c" if field == "temperature" else field] is None


@pytest.mark.parametrize("payload", [{}, [], {"ts": NOW}, {"temperature": 50}])
def test_heartbeat_or_invalid_shape_not_plotted(db, payload):
    conn, _ = db
    insert(conn, payload)
    assert timeline(conn)["samples"] == []


def test_bounded_newest_samples_duplicates_gaps_and_markers(db):
    conn, _ = db
    insert(conn, {"hashrate_hs": 1, "voltage_mv": 1000}, NOW - 2000)
    insert(conn, {"hashrate_hs": 2, "voltage_mv": 1100}, NOW - 999)
    insert(conn, {"hashrate_hs": 3, "voltage_mv": 1100}, NOW - 99)
    insert(conn, {"hashrate_hs": 4, "voltage_mv": 1200, "fan_speed": 25}, NOW - 30)
    insert(conn, {"hashrate_hs": 5, "voltage_mv": 1300, "fan_speed": 30}, NOW - 30)
    result = timeline(conn)
    assert [sample["hashrate_hs"] for sample in result["samples"]] == [1, 2, 3, 5]
    assert result["coverage"]["gaps"] == 1
    assert result["samples"][1]["gap_before_seconds"] == 1001
    assert len(result["markers"]) == 1
    assert result["markers"][0]["changes"] == [
        {"field": "voltage_mv", "before": 1100, "after": 1300}
    ]
    for i in range(305):
        insert(conn, {"hashrate_hs": i}, NOW - i)
    result = timeline(conn)
    assert result["coverage"]["returned"] <= 300
    assert result["coverage"]["scanned"] == 300
    assert result["coverage"]["truncated"] is True
    plan = conn.execute(
        "EXPLAIN QUERY PLAN SELECT id,ts,payload FROM axe_telemetry WHERE tenant_id=? AND device_id=? AND ts BETWEEN ? AND ? ORDER BY ts DESC,id DESC LIMIT 301",
        ("a", "axe-a", NOW - 3600, NOW),
    ).fetchall()
    assert any("idx_axe_telemetry_tenant_device_ts" in str(tuple(row)) for row in plan)


def test_boundary_stale_offline_and_empty(db):
    conn, _ = db
    assert timeline(conn)["state"] == "empty"
    insert(conn, {"hashrate_hs": 1}, NOW - 900)
    assert timeline(conn)["state"] == "current"
    conn.execute("UPDATE axe_telemetry SET ts=?", (NOW - 901,))
    assert timeline(conn)["state"] == "stale"
    conn.execute("UPDATE axe_devices SET status='OFFLINE' WHERE id='axe-a'")
    assert timeline(conn)["state"] == "offline"
    conn.execute("UPDATE axe_devices SET status='PAUSED' WHERE id='axe-a'")
    assert timeline(conn)["state"] == "offline"
    conn.execute("UPDATE axe_devices SET status='sensitive extension' WHERE id='axe-a'")
    assert timeline(conn)["device"]["status"] == "UNKNOWN"


def test_tenant_tombstone_window_future_and_payload_guards(db):
    conn, _ = db
    insert(conn, {"hashrate_hs": 99}, tenant="b")
    insert(conn, {"hashrate_hs": 99}, NOW + 1)
    insert(conn, {"hashrate_hs": 99}, NOW - 3601)
    insert(conn, {"hashrate_hs": 1})
    conn.execute(
        "INSERT INTO axe_telemetry(ts,tenant_id,device_id,payload) VALUES(?,?,?,?)",
        (NOW - 2, "a", "axe-a", "{"),
    )
    insert(conn, {"hashrate_hs": 2, "unknown": "X" * 66000}, NOW - 1)
    result = timeline(conn, hours=1)
    assert [sample["hashrate_hs"] for sample in result["samples"]] == [1]
    assert result["coverage"]["skipped"] == 2
    assert build_thermal_timeline(conn, "b", "axe-a", now=NOW) is None
    assert build_thermal_timeline(conn, "a", "gone", now=NOW) is None
    assert list_timeline_devices(conn, "a")["devices"] == [{"id": "axe-a", "name": "A"}]
    for bad in ("", None):
        with pytest.raises(ValueError):
            build_thermal_timeline(conn, bad, "axe-a", now=NOW)
        with pytest.raises(ValueError):
            list_timeline_devices(conn, bad)
    for hours in (True, 2, "6"):
        with pytest.raises(ValueError):
            timeline(conn, hours=hours)


def test_picker_bounded(db):
    conn, _ = db
    conn.executemany(
        "INSERT INTO axe_devices VALUES(?,?,?,?,?,0)",
        [(f"x{i}", f"X{i}", "a", "", "ONLINE") for i in range(105)],
    )
    result = list_timeline_devices(conn, "a")
    assert len(result["devices"]) == 100
    assert result["truncated"] is True


def test_maintenance_only_unique_tenant_mac_never_names_or_ip(db):
    conn, _ = db
    conn.execute("INSERT INTO devices VALUES('core','a','AABBCCDDEE02')")
    conn.execute("INSERT INTO devices VALUES('foreign','b','AABBCCDDEE02')")
    conn.executemany(
        "INSERT INTO maintenance_records(ts,device_id,type,tenant_id,notes,performed_by) VALUES(?,?,?,?,?,?)",
        [
            (NOW - 20, "core", "cleaning", "a", "SECRET", "SECRET"),
            (NOW - 10, "core", "sensitivecustomtype", "a", "SECRET", "SECRET"),
            (NOW - 5, "core", "repair", None, "SECRET", "SECRET"),
            (NOW - 3, "core", "firmware_update", "b", "SECRET", "SECRET"),
        ],
    )
    result = timeline(conn)
    assert result["maintenance_context"] == "legacy_unscoped"
    assert [m["type"] for m in result["markers"]] == ["cleaning", "other"]
    assert "SECRET" not in json.dumps(result)
    conn.execute("DELETE FROM maintenance_records WHERE tenant_id IS NULL")
    assert timeline(conn)["maintenance_context"] == "available"
    conn.execute("INSERT INTO devices VALUES('ambiguous','a','aa-bb-cc-dd-ee-02')")
    assert timeline(conn)["maintenance_context"] == "ambiguous"
    assert timeline(conn)["markers"] == []
    conn.execute("DELETE FROM devices WHERE id='ambiguous'")
    conn.execute(
        "INSERT INTO axe_devices VALUES('dup','Dup','a','AABBCCDDEE02','ONLINE',0)"
    )
    assert timeline(conn)["maintenance_context"] == "ambiguous"


@pytest.mark.parametrize(
    "mac", ["", "000000000000", "ffffffffffff", "zz:bb:cc:dd:ee:02", None]
)
def test_unlinked_mac_no_inference(db, mac):
    conn, _ = db
    conn.execute("UPDATE axe_devices SET mac_address=? WHERE id='axe-a'", (mac,))
    assert timeline(conn)["maintenance_context"] == "unlinked"


def test_missing_core_table_unlinked(db):
    conn, _ = db
    conn.execute("DROP TABLE devices")
    assert timeline(conn)["maintenance_context"] == "unlinked"


def test_maintenance_bounded_and_does_not_relink_without_core_match(db):
    conn, _ = db
    assert timeline(conn)["maintenance_context"] == "unlinked"
    conn.execute("INSERT INTO devices VALUES('core','a','AABBCCDDEE02')")
    conn.executemany(
        "INSERT INTO maintenance_records(ts,device_id,type,tenant_id) VALUES(?,?,?,?)",
        [(NOW - i, "core", "repair", "a") for i in range(205)],
    )
    result = timeline(conn)
    assert len(result["markers"]) == 200
    assert result["maintenance_truncated"] is True


def test_invalid_observation_breaks_continuity_and_config_markers(db):
    conn, _ = db
    insert(conn, {"hashrate_hs": 1, "voltage_mv": 1000}, NOW - 90)
    insert(conn, {}, NOW - 60)
    insert(conn, {"hashrate_hs": 2, "voltage_mv": 1200}, NOW - 30)
    result = timeline(conn)
    assert result["samples"][-1]["gap_before_seconds"] == 60
    assert result["coverage"]["gaps"] == 1
    assert result["markers"] == []


def test_bootstrap_migration_idempotent_and_legacy_stays_unattributed(
    tmp_path, monkeypatch
):
    from services import bootstrap

    path = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE maintenance_records(id INTEGER PRIMARY KEY, ts INTEGER, device_id TEXT, type TEXT, notes TEXT, performed_by TEXT)"
    )
    conn.execute(
        "INSERT INTO maintenance_records VALUES(1,1,'old','cleaning','note','actor')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("DB_PATH", str(path))
    bootstrap.init_db()
    bootstrap.init_db()
    conn = sqlite3.connect(path)
    try:
        assert conn.execute(
            "SELECT tenant_id FROM maintenance_records WHERE id=1"
        ).fetchone() == (None,)
        indexes = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert {
            "idx_maintenance_tenant_device_ts",
            "idx_axe_telemetry_tenant_device_ts",
        } <= indexes
    finally:
        conn.close()


def test_new_maintenance_writes_record_explicit_tenant_and_legacy_default_null(
    tmp_path, monkeypatch
):
    import app as app_module
    from services import bootstrap
    from core.models.device import Device

    path = tmp_path / "writes.sqlite"
    monkeypatch.setenv("DB_PATH", str(path))
    bootstrap.init_db()
    app_module._add_maintenance_record("legacy", "cleaning", "", "actor")
    device = Device(id="core-owned", name="Owned", tenant_id="a")

    class Registry:
        def get_device(self, device_id, tenant_id=""):
            return device if device_id == device.id and tenant_id == "a" else None

    monkeypatch.setattr(app_module, "_core_registry", Registry())
    monkeypatch.setenv("TENANT_API_KEYS", json.dumps({"a": "test-a"}))
    with app_module.app.test_client() as client:
        response = client.post(
            "/api/devices/core-owned/maintenance",
            headers={"X-API-Key": "test-a"},
            json={"type": "cleaning"},
        )
        assert response.status_code == 201
        assert "tenant_id" not in response.json["record"]
    conn = sqlite3.connect(path)
    try:
        assert conn.execute(
            "SELECT device_id,tenant_id FROM maintenance_records ORDER BY id"
        ).fetchall() == [("legacy", None), ("core-owned", "a")]
    finally:
        conn.close()


@pytest.fixture
def client(db, monkeypatch):
    conn, path = db
    conn.commit()
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("TENANT_API_KEYS", raising=False)
    app = Flask(__name__)
    app.secret_key = "unit-thermal-session"

    def get_db():
        other = sqlite3.connect(path)
        other.row_factory = sqlite3.Row
        return other

    app.register_blueprint(create_thermal_blueprint(get_db))
    return app.test_client()


def test_api_auth_scope_validation_and_private_errors(client, monkeypatch):
    monkeypatch.setenv("TENANT_API_KEYS", json.dumps({"a": "test-a", "b": "test-b"}))
    headers = {"X-API-Key": "test-a"}
    assert client.get("/api/thermal-timeline/devices", headers=headers).json[
        "devices"
    ] == [{"id": "axe-a", "name": "A"}]
    assert (
        client.get("/api/thermal-timeline?device_id=axe-a", headers=headers).status_code
        == 200
    )
    assert (
        client.get("/api/thermal-timeline?device_id=axe-b", headers=headers).status_code
        == 404
    )
    assert (
        client.get("/api/thermal-timeline?device_id=gone", headers=headers).status_code
        == 404
    )
    for url in (
        "/api/thermal-timeline",
        "/api/thermal-timeline?device_id=axe-a&hours=2",
        "/api/thermal-timeline?device_id=" + "a" * 129,
    ):
        assert client.get(url, headers=headers).status_code == 400
    for credentials in (
        {"Authorization": "Bearer invalid"},
        {"Authorization": "Basic invalid"},
        {"X-API-Key": "bad"},
    ):
        response = client.get("/api/thermal-timeline/devices", headers=credentials)
        assert response.status_code == 401
        assert "no-store" in response.headers["Cache-Control"]
    response = client.post("/api/thermal-timeline", headers=headers)
    assert response.status_code == 405
    assert "private" in response.headers["Cache-Control"]
    assert "*" in response.vary
    assert set(("Authorization", "Cookie", "X-API-Key")) <= set(response.vary)
    assert (
        client.get(
            "/api/thermal-timeline/devices", environ_base={"REMOTE_ADDR": "203.0.113.2"}
        ).status_code
        == 403
    )


def test_api_mixed_credentials_empty_tenant_and_db_failure(client, monkeypatch):
    monkeypatch.setenv("TENANT_API_KEYS", json.dumps({"a": "test-a", "b": "test-b"}))
    monkeypatch.setattr(
        "routes.thermal_timeline.verify_token",
        lambda *a, **kw: {"sub": "a", "role": "viewer"},
    )
    assert (
        client.get(
            "/api/thermal-timeline/devices",
            headers={"Authorization": "Bearer ok", "X-API-Key": "test-b"},
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/thermal-timeline/devices",
            headers={"Authorization": "Bearer ok", "X-API-Key": "test-a"},
        ).status_code
        == 200
    )
    monkeypatch.setattr(
        "routes.thermal_timeline.verify_token",
        lambda *a, **kw: {"sub": " ", "role": "viewer"},
    )
    assert (
        client.get(
            "/api/thermal-timeline/devices", headers={"Authorization": "Bearer ok"}
        ).status_code
        == 401
    )
    monkeypatch.setattr(
        "routes.thermal_timeline.list_timeline_devices", lambda *a: 1 / 0
    )
    assert (
        client.get(
            "/api/thermal-timeline/devices", headers={"X-API-Key": "test-a"}
        ).status_code
        == 503
    )


def test_explicit_invalid_credentials_fail_even_open_mode(client):
    assert (
        client.get(
            "/api/thermal-timeline/devices", headers={"X-API-Key": "invalid"}
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/thermal-timeline/devices", headers={"Authorization": "Bearer invalid"}
        ).status_code
        == 401
    )
