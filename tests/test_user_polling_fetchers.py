"""Hermetic tests for services.user_polling global fetchers (Issue #137).

Covers the shared-global fetch layer — _fetch_json/_fetch_text retry +
fallback, and the _fetch_global_* cached fetchers (pool / leaderboard /
highest-diffs / network / btc-price / mempool-fees). Every upstream call is
mocked; no test touches the network. This was the ~73% uncovered tail of
user_polling.py — the sweep paths are covered by tests/test_rentals_sweep.py.
"""
import sys
import threading

import pytest

sys.path.insert(0, ".")

import services.user_polling as up  # noqa: E402


# ── _fetch_json / _fetch_text (retry + fallback) ────────────────────────────

def test_fetch_json_success(monkeypatch):
    calls = []

    class _Resp:
        ok = True

        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    def _get(url, timeout=None, headers=None):
        calls.append(url)
        return _Resp()

    monkeypatch.setattr(up.requests, "get", _get)
    assert up._fetch_json("https://x/a") == {"ok": True}
    assert len(calls) == 1


def test_fetch_json_retries_then_none(monkeypatch):
    calls = []

    def _get(url, timeout=None, headers=None):
        calls.append(url)
        raise up.requests.exceptions.Timeout("boom")

    monkeypatch.setattr(up.requests, "get", _get)
    monkeypatch.setattr(up.time, "sleep", lambda s: None)
    assert up._fetch_json("https://x/b") is None
    # FETCH_MAX_RETRIES(2) + initial attempt = 3 calls
    assert len(calls) == up.FETCH_MAX_RETRIES + 1


def test_fetch_json_bad_status_retries(monkeypatch):
    calls = []

    class _Resp:
        def raise_for_status(self):
            raise up.requests.exceptions.HTTPError("500")

    def _get(url, timeout=None, headers=None):
        calls.append(url)
        return _Resp()

    monkeypatch.setattr(up.requests, "get", _get)
    monkeypatch.setattr(up.time, "sleep", lambda s: None)
    assert up._fetch_json("https://x/c") is None
    assert len(calls) == up.FETCH_MAX_RETRIES + 1


def test_fetch_text_success_and_strip(monkeypatch):
    class _Resp:
        ok = True
        text = "  1234567  \n"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(up.requests, "get", lambda *a, **k: _Resp())
    assert up._fetch_text("https://x/t") == "1234567"


def test_fetch_text_retries_then_none(monkeypatch):
    def _get(*a, **k):
        raise up.requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(up.requests, "get", _get)
    monkeypatch.setattr(up.time, "sleep", lambda s: None)
    assert up._fetch_text("https://x/u") is None


# ── _fetch_global_pool / leaderboard / highest-diffs (cache-first) ──────────

def test_fetch_global_pool_cache_hit(monkeypatch):
    monkeypatch.setattr(up, "_get_global", lambda key, ttl=up.GLOBAL_CACHE_TTL: {"hashrate": 1e15})
    monkeypatch.setattr(up, "_fetch_json", lambda *a, **k: pytest.fail("must not fetch on cache hit"))
    assert up._fetch_global_pool() == {"hashrate": 1e15}


def test_fetch_global_pool_fetch_and_cache(monkeypatch):
    fetched = []

    def _fetch_json(url, timeout=10):
        fetched.append(url)
        return {"hashrate": 2e15}

    def _get_global(key, ttl=up.GLOBAL_CACHE_TTL):
        return None

    monkeypatch.setattr(up, "_fetch_json", _fetch_json)
    monkeypatch.setattr(up, "_get_global", _get_global)
    monkeypatch.setattr(up, "_update_global", lambda key, val: fetched.append(("cached", key)))
    assert up._fetch_global_pool() == {"hashrate": 2e15}
    assert ("cached", "pool") in fetched


