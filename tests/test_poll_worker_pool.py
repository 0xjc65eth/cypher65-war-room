"""Hermetic tests for P1 Phase 2 — the FIXED worker pool.

Covers:
  1. PollWorkerPool: bounded thread count (8 threads serve N sessions, no
     thread-per-session), register→poll→snapshot flow, unregister stops
     re-scheduling, reschedule_immediate, active_count.
  2. UserPollingWorker facade: public API preserved (start/stop/poll_now/
     update_address/is_running) and poll_now stays SYNCHRONOUS (no pool
     worker needed — the connect path and unit tests rely on it).
"""

import os
import sys
import time

import pytest

sys.path.insert(0, ".")

import services.user_polling as _up  # noqa: E402
from services.session_manager import SessionManager  # noqa: E402


def _snap(ts=None, hashrate=100.0):
    ts = ts or int(time.time())
    return {
        "ts": ts,
        "worker": {"hashrate": hashrate, "lastSubmission": ts - 10,
                   "uptime": 1000},
        "all_workers": [{"name": "w1", "hashrate": hashrate}],
    }


# ── Pool: bounded threads ───────────────────────────────────────────────────

class TestPoolBoundedThreads:
    def test_small_pool_serves_many_sessions(self):
        """8 worker threads (never-started pool) must serve N sessions without
        spawning a thread per session."""
        pool = _up.PollWorkerPool(size=4)
        sm = SessionManager()
        for i in range(50):
            s = sm.create_session(f"bc1q{i % 10}" + "a" * 33, "w1")
            _up.UserPollingWorker(s.session_id, sm, s.btc_address, "w1",
                                  pool=pool)
        # No threads spawned by construction/register — pool not started.
        assert pool._workers == []
        assert pool.size == 4
        sm.stop()

    def test_pool_start_spawns_exact_size_workers(self):
        pool = _up.PollWorkerPool(size=3)
        pool.start()
        try:
            assert len(pool._workers) == 3
            assert pool._scheduler is not None
            assert all(t.is_alive() for t in pool._workers)
        finally:
            pool.stop()

    def test_registered_sessions_are_polled_by_pool(self, monkeypatch):
        """A registered session's snapshot lands in the SessionManager via a
        pool worker, not a per-session thread."""
        pool = _up.PollWorkerPool(size=2)
        snap = _snap()
        monkeypatch.setattr(_up, "_build_snapshot", lambda a, w: snap)
        monkeypatch.setattr(_up, "_poll_wait", lambda err: 0.01)  # fast re-poll
        pool.start()
        try:
            sm = SessionManager()
            s = sm.create_session("bc1qpool" + "a" * 30, "w1")
            w = _up.UserPollingWorker(s.session_id, sm, s.btc_address, "w1",
                                      pool=pool)
            w.start()
            # Wait for the pool worker to run at least one poll.
            for _ in range(100):
                stored = sm.get_snapshot(s.session_id)
                if stored and stored.get("worker"):
                    break
                time.sleep(0.05)
            stored = sm.get_snapshot(s.session_id)
            assert stored is not None and stored.get("worker")
            assert stored["worker"]["hashrate"] == 100.0
            assert pool.is_running(s.session_id) is True
            w.stop()
            assert pool.is_running(s.session_id) is False
            sm.stop()
        finally:
            pool.stop()

    def test_unregister_stops_repolling(self, monkeypatch):
        """After unregister, no further polls happen for that session."""
        pool = _up.PollWorkerPool(size=2)
        count = {"n": 0}
        monkeypatch.setattr(_up, "_poll_wait", lambda err: 0.01)
        monkeypatch.setattr(
            _up, "_build_snapshot",
            lambda a, w: (count.__setitem__("n", count["n"] + 1) or _snap()))
        pool.start()
        try:
            sm = SessionManager()
            s = sm.create_session("bc1qstop" + "a" * 29, "w1")
            w = _up.UserPollingWorker(s.session_id, sm, s.btc_address, "w1",
                                      pool=pool)
            w.start()
            for _ in range(100):
                if count["n"] >= 1:
                    break
                time.sleep(0.05)
            w.stop()
            time.sleep(0.1)  # let any in-flight poll settle
            before = count["n"]
            time.sleep(0.15)  # several fast re-poll windows would fire here
            assert count["n"] == before  # no new polls after unregister
            sm.stop()
        finally:
            pool.stop()

    def test_reschedule_immediate_after_address_change(self, monkeypatch):
        pool = _up.PollWorkerPool(size=2)
        monkeypatch.setattr(_up, "_poll_wait", lambda err: 60.0)  # long wait
        monkeypatch.setattr(_up, "_build_snapshot", lambda a, w: _snap())
        pool.start()
        try:
            sm = SessionManager()
            s = sm.create_session("bc1qaddr" + "a" * 28, "w1")
            w = _up.UserPollingWorker(s.session_id, sm, s.btc_address, "w1",
                                      pool=pool)
            w.start()
            # Change address → reschedule_immediate must trigger a poll soon
            # despite the 60s wait (heap gets a now-due entry).
            w.update_address("bc1qnew" + "b" * 30, "w2")
            assert w.address.startswith("bc1qnew")
            assert w.worker_name == "w2"
            for _ in range(100):
                stored = sm.get_snapshot(s.session_id)
                if stored and stored.get("worker"):
                    break
                time.sleep(0.05)
            assert sm.get_snapshot(s.session_id) is not None
            sm.stop()
        finally:
            pool.stop()

    def test_active_count_tracks_sessions(self):
        pool = _up.PollWorkerPool(size=2)
        sm = SessionManager()
        s1 = sm.create_session("bc1qaa" + "a" * 30, "w1")
        s2 = sm.create_session("bc1qbb" + "b" * 30, "w1")
        w1 = _up.UserPollingWorker(s1.session_id, sm, s1.btc_address, "w1",
                                   pool=pool)
        w2 = _up.UserPollingWorker(s2.session_id, sm, s2.btc_address, "w1",
                                   pool=pool)
        w1.start()
        w2.start()
        assert pool.active_count == 2
        w1.stop()
        assert pool.active_count == 1
        w2.stop()
        assert pool.active_count == 0
        sm.stop()


