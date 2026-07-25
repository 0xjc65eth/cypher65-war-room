"""
Minimal structural tests for ProductAgent (stub).
"""

import pytest
from hermes.agents.product_agent import ProductAgent


class TestProductAgent:

    def test_returns_expected_keys(self):
        """Response has agent, status, analysis keys."""
        agent = ProductAgent()
        result = agent.run({})

        assert "agent" in result
        assert result["agent"] == "ProductAgent"
        assert "status" in result
        assert result["status"] == "success"
        assert "analysis" in result

    def test_overall_score_is_numeric(self):
        """analysis.overall_score is a number."""
        agent = ProductAgent()
        result = agent.run({})

        score = result["analysis"]["overall_score"]
        assert isinstance(score, (int, float))
        assert 0 <= score <= 100

    def test_product_score_categories_present(self):
        """Product score dict contains expected categories."""
        agent = ProductAgent()
        result = agent.run({})

        scores = result["analysis"]["product_score"]
        expected_categories = ["security", "reliability", "data_quality",
                               "mining_accuracy", "ux", "mobile",
                               "ai_intelligence", "product_maturity"]
        for cat in expected_categories:
            assert cat in scores, f"Missing category: {cat}"
            assert isinstance(scores[cat], (int, float))
