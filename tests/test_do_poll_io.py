"""
CYPHER65 // app._do_poll — I/O blocks (fetch / persist / purge) in-process
=========================================================================
Cobre o corpo do `_do_poll` (app.py 3555-4539) — o caminho self-hosted do
poll que o test_polling_integration não exercita (ele testa
`services.polling.poll_once`, o caminho SaaS). Estratégia: injeção de mock
nos fetchers upstream (`fetch_json`/`fetch_text`) + DB real descartável
(conftest redireciona DB_PATH antes do import) + engines já inicializados
no import do app.

Cobre (Issue #141 — degrau de cobertura 78 -> 80):
  - fetch fan-out happy path (user/pool/account/leaderboard/highest/network/
    btc/mempool + blockchain.info text)
  - persist snapshot + high-diff events + share timeline
  - timeline delta detection (SHARE_FOUND / BEST_DIFF_BUMP)
  - alert dedup (offline / hashrate drop / stale submission / new high diff)
  - BTC throttle (cache reuso) + stale-while-revalidate
  - network stale-while-revalidate
  - persist failure ladder (CRIT memory alert)
  - purge_old() (snapshots/alerts/timeline/proximity antigos)
  - rotas do dashboard (GET /, /api/healthz) via test_client
"""

import json
import time

import pytest


@pytest.fixture
def poll_env(monkeypatch):
    """app module with reset poll state + mocked upstream fetchers."""
    import app as appmod
    import services.state as state

    monkeypatch.setattr(appmod, "BTC_ADDRESS", "bc1qtestwallet123")
    monkeypatch.setattr(appmod, "WORKER_NAME", "miner1")

    # Reset every mutable poll global (module state leaks across tests).
    appmod.latest_snapshot = {
        "ts": 0,
        "worker": {
            "name": "miner1",
            "hashrate": 219e12,
            "bestDifficulty": "127G",
            "lastSubmission": int(time.time()) - 10,
            "uptime": 3600,
        },
        "pool": {"hashrate": 161.6e15, "workers": 1200, "highestDifficulty": "128.1T"},
        "network": {"height": None, "difficulty": None, "hashrate": None},
        "all_workers": [],
        "btc_price": {"usd": None, "brl": None},
    }
    state.latest_snapshot = appmod.latest_snapshot

    ts = state.timeline_state
    ts.clear()
    ts.update(
        {
            "_primed": False,
            "last_submit_ts": 0,
            "last_best_diff_str": "",
            "share_submit_history": [],
            "share_calc_history": [],
            "session_share_count": 0,
            "session_best_diff_bumps": 0,
            "all_time_best_diff_raw": 0.0,
        }
    )
    appmod.persist_consec_failures = 0
    appmod.memory_critical_alerts = []
    appmod.btc_price_cache = {"ts": 0, "data": None}
    appmod._btc_consec_failures = 0
    appmod._btc_last_fetch_ts = 0
    appmod._last_valid_network = {"difficulty": None, "hashrate": None}
    appmod._last_proximity_sample_ts = 0
    appmod._do_poll._alert_seen = set()
    appmod._do_poll._worker_was_present = False

    # The scratch DB is session-scoped (shared across ALL test files), so
    # every test in this module must start from clean tables — otherwise
    # row-count asserts and UNIQUE(ts) collide with rows left by other tests.
    conn = appmod.get_db()
    for _t in (
        "snapshots",
        "alerts",
        "highest_diff_events",
        "share_timeline",
        "best_diff_history",
        "proximity_history",
    ):
        try:
            conn.execute(f"DELETE FROM {_t}")
        except Exception:
            pass
    conn.commit()
    conn.close()

    yield appmod

    # Teardown: re-aplica o baseline dos globals alterados por atribuição
    # direta (não rastreados por monkeypatch) para não vazar estado para
    # outros arquivos de teste no mesmo processo.
    appmod.latest_snapshot = {"ts": 0}
    state.latest_snapshot = appmod.latest_snapshot
    appmod.persist_consec_failures = 0
    appmod.memory_critical_alerts = []
    appmod.btc_price_cache = {"ts": 0, "data": None}
    appmod._btc_consec_failures = 0
    appmod._btc_last_fetch_ts = 0
    appmod._last_valid_network = {"difficulty": None, "hashrate": None}
    appmod._last_proximity_sample_ts = 0
    appmod._do_poll._alert_seen = set()
    appmod._do_poll._worker_was_present = False


