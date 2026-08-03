"""
CYPHER65 // P0-3 — Command Center contextual action cards
==========================================================
Unit tests for helpers.build_command_center() — the pure aggregation that
surfaces up to 3 contextual "what to do right now" cards from the snapshot
(offline worker, fleet attention, proximity streak, capital allocation,
negative operation, affiliate buy). Hermetic: no network, no DB, no app
import needed (same ethos as test_decision_matrix.py).
"""
import time

import pytest

from helpers import build_command_center, CC_MAX_ACTIONS


def _base_snapshot(**overrides):
    snap = {
        "ts": 1700000000,  # polling is demonstrably active
        "worker": {"name": "miner1", "hashrate": 5e12, "bestDifficulty": "12G"},
        "axe_fleet": [],
        "proximity": {"hot_streak": False, "milestone_cur_pct": 0.01},
        "profitability": {"decision_matrix": {"best_option": "pool"}},
        "market_data": {"affiliate": None},
    }
    snap.update(overrides)
    return snap


class TestNoActions:
    def test_healthy_snapshot_returns_empty(self):
        cards = build_command_center(_base_snapshot())
        assert cards == []

    def test_none_snapshot_never_raises(self):
        assert build_command_center(None) == []
        assert build_command_center({}) == []

    def test_garbage_snapshot_never_raises(self):
        assert build_command_center({"worker": 123, "axe_fleet": "junk", "proximity": None}) == []
        assert build_command_center("nope") == []


class TestWorkerOffline:
    def test_missing_worker_fires_crit(self):
        cards = build_command_center(_base_snapshot(worker=None))
        assert any(c["id"] == "worker_offline" and c["severity"] == "crit" for c in cards)

    def test_worker_offline_ranked_first(self):
        # Offline worker is CRIT — must come before any info card.
        snap = _base_snapshot(
            worker=None,
            proximity={"hot_streak": False, "milestone_cur_pct": 5.0},
        )
        cards = build_command_center(snap)
        assert cards[0]["id"] == "worker_offline"

    def test_empty_worker_dict_fires(self):
        cards = build_command_center(_base_snapshot(worker={}))
        assert any(c["id"] == "worker_offline" for c in cards)


class TestFleetAttention:
    def test_offline_device_fires_warn(self):
        snap = _base_snapshot(axe_fleet=[{"status": "OFFLINE"}, {"status": "ONLINE"}])
        cards = build_command_center(snap)
        fleet = [c for c in cards if c["id"] == "fleet_attention"]
        assert len(fleet) == 1
        assert fleet[0]["severity"] == "warn"
        assert fleet[0]["target"] == "fleet"

    def test_warning_device_fires(self):
        snap = _base_snapshot(axe_fleet=[{"status": "WARNING"}])
        cards = build_command_center(snap)
        assert any(c["id"] == "fleet_attention" for c in cards)

    def test_all_online_no_fleet_card(self):
        snap = _base_snapshot(axe_fleet=[{"status": "ONLINE"}, {"status": "ONLINE"}])
        cards = build_command_center(snap)
        assert all(c["id"] != "fleet_attention" for c in cards)

    def test_fleet_not_a_list_ignored(self):
        snap = _base_snapshot(axe_fleet={"status": "OFFLINE"})
        cards = build_command_center(snap)
        assert all(c["id"] != "fleet_attention" for c in cards)


class TestProximity:
    def test_hot_streak_fires_gold(self):
        snap = _base_snapshot(proximity={"hot_streak": True, "trend_1h_pct": 15.5})
        cards = build_command_center(snap)
        streak = [c for c in cards if c["id"] == "proximity_streak"]
        assert len(streak) == 1
        assert streak[0]["severity"] == "gold"
        assert streak[0]["target"] == "probability"

    def test_milestone_reached_fires_info(self):
        snap = _base_snapshot(proximity={"hot_streak": False, "milestone_cur_pct": 5.0})
        cards = build_command_center(snap)
        ms = [c for c in cards if c["id"] == "proximity_milestone"]
        assert len(ms) == 1
        assert ms[0]["severity"] == "info"

    def test_below_1pct_no_milestone_card(self):
        snap = _base_snapshot(proximity={"hot_streak": False, "milestone_cur_pct": 0.5})
        cards = build_command_center(snap)
        assert all(c["id"] != "proximity_milestone" for c in cards)

    def test_hot_streak_beats_milestone(self):
        snap = _base_snapshot(proximity={"hot_streak": True, "milestone_cur_pct": 5.0})
        cards = build_command_center(snap)
        ids = [c["id"] for c in cards]
        assert "proximity_streak" in ids
        assert "proximity_milestone" not in ids  # elif branch


