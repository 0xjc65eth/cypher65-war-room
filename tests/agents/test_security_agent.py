"""
Unit tests for SecurityAgent.
Tests env-var-based security analysis with controlled environment.
"""

import os
import pytest


class TestSecurityAgentRun:

    def test_api_key_set_returns_protected(self, monkeypatch):
        """API_KEY set → PROTECTED status with endpoints listed."""
        monkeypatch.setenv("API_KEY", "my-secret-key")
        monkeypatch.delenv("DEBUG_MOCK", raising=False)

        from hermes.agents.security_agent import SecurityAgent

        agent = SecurityAgent()
        result = agent.run({})

        assert result["agent"] == "SecurityAgent"
        assert result["status"] == "success"
        assert result["analysis"]["api_key_protected"] is True
        assert "PROTECTED" in result["analysis"]["api_key_status"]

    def test_api_key_not_set_returns_unprotected(self, monkeypatch):
        """No API_KEY → UNPROTECTED with CRITICAL recommendation."""
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("DEBUG_MOCK", raising=False)

        from hermes.agents.security_agent import SecurityAgent

        agent = SecurityAgent()
        result = agent.run({})

        assert result["analysis"]["api_key_protected"] is False
        assert "UNPROTECTED" in result["analysis"]["api_key_status"]
        assert len(result["analysis"]["recommendations"]) >= 1
        assert any("API_KEY" in r for r in result["analysis"]["recommendations"])

    def test_debug_mock_enabled_warns(self, monkeypatch):
        """DEBUG_MOCK=1 → warning present."""
        monkeypatch.setenv("API_KEY", "key")
        monkeypatch.setenv("DEBUG_MOCK", "1")

        from hermes.agents.security_agent import SecurityAgent

        agent = SecurityAgent()
        result = agent.run({})

        assert result["analysis"]["mock_mode_enabled"] is True
        assert "ENABLED" in result["analysis"]["mock_mode_status"]
        assert any("DEBUG_MOCK" in r for r in result["analysis"]["recommendations"])

    def test_debug_mock_disabled_is_safe(self, monkeypatch):
        """No DEBUG_MOCK → production safe message."""
        monkeypatch.setenv("API_KEY", "key")
        monkeypatch.delenv("DEBUG_MOCK", raising=False)

        from hermes.agents.security_agent import SecurityAgent

        agent = SecurityAgent()
        result = agent.run({})

        assert result["analysis"]["mock_mode_enabled"] is False
        assert "DISABLED" in result["analysis"]["mock_mode_status"]
        assert "production safe" in result["analysis"]["mock_mode_status"].lower()

    def test_rate_limit_displayed(self, monkeypatch):
        """RATE_LIMIT_PER_MINUTE is included in analysis."""
        monkeypatch.setenv("API_KEY", "key")
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "120")

        from hermes.agents.security_agent import SecurityAgent

        agent = SecurityAgent()
        result = agent.run({})

        assert result["analysis"]["rate_limit_per_minute"] == 120

    def test_endpoints_protected_list_when_auth_on(self, monkeypatch):
        """When API_KEY is set, protected endpoints are listed."""
        monkeypatch.setenv("API_KEY", "key")

        from hermes.agents.security_agent import SecurityAgent

        agent = SecurityAgent()
        result = agent.run({})

        protected = result["analysis"]["endpoints_protected"]
        assert len(protected) >= 1
        assert "/api/hermes/chat" in protected