def test_fetch_global_pool_fetch_none_falls_back_empty(monkeypatch):
    monkeypatch.setattr(up, "_fetch_json", lambda *a, **k: None)
    monkeypatch.setattr(up, "_get_global", lambda key, ttl=up.GLOBAL_CACHE_TTL: None)
    monkeypatch.setattr(up, "_update_global", lambda key, val: None)
    assert up._fetch_global_pool() == {}


def test_fetch_global_leaderboard(monkeypatch):
    entries = [{"rank": 1}, {"rank": 2}]
    captured = {}

    def _fetch_json(url, timeout=10):
        captured["url"] = url
        return entries

    monkeypatch.setattr(up, "_fetch_json", _fetch_json)
    monkeypatch.setattr(up, "_get_global", lambda key, ttl=up.GLOBAL_CACHE_TTL: None)
    monkeypatch.setattr(up, "_update_global", lambda key, val: None)
    assert up._fetch_global_leaderboard(limit=50) == entries
    assert "limit=50" in captured["url"]


def test_fetch_global_highest_diffs_per_address_cache(monkeypatch):
    monkeypatch.setattr(up, "_get_global", lambda key, ttl=60: [{"difficulty": "1T"}])
    monkeypatch.setattr(up, "_fetch_json", lambda *a, **k: pytest.fail("cache hit — no fetch"))
    assert up._fetch_global_highest_diffs("bc1qabc") == [{"difficulty": "1T"}]


def test_fetch_global_highest_diffs_fetch(monkeypatch):
    data = [{"difficulty": "2T"}]
    monkeypatch.setattr(up, "_fetch_json", lambda *a, **k: data)
    monkeypatch.setattr(up, "_get_global", lambda key, ttl=60: None)
    monkeypatch.setattr(up, "_update_global", lambda key, val: None)
    assert up._fetch_global_highest_diffs("bc1qabc") == data


# ── _fetch_global_network (parallel + derivation fallback) ──────────────────

def test_fetch_global_network_full_cache(monkeypatch):
    def _get_global(key, ttl=up.GLOBAL_CACHE_TTL):
        return {"net_height": 857200, "net_diff": 1e14, "net_hr": 6e20}.get(key)

    monkeypatch.setattr(up, "_get_global", _get_global)
    h, d, hr = up._fetch_global_network()
    assert h == 857200 and d == 1e14 and hr == 6e20


def test_fetch_global_network_fetch_and_derive(monkeypatch):
    """Cold cache → parallel fetch. Height int, diff/HR text parsed via
    safe_num_from_str, hashrate scaled 1e9 (blockchain.info GH/s)."""
    monkeypatch.setattr(up, "_get_global", lambda key, ttl=up.GLOBAL_CACHE_TTL: None)

    class _Fut:
        def __init__(self, val):
            self._val = val

        def result(self):
            return self._val

    results_iter = iter([857201, "126231507121868", "700000", {"fastestFee": 12}])

    class _Ex:
        def __enter__(self_):
            return self_

        def __exit__(self_, *a):
            return False

        def submit(self_, fn, *args):
            return _Fut(next(results_iter))

    monkeypatch.setattr(up.concurrent.futures, "ThreadPoolExecutor",
                        lambda max_workers=4: _Ex())
    monkeypatch.setattr(up, "_update_global", lambda key, val: None)

    h, d, hr = up._fetch_global_network()
    assert h == 857201
    assert d == pytest.approx(126231507121868.0)
    assert hr == pytest.approx(700000.0 * 1e9)


def test_fetch_global_network_hashrate_derived_from_difficulty(monkeypatch):
    """When hashrate is missing but difficulty is present, derive
    hashrate = difficulty * 2^32 / 600 (the canonical Bitcoin formula)."""
    monkeypatch.setattr(up, "_get_global", lambda key, ttl=up.GLOBAL_CACHE_TTL: None)

    class _Fut:
        def __init__(self, val):
            self._val = val

        def result(self):
            return self._val

    results_iter = iter([857202, "126231507121868", None, {"fastestFee": 8}])

    class _Ex:
        def __enter__(self_):
            return self_

        def __exit__(self_, *a):
            return False

        def submit(self_, fn, *args):
            return _Fut(next(results_iter))

    monkeypatch.setattr(up.concurrent.futures, "ThreadPoolExecutor",
                        lambda max_workers=4: _Ex())
    monkeypatch.setattr(up, "_update_global", lambda key, val: None)

    h, d, hr = up._fetch_global_network()
    assert h == 857202
    assert d == pytest.approx(126231507121868.0)
    assert hr == pytest.approx(126231507121868.0 * (2 ** 32) / 600)


