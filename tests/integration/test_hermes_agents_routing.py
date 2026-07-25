"""
Integration tests for Hermes agent routing and listing.
Tests GET /api/hermes/agents and POST /api/hermes/ask-agent.
"""


class TestHermesAgentListing:

    def test_agents_endpoint_returns_list(self, client, valid_headers):
        """GET /agents → agents array + count."""
        resp = client.get("/api/hermes/agents", headers=valid_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "agents" in data
        assert "count" in data
        assert isinstance(data["agents"], list)
        assert data["count"] == len(data["agents"])

    def test_expected_agents_registered(self, client, valid_headers):
        """Core agents are in the listing."""
        resp = client.get("/api/hermes/agents", headers=valid_headers)
        data = resp.get_json()

        expected = [
            "MiningAgent",
            "ProbabilityAgent",
            "FinancialAgent",
            "RentalAgent",
            "SecurityAgent",
            "PerformanceAgent",
            "QAAgent",
            "ResearchAgent",
            "ProductAgent",
            "RedTeamAgent",
        ]
        for agent_name in expected:
            assert agent_name in data["agents"], f"Missing agent: {agent_name}"


class TestHermesAskAgent:

    def test_ask_mining_agent_returns_result(self, client, valid_headers):
        """POST /ask-agent with MiningAgent → 200 with structured result."""
        resp = client.post(
            "/api/hermes/ask-agent",
            json={"agent": "MiningAgent", "payload": {}},
            headers=valid_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["agent"] == "MiningAgent"
        assert data["status"] == "success"

    def test_ask_security_agent_returns_result(self, client, valid_headers):
        """POST /ask-agent with SecurityAgent → 200 with structured result."""
        resp = client.post(
            "/api/hermes/ask-agent",
            json={"agent": "SecurityAgent", "payload": {}},
            headers=valid_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["agent"] == "SecurityAgent"
        assert "analysis" in data

    def test_ask_unknown_agent_returns_error(self, client, valid_headers):
        """POST /ask-agent with nonexistent agent → error in response."""
        resp = client.post(
            "/api/hermes/ask-agent",
            json={"agent": "BogusAgent42", "payload": {}},
            headers=valid_headers,
        )
        assert resp.status_code == 200  # orchestrator returns error dict
        data = resp.get_json()
        assert "error" in data
        assert "BogusAgent42" in data["error"]

    def test_ask_agent_missing_name_returns_400(self, client, valid_headers):
        """POST /ask-agent without agent field → 400."""
        resp = client.post(
            "/api/hermes/ask-agent",
            json={"payload": {}},
            headers=valid_headers,
        )
        assert resp.status_code == 400