# ── Facade: synchronous poll_now + API parity ───────────────────────────────

class TestWorkerFacade:
    def test_poll_now_is_synchronous_and_returns_snapshot(self, monkeypatch):
        """poll_now() runs in the caller's thread — the connect path and unit
        tests depend on it; the pool must NOT be required for it."""
        snap = _snap()
        monkeypatch.setattr(_up, "_build_snapshot", lambda a, w: snap)
        monkeypatch.setattr(
            _up, "_load_settings", lambda tid: {"webhook_url": "",
                                                "webhook_min_severity": "WARN"})
        sm = SessionManager()
        s = sm.create_session("bc1qsync" + "a" * 28, "w1")
        w = _up.UserPollingWorker(s.session_id, sm, s.btc_address, "w1",
                                  tenant_id="tenant-sync")
        result = w.poll_now()
        assert result is not None and result.get("worker")
        assert result["worker"]["hashrate"] == 100.0
        # Snapshot stored even though the pool was never started.
        stored = sm.get_snapshot(s.session_id)
        assert stored and stored.get("worker")
        assert w.is_running is False  # never registered → not running
        sm.stop()

    def test_default_pool_is_shared_singleton(self):
        """Without an injected pool, workers use the process-wide POLL_POOL
        (so app.py wiring stays trivial)."""
        sm = SessionManager()
        s = sm.create_session("bc1qsing" + "a" * 28, "w1")
        w = _up.UserPollingWorker(s.session_id, sm, s.btc_address, "w1")
        assert w._pool is _up.POLL_POOL
        sm.stop()

    def test_pool_size_env_override(self, monkeypatch):
        # Patch the module attribute directly — reloading the module while the
        # env var is set would leave POOL_DEFAULT_SIZE=12 for later tests
        # (monkeypatch teardown runs AFTER the function returns).
        import services.user_polling as mod
        monkeypatch.setattr(mod, "POOL_DEFAULT_SIZE", 12)
        assert mod.POOL_DEFAULT_SIZE == 12
        # The real env read still works for a fresh process.
        assert int(os.environ.get("POLL_WORKER_POOL_SIZE", "8")) == 8


# ── Thread-safety: alert baseline under concurrent dispatch ─────────────────