def test_fetch_global_network_mempool_fees_stored(monkeypatch):
    """Mempool fees ride along with the network fetch and are cached globally."""
    monkeypatch.setattr(up, "_get_global", lambda key, ttl=up.GLOBAL_CACHE_TTL: None)

    class _Fut:
        def __init__(self, val):
            self._val = val

        def result(self):
            return self._val

    results_iter = iter([857203, "1e14", "600000", {"fastestFee": 10, "hourFee": 4}])
    cached = {}

    class _Ex:
        def __enter__(self_):
            return self_

        def __exit__(self_, *a):
            return False

        def submit(self_, fn, *args):
            return _Fut(next(results_iter))

    monkeypatch.setattr(up.concurrent.futures, "ThreadPoolExecutor",
                        lambda max_workers=4: _Ex())
    monkeypatch.setattr(up, "_update_global",
                        lambda key, val: cached.__setitem__(key, val))

    up._fetch_global_network()
    assert cached.get("mempool_fees") == {"fastestFee": 10, "hourFee": 4}
    # network values cached too
    assert cached.get("net_height") == 857203


# ── _fetch_global_btc_price (TTL cache + stale fallback) ────────────────────

def test_btc_price_fresh_cache(monkeypatch):
    monkeypatch.setattr(up, "btc_price_cache",
                        {"ts": 100, "data": {"bitcoin": {"usd": 50000}}})
    monkeypatch.setattr(up, "time", type("T", (), {"time": staticmethod(lambda: 150)})())
    monkeypatch.setattr(up, "_fetch_json", lambda *a, **k: pytest.fail("no fetch on fresh cache"))
    assert up._fetch_global_btc_price() == {"bitcoin": {"usd": 50000}}


def test_btc_price_fetch_success(monkeypatch):
    now = 1_000_000
    monkeypatch.setattr(up, "time", type("T", (), {"time": staticmethod(lambda: now)})())
    monkeypatch.setattr(up, "btc_price_cache", {"ts": 0, "data": None})
    monkeypatch.setattr(up, "_fetch_json",
                        lambda *a, **k: {"bitcoin": {"usd": 61000, "brl": 350000}})
    out = up._fetch_global_btc_price()
    assert out["bitcoin"]["usd"] == 61000
    assert up.btc_price_cache["ts"] == now  # cache written


def test_btc_price_stale_fallback(monkeypatch):
    """Provider fails → falls back to the last real quote (never a fake)."""
    monkeypatch.setattr(up, "time", type("T", (), {"time": staticmethod(lambda: 2_000_000)})())
    monkeypatch.setattr(up, "btc_price_cache",
                        {"ts": 100, "data": {"bitcoin": {"usd": 59000}}})
    monkeypatch.setattr(up, "_fetch_json", lambda *a, **k: None)
    assert up._fetch_global_btc_price() == {"bitcoin": {"usd": 59000}}


def test_btc_price_empty_when_no_cache_and_fetch_fails(monkeypatch):
    monkeypatch.setattr(up, "time", type("T", (), {"time": staticmethod(lambda: 3_000_000)})())
    monkeypatch.setattr(up, "btc_price_cache", {"ts": 0, "data": None})
    monkeypatch.setattr(up, "_fetch_json", lambda *a, **k: None)
    assert up._fetch_global_btc_price() == {}


