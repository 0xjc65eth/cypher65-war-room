"""
Unit tests for PerformanceAgent.
Mocks services.state to avoid real data dependencies.
"""

import time
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def real_payload():
    return {
        "user_hashrate": 300e12,
        "worker_status": "hashing",
        "worker_last_submit": int(time.time()) - 30,
        "worker_uptime": 86400 * 5,
        "all_workers": [
            {"name": "worker-alpha", "hashrate": 200e12},
            {"name": "worker-beta", "hashrate": 100e12},
            {"name": "worker-gamma", "hashrate": 50e12},
        ],
        "session_share_count": 89,
        "_data_source": "REAL",
    }


@pytest.fixture
def empty_payload():
    return {}


class TestPerformanceAgentRun:

    def test_run_with_real_data(self, real_payload):
        """REAL data → structured metrics returned."""
        from hermes.agents.performance_agent import PerformanceAgent

        agent = PerformanceAgent()
        result = agent.run(real_payload)

        assert result["agent"] == "PerformanceAgent"
        assert result["status"] == "success"
        assert result["data_source"] == "REAL"
        assert "analysis" in result

        analysis = result["analysis"]
        assert analysis["hashrate_ths"] == 300.0
        assert analysis["worker_status"] == "hashing"
        assert analysis["session_shares"] == 89
        assert analysis["worker_count"] == 3

    def test_run_with_no_data(self, empty_payload):
        """Empty payload → NO DATA with message."""
        from hermes.agents.performance_agent import PerformanceAgent

        agent = PerformanceAgent()
        result = agent.run(empty_payload)

        assert result["data_source"] == "NO_DATA"
        assert result["analysis"]["status"] == "NO DATA"
        assert "Performance metrics require active mining data" in result["analysis"]["message"]

    def test_stale_worker_detected(self, real_payload):
        """Last share >300s ago → STALE_WORKER flag."""
        from hermes.agents.performance_agent import PerformanceAgent

        stale_payload = {**real_payload, "worker_last_submit": int(time.time()) - 600}

        agent = PerformanceAgent()
        result = agent.run(stale_payload)

        assert result["analysis"]["stale_warning"] is True
        assert "STALE_WORKER" in result["analysis"]["detection_flags"]

    def test_healthy_worker(self, real_payload):
        """Recent share + hashing status → HEALTHY flag."""
        from hermes.agents.performance_agent import PerformanceAgent

        agent = PerformanceAgent()
        result = agent.run(real_payload)

        assert result["analysis"]["stale_warning"] is False
        assert "HEALTHY" in result["analysis"]["detection_flags"]

    def test_offline_detection(self, real_payload):
        """status=offline → OFFLINE in detection flags."""
        from hermes.agents.performance_agent import PerformanceAgent

        offline_payload = {**real_payload, "worker_status": "offline"}

        agent = PerformanceAgent()
        result = agent.run(offline_payload)

        assert "OFFLINE" in result["analysis"]["detection_flags"]

    def test_idle_detection(self, real_payload):
        """status=idle → IDLE in detection flags."""
        from hermes.agents.performance_agent import PerformanceAgent

        idle_payload = {**real_payload, "worker_status": "idle"}

        agent = PerformanceAgent()
        result = agent.run(idle_payload)

        assert "IDLE" in result["analysis"]["detection_flags"]

    def test_worker_ranking_best_worst(self, real_payload):
        """Multiple workers → best/worst identified by hashrate."""
        from hermes.agents.performance_agent import PerformanceAgent

        agent = PerformanceAgent()
        result = agent.run(real_payload)

        assert result["analysis"]["best_worker"] == "worker-alpha"
        assert result["analysis"]["best_worker_hr_ths"] == 200.0
        assert result["analysis"]["worst_worker"] == "worker-gamma"
        assert result["analysis"]["worst_worker_hr_ths"] == 50.0

    def test_worker_ranking_empty_list(self, real_payload):
        """Workers with no hashrate → best/worst not set."""
        from hermes.agents.performance_agent import PerformanceAgent

        empty_workers = [
            {"name": "no-hr-1"},
            {"name": "no-hr-2"},
        ]
        payload = {**real_payload, "all_workers": empty_workers}

        agent = PerformanceAgent()
        result = agent.run(payload)

        assert "best_worker" not in result["analysis"]

    def test_unavailable_metrics_explicitly_marked(self, real_payload):
        """Temp, power, fan, errors all marked NOT AVAILABLE."""
        from hermes.agents.performance_agent import PerformanceAgent

        agent = PerformanceAgent()
        result = agent.run(real_payload)

        unavailable = result["analysis"]["unavailable_metrics"]
        for metric in ["temperature", "power_watts", "fan_speed", "hardware_errors"]:
            assert metric in unavailable
            assert "NOT AVAILABLE" in unavailable[metric]

    def test_uptime_display_format(self, real_payload):
        """Uptime seconds → human-readable 'Xd Yh' format."""
        from hermes.agents.performance_agent import PerformanceAgent

        agent = PerformanceAgent()
        result = agent.run(real_payload)

        assert "uptime_display" in result["analysis"]
        assert "d" in result["analysis"]["uptime_display"]


class TestPerformanceAgentStateFallback:

    def test_fetches_from_state_when_payload_empty(self):
        """Agent reads from state when payload has no data."""
        import hermes.agents.performance_agent as pa

        mock_state = MagicMock()
        mock_state.latest_snapshot = {
            "worker": {"hashrate": 150e12, "status": "online",
                       "lastSubmission": int(time.time()) - 60,
                       "uptime": 172800},
            "all_workers": [{"name": "w1", "hashrate": 150e12}],
        }
        mock_state.session_share_count = 10

        with patch.object(pa, "_state", mock_state):
            agent = pa.PerformanceAgent()
            result = agent.run({})

        assert result["data_source"] == "REAL"
        assert result["analysis"]["hashrate_ths"] == 150.0
