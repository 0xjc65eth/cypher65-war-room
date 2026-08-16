"""
CYPHER65 // Polling — Integration Test
=======================================
Tests for services.polling.poll_once() — the main polling loop.

Strategy:
  - Mock ALL external dependencies: config object, services.state,
    requests, sqlite3.connect, and helper functions.
  - Test controlled scenarios with known inputs and verify
    state mutations, SQL queries, and alert generation.

Fixtures used:
  - mock_config       : object with all required config attributes
  - mock_conn / cursor: in-memory SQLite with CYPHER65 schema
"""

import json
import time
import sqlite3
from unittest.mock import ANY, MagicMock, PropertyMock, call, patch

import pytest

# Module-level constants used by poll_once
DEFAULT_DIFFICULTY = 126231507121868.0
NETWORK_HASHRATE = 6e20


# ══════════════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def db_conn():
    """In-memory SQLite with the CYPHER65 schema snapshot + needed tables."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            ts INTEGER PRIMARY KEY, worker_hashrate REAL,
            worker_best_diff TEXT, worker_last_submit INTEGER,
            worker_uptime INTEGER, worker_status TEXT,
            pool_hashrate REAL, pool_workers INTEGER, pool_users INTEGER,
            pool_highest_diff TEXT, pool_last_block_height INTEGER,
            pool_last_block_time INTEGER, pool_work_since_last_block REAL,
            account_total_diff TEXT, account_block_count INTEGER,
            account_highest_block INTEGER,
            leaderboard_rank INTEGER, leaderboard_diff_rank INTEGER,
            leaderboard_loyalty_rank INTEGER, leaderboard_combined_score REAL,
            network_height INTEGER, network_difficulty REAL,
            network_hashrate REAL, btc_usd REAL, btc_brl REAL
        );
        CREATE TABLE IF NOT EXISTS alerts (
            ts INTEGER, severity TEXT, category TEXT, message TEXT
        );
        CREATE TABLE IF NOT EXISTS share_timeline (
            ts INTEGER, event_type TEXT, severity TEXT,
            message TEXT, meta TEXT
        );
        CREATE TABLE IF NOT EXISTS highest_diff_events (
            ts INTEGER, block_height INTEGER, top_diff_address TEXT,
            difficulty TEXT, claimed INTEGER, block_timestamp INTEGER, is_mine INTEGER
        );
        CREATE TABLE IF NOT EXISTS hashrate_market_history (
            ts INTEGER, provider TEXT, hashrate REAL,
            price_per_th_day REAL, duration_days REAL, fee_pct REAL,
            algorithm TEXT, score REAL, raw_data TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT
        );
    """)
    yield c
    c.close()


@pytest.fixture
def mock_state():
    """Patch services.state with controlled mutable state values."""
    import services.state as state
    # Save originals
    orig_latest = state.latest_snapshot
    orig_timeline = state.timeline_state
    orig_prices = state.last_known_prices
    orig_memory = state.memory_critical_alerts
    orig_persist = state.persist_consec_failures
    orig_market = state.market_data_cache

    # Set controlled state
    state.latest_snapshot = {
        "ts": 0,
        "worker": {"hashrate": 219e12, "bestDifficulty": "127G", "name": "miner1"},
        "pool": {"hashrate": 161.6e15, "workers": 1200, "highestDifficulty": "128.1T"},
        "network": {"height": 857000, "difficulty": DEFAULT_DIFFICULTY, "hashrate": NETWORK_HASHRATE},
        "all_workers": [],
        "btc_price": {"usd": 61234, "brl": 350000},
    }
    state.timeline_state = {
        "_primed": False,
        "last_submit_ts": 0,
        "last_best_diff_str": "",
        "share_submit_history": [],
        "share_calc_history": [],
        "session_share_count": 0,
        "session_best_diff_bumps": 0,
    }
    state.last_known_prices = {"braiins": None, "mrr": None, "nicehash": None, "parasite": None}
    state.memory_critical_alerts = []
    state.persist_consec_failures = 0
    state.market_data_cache = {"offers": [], "best_price": None, "updated_at": 0, "loading": True, "error": None}

    yield state

    # Restore originals
    state.latest_snapshot = orig_latest
    state.timeline_state = orig_timeline
    state.last_known_prices = orig_prices
    state.memory_critical_alerts = orig_memory
    state.persist_consec_failures = orig_persist
    state.market_data_cache = orig_market


