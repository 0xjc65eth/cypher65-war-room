"""Real-SQLite energy scenario isolation and input contracts; no hardware I/O."""

from copy import deepcopy
import json
import sqlite3
from unittest.mock import Mock

from flask import Flask
import pytest

from routes.energy_advisor import create_energy_blueprint
from services.energy_advisor import (
    advisor_snapshot,
    evaluate_energy,
    list_advisor_devices,
    validate_evaluation,
)

NOW = 2_000_000_000


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "energy.sqlite"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE axe_devices(id TEXT PRIMARY KEY,name TEXT,tenant_id TEXT,
          model TEXT,firmware TEXT,firmware_version TEXT,capabilities TEXT,
          status TEXT,removed_at INTEGER DEFAULT 0);
        CREATE TABLE axe_telemetry(id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts INTEGER,tenant_id TEXT,device_id TEXT,payload TEXT);
        CREATE INDEX ix_energy ON axe_telemetry(tenant_id,device_id,ts DESC,id DESC);
        CREATE TABLE axe_agent_commands(id TEXT,payload TEXT);
        INSERT INTO axe_devices VALUES('a','Device A','ta','Gamma','AxeOS','2.9',
          '{"telemetry":true,"frequencyControl":true,"secret":"SECRET"}','ONLINE',0);
        INSERT INTO axe_devices VALUES('b','Device B','tb','Gamma','AxeOS','2.9',
          '{}','ONLINE',0);
        INSERT INTO axe_devices VALUES('gone','Gone','ta','Gamma','AxeOS','2.9',
          '{}','OFFLINE',1);
    """)
    conn.commit()
    yield conn, path
    conn.close()


def insert(conn, payload=None, ts=NOW - 30, *, tenant="ta", device="a"):
    if payload is None:
        payload = {"hashrate_hs": 1e12, "power_watts": 125.5, "temperature": 45}
    conn.execute(
        "INSERT INTO axe_telemetry(ts,tenant_id,device_id,payload) VALUES(?,?,?,?)",
        (ts, tenant, device, json.dumps(payload)),
    )
    conn.commit()


def scenario():
    return {
        "device_id": "a",
        "hours": 6,
        "tariff": {
            "value": 0.3,
            "currency": "EUR",
            "source": "operator",
            "observed_at": NOW - 60,
            "valid_until": NOW + 3600,
        },
        "constraints": {"max_power_watts": 150, "max_cost": 1},
        "profiles": [
            {
                "id": "local",
                "name": "Operator validated observation",
                "model": "Gamma",
                "firmware": "AxeOS",
                "firmware_version": "2.9",
                "expected_power_watts": 100,
                "required_capabilities": ["telemetry"],
                "approved": True,
            }
        ],
    }


def evaluate(conn, value=None):
    return evaluate_energy(conn, "ta", scenario() if value is None else value, now=NOW)


def test_decimal_costs_provenance_expiry_and_no_ranking(db):
    conn, _ = db
    insert(conn)
    result = evaluate(conn)
    assert result["baseline"] == {
        "state": "available",
        "energy_kwh": "0.753000",
        "cost": "0.225900",
        "energy_below_resolution": False,
        "cost_below_resolution": False,
    }
    assert result["profiles"][0]["cost"] == "0.180000"
    assert result["suggestion"] == {
        "type": "review_candidates",
        "profile_id": None,
        "eligible_profile_ids": ["local"],
        "reasons": [],
    }
    assert result["expires_at"] == NOW + 870
    assert result["tariff"] == scenario()["tariff"]
    assert result["mode"] == "read_only"
    assert result["solar"]["state"] == "not_configured"
    assert result["solar"]["power_watts"] is None
    assert "SECRET" not in json.dumps(result)


def test_tenant_tombstone_and_metadata_allowlist(db):
    conn, _ = db
    assert advisor_snapshot(conn, "tb", "a", now=NOW) is None
    assert advisor_snapshot(conn, "ta", "gone", now=NOW) is None
    assert list_advisor_devices(conn, "ta")["devices"] == [
        {
            "id": "a",
            "name": "Device A",
            "model": "Gamma",
            "firmware": "AxeOS",
            "firmware_version": "2.9",
            "capabilities": ["frequencyControl", "telemetry"],
        }
    ]
    assert evaluate_energy(conn, "tb", scenario(), now=NOW) is None
    with pytest.raises(ValueError):
        advisor_snapshot(conn, "", "a", now=NOW)


def test_real_zero_is_valid_no_efficiency_inferred(db):
    conn, _ = db
    insert(conn, {"hashrate_hs": 0, "power_watts": 0, "temperature": 0})
    conn.execute("UPDATE axe_devices SET status='IDLE' WHERE id='a'")
    value = scenario()
    value["tariff"]["value"] = 0
    value["profiles"][0]["expected_power_watts"] = 0
    result = evaluate(conn, value)
    assert result["baseline"]["cost"] == "0.000000"
    assert result["telemetry"]["hashrate_hs"] == 0
    assert result["profiles"][0]["eligible"] is True
    assert result["baseline"]["energy_below_resolution"] is False
    assert result["baseline"]["cost_below_resolution"] is False
    assert result["profiles"][0]["energy_below_resolution"] is False
    assert result["profiles"][0]["cost_below_resolution"] is False
    assert "efficiency" not in json.dumps(result)


@pytest.mark.parametrize(
    "power,price,energy_below,cost_below",
    [
        (1e-10, 0.3, True, True),
        (100, 1e-10, False, True),
        (1e-10, 0, True, False),
        (0, 0.3, False, False),
    ],
)
def test_positive_subresolution_is_never_reported_as_true_zero(
    db, power, price, energy_below, cost_below
):
    conn, _ = db
    insert(conn, {"hashrate_hs": 1, "power_watts": power})
    value = scenario()
    value["tariff"]["value"] = price
    value["profiles"][0]["expected_power_watts"] = power
    result = evaluate(conn, value)
    for item in (result["baseline"], result["profiles"][0]):
        assert item["energy_below_resolution"] is energy_below
        assert item["cost_below_resolution"] is cost_below
        if energy_below:
            assert item["energy_kwh"] == "0.000000"
        if cost_below:
            assert item["cost"] == "0.000000"
    assert result["resolution"] == {
        "energy_kwh": "0.000001",
        "cost": "0.000001",
        "rounding": "half_up",
    }
    if power > 0 and price > 0:
        value["constraints"]["max_cost"] = 0
        assert "cost_limit_exceeded" in evaluate(conn, value)["profiles"][0]["reasons"]


def test_blocked_baseline_does_not_assert_subresolution(db):
    result = evaluate(db[0])
    assert result["baseline"] == {
        "state": "blocked",
        "energy_kwh": None,
        "cost": None,
        "energy_below_resolution": False,
        "cost_below_resolution": False,
    }


@pytest.mark.parametrize(
    "latest",
    [
        {},
        [],
        {"power_watts": 10},
        {"hashrate_hs": True, "power_watts": 10},
        {"hashrate_hs": "1", "power_watts": 10},
        {"hashrate_hs": -1, "power_watts": 10},
        {"hashrate_hs": float("nan")},
        {"hashrate_hs": float("inf")},
        {"hashrate_hs": 10**1000},
        {"hashrate_hs": 5},
        {"hashrate_hs": 5, "power_watts": "10"},
        {"hashrate_hs": 5, "power_watts": True},
        {"hashrate_hs": 5, "power_watts": -1},
        {"hashrate_hs": 5, "power_watts": 10, "mining_paused": True},
        {"hashrate_hs": 5, "power_watts": 10, "_invalid_fields": ["power"]},
    ],
)
def test_invalid_latest_never_falls_back(db, latest):
    conn, _ = db
    insert(conn, ts=NOW - 60)
    insert(conn, latest)
    result = evaluate(conn)
    assert result["telemetry"]["state"] == "unknown"
    assert result["baseline"]["state"] == "blocked"
    assert result["profiles"][0]["eligible"] is False


@pytest.mark.parametrize(
    "ts,state",
    [
        (NOW - 900, "stale"),
        (NOW - 901, "stale"),
        (NOW + 1, "unknown"),
        (0, "unknown"),
        (-1, "unknown"),
    ],
)
def test_freshness_and_future_samples_fail_closed(db, ts, state):
    conn, _ = db
    insert(conn, ts=ts)
    assert evaluate(conn)["telemetry"]["state"] == state
    assert evaluate(conn)["expires_at"] is None


@pytest.mark.parametrize("status", ["OFFLINE", "ERROR", "PAUSED", "STALE", "unknown"])
def test_noncurrent_device_status_blocks_suggestion(db, status):
    conn, _ = db
    insert(conn)
    conn.execute("UPDATE axe_devices SET status=? WHERE id='a'", (status,))
    assert evaluate(conn)["telemetry"]["state"] == "offline"
    assert evaluate(conn)["suggestion"]["eligible_profile_ids"] == []


def test_empty_and_bounded_payloads_duplicate_newest(db):
    conn, _ = db
    assert evaluate(conn)["telemetry"]["state"] == "empty"
    insert(conn)
    insert(conn, {"hashrate_hs": 5, "power_watts": 8, "noise": "x" * 65536})
    assert evaluate(conn)["telemetry"]["state"] == "unknown"
    conn.execute("DELETE FROM axe_telemetry")
    insert(conn)
    conn.execute(
        "INSERT INTO axe_telemetry(ts,tenant_id,device_id,payload) VALUES(?,?,?,?)",
        (NOW - 30, "ta", "a", "{invalid"),
    )
    assert evaluate(conn)["telemetry"]["state"] == "unknown"


@pytest.mark.parametrize("status", ["ONLINE", "HASHING", "IDLE"])
def test_canonical_live_statuses(db, status):
    conn, _ = db
    insert(conn)
    conn.execute("UPDATE axe_devices SET status=? WHERE id='a'", (status,))
    assert evaluate(conn)["telemetry"]["state"] == "current"


@pytest.mark.parametrize("metadata", [None, "x" * 129, " trailing", "invalid\nvalue"])
def test_invalid_metadata_never_matches_operator_profile(db, metadata):
    conn, _ = db
    insert(conn)
    conn.execute("UPDATE axe_devices SET firmware_version=? WHERE id='a'", (metadata,))
    result = evaluate(conn)
    assert result["device"]["firmware_version"] == ""
    assert "firmware_version_mismatch" in result["profiles"][0]["reasons"]


def test_missing_invalid_metadata_caps_fail_closed(db):
    conn, _ = db
    insert(conn)
    conn.execute(
        "UPDATE axe_devices SET capabilities='[]',firmware_version='' WHERE id='a'"
    )
    profile = evaluate(conn)["profiles"][0]
    assert profile["reasons"] == ["firmware_version_mismatch", "capabilities_mismatch"]
    conn.execute("UPDATE axe_devices SET capabilities='invalid' WHERE id='a'")
    assert list_advisor_devices(conn, "ta")["devices"][0]["capabilities"] == []


@pytest.mark.parametrize(
    "field,replacement,reason",
    [
        ("approved", False, "not_operator_approved"),
        ("model", "different", "model_mismatch"),
        ("firmware", "other", "firmware_mismatch"),
        ("firmware_version", "3", "firmware_version_mismatch"),
        ("required_capabilities", ["powerControl"], "capabilities_mismatch"),
        ("expected_power_watts", 200, "power_limit_exceeded"),
    ],
)
def test_profiles_have_explicit_reasons(db, field, replacement, reason):
    conn, _ = db
    insert(conn)
    value = scenario()
    value["profiles"][0][field] = replacement
    assert reason in evaluate(conn, value)["profiles"][0]["reasons"]


def test_cost_limit_before_rounding_and_all_candidates_not_ranked(db):
    conn, _ = db
    insert(conn)
    value = scenario()
    value["constraints"]["max_cost"] = 0.179999999
    assert "cost_limit_exceeded" in evaluate(conn, value)["profiles"][0]["reasons"]
    value["constraints"]["max_cost"] = 1
    second = deepcopy(value["profiles"][0])
    second.update(id="second", expected_power_watts=50)
    value["profiles"].append(second)
    assert evaluate(conn, value)["suggestion"]["eligible_profile_ids"] == [
        "local",
        "second",
    ]


@pytest.mark.parametrize("when,state", [(NOW, "expired"), (NOW - 1, "expired")])
def test_tariff_expiration_independent_from_current_telemetry(db, when, state):
    conn, _ = db
    insert(conn)
    value = scenario()
    value["tariff"]["valid_until"] = when
    result = evaluate(conn, value)
    assert result["telemetry"]["state"] == "current"
    assert result["tariff_state"] == state
    assert result["baseline"]["cost"] is None


def test_tariff_future_and_no_currency_conversion(db):
    conn, _ = db
    insert(conn)
    value = scenario()
    value["tariff"]["observed_at"] = NOW + 1
    assert evaluate(conn, value)["tariff_state"] == "future"
    value["tariff"]["observed_at"] = 0
    value["tariff"]["currency"] = "BRL"
    assert evaluate(conn, value)["currency"] == "BRL"
    assert evaluate(conn, value)["baseline"]["cost"] == "0.225900"


def test_bounded_picker_caps_and_missing_device(db):
    conn, _ = db
    conn.executemany(
        "INSERT INTO axe_devices VALUES(?,?,'ta','M','F','V','{}','ONLINE',0)",
        [(f"x{i}", f"X{i}") for i in range(101)],
    )
    result = list_advisor_devices(conn, "ta")
    assert result["truncated"] and len(result["devices"]) == 100
    conn.execute("UPDATE axe_devices SET capabilities=? WHERE id='a'", ("x" * 70000,))
    assert list_advisor_devices(conn, "ta")["devices"][0]["capabilities"] == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda v: v.update(telemetry={"power_watts": 1}),
        lambda v: v.update(solar={"power_watts": 100}),
        lambda v: v.update(hours=True),
        lambda v: v.update(hours=1.5),
        lambda v: v.update(hours=25),
        lambda v: v.update(device_id=""),
        lambda v: v["tariff"].update(value="0.3"),
        lambda v: v["tariff"].update(value=float("nan")),
        lambda v: v["tariff"].update(value=True),
        lambda v: v["tariff"].update(unexpected="value"),
        lambda v: v["tariff"].update(currency=[]),
        lambda v: v["tariff"].update(source="solar"),
        lambda v: v["tariff"].update(observed_at=True),
        lambda v: v["tariff"].update(valid_until=0),
        lambda v: v["constraints"].update(max_power_watts=-1),
        lambda v: v["constraints"].update(max_cost="3"),
        lambda v: v.update(constraints={}),
        lambda v: v.update(profiles=[v["profiles"][0]] * 9),
        lambda v: v.update(profiles=v["profiles"] * 2),
        lambda v: v["profiles"][0].update(expected_power_watts=float("inf")),
        lambda v: v["profiles"][0].update(approved="true"),
        lambda v: v["profiles"][0].update(firmware_version=""),
        lambda v: v["profiles"][0].update(required_capabilities=[{}]),
        lambda v: v["profiles"][0].update(required_capabilities=["unknown"]),
        lambda v: v["profiles"][0].update(
            required_capabilities=["telemetry", "telemetry"]
        ),
        lambda v: v["profiles"][0].update(frequency_mhz=600),
    ],
)
def test_invalid_operator_input_rejected(mutation):
    value = scenario()
    mutation(value)
    with pytest.raises(ValueError):
        validate_evaluation(value)


@pytest.fixture
def client(db, monkeypatch):
    _, path = db
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("TENANT_API_KEYS", raising=False)
    monkeypatch.setattr("services.energy_advisor.time.time", lambda: NOW)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-secret-0123456789")

    def get_db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    app.register_blueprint(create_energy_blueprint(get_db))
    flask_client = app.test_client()
    with flask_client.session_transaction() as session:
        session.update(authenticated=True, tenant_id="ta", role="viewer")
    yield flask_client


def test_viewer_computes_no_database_write_or_command(db, client):
    conn, _ = db
    insert(conn)
    before = list(conn.iterdump())
    response = client.post("/api/energy-advisor/evaluate", json=scenario())
    assert response.status_code == 200
    assert list(conn.iterdump()) == before
    assert conn.execute("SELECT COUNT(*) FROM axe_agent_commands").fetchone()[0] == 0
    assert client.get("/api/energy-advisor/devices").status_code == 200
    assert client.get("/api/energy-advisor/snapshot?device_id=a").status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Bearer bad"},
        {"Authorization": "Basic x"},
        {"X-API-Key": "bad"},
        {"Authorization": ""},
    ],
)
def test_invalid_explicit_credentials_fail_even_local_open(client, headers):
    assert client.get("/api/energy-advisor/devices", headers=headers).status_code == 401


def test_conflicting_credentials_and_remote_anonymous(client, monkeypatch):
    monkeypatch.setattr(
        "routes.energy_advisor.verify_token",
        lambda *a, **k: {"sub": "ta", "role": "viewer"},
    )
    monkeypatch.setattr(
        "routes.energy_advisor.resolve_tenant_for_api_key", lambda _: "tb"
    )
    response = client.get(
        "/api/energy-advisor/devices",
        headers={"Authorization": "Bearer x", "X-API-Key": "valid"},
    )
    assert response.status_code == 401
    monkeypatch.setenv("API_KEY", "configured")
    with client.session_transaction() as session:
        session.clear()
    assert (
        client.get(
            "/api/energy-advisor/devices", environ_base={"REMOTE_ADDR": "203.0.113.1"}
        ).status_code
        == 403
    )


def test_api_key_only_uses_its_tenant_not_session(client, monkeypatch):
    monkeypatch.setenv("TENANT_API_KEYS", json.dumps({"tb": "test-tenant-key"}))
    response = client.get(
        "/api/energy-advisor/devices", headers={"X-API-Key": "test-tenant-key"}
    )
    assert response.status_code == 200
    assert [device["id"] for device in response.get_json()["devices"]] == ["b"]
    assert (
        client.get(
            "/api/energy-advisor/devices", headers={"X-API-Key": "é"}
        ).status_code
        == 401
    )


def test_missing_session_tenant_never_defaults(client):
    with client.session_transaction() as session:
        session["tenant_id"] = ""
    assert client.get("/api/energy-advisor/devices").status_code == 401


@pytest.mark.parametrize(
    "url,status",
    [
        ("/api/energy-advisor/snapshot?device_id=b", 404),
        ("/api/energy-advisor/snapshot?device_id=gone", 404),
        ("/api/energy-advisor/snapshot?device_id=", 400),
        ("/api/energy-advisor/snapshot?device_id=a&device_id=b", 400),
        ("/api/energy-advisor/snapshot?device_id=a&solar=5", 400),
        ("/api/energy-advisor/absent", 404),
    ],
)
def test_errors_private_and_tenant_scoped(client, url, status):
    response = client.get(url)
    assert response.status_code == status
    assert "no-store" in response.headers["Cache-Control"]
    assert "*" in response.headers["Vary"]


def test_body_limits_malformed_and_unknownkeys(client):
    url = "/api/energy-advisor/evaluate"
    assert client.post(url, data="x").status_code == 415
    assert (
        client.post(url, data="x" * 16385, content_type="application/json").status_code
        == 413
    )
    for raw in ("{", '{"x":NaN}', '{"x":1,"x":2}', "[]", "{}", '"text"'):
        assert (
            client.post(url, data=raw, content_type="application/json").status_code
            == 400
        )
    value = scenario()
    value["solar"] = {"state": "available"}
    assert client.post(url, json=value).status_code == 400


def test_unavailable_is_sanitized_private(client, monkeypatch):
    monkeypatch.setattr(
        "routes.energy_advisor.list_advisor_devices",
        Mock(side_effect=sqlite3.OperationalError("SECRET")),
    )
    response = client.get("/api/energy-advisor/devices")
    assert response.status_code == 503
    assert "SECRET" not in response.get_data(as_text=True)
    assert "no-store" in response.headers["Cache-Control"]