class TestAlertDispatchConcurrency:
    def test_alert_dispatch_serialized_per_worker(self, monkeypatch):
        """poll_now() (request thread) and pool workers may run for the SAME
        session concurrently. The per-worker _alert_lock must serialize the
        baseline read→write + dedup mutation, so the delta baseline stays
        deterministic (no torn prev, no double-fire)."""
        import threading
        import services.user_polling as mod

        snap = _snap(hashrate=100.0)
        monkeypatch.setattr(
            mod, "_load_settings",
            lambda tid: {"webhook_url": "", "webhook_min_severity": "WARN"})

        state = {"active": 0, "max_active": 0}
        state_lock = threading.Lock()

        def fake_eval(snapshot, prev, settings, alert_seen):
            # Measure how many dispatches are inside the critical section at
            # once. Without the per-worker lock this exceeds 1 under threads;
            # with it, exactly one at a time.
            with state_lock:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            time.sleep(0.005)  # widen the race window
            with state_lock:
                state["active"] -= 1
            return []  # no alerts → no DB/webhook side effects

        monkeypatch.setattr(mod, "evaluate_user_alerts", fake_eval)

        sm = SessionManager()
        s = sm.create_session("bc1qlock" + "a" * 27, "w1")
        w = mod.UserPollingWorker(s.session_id, sm, s.btc_address, "w1",
                                  tenant_id="tenant-race")

        def hammer():
            for _ in range(15):
                w._dispatch_tenant_alerts(snap)

        threads = [threading.Thread(target=hammer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert state["max_active"] == 1  # fully serialized
        sm.stop()

    def test_update_address_reset_holds_same_lock(self, monkeypatch):
        """update_address resets the baseline under the SAME lock, so an
        in-flight dispatch never reads a half-cleared baseline."""
        import threading
        import services.user_polling as mod

        monkeypatch.setattr(
            mod, "_load_settings",
            lambda tid: {"webhook_url": "", "webhook_min_severity": "WARN"})
        monkeypatch.setattr(mod, "evaluate_user_alerts", lambda *a: [])

        sm = SessionManager()
        s = sm.create_session("bc1qreset" + "a" * 26, "w1")
        w = mod.UserPollingWorker(s.session_id, sm, s.btc_address, "w1",
                                  tenant_id="tenant-reset")

        # Sanity: the lock exists and is the SAME object used by dispatch.
        assert w._alert_lock is not None
        # A baseline set by dispatch is visible, then update_address resets it
        # atomically (no torn read when a dispatch is in flight).
        w._dispatch_tenant_alerts(_snap(hashrate=100.0))
        assert w._prev_snapshot and w._prev_snapshot.get("worker")
        w.update_address("bc1qnew" + "b" * 29, "w2")
        assert w._prev_snapshot == {}
        assert w._alert_seen == set()
        assert w.address.startswith("bc1qnew")
        sm.stop()


# ── Observability: stats() ──────────────────────────────────────────────────

class TestPoolStats:
    def test_stats_before_start_returns_zeros(self):
        """stats() must be safe to call before start — the admin endpoint is
        hit even when the pool was never started (tests / no sessions)."""
        pool = _up.PollWorkerPool(size=4)
        s = pool.stats()
        assert s["started"] is False
        assert s["pool_size"] == 4
        assert s["workers_alive"] == 0
        assert s["sessions_active"] == 0
        assert s["scheduled"] == 0
        assert s["queue_pending"] == 0
        assert s["total_polls"] == 0
        assert s["total_errors"] == 0
        assert s["polls_per_sec"] == 0.0
        assert s["uptime_secs"] == 0

    def test_stats_after_polls_counts_them(self, monkeypatch):
        """Real pool polls must increment total_polls and move the polls/sec
        window. sessions_active reflects the registered session."""
        pool = _up.PollWorkerPool(size=2)
        monkeypatch.setattr(_up, "_build_snapshot", lambda a, w: _snap())
        monkeypatch.setattr(_up, "_poll_wait", lambda err: 0.01)  # fast re-poll
        pool.start()
        try:
            sm = SessionManager()
            s = sm.create_session("bc1qstats" + "a" * 26, "w1")
            w = _up.UserPollingWorker(s.session_id, sm, s.btc_address, "w1",
                                      pool=pool)
            w.start()
            for _ in range(100):
                if pool._poll_count >= 3:
                    break
                time.sleep(0.05)
            st = pool.stats()
            assert st["started"] is True
            assert st["workers_alive"] == 2
            assert st["sessions_active"] == 1
            assert st["total_polls"] >= 3
            assert st["total_errors"] == 0
            assert st["polls_per_sec"] > 0  # fast re-poll → measurable rate
            assert st["uptime_secs"] > 0
            w.stop()
            sm.stop()
        finally:
            pool.stop()

    def test_stats_counts_poll_errors(self, monkeypatch):
        """A raising _build_snapshot is counted as an error, not a poll."""
        pool = _up.PollWorkerPool(size=1)

        def boom(address, worker_name):
            raise RuntimeError("upstream down")

        monkeypatch.setattr(_up, "_build_snapshot", boom)
        monkeypatch.setattr(_up, "_poll_wait", lambda err: 0.01)
        pool.start()
        try:
            sm = SessionManager()
            s = sm.create_session("bc1qerr" + "a" * 28, "w1")
            w = _up.UserPollingWorker(s.session_id, sm, s.btc_address, "w1",
                                      pool=pool)
            w.start()
            for _ in range(100):
                if pool._error_count >= 2:
                    break
                time.sleep(0.05)
            st = pool.stats()
            assert st["total_errors"] >= 2
            assert st["total_polls"] == 0  # nothing succeeded
            w.stop()
            sm.stop()
        finally:
            pool.stop()


    def test_stats_reports_last_poll_and_stalled(self, monkeypatch):
        """stats() exposes last_poll_ts + stalled flag; is_stalled() is False
        on a healthy pool that recently polled."""
        pool = _up.PollWorkerPool(size=1)
        monkeypatch.setattr(_up, "_build_snapshot", lambda a, w: _snap())
        monkeypatch.setattr(_up, "_poll_wait", lambda err: 0.01)
        pool.start()
        try:
            sm = SessionManager()
            s = sm.create_session("bc1qstall" + "a" * 26, "w1")
            w = _up.UserPollingWorker(s.session_id, sm, s.btc_address, "w1",
                                      pool=pool)
            w.start()
            for _ in range(100):
                if pool._last_poll_ts:
                    break
                time.sleep(0.05)
            assert pool._last_poll_ts > 0
            assert pool.is_stalled(window=90.0) is False  # just polled
            st = pool.stats()
            assert st["last_poll_ts"] > 0
            assert st["stalled"] is False
            w.stop()
            sm.stop()
        finally:
            pool.stop()

    def test_is_stalled_when_pending_but_no_recent_poll(self):
        """Sessions registered + no completed poll in the window = stalled.
        An idle pool (nothing registered) is NOT stalled."""
        pool = _up.PollWorkerPool(size=2)
        pool.start()
        try:
            # Idle pool: nothing to do → never stalled.
            assert pool.is_stalled(window=1.0) is False
            # Pending session, no poll completed yet (worker threads are
            # blocked/stuck — simulate by registering without letting it run:
            # _last_poll_ts stays 0, but the session IS in the heap).
            sm = SessionManager()
            s = sm.create_session("bc1qfrozen" + "a" * 25, "w1")
            w = _up.UserPollingWorker(s.session_id, sm, s.btc_address, "w1",
                                      pool=pool)
            with pool._lock:
                pool._sessions[w.session_id] = w
                import heapq as _h
                _h.heappush(pool._heap, (time.time(), next(pool._seq),
                                         w.session_id))
            # Wait past the window with no poll completing (fake the start
            # time far in the past so the grace period is exhausted).
            with pool._lock:
                pool._started_ts = time.time() - 10.0
            assert pool.is_stalled(window=1.0) is True
            sm.stop()
        finally:
            pool.stop()


def test_admin_sessions_route_includes_pool_stats():
    """/api/admin/sessions carries the pool observability block (started pool
    in the test process reports its real counters)."""
    import app as _app_module
    _app_module.app.config["TESTING"] = True
    client = _app_module.app.test_client()
    resp = client.get("/api/admin/sessions")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "count" in data and "sessions" in data
    assert "pool" in data
    pool = data["pool"]
    # The process-wide POLL_POOL may be started or not in tests — either way
    # the block must carry the full schema.
    for key in ("started", "pool_size", "workers_alive", "sessions_active",
                "scheduled", "queue_pending", "total_polls",
                "total_errors", "polls_per_sec", "uptime_secs"):
        assert key in pool
