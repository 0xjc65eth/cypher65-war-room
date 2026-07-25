"""
Minimal structural tests for QAAgent (stub).
"""

import pytest
from hermes.agents.qa_agent import QAAgent


class TestQAAgent:

    def test_returns_expected_keys(self):
        """Response has agent, status, analysis keys."""
        agent = QAAgent()
        result = agent.run({})

        assert "agent" in result
        assert result["agent"] == "QAAgent"
        assert "status" in result
        assert result["status"] == "success"
        assert "analysis" in result

    def test_checks_performed_is_list(self):
        """analysis.checks_performed is a non-empty list."""
        agent = QAAgent()
        result = agent.run({})

        checks = result["analysis"]["checks_performed"]
        assert isinstance(checks, list)
        assert len(checks) > 0

    def test_recommendation_is_string(self):
        """analysis.recommendation is a non-empty string."""
        agent = QAAgent()
        result = agent.run({})

        rec = result["analysis"]["recommendation"]
        assert isinstance(rec, str)
        assert len(rec) > 0
