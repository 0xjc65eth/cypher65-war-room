"""
Unit tests for MiningAgent.
Mocks services.state to avoid real data dependencies.
"""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def real_payload():
    return {
        "user_hashrate": 500e12,
        "worker_status": "hashing",
        "worker_best_diff": "1.5G",
        "worker_last_submit": 0,  # will be replaced per-test
        "worker_uptime": 86400 * 3,
        "all_workers": [
            {"name": "worker1", "hashrate": 300e12},
            {"name": "worker2", "hashrate": 200e12},
        ],
        "network_hashrate": 6e20,
        "network_difficulty": 112e12,
        "pool_hashrate": 100e15,
        "pool_workers": 42,
        "btc_usd": 67000,
        "session_share_count": 150,
        "_data_source": "REAL",
    }


@pytest.fixture
def empty_payload():
    return {}


@pytest.fixture
def mock_probability_engine():
    engine = MagicMock()
    engine.calculate_block_probability.return_value = {
        "probability_at_least_one": 0.00579,
        "probability_zero": 0.99421,
        "expected_blocks": 0.0058,
        "expected_time_days": 172.7,
    }
    return engine


class TestMiningAgentRun:
    """Happy path and error path tests for MiningAgent.run()."""

    def test_run_with_real_data(self, real_payload):
        """With REAL data, returns structured analysis with summary."""
        from hermes.agents.mining_agent import MiningAgent

        agent = MiningAgent()
        result = agent.run(real_payload)

        assert result["agent"] == "MiningAgent"
        assert result["status"] == "success"
        assert result["data_source"] == "REAL"
        assert "analysis" in result
        assert "summary" in result

        analysis = result["analysis"]
        assert analysis["hashrate_ths"] == 500.0
        assert analysis["worker_count"] == 2
        assert analysis["session_share_count"] == 150

    def test_summary_contains_expected_fields(self, real_payload):
        """Summary string contains hashrate, status, and worker count."""
        from hermes.agents.mining_agent import MiningAgent

        agent = MiningAgent()
        result = agent.run(real_payload)

        summary = result["summary"]
        assert "500.00 TH/s" in summary
        assert "HASHING" in summary
        assert "|" in summary  # pipe-separated format

    def test_run_with_no_data(self, empty_payload):
        """Empty payload returns NO_DATA and a helpful message."""
        from hermes.agents.mining_agent import MiningAgent

        agent = MiningAgent()
        result = agent.run(empty_payload)

        assert result["data_source"] == "NO_DATA"
        assert "No real mining data" in result["summary"]

    def test_run_with_probability_engine(self, real_payload, mock_probability_engine):
        """Inject mock engine → analysis.probability is populated."""
        from hermes.agents.mining_agent import MiningAgent

        agent = MiningAgent(probability_engine=mock_probability_engine)
        result = agent.run(real_payload)

        assert "probability" in result["analysis"]
        prob = result["analysis"]["probability"]
        assert "probability_at_least_one" in prob
        assert prob["probability_at_least_one"] == 0.00579

    def test_run_without_probability_engine(self, real_payload):
        """No engine → probability key not present or None."""
        from hermes.agents.mining_agent import MiningAgent

        agent = MiningAgent(probability_engine=None)
        result = agent.run(real_payload)

        # Without engine, probability should be absent or None
        prob = result["analysis"].get("probability")
        assert prob is None, f"Expected None, got {prob}"

    def test_status_display_labels(self, real_payload):
        """Worker status maps to correct display labels."""
        from hermes.agents.mining_agent import MiningAgent

        agent = MiningAgent()
        status_map = {
            "hashing": "HASHING",
            "online": "ONLINE",
            "idle": "IDLE",
            "offline": "OFFLINE",
            "unknown": "UNKNOWN",
        }

        for status, expected in status_map.items():
            payload = {**real_payload, "worker_status": status}
            result = agent.run(payload)
            assert expected in result["analysis"]["status_display"]


class TestMiningAgentStateFallback:
    """Tests for _get_real_data() fallback when payload has no data."""

    def test_fetches_from_state_when_payload_empty(self):
        """When payload has no _data_source, agent reads from state snapshot."""
        import hermes.agents.mining_agent as ma

        mock_state = MagicMock()
        mock_state.latest_snapshot = {
            "worker": {"hashrate": 250e12, "status": "hashing",
                       "bestDifficulty": "500M", "lastSubmission": 12345,
                       "uptime": 86400},
            "network": {"hashrate": 6e20, "difficulty": 112e12},
            "all_workers": [{"name": "w1"}],
            "pool_hashrate": 80e15,
            "pool_workers": 30,
            "btc_price": {"usd": 66000},
        }
        mock_state.session_share_count = 42

        with patch.object(ma, "_state", mock_state):
            agent = ma.MiningAgent()
            result = agent.run({})

        assert result["data_source"] == "REAL"
        assert result["analysis"]["hashrate_ths"] == 250.0
        assert result["analysis"]["session_share_count"] == 42
