"""
Unit tests for services/probability_engine.py — /api/probability/full endpoint.

Tests the 3 scenarios (conservative, base, aggressive) with 6 time windows
each (1h, 6h, 12h, 24h, 7d, 30d) and various edge cases.

Strategy: create a minimal Flask app, register probability routes, and
mock services.state to provide controlled snapshot data.
"""
import json
import math
from unittest.mock import patch, MagicMock
import pytest

from flask import Flask

from services.probability_engine import register_probability_routes
from services.probability import calculate_block_probability


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def app():
    """Create a minimal Flask app with only probability routes registered."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    register_probability_routes(flask_app)
    return flask_app


@pytest.fixture
def client(app):
    """Return a Flask test client for the probability app."""
    return app.test_client()


@pytest.fixture
def mock_snapshot():
    """Patch services.state.latest_snapshot with controlled mining data.

    Simulates a 100 TH/s worker on a ~600 EH/s network.
    """
    patcher = patch("services.probability_engine._get_snapshot_hashrate")
    mock_fn = patcher.start()
    mock_fn.return_value = {
        "user_hashrate": 100_000_000_000_000.0,   # 100 TH/s
        "network_hashrate": 600_000_000_000_000_000_000.0,  # 600 EH/s
        "network_difficulty": 127_170_500_429_035.0,
    }
    yield mock_fn
    patcher.stop()


# ════════════════════════════════════════════════════════════════════
#  Basic endpoint behavior
# ════════════════════════════════════════════════════════════════════


class TestProbabilityFullEndpoint:
    """Basic endpoint behavior tests."""

    ENDPOINT = "/api/probability/full"

    def test_returns_200_with_valid_hashrate(self, client, mock_snapshot):
        """With valid hashrate, should return 200."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None
        assert "scenarios" in data
        assert "user_hashrate" in data
        assert "network_hashrate" in data
        assert "source" in data

    def test_returns_400_without_hashrate_and_no_snapshot(self, client, monkeypatch):
        """Without hashrate param AND no snapshot, should return 400."""
        # Ensure the shared snapshot carries no worker hashrate — a prior
        # test in the suite may have left a hashrate behind.
        import services.state as _state
        monkeypatch.setattr(_state, "latest_snapshot", {"worker": {}, "network": {}})
        resp = client.get(self.ENDPOINT)
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data
        assert "hashrate" in data.get("hint", "")

    def test_returns_json_content_type(self, client, mock_snapshot):
        """Content-Type should be application/json."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000")
        assert resp.content_type == "application/json"

    def test_uses_snapshot_when_no_hashrate_param(self, client, mock_snapshot):
        """When hashrate param is omitted, should read from snapshot."""
        resp = client.get(self.ENDPOINT)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["source"] == "snapshot"
        assert data["user_hashrate"] == 100_000_000_000_000.0
        assert data["user_hashrate_str"] == "100.00 TH/s"

    def test_source_is_snapshot_when_snapshot_has_data(self, client, mock_snapshot):
        """When snapshot has hashrate > 0, source should be 'snapshot'."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=50000000000000")
        data = resp.get_json()
        assert data["source"] == "snapshot"
        assert data["user_hashrate"] == 50_000_000_000_000.0


# ════════════════════════════════════════════════════════════════════
#  Scenario structure (conservative / base / aggressive)
# ════════════════════════════════════════════════════════════════════


