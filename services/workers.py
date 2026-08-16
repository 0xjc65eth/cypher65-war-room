"""
CYPHER65 — Standalone background-workers entrypoint
=====================================================
Runs the server's background workers (initial poll + poll_loop + Hash
Market warmup + on-chain donation watcher + auto-backup) in a SEPARATE
process, so a WSGI server (gunicorn) can serve HTTP without polling.

Why this exists
---------------
`python app.py` is the single-process default: the __main__ block calls
app._start_background_threads() and then app.run(). That works perfectly
for self-host / Tailscale / Render free tier — but it couples polling to
the dev server, which is why gunicorn app:app would serve HTTP with NO
telemetry (the render.yaml warning).

For a multi-process deploy (gunicorn + worker):

    # Process 1 — HTTP (no polling):
    gunicorn -k gevent -w 2 -b 0.0.0.0:8765 app:app

    # Process 2 — telemetry/workers (this module):
    python -m services.workers

The workers process imports `app` (registers routes + runs init_db) but
never binds a port — it starts the daemon threads and blocks forever.

Honest note on SSE: /api/stream fans out in-process (_sse_clients), so in
a two-process topology live-push only reaches clients connected to the
gunicorn process that owns them. The dashboard's 15s poll fallback keeps
data fresh regardless; for full live-push across workers you'd need a
shared pub/sub (Redis) — not implemented. `python app.py` (single process)
is unaffected and keeps full SSE.

Design rule: this module NEVER imports `app` at module level (only inside
run_workers()), so `import services.workers` from tests has zero
side-effects — matching the project's boot-contract (test_boot_threads).
"""

import logging
import time

log = logging.getLogger("cypher65.workers")


def run_workers() -> None:
    """Start every background worker in THIS process (no HTTP server).

    Intentionally mirrors the __main__ block of app.py. Imported lazily so
    importing this module (e.g. from the test suite) never boots app-level
    side effects or network threads.
    """
    import app as _app  # noqa: PLC0415 — lazy import keeps module import pure

    _app._start_background_threads()
    log.info(
        "[workers] background workers started (poll, market warmup, "
        "donation watcher, auto-backup)"
    )


def main() -> None:
    """CLI entrypoint: `python -m services.workers`."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    run_workers()
    # The worker threads are daemons — they die with the main thread, so
    # block forever (with a periodic wake for signal handling).
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        log.info("[workers] shutdown requested")


if __name__ == "__main__":
    main()
