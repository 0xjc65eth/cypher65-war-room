"""Tests for the UX audit Quick Wins:

  1. POST /api/settings/test-webhook — validate the notification channel
     with a sample payload (PRO-gated, same gate as webhook_url).
  2. GET  /api/automation-executions — expose the automation execution log
     (fim da "caixa preta"), tenant-scoped via a join on the tenant's rules.

These endpoints were added after the Fase 6 blueprint migration (settings_bp
and alerts_bp) — the contracts below lock them in.
"""

import pytest

from app import app

import routes.settings_routes as settings_routes


@pytest.fixture
def client():
    app.config["TESTING"] = True
    yield app.test_client()


def _db():
    from app import get_db
    return get_db()


# ── POST /api/settings/test-webhook ───────────────────────────────────────

class TestTestWebhook:
    def test_400_when_no_webhook_configured(self, client, monkeypatch):
        monkeypatch.setattr(
            settings_routes,
            "load_settings",
            lambda tenant_id="": {"webhook_url": ""},
        )
        r = client.post("/api/settings/test-webhook")
        assert r.status_code == 400
        assert "not configured" in r.get_json()["error"]

    def test_403_when_not_pro(self, client, monkeypatch):
        monkeypatch.setattr(settings_routes, "load_settings",
                            lambda tenant_id="": {"webhook_url": "https://hooks.example.com/abc"})
        monkeypatch.setattr(settings_routes, "is_pro", lambda: False)
        r = client.post("/api/settings/test-webhook")
        assert r.status_code == 403
        assert "PRO" in r.get_json()["error"]

    def test_posts_sample_payload_and_reports_status(self, client, monkeypatch):
        monkeypatch.setattr(settings_routes, "load_settings",
                            lambda tenant_id="": {"webhook_url": "https://hooks.example.com/abc"})
        monkeypatch.setattr(settings_routes, "is_pro", lambda: True)
        sent = {}

        class FakeResp:
            status_code = 204

        def fake_post(url, json=None, timeout=4):
            sent["url"] = url
            sent["payload"] = json
            sent["timeout"] = timeout
            return FakeResp()

        monkeypatch.setattr("requests.post", fake_post)
        r = client.post("/api/settings/test-webhook")
        assert r.status_code == 200
        data = r.get_json()
        assert data["success"] is True
        assert data["status_code"] == 204
        # Payload shape must match what the polling loop fires.
        assert sent["url"] == "https://hooks.example.com/abc"
        assert sent["payload"]["event"] == "cypher65_war_room_alert"
        assert sent["payload"]["severity"] == "TEST"
        assert "message" in sent["payload"]
        assert "worker" in sent["payload"]
        assert "address" in sent["payload"]
        assert sent["timeout"] > 0

    def test_502_on_network_error(self, client, monkeypatch):
        monkeypatch.setattr(settings_routes, "load_settings",
                            lambda tenant_id="": {"webhook_url": "https://hooks.example.com/abc"})
        monkeypatch.setattr(settings_routes, "is_pro", lambda: True)

        def boom(url, json=None, timeout=4):
            raise ConnectionError("no route to host")

        monkeypatch.setattr("requests.post", boom)
        r = client.post("/api/settings/test-webhook")
        assert r.status_code == 502
        assert r.get_json()["success"] is False


# ── GET /api/automation-executions ────────────────────────────────────────

class TestAutomationExecutions:
    @pytest.fixture(autouse=True)
    def _clean_seed(self):
        """Remove this class's seeded rows after each test so assertions are
        order-independent against the session-wide scratch DB."""
        yield
        conn = _db()
        conn.execute("DELETE FROM automation_execution_log WHERE rule_id >= 9000")
        conn.execute("DELETE FROM automation_rules WHERE id >= 9000")
        conn.commit()
        conn.close()

    def _seed(self, conn, tenant_id, rule_id, ts):
        conn.execute(
            "INSERT INTO automation_rules "
            "(id, name, target_device_id, condition_metric, condition_operator, "
            " condition_value, action_command, action_parameters, is_enabled, "
            " min_interval_seconds, tenant_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rule_id, f"rule-{rule_id}", "dev-1", "temperature", ">", 80,
             "restart", "{}", 1, 60, tenant_id),
        )
        conn.execute(
            "INSERT INTO automation_execution_log "
            "(ts, rule_id, rule_name, device_id, action_command, status, reason, result) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, rule_id, f"rule-{rule_id}", "dev-1", "restart",
             "ok", "", "{}"),
        )
        conn.commit()

    def test_empty_when_no_rules(self, client):
        r = client.get("/api/automation-executions")
        assert r.status_code == 200
        assert r.get_json()["executions"] == []

    def test_tenant_isolation(self, client):
        conn = _db()
        self._seed(conn, tenant_id="default", rule_id=9001, ts=1700000000)
        self._seed(conn, tenant_id="acme", rule_id=9002, ts=1700000001)
        conn.close()

        # Default tenant sees ONLY its own executions.
        r = client.get("/api/automation-executions")
        assert r.status_code == 200
        rows = r.get_json()["executions"]
        assert len(rows) == 1
        assert rows[0]["rule_id"] == 9001
        assert rows[0]["status"] == "ok"
        assert rows[0]["result"] == {}

    def test_limit_clamped(self, client):
        conn = _db()
        for i in range(3):
            self._seed(conn, tenant_id="default", rule_id=9100 + i, ts=1700000100 + i)
        conn.close()
        r = client.get("/api/automation-executions?limit=2")
        assert r.status_code == 200
        assert len(r.get_json()["executions"]) == 2
        r2 = client.get("/api/automation-executions?limit=abc")
        assert r2.status_code == 200  # falls back to default limit

    def test_deleted_rule_hides_orphaned_execution(self, client):
        conn = _db()
        self._seed(conn, tenant_id="default", rule_id=9200, ts=1700000200)
        conn.execute("DELETE FROM automation_rules WHERE id=9200 AND tenant_id='default'")
        conn.commit()
        conn.close()
        r = client.get("/api/automation-executions")
        rows = r.get_json()["executions"]
        # The orphaned execution (rule deleted) must never surface.
        assert all(x["rule_id"] != 9200 for x in rows)
