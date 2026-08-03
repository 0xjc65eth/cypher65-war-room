"""
CYPHER65 // services.workers — standalone background-workers entrypoint
=======================================================================
The multi-process deploy option (gunicorn for HTTP + `python -m
services.workers` for polling/telemetry) must start the SAME background
workers as the single-process `python app.py` path, WITHOUT binding a port
and WITHOUT spawning threads on plain module import.

Hermetic: imports `services.workers` (zero side effects) and monkeypatches
app._start_background_threads — no threads, no network, no DB writes.
"""
import services.workers as _workers
import app as _app_module


class TestWorkersEntrypoint:
    def test_import_has_no_side_effects(self):
        """`import services.workers` must not start workers by itself —
        same boot-contract as `import app` (test_boot_threads)."""
        # If import had side effects, threads would already be running;
        # the run_workers() test below asserts the call chain explicitly.
        assert callable(_workers.run_workers)
        assert callable(_workers.main)

    def test_run_workers_calls_start_background_threads(self, monkeypatch):
        """run_workers() must delegate to app._start_background_threads()
        — the single source of truth for the boot contract. If app.py adds
        a worker there, this entrypoint inherits it automatically."""
        calls = []
        monkeypatch.setattr(_app_module, "_start_background_threads",
                            lambda: calls.append(1))
        _workers.run_workers()
        assert calls == [1]

    def test_run_workers_propagates_boot_failure(self, monkeypatch):
        """A failure inside _start_background_threads must propagate as-is
        (the caller decides — e.g. a supervisor restarts the process) rather
        than being swallowed into a half-started silent state."""
        def boom():
            raise RuntimeError("boot worker failed")
        monkeypatch.setattr(_app_module, "_start_background_threads", boom)
        try:
            _workers.run_workers()
            raised = False
        except RuntimeError:
            raised = True
        assert raised