class TestCapitalAllocation:
    def test_lease_best_fires_info(self):
        snap = _base_snapshot(
            profitability={"decision_matrix": {"best_option": "lease"}},
        )
        cards = build_command_center(snap)
        lease = [c for c in cards if c["id"] == "capital_lease"]
        assert len(lease) == 1
        assert lease[0]["target"] == "market"
        assert lease[0]["panel"] == "decision-matrix-panel"

    def test_pool_best_no_lease_card(self):
        snap = _base_snapshot(
            profitability={"decision_matrix": {"best_option": "pool"}},
        )
        cards = build_command_center(snap)
        assert all(c["id"] != "capital_lease" for c in cards)

    def test_negative_pool_net_fires_warn(self):
        snap = _base_snapshot(
            profitability={
                "decision_matrix": {"best_option": "pool"},
                "pool_net_usd_per_day": -4.2,
            },
        )
        cards = build_command_center(snap)
        neg = [c for c in cards if c["id"] == "negative_operation"]
        assert len(neg) == 1
        assert neg[0]["severity"] == "warn"


class TestAffiliate:
    def test_affiliate_url_fires_buy_card(self):
        snap = _base_snapshot(
            market_data={
                "affiliate": {"provider": "mrr", "url": "https://mrr.example/ref"},
            },
        )
        cards = build_command_center(snap)
        buy = [c for c in cards if c["id"] == "affiliate_buy"]
        assert len(buy) == 1
        assert buy[0]["url"] == "https://mrr.example/ref"
        assert buy[0]["target"] == "market"

    def test_affiliate_none_no_card(self):
        snap = _base_snapshot(market_data={"affiliate": None})
        cards = build_command_center(snap)
        assert all(c["id"] != "affiliate_buy" for c in cards)

    def test_affiliate_empty_no_card(self):
        snap = _base_snapshot(market_data={"affiliate": {}})
        cards = build_command_center(snap)
        assert all(c["id"] != "affiliate_buy" for c in cards)


class TestRankingAndCap:
    def test_max_three_cards(self):
        # Fire every rule at once → capped at CC_MAX_ACTIONS.
        snap = _base_snapshot(
            worker=None,
            axe_fleet=[{"status": "OFFLINE"}],
            proximity={"hot_streak": True, "milestone_cur_pct": 5.0},
            profitability={
                "decision_matrix": {"best_option": "lease"},
                "pool_net_usd_per_day": -1.0,
            },
            market_data={"affiliate": {"provider": "mrr", "url": "https://mrr.example/ref"}},
        )
        cards = build_command_center(snap)
        assert len(cards) <= CC_MAX_ACTIONS
        assert len(cards) <= 3

    def test_crit_ranked_first(self):
        snap = _base_snapshot(
            worker=None,
            axe_fleet=[{"status": "OFFLINE"}],
            proximity={"hot_streak": True, "milestone_cur_pct": 5.0},
        )
        cards = build_command_center(snap)
        assert cards[0]["severity"] == "crit"

    def test_gold_before_warn(self):
        snap = _base_snapshot(
            axe_fleet=[{"status": "OFFLINE"}],  # warn
            proximity={"hot_streak": True},      # gold
        )
        cards = build_command_center(snap)
        severities = [c["severity"] for c in cards]
        assert severities.index("gold") < severities.index("warn")

    def test_card_shape_contract(self):
        snap = _base_snapshot(worker=None)
        card = build_command_center(snap)[0]
        for key in ("id", "severity", "title", "message", "action", "target", "panel", "url"):
            assert key in card, f"missing card field: {key}"


