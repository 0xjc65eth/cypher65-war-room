"""
CYPHER65 // Boot consolidation — _start_background_threads()
============================================================
The server's background workers (initial poll + poll_loop + 5-min Hash
Market warmup + on-chain donation watcher + C4 auto-backup worker) start
from ONE helper called only in the __main__ block — never on plain
``test-suite imports, so `import app` spawns no network threads.

P1 Phase 2 adds the fixed user-poll worker pool (start_poll_pool) to the
boot contract. It spawns 1 scheduler + POOL_SIZE worker threads of its own
(not via app.threading), so the tests here monkeypatch it the same way they
monkeypatch poll_once: assert the boot CALLS it, without starting 9 real
threads. The pool itself is covered by tests/test_poll_worker_pool.py.
"""
import app as _app_module


class FakeThread:
    """Records threads instead of running them, so tests can assert on which
    background workers _start_background_threads() would have started."""
    started = []  # populated by start(); reset per-test via FakeThread.started = []

    def __init__(self, target=None, daemon=None):
        self.target = target
        self.daemon = daemon

    def start(self):
        FakeThread.started.append(self)


class TestStartBackgroundThreads:
    """_start_background_threads() must kick off the initial poll and start
    the poll_loop thread, the market warmup thread and the donation watcher
    as daemons."""

    # Expected background workers started by _start_background_threads().
    # Kept as a class attr so both tests assert the same contract.
    # NOTE: if a new background worker is added in app.py's
    # _start_background_threads(), update BOTH lists below — this is the
    # boot-contract lock that catches accidental thread regressions.
    EXPECTED_TARGETS = ("poll_loop", "_hashrate_market_warmup_loop", "_donation_watcher_loop", "_auto_backup_loop")
    EXPECTED_COUNT = 4

    def test_starts_poll_loop_and_warmup(self, monkeypatch):
        FakeThread.started = []
        started = FakeThread.started
        poll_calls = []
        pool_calls = []
        # C4: pin the backup worker ON so the boot contract is deterministic
        # regardless of a developer/CI exporting AUTO_BACKUP_INTERVAL=0.
        monkeypatch.setenv("AUTO_BACKUP_INTERVAL", "3600")
        monkeypatch.setattr(_app_module.threading, "Thread", FakeThread)
        monkeypatch.setattr(_app_module, "poll_once", lambda: poll_calls.append(1))
        # P1 Phase 2: the fixed worker pool is started via its own hook
        # (spawns its own threads, not app.threading) — assert boot calls it.
        monkeypatch.setattr(_app_module, "_start_poll_pool",
                            lambda: pool_calls.append(1))

        _app_module._start_background_threads()

        # Initial kick-off poll ran exactly once, before the threads start.
        assert poll_calls == [1]
        assert pool_calls == [1]
        targets = [t.target for t in started]
        for name in self.EXPECTED_TARGETS:
            assert getattr(_app_module, name) in targets, f"{name} thread not started"
        assert len(started) == self.EXPECTED_COUNT
        assert all(t.daemon for t in started)

    def test_backup_worker_respects_env_off(self, monkeypatch):
        """AUTO_BACKUP_INTERVAL=0 disables the C4 backup worker — the boot
        contract then starts only the 3 network/telemetry workers."""
        FakeThread.started = []
        started = FakeThread.started
        monkeypatch.setenv("AUTO_BACKUP_INTERVAL", "0")
        monkeypatch.setattr(_app_module.threading, "Thread", FakeThread)
        monkeypatch.setattr(_app_module, "poll_once", lambda: None)

        _app_module._start_background_threads()

        targets = [t.target for t in started]
        assert _app_module._auto_backup_loop not in targets, "backup worker must be disabled"
        assert len(started) == self.EXPECTED_COUNT - 1

    def test_survives_initial_poll_failure(self, monkeypatch):
        """A cold-start provider outage must not take down boot — the loop
        retries on its own cycle, but all workers still start."""
        FakeThread.started = []
        started = FakeThread.started

        def broken_poll():
            raise RuntimeError("pool API down at boot")

        # C4: pin the backup worker ON for a deterministic boot contract.
        monkeypatch.setenv("AUTO_BACKUP_INTERVAL", "3600")
        monkeypatch.setattr(_app_module.threading, "Thread", FakeThread)
        monkeypatch.setattr(_app_module, "poll_once", broken_poll)
        monkeypatch.setattr(_app_module, "_start_poll_pool", lambda: None)

        # Must not raise; all workers still start.
        _app_module._start_background_threads()
        assert len(started) == self.EXPECTED_COUNT
        targets = [t.target for t in started]
        for name in self.EXPECTED_TARGETS:
            assert getattr(_app_module, name) in targets, f"{name} thread not started"
