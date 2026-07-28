"""Tests for Milestone 9 alert/automation endpoints."""
import json
import pytest
from app import app, get_db


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _clean_tables():
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM alerts")
    c.execute("DELETE FROM alert_history")
    c.execute("DELETE FROM automation_rules")
    conn.commit()
    conn.close()


def test_get_alerts_empty(client):
    _clean_tables()
    resp = client.get("/api/alerts")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "alerts" in data


def test_acknowledge_alert(client):
    _clean_tables()
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO alerts (ts, severity, category, message, active, is_acknowledged) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "CRIT", "temperature", "hot", 1, 0),
    )
    conn.commit()
    row = c.execute("SELECT id FROM alerts").fetchone()
    conn.close()

    resp = client.post("/api/alerts/acknowledge", json={"id": row["id"]})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_automation_rules_crud(client):
    _clean_tables()
    payload = {
        "name": "test-rule",
        "target_device_id": "test-device",
        "condition_metric": "temperature",
        "condition_operator": ">",
        "condition_value": 80,
        "action_command": "restart",
        "action_parameters": {},
        "is_enabled": True,
    }
    resp = client.post("/api/automation-rules", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    rule_id = data["id"]

    resp = client.get("/api/automation-rules")
    assert resp.status_code == 200
    assert any(r["id"] == rule_id for r in resp.get_json()["rules"])

    resp = client.delete(f"/api/automation-rules/{rule_id}")
    assert resp.status_code == 200


def test_alert_history(client):
    _clean_tables()
    resp = client.get("/api/alerts/history")
    assert resp.status_code == 200
    assert "history" in resp.get_json()


def test_update_automation_rule_validates_operator(client):
    _clean_tables()
    payload = {
        "name": "test-rule",
        "target_device_id": "test-device",
        "condition_metric": "temperature",
        "condition_operator": ">",
        "condition_value": 80,
        "action_command": "restart",
        "action_parameters": {},
        "is_enabled": True,
    }
    resp = client.post("/api/automation-rules", json=payload)
    assert resp.status_code == 200
    rule_id = resp.get_json()["id"]

    resp = client.put(f"/api/automation-rules/{rule_id}", json={"condition_operator": "invalid"})
    assert resp.status_code == 400
    assert "invalid operator" in resp.get_json()["error"]


def test_update_automation_rule_validates_condition_value(client):
    _clean_tables()
    payload = {
        "name": "test-rule",
        "target_device_id": "test-device",
        "condition_metric": "temperature",
        "condition_operator": ">",
        "condition_value": 80,
        "action_command": "restart",
        "action_parameters": {},
        "is_enabled": True,
    }
    resp = client.post("/api/automation-rules", json=payload)
    assert resp.status_code == 200
    rule_id = resp.get_json()["id"]

    resp = client.put(f"/api/automation-rules/{rule_id}", json={"condition_value": "not-a-number"})
    assert resp.status_code == 400
    assert "numeric" in resp.get_json()["error"]