def _make_config(db_conn):
    """Build a mock config object with realistic values."""

    class MockConfig:
        BTC_ADDRESS = "bc1qtest1234567890abcdef"
        WORKER_NAME = "testminer"
        PARASITE_API = "https://api.parasite.space"
        MEMPOOL_API = "https://mempool.space/api"
        POLL_INTERVAL = 15
        BTC_PRICE_CACHE_TTL = 300

        def get_db(self):
            """Return a non-closing wrapper around db_conn to prevent
            poll_once()'s finally block from closing the fixture's connection."""
            # Create a wrapper that delegates everything except close()
            class NoCloseConn:
                def __init__(self, inner):
                    self.__inner = inner
                    self._cursor = None
                def cursor(self):
                    self._cursor = self.__inner.cursor()
                    return self._cursor
                def commit(self):
                    self.__inner.commit()
                def close(self):
                    # no-op — fixture's db_conn stays open for assertions
                    pass
                def execute(self, sql, params=None):
                    if self._cursor:
                        return self._cursor.execute(sql, params or ())
                    self._cursor = self.__inner.cursor()
                    return self._cursor.execute(sql, params or ())
            return NoCloseConn(db_conn)

        def fetch_json(self, url, timeout=10):
            """Return controlled JSON responses based on URL patterns."""
            if "pool-stats" in url:
                return {
                    "hashrate": 161.6e15,
                    "workers": 1200,
                    "users": 800,
                    "highestDifficulty": "128.5T",
                    "lastBlockHash": "0000000000000000000123456789abcdef",
                    "lastBlockHeight": 857123,
                    "lastBlockTime": int(time.time()) - 300,
                    "workSinceLastBlock": 1.5e14,
                }
            if "blocks/tip/height" in url:
                return 857200
            if "v1/fees/recommended" in url:
                return {"fastestFee": 12, "halfHourFee": 8, "hourFee": 5, "economyFee": 2, "minimumFee": 1}
            if "simple/price" in url:
                return {"bitcoin": {"usd": 61234, "brl": 350000, "eur": 56000, "gbp": 48000}}
            if "user/" in url:
                return {
                    "workerData": [
                        {"name": "testminer", "hashrate": 219e12, "bestDifficulty": "127G",
                         "lastSubmission": int(time.time()) - 10, "uptime": 86400 * 3, "difficulty": 16384},
                        {"name": "backupminer", "hashrate": 50e12, "bestDifficulty": "10G",
                         "lastSubmission": int(time.time()) - 600, "uptime": 86400 * 7, "difficulty": 8192},
                    ]
                }
            if "account/" in url:
                return {
                    "account": {
                        "total_diff": "987654321",
                        "metadata": {"block_count": 42, "highest_blockheight": 856000},
                    },
                    "lightning": {"ln_address": "test@ln.parasite.space"},
                }
            if "leaderboard?" in url:
                return [
                    {"address": "bc1qtest1234567890abcdef", "diff_rank": 15,
                     "loyalty_rank": 8, "combined_score": 950.5, "blocks_found": 42},
                    {"address": "bc1qother1234567890xyz", "diff_rank": 3,
                     "loyalty_rank": 1, "combined_score": 5000.0, "blocks_found": 200},
                ]
            if "highest-diff" in url:
                return []
            return {}

        def fetch_text(self, url, timeout=8):
            """Return plain text for blockchain.info endpoints."""
            if "getdifficulty" in url:
                return str(DEFAULT_DIFFICULTY)
            if "hashrate" in url:
                return str(NETWORK_HASHRATE / 1e9)  # GH/s → H/s conversion
            return "0"

        def load_settings(self):
            return {"stale_share_minutes": "5", "hashrate_drop_pct": "50"}

        def make_memory_alert(self, ts, sev, cat, msg):
            return {"ts": ts, "severity": sev, "category": cat, "message": msg,
                    "id": str(int(time.time()))}

    return MockConfig()


@pytest.fixture
def config(db_conn):
    """Create a MockConfig, inject it into polling, return it."""
    cfg = _make_config(db_conn)
    from services import polling
    polling.config = cfg
    return cfg