class TestProbabilityScenarios:
    """Tests for the 3 scenarios returned by the endpoint."""

    ENDPOINT = "/api/probability/full"

    def test_returns_three_scenarios(self, client, mock_snapshot):
        """Should return conservative, base, and aggressive scenarios."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000")
        data = resp.get_json()
        scenarios = data["scenarios"]
        assert "conservative" in scenarios
        assert "base" in scenarios
        assert "aggressive" in scenarios

    def test_conservative_is_80_percent_of_input(self, client, mock_snapshot):
        """Conservative scenario hashrate should be 80% of input."""
        input_hr = 100_000_000_000_000.0
        resp = client.get(f"{self.ENDPOINT}?hashrate={input_hr}")
        data = resp.get_json()
        cons = data["scenarios"]["conservative"]
        expected_hr = round(input_hr * 0.80, 0)
        assert cons["hashrate"] == expected_hr

    def test_base_is_100_percent_of_input(self, client, mock_snapshot):
        """Base scenario hashrate should be 100% of input."""
        input_hr = 100_000_000_000_000.0
        resp = client.get(f"{self.ENDPOINT}?hashrate={input_hr}")
        data = resp.get_json()
        base = data["scenarios"]["base"]
        assert base["hashrate"] == round(input_hr, 0)

    def test_aggressive_is_120_percent_of_input(self, client, mock_snapshot):
        """Aggressive scenario hashrate should be 120% of input."""
        input_hr = 100_000_000_000_000.0
        resp = client.get(f"{self.ENDPOINT}?hashrate={input_hr}")
        data = resp.get_json()
        aggr = data["scenarios"]["aggressive"]
        expected_hr = round(input_hr * 1.20, 0)
        assert aggr["hashrate"] == expected_hr

    def test_scenario_hashrates_are_correctly_ordered(self, client, mock_snapshot):
        """Hashrates should be: conservative < base < aggressive."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000")
        data = resp.get_json()
        scenarios = data["scenarios"]
        assert scenarios["conservative"]["hashrate"] < scenarios["base"]["hashrate"]
        assert scenarios["base"]["hashrate"] < scenarios["aggressive"]["hashrate"]

    def test_each_scenario_has_hashrate_str(self, client, mock_snapshot):
        """Each scenario should have a human-readable hashrate_str."""
        input_hr = 100_000_000_000_000.0
        resp = client.get(f"{self.ENDPOINT}?hashrate={input_hr}")
        data = resp.get_json()
        for name in ("conservative", "base", "aggressive"):
            s = data["scenarios"][name]
            assert "hashrate_str" in s
            assert isinstance(s["hashrate_str"], str)
            assert "TH/s" in s["hashrate_str"] or "PH/s" in s["hashrate_str"]

    def test_conservative_has_lowest_probability(self, client, mock_snapshot):
        """Conservative scenario should have the lowest probability for same period."""
        input_hr = 100_000_000_000_000.0
        resp = client.get(f"{self.ENDPOINT}?hashrate={input_hr}")
        data = resp.get_json()
        scenarios = data["scenarios"]
        # For 24h period, probabilities should be ordered: cons < base < aggr
        p_cons = scenarios["conservative"]["periods"]["24h"]["probability_at_least_one"]
        p_base = scenarios["base"]["periods"]["24h"]["probability_at_least_one"]
        p_aggr = scenarios["aggressive"]["periods"]["24h"]["probability_at_least_one"]
        assert p_cons < p_base < p_aggr


# ════════════════════════════════════════════════════════════════════
#  Period structure (1h, 6h, 12h, 24h, 7d, 30d)
# ════════════════════════════════════════════════════════════════════


