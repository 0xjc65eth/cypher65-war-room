"""Tests for Fase 6 dashboard_bp migration (routes/dashboard_routes.py).

Locks the API contract of the routes migrated OUT of app.py INTO the
dashboard blueprint:

  /snapshot, /history, /diff_events, /leaderboard, /share_timeline,
  /event_stats, /halving, /mempool_fees, /profitability, /network_share,
  /milestones, /workers, /monte_carlo, /proximity

plus the contract guarantees the migration promised (mesmas respostas):
  - /api/history payload key is "rows" (NOT "history") — preserved from the
    pre-migration app.py route so existing clients keep working.
  - /api/alerts is served by alerts_bp (routes/alerts_routes.py) and the
    old app.py copy is gone (no shadowed dead duplicate).
  - pro_required gates are preserved on /monte_carlo and /proximity.
"""

import time

import pytest

from app import app, latest_snapshot
from services.snapshot_enrichment import enrich_snapshot


class TestMigratedDashboardRoutes:
    @pytest.fixture
    def client(self):
        app.config["TESTING"] = True
        yield app.test_client()

    @pytest.fixture
    def seeded_snapshot(self, monkeypatch):
        """Deterministic snapshot so snapshot-derived routes have data."""
        snap = dict(latest_snapshot)
        snap.update({
            "milestones": [{"title": "First block", "ts": 1}],
            "all_workers": [{"name": "miner-01", "hashrate": 1e12}],
            "network_share_gauge": {"share_pct": 1.5, "rank": 42},
            "network": {"difficulty": 8e13, "hashrate": 6e20, "height": 840000},
            "worker": {"hashrate": 1e12, "bestDifficulty": "10G"},
            "leaderboard_entry": {"rank": 7, "diffRank": 6},
            "leaderboard_table_top_30": [
                {"address": "bc1qabc", "rank": 1},
                {"address": snap.get("btc_address") or "bc1qtest", "rank": 2},
            ],
            "proximity": {"distance": 0.42, "all_time_best_diff_raw": 1e13},
            "halving": {"next_height": 840000, "eta_blocks": 1000},
            "mempool_fees": {"fastest_fee": 12, "hour_fee": 8},
            "profitability": {"net_usd_per_day": 1.23},
            "event_stats": {"total_events": 5},
        })
        monkeypatch.setattr("app.latest_snapshot", snap, raising=False)
        import services.state as state
        monkeypatch.setattr(state, "latest_snapshot", snap, raising=False)
        return snap

    # ── /api/history contract ────────────────────────────────────────────

    def test_history_returns_rows_key(self, client, monkeypatch):
        """Fase 6 parity: /api/history payload uses 'rows' (not 'history')."""
        monkeypatch.setattr(
            "app.latest_snapshot",
            {"worker_hashrate": 1e12},
            raising=False,
        )
        r = client.get("/api/history?metric=worker_hashrate&range=24h")
        assert r.status_code == 200
        data = r.get_json()
        assert "rows" in data
        assert "history" not in data
        assert data["metric"] == "worker_hashrate"
        assert data["range"] == "24h"
        assert isinstance(data["rows"], list)
        assert set(data) == {"metric", "range", "rows"}

    def test_history_invalid_metric_400(self, client):
        r = client.get("/api/history?metric=not_a_real_metric")
        assert r.status_code == 400

    def test_history_limit_offset_has_more(self, client, monkeypatch, tmp_path):
        import sqlite3

        import routes.dashboard_routes as dr

        db_path = tmp_path / "history.sqlite"
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE snapshots (ts INTEGER, worker_hashrate REAL)")
        now = int(time.time())
        db.executemany(
            "INSERT INTO snapshots (ts, worker_hashrate) VALUES (?, ?)",
            [(now - 3, 10.0), (now - 2, 20.0), (now - 1, 30.0)],
        )
        db.commit()
        db.close()

        def open_db():
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            return conn

        monkeypatch.setattr(dr, "get_db", open_db)

        first = client.get(
            "/api/history?metric=worker_hashrate&range=24h&limit=2&offset=0"
        )
        assert first.status_code == 200
        data = first.get_json()
        assert data["rows"] == [
            {"ts": now - 3, "value": 10.0},
            {"ts": now - 2, "value": 20.0},
        ]
        assert data["total"] == 3
        assert data["has_more"] is True

        second = client.get(
            "/api/history?metric=worker_hashrate&range=24h&limit=2&offset=2"
        )
        assert second.get_json()["rows"] == [
            {"ts": now - 1, "value": 30.0}
        ]
        assert second.get_json()["has_more"] is False

    def test_leaderboard_paginates(self, client, seeded_snapshot, monkeypatch):
        import services.state as state

        rows = [{"address": f"bc1q{i}", "rank": i} for i in range(3)]
        monkeypatch.setattr(state, "leaderboard_rows", rows, raising=False)
        monkeypatch.setattr(
            state,
            "latest_snapshot",
            {"btc_address": "bc1q1", "leaderboard_total": 3},
            raising=False,
        )
        first = client.get("/api/leaderboard?limit=2&offset=0")
        assert first.status_code == 200
        body = first.get_json()
        assert body["count"] == 2
        assert body["has_more"] is True
        assert body["entries"][1]["is_me"] is True
        second = client.get("/api/leaderboard?limit=2&offset=2")
        assert second.get_json()["count"] == 1
        assert second.get_json()["has_more"] is False

    def test_leaderboard_default_preserves_top_30(self, client, monkeypatch):
        import services.state as state

        rows = [{"address": f"bc1q{i}", "rank": i} for i in range(60)]
        monkeypatch.setattr(state, "leaderboard_rows", rows, raising=False)
        monkeypatch.setattr(
            state, "latest_snapshot", {"leaderboard_total": 60}, raising=False
        )
        body = client.get("/api/leaderboard").get_json()
        assert body["limit"] == 30
        assert body["count"] == 30
        assert body["has_more"] is True

    # ── Simple snapshot-derived routes ───────────────────────────────────

    def test_milestones(self, client, seeded_snapshot):
        r = client.get("/api/milestones")
        assert r.status_code == 200
        assert r.get_json()["milestones"][0]["title"] == "First block"

    def test_workers(self, client, seeded_snapshot):
        r = client.get("/api/workers")
        assert r.status_code == 200
        assert r.get_json()["workers"][0]["name"] == "miner-01"

    def test_network_share(self, client, seeded_snapshot):
        r = client.get("/api/network_share")
        assert r.status_code == 200
        assert r.get_json()["share_pct"] == 1.5

    def test_healthz_persistence_flags(self, client, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "github-secret-value")
        monkeypatch.setenv("REMOTE_BACKUP_ENCRYPTION_KEY", "backup-secret-value")
        monkeypatch.setenv("SENTRY_DSN", "https://sentry-secret.example/1")
        # Issue #586: o terceiro flag é o modo da blacklist persistente. Ele é
        # reportado pelo MESMO predicado que `services.auth` usa — a sonda
        # responde "o que o auth está fazendo agora", não "o que está no env".
        monkeypatch.setenv("REVOKED_TOKENS_DB", "1")
        r = client.get("/api/healthz")
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert data["persistence"] == {
            "remote_backup": True,
            "sentry": True,
            "revoked_tokens_db": True,
        }
        assert data["rate_limit_scope"] == "process"
        assert "github-secret-value" not in r.get_data(as_text=True)
        assert "backup-secret-value" not in r.get_data(as_text=True)
        assert "sentry-secret" not in r.get_data(as_text=True)

    def test_halving(self, client, seeded_snapshot):
        r = client.get("/api/halving")
        assert r.status_code == 200
        assert r.get_json()["eta_blocks"] == 1000

    def test_mempool_fees(self, client, seeded_snapshot):
        r = client.get("/api/mempool_fees")
        assert r.status_code == 200
        assert r.get_json()["fastest_fee"] == 12

    def test_profitability(self, client, seeded_snapshot):
        r = client.get("/api/profitability")
        assert r.status_code == 200
        assert r.get_json()["net_usd_per_day"] == 1.23

    def test_event_stats(self, client, seeded_snapshot):
        r = client.get("/api/event_stats")
        assert r.status_code == 200
        assert r.get_json()["total_events"] == 5
        assert r.get_json()["server_now"] > 0

    def test_share_timeline_corrupt_meta_becomes_null(self, client, monkeypatch, caplog):
        """Sev-3 #205: a corrupt meta JSON cell must surface as null (never the
        raw string) and log a warning — the event still renders, nothing is
        lost silently."""
        import logging
        import sqlite3

        import routes.dashboard_routes as dr

        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute(
            "CREATE TABLE share_timeline (id INTEGER PRIMARY KEY, ts INTEGER,"
            " event_type TEXT, severity TEXT, message TEXT, meta TEXT)"
        )
        db.execute(
            "INSERT INTO share_timeline (id, ts, event_type, severity, message, meta)"
            " VALUES (1, 1784505600, 'SHARE_FOUND', 'INFO', 'ok', '{\"n\":1}'),"
            " (2, 1784505600, 'SHARE_FOUND', 'INFO', 'broken', '{not-json')"
        )
        db.commit()
        monkeypatch.setattr(dr, "get_db", lambda: db)

        with caplog.at_level(logging.WARNING, logger="cypher65.dashboard"):
            r = client.get("/api/share_timeline")

        assert r.status_code == 200
        events = {e["id"]: e for e in r.get_json()["events"]}
        assert events[1]["meta"] == {"n": 1}
        assert events[2]["meta"] is None
        assert any("meta JSON corrupt" in rec.message for rec in caplog.records)
        db.close()

    def test_leaderboard(self, client, seeded_snapshot):
        r = client.get("/api/leaderboard")
        assert r.status_code == 200
        data = r.get_json()
        assert data["entries"]
        assert any("is_me" in e for e in data["entries"])
        assert data["stale_after_s"] > 0

    # ── pro_required gates preserved ─────────────────────────────────────

    def test_monte_carlo_open_mode(self, client):
        """Open mode: never 402 (may be 'insufficient data')."""
        r = client.get("/api/monte_carlo?hours=1&runs=100")
        assert r.status_code == 200

    def test_proximity_open_mode(self, client, seeded_snapshot):
        r = client.get("/api/proximity")
        assert r.status_code == 200

    # ── /api/alerts served by alerts_bp (no shadowed dead duplicate) ─────

    def test_alerts_route_still_served(self, client):
        r = client.get("/api/alerts")
        assert r.status_code == 200
        assert "alerts" in r.get_json()

    # ── /api/snapshot enrichment still wired ─────────────────────────────

    def test_snapshot_still_enriched(self, client, seeded_snapshot, monkeypatch):
        monkeypatch.setattr(
            "services.snapshot_enrichment._get_hashrate_market_offers",
            lambda s: [],
            raising=False,
        )
        r = client.get("/api/snapshot")
        assert r.status_code == 200
        data = r.get_json()
        # Enrichment blocks present (market, auto-pilot, block-hunt, command center)
        assert "market_highlights" in data
        assert "market_data" in data
        assert "block_hunt" in data
        assert "auto_pilot" in data
        assert "command_center" in data

    def test_enrich_snapshot_does_not_mutate_input(self):
        """enrich_snapshot must return a NEW dict (migration guarantee)."""
        snap = {"ts": 1, "worker": {"hashrate": 1e12}}
        out = enrich_snapshot(dict(snap))
        assert out is not snap
        assert snap == {"ts": 1, "worker": {"hashrate": 1e12}}

    def test_institutional_btc_usd_wired_from_btc_price(self, monkeypatch):
        """Real-user audit: institutional view must read btc_usd from the
        top-level btc_price block (network.btc_usd never existed), so the
        Market tab BTC/USD + Rent-vs-Own cells stop showing "—" forever."""
        from services.hashrate_market import NormalizedOffer

        def _offers():
            return [
                NormalizedOffer(provider="braiins", hashrate=1000,
                                price_per_th_day=3e-7, duration_days=1.0,
                                fee_pct=0.0, algorithm="sha256",
                                source="braiins", estimated=False),
                NormalizedOffer(provider="mrr", hashrate=100000,
                                price_per_th_day=4e-7, duration_days=1.0,
                                fee_pct=0.0, algorithm="sha256",
                                source="mrr", estimated=False),
            ]

        monkeypatch.setattr("services.snapshot_enrichment._fetch_all_offers",
                            lambda network_hashrate=None: _offers(), raising=False)

        # btc_price.usd is the canonical source → institutional.snapshot.btc_usd
        snap = {"ts": 1, "network": {"hashrate": 6e20},
                "btc_price": {"usd": 60000.0, "brl": 320000.0}}
        out = enrich_snapshot(dict(snap))
        inst = out.get("institutional") or {}
        assert inst.get("snapshot", {}).get("btc_usd") == 60000.0
        assert inst.get("snapshot", {}).get("rent_vs_own") is not None

        # Legacy fallback: network.btc_usd still honoured when btc_price absent.
        snap2 = {"ts": 1, "network": {"hashrate": 6e20, "btc_usd": 55000.0}}
        out2 = enrich_snapshot(dict(snap2))
        assert (out2.get("institutional") or {}).get("snapshot", {}).get("btc_usd") == 55000.0

        # Neither present → None (renderer shows "—", never crashes).
        snap3 = {"ts": 1, "network": {"hashrate": 6e20}}
        out3 = enrich_snapshot(dict(snap3))
        assert (out3.get("institutional") or {}).get("snapshot", {}).get("btc_usd") is None
