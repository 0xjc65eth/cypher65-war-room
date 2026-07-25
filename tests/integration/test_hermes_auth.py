"""
Integration tests for Hermes authentication.
Tests auth enforcement on /api/hermes/* endpoints.
"""


class TestHermesAuthIntegration:

    def test_chat_no_key_returns_401(self, client_auth_enabled):
        """No X-API-Key header → 401."""
        resp = client_auth_enabled.post(
            "/api/hermes/chat",
            json={"message": "hello"},
        )
        assert resp.status_code == 401

    def test_chat_invalid_key_returns_401(self, client_auth_enabled):
        """Wrong key → 401."""
        resp = client_auth_enabled.post(
            "/api/hermes/chat",
            json={"message": "hello"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    def test_chat_valid_key_returns_200(self, client_auth_enabled, valid_headers):
        """Correct key → 200."""
        resp = client_auth_enabled.post(
            "/api/hermes/chat",
            json={"message": "hello"},
            headers=valid_headers,
        )
        assert resp.status_code == 200

    def test_agents_no_key_returns_401(self, client_auth_enabled):
        """GET /agents without key → 401."""
        resp = client_auth_enabled.get("/api/hermes/agents")
        assert resp.status_code == 401

    def test_agents_valid_key_returns_200(self, client_auth_enabled, valid_headers):
        """GET /agents with valid key → 200."""
        resp = client_auth_enabled.get("/api/hermes/agents", headers=valid_headers)
        assert resp.status_code == 200

    def test_health_is_public(self, client_auth_enabled):
        """GET /health should be public (no auth required)."""
        resp = client_auth_enabled.get("/api/hermes/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"

    def test_ask_agent_no_key_returns_401(self, client_auth_enabled):
        """POST /ask-agent without key → 401."""
        resp = client_auth_enabled.post(
            "/api/hermes/ask-agent",
            json={"agent": "MiningAgent", "payload": {}},
        )
        assert resp.status_code == 401

    def test_ask_agent_valid_key_returns_result(self, client_auth_enabled, valid_headers):
        """POST /ask-agent with valid key → 200."""
        resp = client_auth_enabled.post(
            "/api/hermes/ask-agent",
            json={"agent": "MiningAgent", "payload": {}},
            headers=valid_headers,
        )
        assert resp.status_code == 200