def test_btc_price_bad_quote_ignored_stale_kept(monkeypatch):
    """Fetch returns a malformed payload → not cached, stale quote returned."""
    monkeypatch.setattr(up, "time", type("T", (), {"time": staticmethod(lambda: 4_000_000)})())
    monkeypatch.setattr(up, "btc_price_cache",
                        {"ts": 500, "data": {"bitcoin": {"usd": 58000}}})
    monkeypatch.setattr(up, "_fetch_json", lambda *a, **k: {"bitcoin": None})
    assert up._fetch_global_btc_price() == {"bitcoin": {"usd": 58000}}


# ── _fetch_global_mempool_fees ──────────────────────────────────────────────

def test_mempool_fees_cache_hit(monkeypatch):
    monkeypatch.setattr(up, "_get_global", lambda key, ttl=up.GLOBAL_CACHE_TTL: {"fastestFee": 11})
    assert up._fetch_global_mempool_fees() == {"fastestFee": 11}


def test_mempool_fees_miss_returns_none_shape(monkeypatch):
    monkeypatch.setattr(up, "_get_global", lambda key, ttl=up.GLOBAL_CACHE_TTL: None)
    out = up._fetch_global_mempool_fees()
    assert out == {"fastestFee": None, "halfHourFee": None, "hourFee": None}


# ── _cached_user_fetch dedup (per-address short TTL) ────────────────────────

def test_cached_user_fetch_hit_no_upstream(monkeypatch):
    monkeypatch.setattr(up, "_get_global", lambda key, ttl=up.USER_FETCH_TTL: {"data": 1})
    fetched = []

    def _fetcher(*a):
        fetched.append(a)
        return {"data": 2}

    assert up._cached_user_fetch("user_bc1q", _fetcher, "arg") == {"data": 1}
    assert fetched == []  # dedup — upstream never called


def test_cached_user_fetch_miss_fetches_and_caches(monkeypatch):
    monkeypatch.setattr(up, "_get_global", lambda key, ttl=up.USER_FETCH_TTL: None)
    stored = {}

    def _fetcher(*a):
        return {"data": "fresh"}

    monkeypatch.setattr(up, "_update_global", lambda key, val: stored.__setitem__(key, val))
    assert up._cached_user_fetch("user_bc1q", _fetcher) == {"data": "fresh"}
    assert stored.get("user_bc1q") == {"data": "fresh"}


# ── _update_global LRU eviction guard ───────────────────────────────────────

def test_update_global_evicts_oldest_when_over_cap(monkeypatch):
    orig = dict(up._global_cache)
    up._global_cache.clear()
    up._global_cache["a"] = {"data": 1, "ts": 1}
    up._global_cache["b"] = {"data": 2, "ts": 2}
    monkeypatch.setattr(up, "_GLOBAL_CACHE_MAX", 2)
    up._update_global("c", 3)
    assert "a" not in up._global_cache  # oldest evicted
    assert up._global_cache["c"]["data"] == 3
    up._global_cache.clear()
    up._global_cache.update(orig)


def test_update_global_empty_cache_eviction_guard(monkeypatch):
    """The StopIteration branch of the eviction (cache empty + over cap) is
    defensive-only — never raises."""
    orig = dict(up._global_cache)
    up._global_cache.clear()
    monkeypatch.setattr(up, "_GLOBAL_CACHE_MAX", 0)
    up._update_global("only", 1)
    assert up._global_cache["only"]["data"] == 1
    up._global_cache.clear()
    up._global_cache.update(orig)


# ── Async dispatch exception guards ─────────────────────────────────────────

def test_notify_tenant_push_exception_swallowed(monkeypatch):
    """The internal notify call raising (push provider down) is swallowed by
    the function's own guard — never propagates."""
    def _boom(*a, **k):
        raise RuntimeError("push provider down")

    # The import is local inside the function — patch at the source module.
    monkeypatch.setattr("services.push_notifier.notify_tenant_alert", _boom)
    up._notify_tenant_push("t1", "CRIT", "cat", "msg")  # no raise