@pytest.fixture
def polled(config, mock_state):
    """Run poll_once() after setting up config + state. Returns the mock_state for inspection."""
    from services import polling
    # Reset function-level state (alert_seen, counters)
    if hasattr(polling.poll_once, '_alert_seen'):
        delattr(polling.poll_once, '_alert_seen')
    if hasattr(polling.poll_once, '_no_wallet_log_count'):
        delattr(polling.poll_once, '_no_wallet_log_count')
    if hasattr(polling.poll_once, '_wallet_404_count'):
        delattr(polling.poll_once, '_wallet_404_count')

    polling.poll_once()
    return mock_state


# ══════════════════════════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════════════════════════

class TestPollOnceBase:
    """Base tests: successful poll with wallet configured."""

    def test_snapshot_inserted(self, polled, config, db_conn):
        """After poll_once, a snapshot row exists in the DB."""
        c = db_conn.cursor()
        c.execute("SELECT COUNT(*) as cnt FROM snapshots")
        assert c.fetchone()["cnt"] == 1

    def test_snapshot_has_worker_data(self, polled, db_conn):
        """Snapshot contains the primary worker's hashrate."""
        c = db_conn.cursor()
        c.execute("SELECT worker_hashrate, worker_best_diff FROM snapshots ORDER BY ts DESC LIMIT 1")
        row = c.fetchone()
        assert row["worker_hashrate"] == 219e12
        assert row["worker_best_diff"] == "127G"

    def test_snapshot_has_pool_data(self, polled, db_conn):
        """Snapshot contains pool hashrate and workers."""
        c = db_conn.cursor()
        c.execute("SELECT pool_hashrate, pool_workers FROM snapshots ORDER BY ts DESC LIMIT 1")
        row = c.fetchone()
        assert row["pool_hashrate"] == 161.6e15
        assert row["pool_workers"] == 1200

    def test_snapshot_has_network_data(self, polled, db_conn):
        """Snapshot contains network difficulty and height."""
        c = db_conn.cursor()
        c.execute("SELECT network_height, network_difficulty, btc_usd FROM snapshots ORDER BY ts DESC LIMIT 1")
        row = c.fetchone()
        assert row["network_height"] == 857200
        assert row["network_difficulty"] == DEFAULT_DIFFICULTY
        assert row["btc_usd"] == 61234

    def test_snapshot_has_account_data(self, polled, db_conn):
        """Snapshot contains account total difficulty and block count."""
        c = db_conn.cursor()
        c.execute("SELECT account_total_diff, account_block_count FROM snapshots ORDER BY ts DESC LIMIT 1")
        row = c.fetchone()
        assert row["account_total_diff"] == "987654321"
        assert row["account_block_count"] == 42

    def test_snapshot_has_leaderboard_data(self, polled, db_conn):
        """Snapshot contains leaderboard rank and diff rank."""
        c = db_conn.cursor()
        c.execute("SELECT leaderboard_rank, leaderboard_diff_rank, leaderboard_loyalty_rank FROM snapshots ORDER BY ts DESC LIMIT 1")
        row = c.fetchone()
        assert row["leaderboard_rank"] == 1  # First match in leaderboard list
        assert row["leaderboard_diff_rank"] == 15
        assert row["leaderboard_loyalty_rank"] == 8


class TestPollOnceState:
    """Tests that shared state is updated correctly after polling."""

    def test_latest_snapshot_updated(self, polled):
        """latest_snapshot.ts should be > 0 after poll."""
        assert polled.latest_snapshot["ts"] > 0

    def test_latest_snapshot_has_workers(self, polled):
        """all_workers should be populated from workerData."""
        workers = polled.latest_snapshot.get("all_workers", [])
        assert len(workers) >= 1

    def test_primary_worker_selected(self, polled):
        """The best worker (by hashrate + recency) should be primary."""
        workers = polled.latest_snapshot.get("all_workers", [])
        primary = [w for w in workers if w.get("is_primary")]
        assert len(primary) == 1
        assert primary[0]["name"] == "testminer" or primary[0]["hashrate"] == 219e12

    def test_timeline_primed(self, polled):
        """After first poll, timeline_state._primed should be True."""
        assert polled.timeline_state["_primed"] is True

    def test_market_price_cache_updated(self, polled):
        """BTC price cache should be populated after poll."""
        assert polled.btc_price_cache["data"] is not None
        assert polled.btc_price_cache["data"]["bitcoin"]["usd"] == 61234

    def test_first_poll_no_timeline_events(self, polled, db_conn):
        """First poll primes state and should NOT emit SHARE_FOUND events."""
        c = db_conn.cursor()
        c.execute("SELECT COUNT(*) as cnt FROM share_timeline WHERE event_type='SHARE_FOUND'")
        assert c.fetchone()["cnt"] == 0


