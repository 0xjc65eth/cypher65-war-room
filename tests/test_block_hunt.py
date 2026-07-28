"""Tests for Milestone 6: Block Hunt + Best Difficulty history."""

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


class TestBestDiffHistory:
    @pytest.fixture
    def client(self):
        app.config["TESTING"] = True
        yield app.test_client()

    def test_global_best_diff_history(self, client):
        _persist_best_diff_history(1234567890, 4.5e12, "4.5T", "cypher65", "parasite")

        response = client.get("/api/best-diff-history")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert any(r["best_diff_str"] == "4.5T" and r["device_id"] == "cypher65" and r["pool"] == "parasite" and "timestamp" in r for r in data["records"])

    def test_device_best_diff_history(self, client):
        _persist_best_diff_history(1234567891, 5.0e12, "5.0T", "worker-01", "parasite")

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
