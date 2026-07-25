"""
CYPHER65 // P0 HERMES TESTS
============================
Tests for Phase 5 P0 security remediation:
- P0.1: Authentication (no key → 401, invalid key → 401, valid key → success)
- P0.4: Input validation (empty, null, long message, malformed JSON)
- Session isolation (User A cannot see User B data)
"""

import os
import pytest
from app import app as flask_app
from hermes.memory import MemoryManager
from hermes.context import ContextOrchestrator


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def client():
    """Flask test client with API_KEY set for auth testing.
    Sets HERMES_AUTH_DISABLED=1 so we can test with/without headers freely.
    Restores previous env state on teardown."""
    old_key = os.environ.get("API_KEY")
    old_disabled = os.environ.get("HERMES_AUTH_DISABLED")
    os.environ["HERMES_AUTH_DISABLED"] = "1"
    os.environ["API_KEY"] = "test-p0-key-2026"
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c
    # Restore previous state
    if old_key is None:
        os.environ.pop("API_KEY", None)
    else:
        os.environ["API_KEY"] = old_key
    if old_disabled is None:
        os.environ.pop("HERMES_AUTH_DISABLED", None)
    else:
        os.environ["HERMES_AUTH_DISABLED"] = old_disabled


@pytest.fixture
def client_auth_enabled():
    """Flask test client with AUTH ENABLED (HERMES_AUTH_DISABLED not set).
    Used to test that auth actually blocks unauthenticated requests."""
    old_key = os.environ.get("API_KEY")
    old_disabled = os.environ.get("HERMES_AUTH_DISABLED")
    os.environ["API_KEY"] = "test-p0-key-2026"
    # Explicitly remove HERMES_AUTH_DISABLED so auth is ACTIVE
    os.environ.pop("HERMES_AUTH_DISABLED", None)
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c
    # Restore previous state
    if old_key is None:
        os.environ.pop("API_KEY", None)
    else:
        os.environ["API_KEY"] = old_key
    if old_disabled is not None:
        os.environ["HERMES_AUTH_DISABLED"] = old_disabled
    else:
        os.environ.pop("HERMES_AUTH_DISABLED", None)


@pytest.fixture
def auth_headers():
    """Valid authentication headers."""
    return {"X-API-Key": "test-p0-key-2026"}


