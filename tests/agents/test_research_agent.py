"""
Minimal structural tests for ResearchAgent (stub).
"""

import pytest
from hermes.agents.research_agent import ResearchAgent


class TestResearchAgent:

    def test_returns_expected_keys(self):
        """Response has agent, status, analysis keys."""
        agent = ResearchAgent()
        result = agent.run({})

        assert "agent" in result
        assert result["agent"] == "ResearchAgent"
        assert "status" in result
        assert result["status"] == "success"
        assert "analysis" in result

    def test_analysis_contains_message(self):
        """analysis.message is a non-empty string."""
        agent = ResearchAgent()
        result = agent.run({})

        msg = result["analysis"]["message"]
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_planned_sources_is_list(self):
        """analysis.planned_sources is a non-empty list."""
        agent = ResearchAgent()
        result = agent.run({})

        sources = result["analysis"]["planned_sources"]
        assert isinstance(sources, list)
        assert len(sources) > 0