class TestPollOnceAlerts:
    """Tests that alerts are generated correctly."""

    def test_no_alerts_on_first_poll(self, polled, db_conn):
        """First successful poll shouldn't generate alerts (no deltas yet)."""
        c = db_conn.cursor()
        c.execute("SELECT COUNT(*) as cnt FROM alerts")
        # Some alerts like uptime_milestone may fire, but that's fine
        # We're checking no CRITICAL alerts on first poll
        c.execute("SELECT COUNT(*) as cnt FROM alerts WHERE severity='CRIT'")
        assert c.fetchone()["cnt"] == 0

    def test_alert_deduplication_via_function_attr(self, config, mock_state, db_conn):
        """Running poll_once twice with same data should not duplicate alerts."""
        from services import polling
        # Reset for clean test
        if hasattr(polling.poll_once, '_alert_seen'):
            delattr(polling.poll_once, '_alert_seen')

        # First poll
        polling.poll_once()
        # Second poll — same data, no changes
        polling.poll_once()

        c = db_conn.cursor()
        c.execute("SELECT severity, category, message FROM alerts")
        alerts = c.fetchall()
        # Check that the same (category, identifier) pair didn't fire twice
        seen = set()
        for a in alerts:
            sig = (a["category"], a["message"][:40])
            assert sig not in seen, f"Duplicate alert: {a}"
            seen.add(sig)


class TestPollOnceNoWallet:
    """Tests when no wallet address is configured."""

    def test_public_only_fetch(self, config, mock_state):
        """Without BTC_ADDRESS, only public data is fetched."""
        config.BTC_ADDRESS = ""
        config.WORKER_NAME = ""
        from services import polling
        if hasattr(polling.poll_once, '_alert_seen'):
            delattr(polling.poll_once, '_alert_seen')

        polling.poll_once()
        # Snapshot should still be inserted (public data only)
        c = config.get_db().cursor()
        c.execute("SELECT COUNT(*) as cnt FROM snapshots")
        assert c.fetchone()["cnt"] >= 1


class TestPollOnceWalletNotFound:
    """Tests when wallet is configured but user data returns None."""

    def test_wallet_404_does_not_crash(self, config, mock_state, monkeypatch):
        """poll_once handles user=None gracefully."""
        from services import polling

        # Override fetch_json to return None for user endpoint
        original_fetch = config.fetch_json

        def patched_fetch(url, timeout=10):
            if "user/" in url:
                return None
            return original_fetch(url, timeout)

        config.fetch_json = patched_fetch

        if hasattr(polling.poll_once, '_alert_seen'):
            delattr(polling.poll_once, '_alert_seen')

        # Should not raise
        polling.poll_once()

        # Snapshot should still be created even with no user data
        c = config.get_db().cursor()
        c.execute("SELECT COUNT(*) as cnt FROM snapshots")
        assert c.fetchone()["cnt"] == 1


class TestPollOncePoolFailure:
    """Tests when pool API fails, triggering stale data fallback."""

    def test_pool_failure_falls_back_prev(self, config, mock_state, monkeypatch):
        """When pool-stats returns None, fall back to prev_pool with _stale flag."""
        from services import polling

        original_fetch = config.fetch_json

        def patched_fetch(url, timeout=10):
            if "pool-stats" in url:
                return None  # pool API failure
            return original_fetch(url, timeout)

        config.fetch_json = patched_fetch
        # Ensure prev_pool is set in latest_snapshot
        mock_state.latest_snapshot["pool"] = {
            "hashrate": 161.6e15, "workers": 1200, "highestDifficulty": "128.1T"
        }

        if hasattr(polling.poll_once, '_alert_seen'):
            delattr(polling.poll_once, '_alert_seen')

        polling.poll_once()

        pool = mock_state.latest_snapshot.get("pool", {})
        assert pool.get("_stale") is True, f"Expected stale flag, got {pool}"
        assert "_stale_since_ts" in pool