class TestProbabilityPeriods:
    """Tests for the 6 time windows returned per scenario."""

    ENDPOINT = "/api/probability/full"

    SIX_PERIODS = {"1h", "6h", "12h", "24h", "7d", "30d"}

    def test_each_scenario_has_six_periods(self, client, mock_snapshot):
        """Each scenario should have all 6 standard time windows."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000")
        data = resp.get_json()
        for name in ("conservative", "base", "aggressive"):
            periods = data["scenarios"][name]["periods"]
            period_keys = set(periods.keys())
            assert period_keys == self.SIX_PERIODS, (
                f"{name} has {period_keys - self.SIX_PERIODS} extra, "
                f"missing {self.SIX_PERIODS - period_keys}"
            )

    def test_longer_periods_have_higher_probability(self, client, mock_snapshot):
        """Within a scenario, longer periods should have higher probability >= 1 block."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000")
        data = resp.get_json()
        periods = data["scenarios"]["base"]["periods"]
        # Check monotonic: 1h <= 6h <= 12h <= 24h <= 7d <= 30d
        prev_p = 0.0
        for label in ("1h", "6h", "12h", "24h", "7d", "30d"):
            p = periods[label]["probability_at_least_one"]
            assert p >= prev_p, f"{label} probability {p} < previous {prev_p}"
            prev_p = p

    def test_each_period_has_expected_fields(self, client, mock_snapshot):
        """Each period should contain all calculation result fields."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000")
        data = resp.get_json()
        period = data["scenarios"]["base"]["periods"]["24h"]
        required_fields = [
            "probability_at_least_one",
            "probability_zero",
            "expected_blocks",
            "expected_time_to_block_seconds",
            "expected_time_to_block_human",
            "lambda",
            "duration_seconds",
            "note",
        ]
        for field in required_fields:
            assert field in period, f"Missing field: {field}"

    def test_probability_values_are_in_range(self, client, mock_snapshot):
        """All probability values should be between 0 and 1."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000")
        data = resp.get_json()
        for name in ("conservative", "base", "aggressive"):
            for label in ("1h", "6h", "12h", "24h", "7d", "30d"):
                p = data["scenarios"][name]["periods"][label]
                assert 0.0 <= p["probability_at_least_one"] <= 1.0
                assert 0.0 <= p["probability_zero"] <= 1.0
                assert p["expected_blocks"] >= 0.0

    def test_probability_zero_plus_at_least_one_equals_one(self, client, mock_snapshot):
        """probability_zero + probability_at_least_one should equal approximately 1."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000")
        data = resp.get_json()
        period = data["scenarios"]["base"]["periods"]["24h"]
        total = period["probability_zero"] + period["probability_at_least_one"]
        assert abs(total - 1.0) < 0.0001, f"Sum is {total}, expected ~1.0"

    def test_lambda_equals_duration_times_hashrate_ratio(self, client, mock_snapshot):
        """Verify lambda = (user_hr / net_hr) * (duration / 600)."""
        input_hr = 100_000_000_000_000.0
        net_hr = 600_000_000_000_000_000_000.0
        # Use query_string dict to avoid URL encoding issues with `+` in `6e+20`
        resp = client.get(self.ENDPOINT, query_string={
            "hashrate": str(input_hr),
            "network_hashrate": str(net_hr),
        })
        data = resp.get_json()
        period = data["scenarios"]["base"]["periods"]["24h"]  # 86400s
        expected_lambda = (input_hr / net_hr) * (86400 / 600.0)
        assert period["lambda"] == pytest.approx(expected_lambda, rel=1e-3)


# ════════════════════════════════════════════════════════════════════
#  Network info in response
# ════════════════════════════════════════════════════════════════════


class TestProbabilityNetworkInfo:
    """Tests for network info fields in the response."""

    ENDPOINT = "/api/probability/full"

    def test_returns_network_hashrate(self, client, mock_snapshot):
        """Response should include network_hashrate."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000")
        data = resp.get_json()
        assert "network_hashrate" in data
        assert data["network_hashrate"] > 0

    def test_returns_network_hashrate_str(self, client, mock_snapshot):
        """Response should include human-readable network_hashrate_str."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000")
        data = resp.get_json()
        assert "network_hashrate_str" in data
        assert isinstance(data["network_hashrate_str"], str)

    def test_returns_network_difficulty(self, client, mock_snapshot):
        """Response should include network_difficulty from snapshot."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000")
        data = resp.get_json()
        assert "network_difficulty" in data
        assert data["network_difficulty"] == 127_170_500_429_035.0

    def test_network_difficulty_none_when_not_in_snapshot(self, client):
        """When snapshot has no difficulty, response should include None."""
        with patch("services.probability_engine._get_snapshot_hashrate") as mock_fn:
            mock_fn.return_value = {
                "user_hashrate": 100_000_000_000_000.0,
                "network_hashrate": 600_000_000_000_000_000_000.0,
                "network_difficulty": None,
            }
            resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000")
            data = resp.get_json()
            assert data["network_difficulty"] is None


# ════════════════════════════════════════════════════════════════════
#  Mathematical correctness
# ════════════════════════════════════════════════════════════════════