# ── Payload factories (shapes realistas dos endpoints upstream) ────────────


def _base_payloads(worker=None, worker_hr=None):
    """Full realistic upstream payload set for a happy-path poll."""
    now = int(time.time())
    w = worker or {
        "name": "miner1",
        "id": "miner1",
        "hashrate": worker_hr if worker_hr is not None else 219e12,
        "bestDifficulty": "127G",
        "lastSubmission": now - 10,
        "uptime": 3600,
    }
    # Keys are URL substrings matched by install_fetch (longest match wins).
    return {
        "user": {"workerData": [w]},
        "pool": {
            "hashrate": 161.6e15,
            "workers": 1200,
            "users": 5,
            "highestDifficulty": "128.1T",
            "lastBlockTime": 857000,
            "workSinceLastBlock": 1e15,
            "lastBlockHash": "abc123",
        },
        "account": {
            "account": {
                "total_diff": "1.2P",
                "metadata": {"block_count": 2, "highest_blockheight": 857000},
            },
            "lightning": {"balance": 1000},
        },
        "leaderboard": [
            {
                "address": "bc1qtestwallet123",
                "diff_rank": 3,
                "loyalty_rank": 1,
                "combined_score": 95.5,
            }
        ],
        "highest": [
            {
                "block_height": 857001,
                "top_diff_address": "bc1qother",
                "difficulty": "1.2T",
                "claimed": 1,
                "block_timestamp": 857000,
            }
        ],
        # mempool.space endpoints
        "blocks/tip/height": 857000,
        "fees/recommended": {"fastestFee": 12, "halfHourFee": 8, "hourFee": 5},
        # coin gecko + binance price endpoints
        "coingecko": {
            "bitcoin": {
                "usd": 61234.5,
                "brl": 350000.0,
                "eur": 56000.0,
                "gbp": 48000.0,
                "jpy": 9000000.0,
                "krw": 80000000.0,
                "cny": 440000.0,
            }
        },
        "BTCUSDT": {"symbol": "BTCUSDT", "price": "61234.5"},
        "BTCBRL": {"symbol": "BTCBRL", "price": "350000"},
    }


def install_fetch(appmod, monkeypatch, payloads, fail_urls=(), fail_text=()):
    """Monkeypatch fetch_json/fetch_text dispatching by URL substring."""
    calls = {"json": [], "text": []}

    def _fake_json(url, timeout=10):
        calls["json"].append(url)
        for frag in fail_urls:
            if frag in url:
                raise RuntimeError(f"mock failure {frag}")
        # Longest-match wins: URLs share fragments (e.g. `user` appears inside
        # `...highest-diff?type=user-diffs...`), so first-match would route the
        # wrong payload.
        matches = [(frag, p) for frag, p in payloads.items() if frag in url]
        if matches:
            matches.sort(key=lambda kv: len(kv[0]), reverse=True)
            return matches[0][1]
        raise RuntimeError(f"no mock for {url}")

    def _fake_text(url, timeout=8):
        calls["text"].append(url)
        for frag in fail_text:
            if frag in url:
                raise RuntimeError(f"mock failure {frag}")
        if "getdifficulty" in url:
            return "126231507121868"
        if "hashrate" in url:
            return "600000000000000000000"
        raise RuntimeError(f"no mock for text {url}")

    monkeypatch.setattr(appmod, "fetch_json", _fake_json)
    monkeypatch.setattr(appmod, "fetch_text", _fake_text)
    return calls


def _snapshot_row_count(appmod):
    conn = appmod.get_db()
    n = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    conn.close()
    return n


# ═══════════════════════════════════════════════════════════════════════
#  Fetch + persist happy path
# ═══════════════════════════════════════════════════════════════════════