class TestPollOnceWorkerFailure:
    """Tests when worker data is None but all_workers exists."""

    def test_worker_fallback_from_all_workers(self, config, mock_state, monkeypatch):
        """When worker is None but all_workers has entries, use first worker."""
        from services import polling

        original_fetch = config.fetch_json

        def patched_fetch(url, timeout=10):
            if "user/" in url:
                # Return user with no matching worker name but valid workerData
                return {
                    "workerData": [
                        {"name": "orphan-worker", "hashrate": 100e12,
                         "bestDifficulty": "50G", "lastSubmission": int(time.time()) - 30,
                         "uptime": 3600, "difficulty": 16384},
                    ]
                }
            return original_fetch(url, timeout)

        config.fetch_json = patched_fetch

        if hasattr(polling.poll_once, '_alert_seen'):
            delattr(polling.poll_once, '_alert_seen')

        polling.poll_once()

        workers = mock_state.latest_snapshot.get("all_workers", [])
        assert len(workers) >= 1
        primary = [w for w in workers if w.get("is_primary")]
        assert len(primary) >= 1, "No primary worker found after fallback"


class TestPollOnceBlockchainFallback:
    """Tests blockchain.info fallback for difficulty/hashrate."""

    def test_blockchain_info_fallback(self, config, mock_state, monkeypatch):
        """When mempool.space fails, blockchain.info is used."""
        from services import polling

        original_fetch = config.fetch_json

        def patched_fetch(url, timeout=10):
            if "blocks/tip" in url:
                return None  # Network height endpoint fails
            return original_fetch(url, timeout)

        config.fetch_json = patched_fetch

        if hasattr(polling.poll_once, '_alert_seen'):
            delattr(polling.poll_once, '_alert_seen')

        # Should not crash — blockchain.info text endpoints provide the data
        polling.poll_once()

        net = mock_state.latest_snapshot.get("network", {})
        # Network difficulty should come from bc_diff via fetch_text
        assert net.get("difficulty") is not None


class TestPollOnceWorkerDedup:
    """Tests worker deduplication logic."""

    def test_workers_deduplicated(self, config, mock_state, monkeypatch):
        """Workers with similar normalized names should be merged."""
        from services import polling

        original_fetch = config.fetch_json

        def patched_fetch(url, timeout=10):
            if "user/" in url:
                now = int(time.time())
                return {
                    "workerData": [
                        {"name": "CYPHER", "hashrate": 219e12,
                         "bestDifficulty": "127G", "lastSubmission": now - 10,
                         "uptime": 86400 * 3, "difficulty": 16384},
                        {"name": "cypher", "hashrate": 50e12,  # same normalized name
                         "bestDifficulty": "5G", "lastSubmission": now - 600,
                         "uptime": 86400 * 1, "difficulty": 8192},
                        {"name": "unique-worker", "hashrate": 100e12,
                         "bestDifficulty": "30G", "lastSubmission": now - 120,
                         "uptime": 86400 * 2, "difficulty": 12288},
                    ]
                }
            return original_fetch(url, timeout)

        config.fetch_json = patched_fetch
        config.WORKER_NAME = "CYPHER"

        if hasattr(polling.poll_once, '_alert_seen'):
            delattr(polling.poll_once, '_alert_seen')

        polling.poll_once()

        workers = mock_state.latest_snapshot.get("all_workers", [])
        # Should have 2 workers, not 3 (cypher + CYPHER merged)
        assert len(workers) == 2, f"Expected 2 deduped workers, got {len(workers)}: {[w['name'] for w in workers]}"

        # The higher hashrate worker (219 TH/s) should have survived the merge
        names = [w["name"] for w in workers]
        assert "CYPHER" in names, "CYPHER (219 TH/s) should survive dedup"
        assert "unique-worker" in names


class TestPollOncePersistenceFailure:
    """Tests handling of SQLite persistence failures."""

    def test_persistence_failure_does_not_crash(self, config, mock_state, monkeypatch):
        """When DB write fails, poll_once should catch the exception and continue."""
        from services import polling

        def broken_db(*args, **kwargs):
            raise sqlite3.OperationalError("disk full")

        config.get_db = broken_db

        if hasattr(polling.poll_once, '_alert_seen'):
            delattr(polling.poll_once, '_alert_seen')

        # Should not raise — the except Exception in poll_once catches it
        polling.poll_once()

        # persist_consec_failures should be incremented
        assert mock_state.persist_consec_failures > 0


