"""
Integration tests for POST /api/hermes/chat.
Tests message routing, response structure, and input validation
through the full Flask → HermesCore → Agent pipeline.
"""

import uuid


class TestHermesChatRouting:

    def test_valid_message_returns_200(self, client, valid_headers):
        """A well-formed message gets 200 with session_id, intent, response."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": "hello"},
            headers=valid_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "session_id" in data
        assert "intent" in data
        assert "response" in data
        assert data["message"] == "hello"

    def test_mining_status_query_routes_correctly(self, client, valid_headers):
        """'Como está minha mineração?' → intent=MINING_STATUS."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": "Como está minha mineração?"},
            headers=valid_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["intent"] == "MINING_STATUS"

    def test_probability_query_routes_correctly(self, client, valid_headers):
        """'qual a chance de achar bloco?' → intent=PROBABILITY."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": "qual a chance de achar bloco?"},
            headers=valid_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["intent"] == "PROBABILITY"

    def test_financial_query_routes_correctly(self, client, valid_headers):
        """'qual o custo?' → intent=FINANCIAL."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": "qual o custo?"},
            headers=valid_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["intent"] == "FINANCIAL"

    def test_worker_health_query_routes_correctly(self, client, valid_headers):
        """'temperatura do rig está anormal?' → intent=WORKER_HEALTH."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": "temperatura do rig está anormal?"},
            headers=valid_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["intent"] == "WORKER_HEALTH"

    def test_rental_query_routes_correctly(self, client, valid_headers):
        """'onde alugar?' → intent=RENTAL_COMPARISON."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": "onde alugar?"},
            headers=valid_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["intent"] == "RENTAL_COMPARISON"

    def test_unknown_query_gets_unknown_intent(self, client, valid_headers):
        """Gibberish message → intent=UNKNOWN (not error)."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": "xyzzy123"},
            headers=valid_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["intent"] == "UNKNOWN"
        # Should still return a response string
        assert isinstance(data["response"], str)
        assert len(data["response"]) > 0


class TestHermesChatInputValidation:

    def test_empty_message_returns_400(self, client, valid_headers):
        """Empty string → 400."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": ""},
            headers=valid_headers,
        )
        assert resp.status_code == 400

    def test_missing_message_returns_400(self, client, valid_headers):
        """No message field → 400."""
        resp = client.post(
            "/api/hermes/chat",
            json={"other": "stuff"},
            headers=valid_headers,
        )
        assert resp.status_code == 400

    def test_message_not_string_returns_400(self, client, valid_headers):
        """Message is a number → 400."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": 42},
            headers=valid_headers,
        )
        assert resp.status_code == 400

    def test_invalid_json_returns_400(self, client, valid_headers):
        """Malformed JSON body → 400."""
        resp = client.post(
            "/api/hermes/chat",
            data="not json {{{",
            headers={**valid_headers, "Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_portuguese_accepted(self, client, valid_headers):
        """Portuguese message works fine."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": "Como está a operação hoje?"},
            headers=valid_headers,
        )
        assert resp.status_code == 200


class TestHermesChatSessionHandling:

    def test_new_session_gets_uuid(self, client, valid_headers):
        """No session_id sent → response contains a new UUID."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": "hello"},
            headers=valid_headers,
        )
        data = resp.get_json()
        sid = data["session_id"]
        # Should be a valid UUID (36 chars with hyphens, or at least long)
        assert len(sid) >= 32

    def test_session_id_is_echoed_back(self, client, valid_headers, fresh_session_id):
        """Send session_id → same value returned."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": "hello", "session_id": fresh_session_id},
            headers=valid_headers,
        )
        data = resp.get_json()
        assert data["session_id"] == fresh_session_id

    def test_two_sessions_work_independently(self, client, valid_headers):
        """Two different session_ids both return 200."""
        sid1 = str(uuid.uuid4())
        sid2 = str(uuid.uuid4())

        r1 = client.post(
            "/api/hermes/chat",
            json={"message": "hello", "session_id": sid1},
            headers=valid_headers,
        )
        r2 = client.post(
            "/api/hermes/chat",
            json={"message": "hello", "session_id": sid2},
            headers=valid_headers,
        )

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.get_json()["session_id"] == sid1
        assert r2.get_json()["session_id"] == sid2
