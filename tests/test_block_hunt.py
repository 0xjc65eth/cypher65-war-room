"""Tests for Milestone 6: Block Hunt + Best Difficulty history."""

import time
import pytest

from app import app, _persist_best_diff_history, _get_best_diff_history, latest_snapshot


class TestBlockHunt:
    @pytest.fixture
    def client(self):
        app.config["TESTING"] = True
        yield app.test_client()

    def test_block_hunt_returns_panel(self, client, monkeypatch):
        # Provide a deterministic latest_snapshot for the test
        monkeypatch.setattr(
            "app.latest_snapshot",
            {
                "network": {"hashrate": 6e20, "difficulty": 8e13, "height": 840000},
                "worker": {"hashrate": 1.5e14, "bestDifficulty": "45.2T"},
                "leaderboard_entry": {"rank": 12, "diffRank": 11},
            },
            raising=False,
        )

        response = client.get("/api/block-hunt")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

        assert data["network"]["hashrate"] == 6e20
        assert data["network"]["difficulty"] == 8e13
        assert data["network"]["block_height"] == 840000

        assert data["user"]["hashrate"] == 1.5e14
        assert data["user"]["best_difficulty"] > 0

        prob = data["probability"]
        assert "chance_1h" in prob
        assert "chance_24h" in prob
        assert "chance_7d" in prob
        assert prob["chance_24h"] is not None
        assert prob["chance_24h"] > 0

        comparison = data["network_comparison"]
        assert comparison["hashrate_pct_of_network"] > 0
        assert comparison["distance_to_block_factor"] is not None
        assert comparison["distance_to_all_time_best_factor"] is None
        assert comparison["approx_difficulty_rank"] == 11

    def test_block_hunt_handles_missing_snapshot(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.latest_snapshot",
            {"network": {}, "worker": {}},
            raising=False,
        )

        response = client.get("/api/block-hunt")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["probability"]["chance_24h"] is None


class TestBlockHuntSnapshotInjection:
    """P1.2 — /api/snapshot must inject the `block_hunt` payload consumed by
    renderBlockHunt(snap) in static/app.js (snap.block_hunt)."""

    @pytest.fixture
    def client(self):
        app.config["TESTING"] = True
        yield app.test_client()

    def _snapshot(self):
        return {
            "network": {"hashrate": 6e20, "difficulty": 8e13, "height": 840000},
            "worker": {"hashrate": 1.5e14, "bestDifficulty": "45.2T", "name": "cypher65"},
            "leaderboard_entry": {"rank": 12, "diffRank": 11},
            "proximity": {
                "all_time_best_diff_raw": 9e13,
                "live_calc": {
                    "session_totals": {"cum_p_block": 0.0314},
                },
            },
        }

    def test_snapshot_injects_block_hunt(self, client, monkeypatch):
        """/api/snapshot should include snap.block_hunt with the flat fields
        renderBlockHunt reads: network_difficulty, best_difficulty,
        p_block_per_share, expected_time_seconds, cumulative_p_block,
        best_diff_worker."""
        monkeypatch.setattr("app.latest_snapshot", self._snapshot(), raising=False)
        # Stub the market plumbing that /api/snapshot also calls.
        monkeypatch.setattr("app._get_hashrate_market_offers", lambda: [], raising=False)
        monkeypatch.setattr("app._build_market_highlights", lambda *a, **k: [], raising=False)

        response = client.get("/api/snapshot")
        assert response.status_code == 200
        data = response.get_json()

        bh = data.get("block_hunt") or {}
        assert bh["network_difficulty"] == 8e13
        assert bh["best_difficulty"] == 45.2e12
        # p_block_per_share = best_difficulty / network_difficulty
        assert bh["p_block_per_share"] == pytest.approx(45.2e12 / 8e13)
        assert bh["expected_time_seconds"] is not None
        assert bh["cumulative_p_block"] == pytest.approx(0.0314)
        assert bh["best_diff_worker"] == "cypher65"
        # grouped contract still present
        assert bh["network"]["hashrate"] == 6e20
        assert bh["user"]["hashrate"] == 1.5e14
        assert bh["probability"]["chance_24h"] > 0

    def test_snapshot_block_hunt_empty_when_no_data(self, client, monkeypatch):
        """Empty snapshot should produce zeroed block_hunt (no crash, no NaN)."""
        monkeypatch.setattr(
            "app.latest_snapshot",
            {"network": {}, "worker": {}, "proximity": {}},
            raising=False,
        )
        monkeypatch.setattr("app._get_hashrate_market_offers", lambda: [], raising=False)
        monkeypatch.setattr("app._build_market_highlights", lambda *a, **k: [], raising=False)

        response = client.get("/api/snapshot")
        assert response.status_code == 200
        bh = response.get_json().get("block_hunt") or {}
        assert bh["network_difficulty"] == 0
        assert bh["best_difficulty"] == 0
        assert bh["p_block_per_share"] is None
        assert bh["expected_time_seconds"] is None
        assert bh["cumulative_p_block"] is None

    def test_snapshot_block_hunt_matches_dedicated_endpoint(self, client, monkeypatch):
        """The injected block_hunt payload should agree with /api/block-hunt
        for the same snapshot (shared computation)."""
        monkeypatch.setattr("app.latest_snapshot", self._snapshot(), raising=False)
        monkeypatch.setattr("app._get_hashrate_market_offers", lambda: [], raising=False)
        monkeypatch.setattr("app._build_market_highlights", lambda *a, **k: [], raising=False)

        snap_resp = client.get("/api/snapshot")
        bh_resp = client.get("/api/block-hunt")
        bh = snap_resp.get_json()["block_hunt"]
        endp = bh_resp.get_json()

        assert bh["network_difficulty"] == endp["network"]["difficulty"]
        assert bh["best_difficulty"] == endp["user"]["best_difficulty"]
        assert bh["expected_time_seconds"] == endp["probability"]["expected_time_to_block_seconds"]


class TestBestDiffHistory:
    @pytest.fixture
    def client(self):
        app.config["TESTING"] = True
        yield app.test_client()

    def test_global_best_diff_history(self, client):
        _persist_best_diff_history(int(time.time()), 4.5e12, "4.5T", "cypher65", "parasite")

        response = client.get("/api/best-diff-history")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert any(r["best_diff_str"] == "4.5T" and r["device_id"] == "cypher65" and r["pool"] == "parasite" and "timestamp" in r for r in data["records"])

    def test_device_best_diff_history(self, client):
        _persist_best_diff_history(int(time.time()) + 1, 5.0e12, "5.0T", "worker-01", "parasite")

        response = client.get("/api/devices/worker-01/best-diff-history")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["device_id"] == "worker-01"
        assert any(r["best_diff_str"] == "5.0T" for r in data["records"])

    def test_device_best_diff_history_empty(self, client):
        response = client.get("/api/devices/non-existent/best-diff-history")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["records"] == []
