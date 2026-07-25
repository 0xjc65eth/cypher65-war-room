"""
Unit tests for FinancialAgent.
Mocks services.state to avoid real data dependencies.
"""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def complete_payload():
    """Payload with all data needed for revenue calculation."""
    return {
        "user_hashrate": 500e12,
        "network_hashrate": 6e20,
        "pool_hashrate": 100e15,
        "btc_usd": 67000,
        "btc_brl": 350000,
        "_data_source": "REAL",
    }


@pytest.fixture
def empty_payload():
    return {}


class TestFinancialAgentRun:

    def test_run_with_complete_data(self, complete_payload):
        """Real data → revenue estimates calculated."""
        from hermes.agents.financial_agent import FinancialAgent

        agent = FinancialAgent()
        result = agent.run(complete_payload)

        assert result["agent"] == "FinancialAgent"
        assert result["status"] == "success"
        assert result["data_source"] == "REAL"

        analysis = result["analysis"]
        assert analysis["status"] == "ESTIMATED"
        assert analysis["estimated_daily_usd"] > 0
        assert analysis["estimated_daily_btc"] > 0
        assert analysis["hashrate_ths"] == 500.0
        assert analysis["btc_price_usd"] == 67000

    def test_estimated_monthly_is_30x_daily(self, complete_payload):
        """Monthly estimates = daily * 30."""
        from hermes.agents.financial_agent import FinancialAgent

        agent = FinancialAgent()
        result = agent.run(complete_payload)

        daily = result["analysis"]["estimated_daily_usd"]
        monthly = result["analysis"]["estimated_monthly_usd"]
        assert monthly == pytest.approx(daily * 30, rel=1e-2)

    def test_brl_conversion(self, complete_payload):
        """When btc_brl is provided, BRL estimates are calculated."""
        from hermes.agents.financial_agent import FinancialAgent

        agent = FinancialAgent()
        result = agent.run(complete_payload)

        assert result["analysis"]["estimated_daily_brl"] > 0
        assert result["analysis"]["estimated_monthly_brl"] > 0

    def test_run_with_no_data(self, empty_payload):
        """Empty payload → DATA REQUIRED status."""
        from hermes.agents.financial_agent import FinancialAgent

        agent = FinancialAgent()
        result = agent.run(empty_payload)

        assert result["data_source"] == "NO_DATA"
        assert result["analysis"]["status"] == "DATA REQUIRED"
        assert "Financial analysis requires real mining data" in result["analysis"]["message"]

    def test_run_with_insufficient_data(self, complete_payload):
        """When real data source but no usable metrics → appropriate status."""
        from hermes.agents.financial_agent import FinancialAgent

        # _data_source=REAL but hashrate=0 triggers early return with DATA REQUIRED
        zero_payload = {**complete_payload, "user_hashrate": 0, "_data_source": "REAL"}
        agent = FinancialAgent()
        result = agent.run(zero_payload)

        # Agent returns early with DATA REQUIRED when hashrate <= 0
        assert result["analysis"]["status"] == "DATA REQUIRED"
        assert "Financial analysis requires real mining data" in result["analysis"]["message"]

    def test_all_outputs_marked_estimated(self, complete_payload):
        """Status is always ESTIMATED when data is real."""
        from hermes.agents.financial_agent import FinancialAgent

        agent = FinancialAgent()
        result = agent.run(complete_payload)

        assert result["analysis"]["status"] == "ESTIMATED"
        assert "note" in result["analysis"]
        assert "ESTIMATED" in result["analysis"]["note"]

    def test_data_provenance_declared(self, complete_payload):
        """Data provenance field explains what's real vs estimated."""
        from hermes.agents.financial_agent import FinancialAgent

        agent = FinancialAgent()
        result = agent.run(complete_payload)

        assert "data_provenance" in result["analysis"]
        assert "REAL hashrate" in result["analysis"]["data_provenance"]


class TestFinancialAgentStateFallback:

    def test_fetches_from_state_when_payload_empty(self):
        """Agent reads from state when payload has no data."""
        import hermes.agents.financial_agent as fa

        mock_state = MagicMock()
        mock_state.latest_snapshot = {
            "worker": {"hashrate": 400e12},
            "network": {"hashrate": 6e20},
            "btc_price": {"usd": 68000, "brl": 355000},
            "pool_hashrate": 120e15,
        }

        with patch.object(fa, "_state", mock_state):
            agent = fa.FinancialAgent()
            result = agent.run({})

        assert result["data_source"] == "REAL"
        assert result["analysis"]["hashrate_ths"] == 400.0