class TestSnapshotInjection:
    """P0-3 integration — /api/snapshot must inject the command_center payload
    AFTER the affiliate link is attached, so the affiliate_buy rule sees the
    real market_data.affiliate (regression: computing from latest_snapshot
    before attach_affiliate produced a dead card in production)."""

    @pytest.fixture
    def client(self):
        import app as _app_module
        _app_module.app.config["TESTING"] = True
        yield _app_module.app.test_client()

    def test_snapshot_injects_command_center(self, client, monkeypatch):
        import app as _app_module
        import services.state as _state
        monkeypatch.setattr(
            "app.latest_snapshot",
            {
                "ts": int(time.time()),
                "network": {"hashrate": 6e20, "difficulty": 8e13, "height": 840000},
                "worker": {"hashrate": 1.5e14, "bestDifficulty": "45.2T", "name": "cypher65"},
                "proximity": {"hot_streak": False, "milestone_cur_pct": 0.5},
                "profitability": {"decision_matrix": {"best_option": "pool"}},
            },
            raising=False,
        )
        # No external HTTP: stub the fetch; feed the REAL build_highlights
        # path via last_known_prices so attach_affiliate runs for real
        # (the code path that resolves market_data.affiliate from offers).
        monkeypatch.setattr("app._get_hashrate_market_offers", lambda: [], raising=False)
        _state.last_known_prices = {
            "braiins": {"price": 0.0001, "ts": int(time.time()), "source": "braiins", "label": "Braiins"},
            "mrr": {"price": 0.0004, "ts": int(time.time()), "source": "mrr", "label": "MRR"},
        }
        monkeypatch.setattr("app.affiliate_map_from_env", lambda: {"mrr": "https://mrr.example/ref"})

        response = client.get("/api/snapshot")
        assert response.status_code == 200
        data = response.get_json()
        cc = data.get("command_center") or []
        # Healthy snapshot → no crit/warn; affiliate link present → buy card.
        assert isinstance(cc, list)
        assert len(cc) <= 3
        assert any(c["id"] == "affiliate_buy" for c in cc)
        # The affiliate_buy card must carry the REAL resolved URL.
        buy = next(c for c in cc if c["id"] == "affiliate_buy")
        assert buy["url"] == "https://mrr.example/ref"

    def test_snapshot_worker_offline_after_poll(self, client, monkeypatch):
        """A snapshot with ts>0 and no worker must produce the crit card
        (real offline condition, not a cold boot)."""
        import app as _app_module
        monkeypatch.setattr(
            "app.latest_snapshot",
            {
                "ts": int(time.time()),
                "worker": None,
                "network": {"hashrate": 6e20, "difficulty": 8e13, "height": 840000},
            },
            raising=False,
        )
        monkeypatch.setattr("app._get_hashrate_market_offers", lambda: [], raising=False)
        monkeypatch.setattr("app._build_market_highlights", lambda *a, **k: [], raising=False)

        response = client.get("/api/snapshot")
        assert response.status_code == 200
        cc = response.get_json().get("command_center") or []
        assert any(c["id"] == "worker_offline" and c["severity"] == "crit" for c in cc)

    def test_snapshot_cold_boot_no_worker_card(self, client, monkeypatch):
        """Cold boot (ts == 0, worker None) must NOT fire worker_offline —
        no wallet connected yet is not an anomaly (honest telemetry)."""
        import app as _app_module
        monkeypatch.setattr(
            "app.latest_snapshot",
            {
                "ts": 0,
                "worker": None,
                "btc_address": "",
                "network": {"hashrate": None, "difficulty": None, "height": None},
                "pool": None,
                "market_data": {"affiliate": None},
            },
            raising=False,
        )
        monkeypatch.setattr("app._get_hashrate_market_offers", lambda: [], raising=False)
        monkeypatch.setattr("app._build_market_highlights", lambda *a, **k: [], raising=False)

        response = client.get("/api/snapshot")
        assert response.status_code == 200
        cc = response.get_json().get("command_center") or []
        assert all(c["id"] != "worker_offline" for c in cc)
