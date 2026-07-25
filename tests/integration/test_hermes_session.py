"""
Integration tests for Hermes session handling.
Tests session creation, persistence, and isolation through the API.
"""

import uuid


class TestHermesSessionIntegration:

    def test_no_session_id_creates_one(self, client, valid_headers):
        """Omitting session_id → server creates a new UUID."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": "hello"},
            headers=valid_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "session_id" in data
        assert len(data["session_id"]) >= 32

    def test_provided_session_id_is_preserved(self, client, valid_headers):
        """Sending a session_id → same value returned."""
        my_sid = str(uuid.uuid4())
        resp = client.post(
            "/api/hermes/chat",
            json={"message": "hello", "session_id": my_sid},
            headers=valid_headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()["session_id"] == my_sid

    def test_turn_number_increments(self, client, valid_headers):
        """Multiple messages with same session_id → turn_number increments."""
        sid = str(uuid.uuid4())

        r1 = client.post(
            "/api/hermes/chat",
            json={"message": "first", "session_id": sid},
            headers=valid_headers,
        )
        r2 = client.post(
            "/api/hermes/chat",
            json={"message": "second", "session_id": sid},
            headers=valid_headers,
        )

        turn1 = r1.get_json().get("turn_number", 0)
        turn2 = r2.get_json().get("turn_number", 0)
        assert turn2 > turn1, f"Turn should increment: {turn1} → {turn2}"
