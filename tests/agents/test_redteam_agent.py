"""
Minimal structural tests for RedTeamAgent (stub).
"""

import pytest
from hermes.agents.redteam_agent import RedTeamAgent


class TestRedTeamAgent:

    def test_returns_expected_keys(self):
        """Response has agent, status, findings, summary keys."""
        agent = RedTeamAgent()
        result = agent.run({})

        assert "agent" in result
        assert result["agent"] == "RedTeamAgent"
        assert "status" in result
        assert result["status"] == "success"
        assert "findings" in result
        assert "summary" in result

    def test_findings_is_list_with_required_fields(self):
        """Each finding has type and message."""
        agent = RedTeamAgent()
        result = agent.run({})

        findings = result["findings"]
        assert isinstance(findings, list)
        assert len(findings) >= 1

        for finding in findings:
            assert "type" in finding
            assert "message" in finding
            assert finding["type"] in ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")

    def test_summary_is_string(self):
        """summary is a non-empty string."""
        agent = RedTeamAgent()
        result = agent.run({})

        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0
