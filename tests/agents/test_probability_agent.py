"""
Unit tests for ProbabilityAgent.
Tests engine delegation, missing-engine handling, and zero-hashrate edge cases.
"""

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.calculate_block_probability.return_value = {
        "probability_at_least_one": 0.0624,
        "probability_zero": 0.9376,
        "expected_blocks": 0.0644,
        "expected_time_days": 15989,
        "lambda": 0.0644,
    }
    return engine


@pytest.fixture
def valid_payload():
    return {
        "user_hashrate": 500e12,
        "network_hashrate": 6e20,
        "duration": 86400,
        "network_difficulty": 112e12,
    }


class TestProbabilityAgentRun:

    def test_run_with_engine_returns_probability(self, mock_engine, valid_payload):
        """Valid data + engine → probability dict with summary."""
        from hermes.agents.probability_agent import ProbabilityAgent

        agent = ProbabilityAgent(probability_engine=mock_engine)
        result = agent.run(valid_payload)

        assert result["agent"] == "ProbabilityAgent"
        assert result["status"] == "success"
        assert "probability" in result
        assert result["probability"]["probability_at_least_one"] == 0.0624

        mock_engine.calculate_block_probability.assert_called_once()

    def test_run_without_engine_returns_error(self, valid_payload):
        """No engine injected → error status with message."""
        from hermes.agents.probability_agent import ProbabilityAgent

        agent = ProbabilityAgent(probability_engine=None)
        result = agent.run(valid_payload)

        assert result["status"] == "error"
        assert "not available" in result.get("message", "").lower()

    def test_run_with_zero_hashrate(self, mock_engine):
        """Hashrate=0 → error with helpful message."""
        from hermes.agents.probability_agent import ProbabilityAgent

        agent = ProbabilityAgent(probability_engine=mock_engine)
        result = agent.run({"user_hashrate": 0, "network_hashrate": 6e20,
                            "duration": 86400, "network_difficulty": 112e12})

        assert result["status"] == "error"
        assert "hashrate" in result.get("message", "").lower()
        # Engine should NOT be called with zero hashrate
        mock_engine.calculate_block_probability.assert_not_called()

    def test_summary_contains_expected_format(self, mock_engine, valid_payload):
        """Summary string contains TH/s, hours, percentage, days."""
        from hermes.agents.probability_agent import ProbabilityAgent

        agent = ProbabilityAgent(probability_engine=mock_engine)
        result = agent.run(valid_payload)

        summary = result["summary"]
        assert "TH/s" in summary
        assert "%" in summary
        assert "days" in summary


class TestProbabilityAgentStateFallback:
    """Test fallback to state when payload has missing hashrate."""

    def test_fetches_hashrate_from_state(self, mock_engine):
        """When payload hashrate=0, agent reads from state.latest_snapshot."""
        import hermes.agents.probability_agent as proba
        from unittest.mock import MagicMock, patch

        mock_state = MagicMock()
        mock_state.latest_snapshot = {
            "worker": {"hashrate": 300e12},
            "network": {"hashrate": 7e20, "difficulty": 115e12},
        }

        with patch.object(proba, "_state", mock_state):
            agent = proba.ProbabilityAgent(probability_engine=mock_engine)
            result = agent.run({
                "user_hashrate": 0,
                "network_hashrate": 0,
                "duration": 86400,
                "network_difficulty": 0,
            })

        assert result["status"] == "success"
        # Engine called with state values
        call_args = mock_engine.calculate_block_probability.call_args
        assert call_args[0][0] == 300e12  # user hashrate from state