class TestDoPollHappyPath:
    def test_first_poll_persists_snapshot(self, poll_env, monkeypatch):
        appmod = poll_env
        install_fetch(appmod, monkeypatch, _base_payloads())
        appmod._do_poll()
        snap = appmod.latest_snapshot
        assert snap["ts"] > 0
        assert snap["worker"]["name"] == "miner1"
        assert snap["worker"]["hashrate"] == 219e12
        assert snap["pool"]["highestDifficulty"] == "128.1T"
        assert snap["network"]["height"] == 857000
        assert snap["network"]["stale"] is False
        assert snap["btc_price"]["usd"] == 61234.5
        assert snap["btc_price"]["stale"] is False
        assert snap["halving"]["next_height"]  # compute_halving_countdown
        assert _snapshot_row_count(appmod) == 1

    def test_second_poll_share_delta_emits_timeline_event(self, poll_env, monkeypatch):
        appmod = poll_env
        now = int(time.time())
        payloads = _base_payloads()
        install_fetch(appmod, monkeypatch, payloads)
        appmod._do_poll()  # prime
        # share lands: lastSubmission moves forward
        payloads["user"]["workerData"][0]["lastSubmission"] = now
        appmod._do_poll()
        snaps = appmod.latest_snapshot
        kinds = [e[1] for e in snaps["timeline_last_n"]]
        assert "SHARE_FOUND" in kinds
        # persisted into share_timeline
        conn = appmod.get_db()
        n = conn.execute(
            "SELECT COUNT(*) FROM share_timeline WHERE event_type='SHARE_FOUND'"
        ).fetchone()[0]
        conn.close()
        assert n >= 1

    def test_best_diff_bump_persists_history(self, poll_env, monkeypatch):
        appmod = poll_env
        payloads = _base_payloads()
        install_fetch(appmod, monkeypatch, payloads)
        appmod._do_poll()
        payloads["user"]["workerData"][0]["bestDifficulty"] = "128G"
        appmod._do_poll()
        kinds = [e[1] for e in appmod.latest_snapshot["timeline_last_n"]]
        assert "BEST_DIFF_BUMP" in kinds
        conn = appmod.get_db()
        n = conn.execute("SELECT COUNT(*) FROM best_diff_history").fetchone()[0]
        conn.close()
        assert n >= 1

    def test_high_diff_event_persisted(self, poll_env, monkeypatch):
        appmod = poll_env
        install_fetch(appmod, monkeypatch, _base_payloads())
        appmod._do_poll()
        conn = appmod.get_db()
        n = conn.execute(
            "SELECT COUNT(*) FROM highest_diff_events WHERE block_height=857001"
        ).fetchone()[0]
        conn.close()
        assert n == 1

    def test_leaderboard_and_ranks_in_snapshot(self, poll_env, monkeypatch):
        appmod = poll_env
        install_fetch(appmod, monkeypatch, _base_payloads())
        appmod._do_poll()
        snap = appmod.latest_snapshot
        assert snap["leaderboard_entry"]["diff_rank"] == 3
        assert snap["leaderboard_total"] == 1
        assert snap["account_meta"]["block_count"] == 2

    def test_proximity_sampled(self, poll_env, monkeypatch):
        appmod = poll_env
        install_fetch(appmod, monkeypatch, _base_payloads())
        appmod._do_poll()
        conn = appmod.get_db()
        n = conn.execute("SELECT COUNT(*) FROM proximity_history").fetchone()[0]
        conn.close()
        assert n >= 1


# ═══════════════════════════════════════════════════════════════════════
#  Alert paths
# ═══════════════════════════════════════════════════════════════════════