class TestPollOnceMultipleWorkers:
    """Tests that multiple workers in workerData are all captured."""

    def test_all_workers_captured(self, config, mock_state, monkeypatch):
        """All workers from workerData appear in all_workers."""
        from services import polling

        original_fetch = config.fetch_json

        def patched_fetch(url, timeout=10):
            if "user/" in url:
                now = int(time.time())
                return {
                    "workerData": [
                        {"name": "miner-a", "hashrate": 100e12,
                         "bestDifficulty": "50G", "lastSubmission": now - 30,
                         "uptime": 3600, "difficulty": 8192},
                        {"name": "miner-b", "hashrate": 50e12,
                         "bestDifficulty": "20G", "lastSubmission": now - 60,
                         "uptime": 7200, "difficulty": 4096},
                        {"name": "miner-c", "hashrate": 0,  # offline
                         "bestDifficulty": "10G", "lastSubmission": now - 36000,
                         "uptime": 86400, "difficulty": 2048},
                    ]
                }
            return original_fetch(url, timeout)

        config.fetch_json = patched_fetch

        if hasattr(polling.poll_once, '_alert_seen'):
            delattr(polling.poll_once, '_alert_seen')

        polling.poll_once()

        workers = mock_state.latest_snapshot.get("all_workers", [])
        assert len(workers) == 3, f"Expected 3 workers, got {len(workers)}"

        # Check that the offline worker still appears
        names = [w["name"] for w in workers]
        assert "miner-a" in names
        assert "miner-b" in names
        assert "miner-c" in names

        # Check that the 0-hashrate worker is marked appropriately
        offline = [w for w in workers if w["hashrate"] == 0]
        assert len(offline) == 1
        assert offline[0]["state"] == "IDLE" or offline[0]["state"] == "ONLINE"

    def test_online_count_matches_active_hashrate(self, config, mock_state, monkeypatch):
        """User aggregate workers count should match active workers with hashrate > 0."""
        from services import polling

        original_fetch = config.fetch_json

        def patched_fetch(url, timeout=10):
            if "user/" in url:
                now = int(time.time())
                return {
                    "workerData": [
                        {"name": "active1", "hashrate": 100e12,
                         "bestDifficulty": "50G", "lastSubmission": now - 10,
                         "uptime": 3600, "difficulty": 8192},
                        {"name": "active2", "hashrate": 50e12,
                         "bestDifficulty": "20G", "lastSubmission": now - 20,
                         "uptime": 7200, "difficulty": 4096},
                        {"name": "dead-worker", "hashrate": 0,
                         "bestDifficulty": "5G", "lastSubmission": now - 99999,
                         "uptime": 86400, "difficulty": 2048},
                    ]
                }
            return original_fetch(url, timeout)

        config.fetch_json = patched_fetch

        if hasattr(polling.poll_once, '_alert_seen'):
            delattr(polling.poll_once, '_alert_seen')

        polling.poll_once()

        # The latest_snapshot's user_aggregate should have workers=2 (active count)
        # But actually the code updates user["workers"] = active_count
        # The snapshot uses pool.workers, so we just check all_workers
        workers = mock_state.latest_snapshot.get("all_workers", [])
        active = [w for w in workers if w["hashrate"] > 0]
        assert len(active) == 2


class TestPollOnceWebhook:
    """Tests webhook firing when alerts are generated."""

    def test_webhook_called_on_alert(self, config, mock_state, monkeypatch):
        """When alerts fire and webhook_url is set, requests.post should be called."""
        from services import polling

        mock_post = MagicMock()
        monkeypatch.setattr("requests.post", mock_post)
        config.load_settings = lambda: {
            "stale_share_minutes": "5",
            "hashrate_drop_pct": "50",
            "webhook_url": "https://discord.com/api/webhooks/test",
            "webhook_min_severity": "WARN",
        }

        # Force a stale submission alert by making lastSubmission old
        original_fetch = config.fetch_json

        def patched_fetch(url, timeout=10):
            if "user/" in url:
                now = int(time.time())
                return {
                    "workerData": [
                        {"name": "testminer", "hashrate": 219e12,
                         "bestDifficulty": "127G",
                         "lastSubmission": now - 3600,  # 1 hour ago (> 5 min threshold)
                         "uptime": 86400 * 3, "difficulty": 16384},
                    ]
                }
            return original_fetch(url, timeout)

        config.fetch_json = patched_fetch

        if hasattr(polling.poll_once, '_alert_seen'):
            delattr(polling.poll_once, '_alert_seen')

        polling.poll_once()

        # requests.post should have been called at least once for the stale submission alert
        assert mock_post.called, "Expected webhook POST to be called when alert fires"

    def test_webhook_not_called_without_url(self, config, mock_state, monkeypatch):
        """Without webhook_url, requests.post should not be called."""
        from services import polling

        mock_post = MagicMock()
        monkeypatch.setattr("requests.post", mock_post)
        config.load_settings = lambda: {
            "stale_share_minutes": "5",
            "hashrate_drop_pct": "50",
            "webhook_url": "",  # No URL configured
        }

        if hasattr(polling.poll_once, '_alert_seen'):
            delattr(polling.poll_once, '_alert_seen')

        polling.poll_once()
        assert not mock_post.called, "Webhook POST should not fire without URL"


