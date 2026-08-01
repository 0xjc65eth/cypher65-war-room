"""
CYPHER65 // Boot consolidation — _start_background_threads()
============================================================
The server's background workers (initial poll + poll_loop + 5-min Hash
Market warmup + on-chain donation watcher) start from ONE helper called
only in the __main__ block — never on plain test-suite imports, so
`import app` spawns no network threads.
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
    EXPECTED_TARGETS = ("poll_loop", "_hashrate_market_warmup_loop", "_donation_watcher_loop")
    EXPECTED_COUNT = 3

    def test_starts_poll_loop_and_warmup(self, monkeypatch):
        FakeThread.started = []
        started = FakeThread.started
        poll_calls = []
        monkeypatch.setattr(_app_module.threading, "Thread", FakeThread)
        monkeypatch.setattr(_app_module, "poll_once", lambda: poll_calls.append(1))

        _app_module._start_background_threads()

        # Initial kick-off poll ran exactly once, before the threads start.
        assert poll_calls == [1]
        targets = [t.target for t in started]
        for name in self.EXPECTED_TARGETS:
            assert getattr(_app_module, name) in targets, f"{name} thread not started"
        assert len(started) == self.EXPECTED_COUNT
        assert all(t.daemon for t in started)

    def test_survives_initial_poll_failure(self, monkeypatch):
        """A cold-start provider outage must not take down boot — the loop
        retries on its own cycle, but all workers still start."""
        FakeThread.started = []
        started = FakeThread.started

        def broken_poll():
            raise RuntimeError("pool API down at boot")

        monkeypatch.setattr(_app_module.threading, "Thread", FakeThread)
        monkeypatch.setattr(_app_module, "poll_once", broken_poll)

        # Must not raise; all workers still start.
        _app_module._start_background_threads()
        assert len(started) == self.EXPECTED_COUNT
        targets = [t.target for t in started]
        for name in self.EXPECTED_TARGETS:
            assert getattr(_app_module, name) in targets, f"{name} thread not started"