class TestDoPollAlerts:
    def test_worker_offline_alert(self, poll_env, monkeypatch):
        appmod = poll_env
        payloads = _base_payloads(worker=None)
        payloads["user"] = {"workerData": []}
        install_fetch(appmod, monkeypatch, payloads)
        appmod._do_poll._worker_was_present = True  # foi online no poll passado
        appmod._do_poll()
        conn = appmod.get_db()
        row = conn.execute(
            "SELECT * FROM alerts WHERE category='worker_offline'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["severity"] == "CRIT"

    def test_hashrate_drop_alert(self, poll_env, monkeypatch):
        appmod = poll_env
        payloads = _base_payloads(worker_hr=5e12)  # caiu de 219e12 p/ 5e12
        install_fetch(appmod, monkeypatch, payloads)
        appmod._do_poll()
        conn = appmod.get_db()
        row = conn.execute(
            "SELECT * FROM alerts WHERE category='hashrate_drop'"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_stale_submission_alert(self, poll_env, monkeypatch):
        appmod = poll_env
        w = {
            "name": "miner1",
            "id": "miner1",
            "hashrate": 219e12,
            "bestDifficulty": "127G",
            "lastSubmission": int(time.time()) - 3600,  # 60 min atrás
            "uptime": 3600,
        }
        install_fetch(appmod, monkeypatch, _base_payloads(worker=w))
        appmod._do_poll()
        conn = appmod.get_db()
        row = conn.execute(
            "SELECT * FROM alerts WHERE category='stale_submission'"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_new_high_diff_alert(self, poll_env, monkeypatch):
        appmod = poll_env
        install_fetch(appmod, monkeypatch, _base_payloads())
        appmod._do_poll()
        # pool sobe o highestDifficulty → GOLD new_high_diff
        payloads = _base_payloads()
        payloads["pool"]["highestDifficulty"] = "130T"
        install_fetch(appmod, monkeypatch, payloads)
        appmod._do_poll()
        conn = appmod.get_db()
        row = conn.execute(
            "SELECT * FROM alerts WHERE category='new_high_diff'"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_alert_dedup_same_sig_not_refired(self, poll_env, monkeypatch):
        appmod = poll_env
        install_fetch(appmod, monkeypatch, _base_payloads())
        appmod._do_poll()
        payloads = _base_payloads()
        payloads["pool"]["highestDifficulty"] = "130T"
        install_fetch(appmod, monkeypatch, payloads)
        appmod._do_poll()
        # mesma sig de novo → sem nova linha
        install_fetch(appmod, monkeypatch, payloads)
        appmod._do_poll()
        conn = appmod.get_db()
        n = conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE category='new_high_diff'"
        ).fetchone()[0]
        conn.close()
        assert n == 1


# ═══════════════════════════════════════════════════════════════════════
#  Throttle / stale / failure paths
# ═══════════════════════════════════════════════════════════════════════


class TestDoPollFallbacks:
    def test_btc_throttle_reuses_cache(self, poll_env, monkeypatch):
        appmod = poll_env
        calls = install_fetch(appmod, monkeypatch, _base_payloads())
        appmod._do_poll()  # 1º poll: btc fetched
        assert any("coingecko" in u for u in calls["json"])
        # throttle: marca como recém-fetched → 2º poll NÃO fetcha coingecko
        appmod._btc_last_fetch_ts = int(time.time())
        calls["json"] = []
        appmod._do_poll()
        assert not any("coingecko" in u for u in calls["json"])
        assert appmod.latest_snapshot["btc_price"]["usd"] == 61234.5

    def test_btc_stale_serves_last_real_price(self, poll_env, monkeypatch):
        appmod = poll_env
        install_fetch(appmod, monkeypatch, _base_payloads())
        appmod._do_poll()
        # cache populado no 1º poll; 2º poll com coingecko falhando
        appmod._btc_last_fetch_ts = 0
        payloads = _base_payloads()
        install_fetch(appmod, monkeypatch, payloads, fail_urls=("coingecko",))
        appmod._do_poll()
        snap = appmod.latest_snapshot
        assert snap["btc_price"]["stale"] is True
        assert snap["btc_price"]["usd"] == 61234.5  # último valor REAL

    def test_network_stale_serves_last_valid(self, poll_env, monkeypatch):
        appmod = poll_env
        install_fetch(appmod, monkeypatch, _base_payloads())
        appmod._do_poll()
        # 2º poll: blockchain.info falha → serve último valor conhecido (stale)
        appmod._last_valid_network["difficulty"] = 126231507121868.0
        appmod._last_valid_network["hashrate"] = 6e20
        payloads = _base_payloads()
        install_fetch(
            appmod, monkeypatch, payloads, fail_text=("getdifficulty", "hashrate")
        )
        appmod._do_poll()
        snap = appmod.latest_snapshot
        assert snap["network"]["stale"] is True
        assert snap["network"]["difficulty"] == 126231507121868.0

    def test_persist_failure_escalates_crit(self, poll_env, monkeypatch):
        appmod = poll_env
        install_fetch(appmod, monkeypatch, _base_payloads())

        def _boom():
            raise RuntimeError("disk full (mock)")

        monkeypatch.setattr(appmod, "get_db", _boom)
        appmod.persist_consec_failures = 1  # próximo falha = 2 → na ladder
        appmod._do_poll()
        assert appmod.persist_consec_failures == 2
        cats = [a.get("category") for a in appmod.memory_critical_alerts]
        assert "disk_write_failure" in cats

    def test_persist_recovery_clears_failure(self, poll_env, monkeypatch):
        appmod = poll_env
        install_fetch(appmod, monkeypatch, _base_payloads())

        real_get_db = appmod.get_db

        def _boom():
            raise RuntimeError("disk full (mock)")

        monkeypatch.setattr(appmod, "get_db", _boom)
        appmod.persist_consec_failures = 1
        appmod._do_poll()
        assert appmod.persist_consec_failures == 2
        # Recupera restaurando SÓ get_db (nunca monkeypatch.undo(), que
        # desfaria também os fetchers mockados e bateria na rede real).
        monkeypatch.setattr(appmod, "get_db", real_get_db)
        appmod._do_poll()
        assert appmod.persist_consec_failures == 0
        cats = [a.get("category") for a in appmod.memory_critical_alerts]
        assert "disk_write_recovered" in cats


# ═══════════════════════════════════════════════════════════════════════
#  Purge
# ═══════════════════════════════════════════════════════════════════════


class TestPurgeOld:
    def test_purge_old_deletes_only_old_rows(self, poll_env):
        appmod = poll_env
        old = int(time.time()) - 40 * 86400
        recent = int(time.time())
        conn = appmod.get_db()
        conn.execute(
            "INSERT INTO snapshots (ts, worker_hashrate) VALUES (?, ?)",
            (old, 1.0),
        )
        conn.execute(
            "INSERT INTO snapshots (ts, worker_hashrate) VALUES (?, ?)",
            (recent, 2.0),
        )
        conn.commit()
        conn.close()
        appmod.purge_old()
        conn = appmod.get_db()
        rows = conn.execute("SELECT ts FROM snapshots ORDER BY ts").fetchall()
        conn.close()
        assert [r["ts"] for r in rows] == [recent]


# ═══════════════════════════════════════════════════════════════════════
#  Dashboard routes (public, no auth)
# ═══════════════════════════════════════════════════════════════════════


class TestDashboardRoutes:
    def test_index_renders_dashboard(self, poll_env):
        client = poll_env.app.test_client()
        r = client.get("/")
        assert r.status_code == 200
        assert b"app-shell" in r.data

    def test_healthz_served(self, poll_env):
        client = poll_env.app.test_client()
        r = client.get("/api/healthz")
        assert r.status_code in (200, 204)

    def test_session_status_public(self, poll_env):
        client = poll_env.app.test_client()
        r = client.get("/api/session-status")
        assert r.status_code in (200, 302)


# ═══════════════════════════════════════════════════════════════════════
#  Sentinel policy (Issue #203)
# ═══════════════════════════════════════════════════════════════════════


class TestDoPollSentinelPolicy:
    """Missing lastSubmission must stay a None sentinel — never 0/epoch."""

    def test_worker_without_last_submission_primes_none(self, poll_env, monkeypatch):
        import services.state as state

        appmod = poll_env
        w = {
            "name": "miner1",
            "id": "miner1",
            "hashrate": 219e12,
            "bestDifficulty": "127G",
            # NO lastSubmission key — absent data must stay absent (Issue #203)
            "uptime": 3600,
        }
        install_fetch(appmod, monkeypatch, _base_payloads(worker=w))
        appmod._do_poll()
        assert state.timeline_state["last_submit_ts"] is None

    def test_worker_with_last_submission_primes_real_ts(self, poll_env, monkeypatch):
        import services.state as state

        appmod = poll_env
        install_fetch(appmod, monkeypatch, _base_payloads())
        appmod._do_poll()
        ts = state.timeline_state["last_submit_ts"]
        assert ts is not None
        assert ts > 0