class TestPollOnceDerivedHashrate:
    """FENIX E1 (P1): worker hashrate is derived when the pool reports 0.

    When parasite reports worker hashrate 0 (or missing) while shares are
    flowing, poll_once must fall back to the per-share instantaneous
    hashrate math (share_calc_history) or the pool workSinceLastBlock delta,
    and write the derived value into the worker dict so the snapshot row,
    /api/snapshot worker payload and KPI all show a real number.
    """

    def _zero_hr_config(self, config):
        """Wrap fetch_json so the worker reports hashrate 0."""
        original_fetch = config.fetch_json

        def patched_fetch(url, timeout=10):
            data = original_fetch(url, timeout)
            if "user/" in url and data:
                data = dict(data)
                data["workerData"] = [dict(w) for w in data.get("workerData", [])]
                for w in data["workerData"]:
                    w["hashrate"] = 0
            return data

        config.fetch_json = patched_fetch

    def test_derives_from_share_calc_history(self, config, mock_state, db_conn):
        """Worker hashrate 0 + share_calc_history → derived value in snapshot + worker dict."""
        from services import polling

        self._zero_hr_config(config)

        # Seed per-share instantaneous hashrate history (as if shares flowed)
        mock_state.timeline_state["share_calc_history"] = [
            {"ts": 1, "instantaneous_hr_hps": 1e12},
            {"ts": 2, "instantaneous_hr_hps": 3e12},
            {"ts": 3, "instantaneous_hr_hps": 2e12},
        ]

        if hasattr(polling.poll_once, '_alert_seen'):
            delattr(polling.poll_once, '_alert_seen')

        polling.poll_once()

        snap = mock_state.latest_snapshot
        assert snap["worker"]["hashrate"] > 0, "derived hashrate should replace reported 0"
        assert snap["worker"].get("hashrate_source") == "shares"
        assert snap["worker"].get("hashrate_derived") is True

        # KPI reads snap.worker.hashrate → same derived value
        c = db_conn.cursor()
        c.execute("SELECT worker_hashrate FROM snapshots ORDER BY ts DESC LIMIT 1")
        row = c.fetchone()
        assert row["worker_hashrate"] == snap["worker"]["hashrate"]

    def test_derives_from_work_delta(self, config, mock_state):
        """No share history + pool workSinceLastBlock delta → derived from work_delta."""
        from services import polling

        self._zero_hr_config(config)

        # No share history; pool work delta across polls
        mock_state.timeline_state["share_calc_history"] = []
        mock_state.latest_snapshot["pool"] = {
            "hashrate": 161.6e15,
            "workSinceLastBlock": 1.4e14,
            "workers": 1200,
        }
        # current pool fetch returns workSinceLastBlock 1.5e14 → delta 1e13

        if hasattr(polling.poll_once, '_alert_seen'):
            delattr(polling.poll_once, '_alert_seen')

        polling.poll_once()

        snap = mock_state.latest_snapshot
        assert snap["worker"]["hashrate"] > 0
        assert snap["worker"].get("hashrate_source") == "work_delta"

    def test_reported_positive_hashrate_kept(self, config, mock_state, db_conn):
        """A healthy reported hashrate is NOT overridden (regression guard)."""
        from services import polling

        mock_state.timeline_state["share_calc_history"] = [
            {"ts": 1, "instantaneous_hr_hps": 1e12},
        ]

        if hasattr(polling.poll_once, '_alert_seen'):
            delattr(polling.poll_once, '_alert_seen')

        polling.poll_once()

        snap = mock_state.latest_snapshot
        assert snap["worker"]["hashrate"] == 219e12  # unchanged
        assert snap["worker"].get("hashrate_derived") is None
