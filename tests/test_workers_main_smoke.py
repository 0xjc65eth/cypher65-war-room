"""
CYPHER65 // services.workers — main() CLI smoke tests (Issue #474)
==================================================================
The audit (enterprise-code-review, 2026-09-10) flagged `services.workers`
at 53% coverage: the entrypoint of the multi-process deploy topology
(gunicorn HTTP + `python -m services.workers`) was only exercised in
production. test_workers_entry.py already pins import purity and the
run_workers() delegation contract; this module pins `main()`:

  - logging is configured BEFORE workers start (operator sees boot logs)
  - workers start exactly once, before the blocking loop
  - the process blocks forever with PERIODIC wakes (sleep(3600) in a
    loop, not a single join — keeps signal handling responsive)
  - KeyboardInterrupt in the loop exits cleanly (graceful shutdown)
  - a boot failure propagates as-is (supervisor restarts — same contract
    as test_run_workers_propagates_boot_failure)

Hermetic: time.sleep is stubbed on the module namespace (never the real
stdlib module), logging.basicConfig is captured, run_workers is
monkeypatched — no threads, no network, no real waiting.
"""
import types

import services.workers as _workers


class TestWorkersMain:
    def test_main_configures_logging_then_starts_workers(self, monkeypatch):
        """main() must configure root logging before run_workers() — a
        supervisor reading stdout/stderr must see the boot log line."""
        events = []
        monkeypatch.setattr(
            _workers.logging, "basicConfig",
            lambda **kw: events.append(("basicConfig", kw)),
        )
        monkeypatch.setattr(
            _workers, "run_workers", lambda: events.append(("run_workers", None))
        )
        monkeypatch.setattr(
            _workers, "time",
            types.SimpleNamespace(sleep=lambda s: (_ for _ in ()).throw(KeyboardInterrupt())),
        )
        _workers.main()
        assert [name for name, _ in events] == ["basicConfig", "run_workers"]
        kwargs = events[0][1]
        assert kwargs.get("level") == _workers.logging.INFO
        # Structured-ish format: timestamp + level + logger name + message.
        fmt = kwargs.get("format", "")
        for token in ("%(asctime)s", "%(levelname)s", "%(name)s", "%(message)s"):
            assert token in fmt, f"logging format missing {token}"

    def test_main_blocks_with_periodic_wake(self, monkeypatch):
        """The blocking loop must sleep(3600) REPEATEDLY (periodic wake for
        signal handling) — not a single one-shot join."""
        monkeypatch.setattr(_workers, "run_workers", lambda: None)
        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) >= 3:  # wake 3 times, then "Ctrl-C"
                raise KeyboardInterrupt()

        monkeypatch.setattr(_workers, "time", types.SimpleNamespace(sleep=fake_sleep))
        _workers.main()
        assert sleeps == [3600, 3600, 3600]

    def test_main_keyboard_interrupt_exits_cleanly(self, monkeypatch):
        """Ctrl-C in the blocking loop is a graceful shutdown request:
        main() must return None — never let KeyboardInterrupt escape
        (a bare traceback on SIGINT reads as a crash to the supervisor)."""
        monkeypatch.setattr(_workers, "run_workers", lambda: None)

        def fake_sleep(seconds):
            raise KeyboardInterrupt()

        monkeypatch.setattr(_workers, "time", types.SimpleNamespace(sleep=fake_sleep))
        assert _workers.main() is None

    def test_main_propagates_boot_failure(self, monkeypatch):
        """A failure inside run_workers() must propagate as-is — the
        supervisor decides (restart/backoff). Swallowing it here would
        leave a 'running' worker process with NO workers started."""

        def boom():
            raise RuntimeError("boot worker failed")

        monkeypatch.setattr(_workers, "run_workers", boom)
        try:
            _workers.main()
            raised = False
        except RuntimeError:
            raised = True
        assert raised

    def test_main_logs_shutdown_on_keyboard_interrupt(self, monkeypatch, caplog):
        """Graceful shutdown must be observable: the '[workers] shutdown
        requested' INFO line goes to the cypher65.workers logger."""
        import logging as _logging

        monkeypatch.setattr(_workers, "run_workers", lambda: None)
        monkeypatch.setattr(
            _workers, "time",
            types.SimpleNamespace(sleep=lambda s: (_ for _ in ()).throw(KeyboardInterrupt())),
        )
        with caplog.at_level(_logging.INFO, logger="cypher65.workers"):
            _workers.main()
        assert any("shutdown requested" in rec.message for rec in caplog.records)