def test_dispatch_rental_pl_alerts_noop_when_empty(monkeypatch):
    monkeypatch.setattr(up, "_dispatch_tenant_alert_family",
                        lambda *a, **k: pytest.fail("must not dispatch on empty"))
    up.dispatch_rental_pl_alerts("t1", [])


def test_dispatch_rental_pl_alerts_exception_swallowed(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("dispatch failed")

    monkeypatch.setattr(up, "_dispatch_tenant_alert_family", _boom)
    up.dispatch_rental_pl_alerts("t1", [("WARN", "cat", "msg")])  # no raise


# ── _build_snapshot (worker build + dedup + halving) ────────────────────────

def test_build_snapshot_with_real_workers(monkeypatch):
    """The worker build loop (primary match by name, dedup, halving) is the
    ~46-line block that previously only ran live. All upstream fetchers are
    mocked; workerData is real so the loop executes."""
    from unittest.mock import patch

    user = {"workerData": [
        {"name": "MINER-A", "id": "1", "hashrate": 100e12,
         "bestDifficulty": "87T", "lastSubmission": 1000, "uptime": 90000},
        {"name": "miner-a", "id": "2", "hashrate": 200e12,  # dup — wins
         "bestDifficulty": "90T", "lastSubmission": 2000, "uptime": 100},
        {"name": "backup", "id": "3", "hashrate": 50e12,
         "bestDifficulty": "1T", "lastSubmission": 3000, "uptime": 0},
    ]}
    with patch("services.user_polling._fetch_user_data", return_value=user), \
         patch("services.user_polling._fetch_account", return_value=None), \
         patch("services.user_polling._fetch_global_pool",
               return_value={"hashrate": 1e15}), \
         patch("services.user_polling._fetch_global_leaderboard",
               return_value=[]), \
         patch("services.user_polling._fetch_global_highest_diffs",
               return_value=[]), \
         patch("services.user_polling._fetch_global_network",
               return_value=(857200, 1.26e14, 6e20)), \
         patch("services.user_polling._fetch_global_btc_price",
               return_value={"bitcoin": {"usd": 61234, "brl": 350000}}), \
         patch("services.user_polling._fetch_global_mempool_fees",
               return_value={"fastestFee": 12}):
        snap = up._build_snapshot("bc1qtest", "miner-a")

    # Primary matched by normalized name (case-insensitive) → idx 1 (the dup).
    assert snap["worker"]["name"] == "miner-a"
    assert snap["worker_index"] == 1
    # Dedup merged the two MINER-A entries → 2 workers left (primary + backup).
    assert len(snap["all_workers"]) == 2
    # Halving computed from the mocked height.
    assert snap["halving"]["current_height"] == 857200
    assert snap["network"]["hashrate"] == 6e20
    assert snap["btc_price"]["usd"] == 61234


def test_build_snapshot_no_worker_data(monkeypatch):
    """Empty workerData — worker stays None, snapshot still assembles."""
    from unittest.mock import patch

    with patch("services.user_polling._fetch_user_data",
               return_value={"workerData": []}), \
         patch("services.user_polling._fetch_account", return_value=None), \
         patch("services.user_polling._fetch_global_pool",
               return_value={"hashrate": 1e15}), \
         patch("services.user_polling._fetch_global_leaderboard",
               return_value=[]), \
         patch("services.user_polling._fetch_global_highest_diffs",
               return_value=[]), \
         patch("services.user_polling._fetch_global_network",
               return_value=(None, None, None)), \
         patch("services.user_polling._fetch_global_btc_price",
               return_value={}), \
         patch("services.user_polling._fetch_global_mempool_fees",
               return_value={}):
        snap = up._build_snapshot("bc1qempty", "nope")

    assert snap["worker"] is None
    assert snap["all_workers"] == []
    assert snap["halving"]["height"] is None  # base shape (no int height)


def test_build_snapshot_exception_survives(monkeypatch):
    """A fetch exception inside the build try is logged, never propagated."""
    from unittest.mock import patch

    def _boom(*a, **k):
        raise RuntimeError("fetch exploded")

    with patch("services.user_polling._fetch_user_data", _boom), \
         patch("services.user_polling._fetch_account", return_value=None), \
         patch("services.user_polling._fetch_global_pool", return_value={}), \
         patch("services.user_polling._fetch_global_leaderboard", return_value=[]), \
         patch("services.user_polling._fetch_global_highest_diffs", return_value=[]), \
         patch("services.user_polling._fetch_global_network",
               return_value=(None, None, None)), \
         patch("services.user_polling._fetch_global_btc_price", return_value={}), \
         patch("services.user_polling._fetch_global_mempool_fees", return_value={}):
        snap = up._build_snapshot("bc1qboom", "x")
    assert isinstance(snap, dict)  # base shape survived


def test_build_snapshot_empty_address_short_circuits(monkeypatch):
    """No address → returns the empty base snapshot without fetching."""
    from unittest.mock import patch

    with patch("services.user_polling._fetch_user_data",
               side_effect=AssertionError("must not fetch without address")):
        snap = up._build_snapshot("", "x")
    assert snap["btc_address"] == ""
    assert snap["worker"] is None
    assert snap["all_workers"] == []
    assert "ts" in snap


def test_build_snapshot_pool_stale_normalized(monkeypatch):
    """A non-dict/empty pool payload is normalized to {} + stale flag — the
    snapshot still assembles with pool=None."""
    from unittest.mock import patch

    with patch("services.user_polling._fetch_user_data",
               return_value={"workerData": []}), \
         patch("services.user_polling._fetch_account", return_value=None), \
         patch("services.user_polling._fetch_global_pool", return_value=None), \
         patch("services.user_polling._fetch_global_leaderboard", return_value=[]), \
         patch("services.user_polling._fetch_global_highest_diffs", return_value=[]), \
         patch("services.user_polling._fetch_global_network",
               return_value=(857200, 1.26e14, 6e20)), \
         patch("services.user_polling._fetch_global_btc_price", return_value={}), \
         patch("services.user_polling._fetch_global_mempool_fees", return_value={}):
        snap = up._build_snapshot("bc1qstale", "x")
    assert snap["pool"] is None  # stale pool normalized


def test_build_snapshot_leaderboard_substring_match(monkeypatch):
    """Leaderboard exact-address match fails → substring fallback matches
    on the last-8-chars (case-insensitive)."""
    from unittest.mock import patch

    with patch("services.user_polling._fetch_user_data",
               return_value={"workerData": []}), \
         patch("services.user_polling._fetch_account", return_value=None), \
         patch("services.user_polling._fetch_global_pool",
               return_value={"hashrate": 1e15}), \
         patch("services.user_polling._fetch_global_leaderboard",
               return_value=[{"address": "bc1qxxxxxABC12345", "rank": 3}]), \
         patch("services.user_polling._fetch_global_highest_diffs", return_value=[]), \
         patch("services.user_polling._fetch_global_network",
               return_value=(857200, 1.26e14, 6e20)), \
         patch("services.user_polling._fetch_global_btc_price", return_value={}), \
         patch("services.user_polling._fetch_global_mempool_fees", return_value={}):
        snap = up._build_snapshot("bc1qxxxxxabc12345", "x")  # suffix matches
    assert snap["leaderboard_entry"]["rank"] == 3


# ── evaluate_user_alerts GC guard ───────────────────────────────────────────

def test_evaluate_user_alerts_gc_trims_oversized_seen_set():
    """alert_seen > 1000 → trimmed in place to the last 500 (same policy as
    _do_poll), so a persistent condition's signature never leaks."""
    seen = {("cat", f"sig-{i}") for i in range(1005)}
    snap = {"ts": 1000, "worker": None}
    alerts = up.evaluate_user_alerts(snap, {}, {}, seen)
    assert alerts == []
    assert len(seen) == 500  # GC applied in place


# ── auto-exclude counter / dispatch guards ──────────────────────────────────

def test_bump_auto_exclude_counter_rejects_invalid_path():
    orig = dict(up._AUTO_EXCLUDE_ALERTS_BY_PATH)
    up._bump_auto_exclude_alert_counter("typo", 5)  # no-op (invalid path)
    assert up._AUTO_EXCLUDE_ALERTS_BY_PATH == orig
    up._bump_auto_exclude_alert_counter("panel", 0)  # n <= 0 → no-op
    assert up._AUTO_EXCLUDE_ALERTS_BY_PATH == orig


def test_dispatch_auto_exclude_alerts_empty_returns_zero():
    assert up.dispatch_auto_exclude_alerts("t1", []) == 0


def test_dispatch_rental_families_noop_when_empty():
    """market/arb/reco-worse families share the same no-op-on-empty guard."""
    up.dispatch_rental_market_alerts("t1", [])  # no raise, no dispatch
    up.dispatch_rental_arb_alerts("t1", [])
    up.dispatch_reco_worse_alerts("t1", [])


def test_dispatch_rental_families_exception_swallowed(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("family dispatch failed")

    monkeypatch.setattr(up, "_dispatch_tenant_alert_family", _boom)
    up.dispatch_rental_market_alerts("t1", [("WARN", "cat", "msg")])
    up.dispatch_rental_arb_alerts("t1", [("WARN", "cat", "msg")])
    up.dispatch_reco_worse_alerts("t1", [("WARN", "cat", "msg")])


def test_fire_webhook_async_fallback_on_queue_failure(monkeypatch):
    """When the retry queue itself blows up, the last-resort direct webhook
    send runs (never crash the daemon thread)."""
    import threading
    calls = []

    def _boom(**kw):
        raise RuntimeError("queue down")

    def _direct(**kw):
        calls.append(kw)

    monkeypatch.setattr(up, "_send_webhook_for_alert", _direct)
    monkeypatch.setattr("services.webhook_queue.dispatch_webhook_or_queue", _boom)
    up._fire_webhook_async({"severity": "CRIT", "category": "cat", "message": "m"})
    # Join the daemon thread it spawned (short-lived) so the fallback ran.
    for t in threading.enumerate():
        if t.name == "cypher65-webhook" and t.is_alive():
            t.join(timeout=2)
    assert calls, "fallback webhook must have fired after queue failure"


def test_fetch_user_data_and_account_delegate_to_cached_fetch(monkeypatch):
    calls = []

    def _cached(key, fetcher, *args):
        calls.append((key, args))
        return {"data": key}

    monkeypatch.setattr(up, "_cached_user_fetch", _cached)
    assert up._fetch_user_data("bc1qx") == {"data": "user_bc1qx"}
    assert up._fetch_account("bc1qx") == {"data": "acct_bc1qx"}
    assert len(calls) == 2


def test_network_mempool_fees_empty_payload_fallback(monkeypatch):
    """Mempool fees payload with no numeric fields → the None-shape fallback
    is cached globally (no partial garbage)."""
    monkeypatch.setattr(up, "_get_global", lambda key, ttl=up.GLOBAL_CACHE_TTL: None)

    class _Fut:
        def result(self):
            return None

    results_iter = iter([857204, "1e14", "600000", {"fastestFee": "fast"}])
    cached = {}

    class _Ex:
        def __enter__(self_):
            return self_

        def __exit__(self_, *a):
            return False

        def submit(self_, fn, *args):
            return _Fut()

    monkeypatch.setattr(up.concurrent.futures, "ThreadPoolExecutor",
                        lambda max_workers=4: _Ex())
    monkeypatch.setattr(up, "_update_global",
                        lambda key, val: cached.__setitem__(key, val))
    up._fetch_global_network()
    assert cached.get("mempool_fees") == {"fastestFee": None,
                                           "halfHourFee": None,
                                           "hourFee": None}