class TestProbabilityMath:
    """Verify the math correctness of the probability calculations."""

    ENDPOINT = "/api/probability/full"

    def test_expected_blocks_matches_lambda(self, client, mock_snapshot):
        """expected_blocks should equal lambda for each period.
        Note: expected_blocks uses round(x, 4) while lambda uses round(x, 6).
        Maximum rounding delta is ~0.00005, so abs=1e-3 covers all cases."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000")
        data = resp.get_json()
        for name in ("conservative", "base", "aggressive"):
            for label in ("1h", "6h", "12h", "24h", "7d", "30d"):
                p = data["scenarios"][name]["periods"][label]
                assert p["expected_blocks"] == pytest.approx(p["lambda"], abs=1e-3)

    def test_duration_seconds_correct(self, client, mock_snapshot):
        """Each period should report its correct duration in seconds."""
        expected_durations = {
            "1h": 3600, "6h": 21600, "12h": 43200,
            "24h": 86400, "7d": 604800, "30d": 2592000,
        }
        resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000")
        data = resp.get_json()
        for label, expected_secs in expected_durations.items():
            p = data["scenarios"]["base"]["periods"][label]
            assert p["duration_seconds"] == expected_secs, (
                f"{label} duration_seconds: {p['duration_seconds']} != {expected_secs}"
            )

    def test_very_small_hashrate_still_valid(self, client, mock_snapshot):
        """Very small hashrate (1 GH/s) should still produce valid calculations."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=1000000000")
        assert resp.status_code == 200
        data = resp.get_json()
        scenarios = data["scenarios"]
        for name in ("conservative", "base", "aggressive"):
            for label in ("1h", "6h", "12h", "24h", "7d", "30d"):
                p = scenarios[name]["periods"][label]
                assert 0.0 <= p["probability_at_least_one"] <= 1.0
                assert p["expected_blocks"] >= 0.0
                assert p["expected_time_to_block_seconds"] > 0

    def test_large_hashrate_near_certainty(self, client, mock_snapshot):
        """Very large hashrate (~1% of network) should approach certainty."""
        # 1% of 600 EH/s = 6e18 H/s → expected ~43 blocks/month
        resp = client.get(f"{self.ENDPOINT}?hashrate=6000000000000000000")
        assert resp.status_code == 200
        data = resp.get_json()
        p_30d = data["scenarios"]["base"]["periods"]["30d"]["probability_at_least_one"]
        assert p_30d > 0.99
        # Also verify expected blocks ~43/month for 1% of network
        exp_blocks = data["scenarios"]["base"]["periods"]["30d"]["expected_blocks"]
        assert exp_blocks > 40.0

    def test_expected_time_to_block_is_human_readable(self, client, mock_snapshot):
        """expected_time_to_block_human should be a non-empty string."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000")
        data = resp.get_json()
        for name in ("conservative", "base", "aggressive"):
            p = data["scenarios"][name]["periods"]["1h"]
            assert isinstance(p["expected_time_to_block_human"], str)
            assert len(p["expected_time_to_block_human"]) > 0

    def test_disclaimer_note_present(self, client, mock_snapshot):
        """Each period should have the 'expected value' disclaimer note."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000")
        data = resp.get_json()
        p = data["scenarios"]["base"]["periods"]["24h"]
        assert "EXPECTED VALUE" in p["note"]
        assert "NOT A GUARANTEE" in p["note"]


# ════════════════════════════════════════════════════════════════════
#  Error handling
# ════════════════════════════════════════════════════════════════════


class TestProbabilityErrorHandling:
    """Error handling and edge cases."""

    ENDPOINT = "/api/probability/full"

    def test_zero_hashrate_returns_error(self, client, mock_snapshot):
        """Zero hashrate should return 400 with hint message."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=0")
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data
        assert "hint" in data

    def test_negative_hashrate_returns_error(self, client, mock_snapshot):
        """Negative hashrate should return 400."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=-1000")
        assert resp.status_code == 400

    def test_invalid_hashrate_param_returns_error(self, client, mock_snapshot):
        """Non-numeric hashrate should return 400."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=abc")
        assert resp.status_code == 400

    def test_network_hashrate_zero_passed_through(self, client, mock_snapshot):
        """When network_hashrate=0 is passed, it overrides snapshot (no default)."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000&network_hashrate=0")
        # Even with network_hr=0, the endpoint will calculate (network_hashrate=0 in response)
        # The endpoint passes the query param through — 0 is used as-is
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["network_hashrate"] == 0.0

    def test_hashrate_as_float_string(self, client, mock_snapshot):
        """Hashrate as a float string should be accepted."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=100000000000000.0")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["user_hashrate"] == 100_000_000_000_000.0

    def test_large_hashrate_as_scientific_notation(self, client, mock_snapshot):
        """Hashrate as scientific notation should be accepted."""
        resp = client.get(f"{self.ENDPOINT}?hashrate=1e14")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["user_hashrate"] == 100_000_000_000_000.0

    def test_calculations_match_direct_function_call(self, client, mock_snapshot):
        """Endpoint results should match direct calculate_multiple_periods call."""
        input_hr = 100_000_000_000_000.0
        net_hr = 600_000_000_000_000_000_000.0

        # Use query_string dict to avoid URL encoding issues with `+` in `6e+20`
        resp = client.get(self.ENDPOINT, query_string={
            "hashrate": str(input_hr),
            "network_hashrate": str(net_hr),
        })
        data = resp.get_json()

        # Direct calculation
        from services.probability import calculate_multiple_periods
        direct = calculate_multiple_periods(input_hr, net_hr)

        base_periods = data["scenarios"]["base"]["periods"]
        direct_periods = direct["periods"]

        for label in ("1h", "6h", "12h", "24h", "7d", "30d"):
            ep = base_periods[label]
            dp = direct_periods[label]
            assert ep["probability_at_least_one"] == pytest.approx(
                dp["probability_at_least_one"], rel=1e-6
            )
            # Both use round(x,4) — should be identical, but use abs=1e-3 for safety
            assert ep["expected_blocks"] == pytest.approx(
                dp["expected_blocks"], abs=1e-3
            )
