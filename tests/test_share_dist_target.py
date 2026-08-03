"""
CYPHER65 // P0-1 — Live Mining → Probability funnel
====================================================
The Share Difficulty histogram (/api/chart-data?chart=share_dist) now carries
the network target difficulty + its histogram bucket so the UI can draw a
purple "target" reference line — actionable intel ("how far are my shares from
block-winning difficulty?"), not raw data.

Hermetic: conftest redirects DB_PATH to scratch BEFORE `import app`; the
chart-data route reads in-memory timeline_state + _last_valid_network, so
tests seed those globals directly and never touch the production DB.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as _app_module  # noqa: E402

app = _app_module.app


def _seed_session(diffs):
    """Seed the in-memory share_calc_history with raw share difficulties."""
    _app_module.timeline_state["share_calc_history"] = [
        {"ts": 1_700_000_000 + i, "share_diff_raw": d, "p_block_this_share": 0.01}
        for i, d in enumerate(diffs)
    ]


def _seed_network(difficulty):
    _app_module._last_valid_network["difficulty"] = difficulty


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset the in-memory session/network globals before each test so the
    share_dist route sees a deterministic histogram."""
    _seed_session([1e11, 2e11, 3e11, 4e11, 5e11])
    _seed_network(None)
    yield
    _seed_session([])
    _seed_network(None)


class TestShareDistTarget:
    def test_histogram_exposes_target_diff_and_bucket(self):
        _seed_network(3e11)  # falls inside the 1e11..5e11 histogram
        with app.test_client() as c:
            r = c.get("/api/chart-data?chart=share_dist&range=1h")
        assert r.status_code == 200
        d = r.get_json()
        assert d["target_diff"] == 3e11
        assert d["target_bucket"] is not None
        assert 0 <= d["target_bucket"] < len(d["datasets"][0]["data"])

    def test_target_below_histogram_clamps_to_zero(self):
        _seed_network(5e10)  # below lo=1e11 → bucket 0
        with app.test_client() as c:
            d = c.get("/api/chart-data?chart=share_dist&range=1h").get_json()
        assert d["target_diff"] == 5e10
        assert d["target_bucket"] == 0

    def test_target_above_histogram_clamps_to_last(self):
        _seed_network(9e11)  # above hi=5e11 → last bucket
        with app.test_client() as c:
            d = c.get("/api/chart-data?chart=share_dist&range=1h").get_json()
        assert d["target_bucket"] == len(d["datasets"][0]["data"]) - 1

    def test_no_network_difficulty_yields_null_target(self):
        with app.test_client() as c:
            d = c.get("/api/chart-data?chart=share_dist&range=1h").get_json()
        assert d["target_diff"] is None
        assert d["target_bucket"] is None

    def test_cum_p_chart_has_no_target_fields(self):
        with app.test_client() as c:
            d = c.get("/api/chart-data?chart=cum_p&range=1h").get_json()
        assert d["target_diff"] is None
        assert d["target_bucket"] is None

    def test_empty_session_yields_empty_histogram(self):
        _seed_session([])
        with app.test_client() as c:
            d = c.get("/api/chart-data?chart=share_dist&range=1h").get_json()
        assert d["labels"] == []
        assert d["datasets"][0]["data"] == []