# ═══════════════════════════════════════════════════════════════════════════
# P0.1 — AUTHENTICATION TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestHermesAuth:
    """Verify Hermes endpoints require valid authentication."""

    def test_chat_no_api_key_returns_401(self, client_auth_enabled):
        """No API key → 401 Unauthorized (when auth is enabled)."""
        resp = client_auth_enabled.post(
            "/api/hermes/chat",
            json={"message": "hello"},
        )
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"

    def test_chat_invalid_api_key_returns_401(self, client_auth_enabled):
        """Invalid API key → 401 Unauthorized."""
        resp = client_auth_enabled.post(
            "/api/hermes/chat",
            json={"message": "hello"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"

    def test_chat_malformed_api_key_returns_401(self, client_auth_enabled):
        """Malformed/missing API key header → 401."""
        resp = client_auth_enabled.post(
            "/api/hermes/chat",
            json={"message": "hello"},
            headers={"X-API-Key": ""},
        )
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"

    def test_chat_valid_api_key_returns_success(self, client_auth_enabled, auth_headers):
        """Valid API key → 200 OK with expected response structure."""
        resp = client_auth_enabled.post(
            "/api/hermes/chat",
            json={"message": "how is my mining?"},
            headers=auth_headers,
        )
        # With valid auth, should not be 401
        assert resp.status_code != 401, f"Got 401 despite valid API key"
        # Should be 200 (successful processing)
        assert resp.status_code == 200, f"Unexpected status: {resp.status_code}"
        # Verify response structure
        data = resp.get_json()
        assert "session_id" in data, "Response missing session_id"
        assert "intent" in data, "Response missing intent"
        assert "response" in data, "Response missing response"

    def test_agents_no_api_key_returns_401(self, client_auth_enabled):
        """GET /agents without key → 401."""
        resp = client_auth_enabled.get("/api/hermes/agents")
        assert resp.status_code == 401

    def test_agents_valid_key_returns_success(self, client_auth_enabled, auth_headers):
        """GET /agents with valid key → 200."""
        resp = client_auth_enabled.get("/api/hermes/agents", headers=auth_headers)
        assert resp.status_code == 200

    def test_ask_agent_no_key_returns_401(self, client_auth_enabled):
        """POST /ask-agent without key → 401."""
        resp = client_auth_enabled.post(
            "/api/hermes/ask-agent",
            json={"agent": "MiningAgent", "payload": {}},
        )
        assert resp.status_code == 401

    def test_health_is_public(self, client_auth_enabled):
        """GET /health should ALWAYS be public (no auth required)."""
        resp = client_auth_enabled.get("/api/hermes/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"
        assert "version" in data

    def test_dev_mode_allows_all_access(self, client):
        """When HERMES_AUTH_DISABLED=1 is set, all endpoints are open."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": "test in dev mode"},
        )
        # In dev mode (HERMES_AUTH_DISABLED=1), auth should allow all requests
        assert resp.status_code == 200, f"Dev mode should allow access: {resp.status_code}"


# ═══════════════════════════════════════════════════════════════════════════
# P0.4 — INPUT VALIDATION TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestHermesInputValidation:
    """Verify input validation blocks malicious/broken inputs."""

    def test_empty_message_returns_400(self, client, auth_headers):
        """Empty string message → 400."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_null_message_returns_400(self, client, auth_headers):
        """Null/None message → 400."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": None},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_missing_message_field_returns_400(self, client, auth_headers):
        """Missing 'message' field entirely → 400."""
        resp = client.post(
            "/api/hermes/chat",
            json={"other_field": "value"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_very_long_message_is_truncated_not_rejected(self, client, auth_headers):
        """Very long message (>2000 chars) should be accepted but truncated."""
        long_msg = "x" * 5000
        resp = client.post(
            "/api/hermes/chat",
            json={"message": long_msg},
            headers=auth_headers,
        )
        # Should not return 400 — truncation is safe handling
        assert resp.status_code != 400, f"Long message rejected instead of truncated"

    def test_malformed_json_returns_400(self, client, auth_headers):
        """Malformed JSON body → 400."""
        resp = client.post(
            "/api/hermes/chat",
            data="this is not json {{{",
            headers={**auth_headers, "Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_non_dict_json_returns_400(self, client, auth_headers):
        """JSON array instead of object → 400."""
        resp = client.post(
            "/api/hermes/chat",
            json=["array", "not", "dict"],
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_message_not_string_returns_400(self, client, auth_headers):
        """Message field is a number, not string → 400."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": 12345},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_whitespace_only_message_returns_400(self, client, auth_headers):
        """Whitespace-only message → 400."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": "   \n\t   "},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_unicode_message_accepted(self, client, auth_headers):
        """Unicode message (Portuguese, emoji) should be accepted."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": "Como está minha mineração? 🚀"},
            headers=auth_headers,
        )
        assert resp.status_code != 400  # Should not reject unicode

    def test_special_characters_accepted(self, client, auth_headers):
        """Special characters (<, >, &, etc.) should be accepted (sanitized later)."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": "<script>alert('xss')</script>"},
            headers=auth_headers,
        )
        # Should not reject — sanitization is formatting concern, not validation
        assert resp.status_code != 400

    def test_very_large_body_returns_413(self, client, auth_headers):
        """Body > 100KB → 413 Payload Too Large."""
        large_msg = "x" * 150 * 1024  # 150KB
        resp = client.post(
            "/api/hermes/chat",
            data='{"message": "' + large_msg + '"}',
            headers={**auth_headers, "Content-Type": "application/json"},
        )
        assert resp.status_code in (413, 400), \
            f"Large body should return 413 or 400, got {resp.status_code}"

    def test_ask_agent_empty_name_returns_400(self, client, auth_headers):
        """Empty agent name → 400."""
        resp = client.post(
            "/api/hermes/ask-agent",
            json={"agent": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_ask_agent_missing_name_returns_400(self, client, auth_headers):
        """Missing agent name → 400."""
        resp = client.post(
            "/api/hermes/ask-agent",
            json={"payload": {}},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_ask_agent_long_name_rejected(self, client, auth_headers):
        """Agent name > 64 chars → 400."""
        resp = client.post(
            "/api/hermes/ask-agent",
            json={"agent": "A" * 100},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_no_stack_trace_in_error(self, client, auth_headers):
        """Error responses must never expose stack traces or internal paths."""
        resp = client.post(
            "/api/hermes/chat",
            json={"message": None},
            headers=auth_headers,
        )
        data = resp.get_json()
        error_msg = data.get("error", "")
        # Must not contain Python traceback indicators
        assert "Traceback" not in error_msg
        assert "File " not in error_msg
        assert "/hermes/" not in error_msg
        assert "api_key" not in error_msg.lower()  # No sensitive info


# ═══════════════════════════════════════════════════════════════════════════
# SESSION ISOLATION TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestSessionIsolation:
    """Verify per-session memory isolation: User A cannot see User B data."""

    def test_short_term_memory_isolation(self):
        """Session A's short-term memory is isolated from Session B."""
        mm = MemoryManager()

        mm.add_to_short_term("session_A", {"role": "user", "message": "A: status"})
        mm.add_to_short_term("session_B", {"role": "user", "message": "B: hashrate"})

        st_a = mm.get_short_term("session_A")
        st_b = mm.get_short_term("session_B")

        # Session A should only see its own message
        assert len(st_a) == 1
        assert "A: status" in st_a[0]["message"], f"Session A data leak: {st_a}"

        # Session B should only see its own message
        assert len(st_b) == 1
        assert "B: hashrate" in st_b[0]["message"], f"Session B data leak: {st_b}"

    def test_long_term_memory_isolation(self):
        """Session A's long-term preferences are isolated from Session B."""
        mm = MemoryManager()

        mm.save_long_term("session_A", "wallet", "bc1qAAAA")
        mm.save_long_term("session_B", "wallet", "bc1qBBBB")

        assert mm.get_long_term("session_A", "wallet") == "bc1qAAAA"
        assert mm.get_long_term("session_B", "wallet") == "bc1qBBBB"
        # Session C (new) should not have access to A or B data
        assert mm.get_long_term("session_C", "wallet") is None

    def test_user_profile_isolation(self):
        """User profiles are isolated per session."""
        mm = MemoryManager()

        mm.update_user_profile("session_A", {"wallet": "bc1qA", "name": "Alice"})
        mm.update_user_profile("session_B", {"wallet": "bc1qB", "name": "Bob"})

        profile_a = mm.get_user_profile("session_A")
        profile_b = mm.get_user_profile("session_B")

        assert profile_a["wallet"] == "bc1qA"
        assert profile_b["wallet"] == "bc1qB"
        assert profile_a["name"] == "Alice"
        assert profile_b["name"] == "Bob"

    def test_context_orchestrator_isolation(self):
        """ContextOrchestrator keeps per-session conversation history."""
        co = ContextOrchestrator()

        co.build_context("session_A", "msg A1", "MINING_STATUS",
                         user_data={"wallet": "bc1qA"})
        co.build_context("session_B", "msg B1", "PROBABILITY",
                         user_data={"wallet": "bc1qB"})
        co.build_context("session_A", "msg A2", "MINING_STATUS",
                         user_data={"wallet": "bc1qA"})

        history_a = co.get_history("session_A")
        history_b = co.get_history("session_B")

        # Session A has 2 turns
        assert len(history_a) == 2
        assert history_a[0]["message"] == "msg A1"
        assert history_a[1]["message"] == "msg A2"

        # Session B has 1 turn (isolated from A)
        assert len(history_b) == 1
        assert history_b[0]["message"] == "msg B1"

    def test_session_count_tracks_active_sessions(self):
        """MemoryManager tracks the number of active sessions."""
        mm = MemoryManager()
        assert mm.session_count() == 0

        mm.add_to_short_term("s1", {"msg": "hello"})
        mm.add_to_short_term("s2", {"msg": "world"})
        assert mm.session_count() == 2

    def test_session_exists_checks_activity(self):
        """session_exists() returns True for active sessions."""
        mm = MemoryManager()
        mm.add_to_short_term("active_session", {"msg": "test"})
        assert mm.session_exists("active_session")
        assert not mm.session_exists("nonexistent")

    def test_context_summary_includes_session_info(self):
        """Context summary returns per-session stats."""
        mm = MemoryManager()
        mm.add_to_short_term("s_test", {"msg": "test"})
        mm.save_long_term("s_test", "pref", "value")

        summary = mm.get_context_summary("s_test")
        assert summary["session_id"] == "s_test"
        assert summary["short_term_turns"] == 1
        assert "pref" in summary["long_term_keys"]
