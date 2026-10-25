"""Hermetic Flask server for #868. No collectors, providers or real credentials.

Run with the repository's existing Python environment. The JSON ready message
is consumed in memory by Playwright, never printed as test evidence or persisted.
"""

import json
import logging
import os
import signal
import sys
import tempfile
from pathlib import Path

from flask import Response
from werkzeug.serving import make_server


def main():
    """Serve production Flask routes/assets with synthetic settings and JWTs.

    Example: ``python tests/e2e/support/public_static_cache_fixture.py``.
    The process uses a disposable SQLite database and never starts app workers.
    """
    logging.disable(logging.CRITICAL)

    def stop_fixture(_signum, _frame):
        """Exit through the scratch-directory cleanup context."""
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop_fixture)
    with tempfile.TemporaryDirectory(prefix="cypher65-cache-fixture-") as scratch:
        os.environ["DB_PATH"] = str(Path(scratch) / "fixture.sqlite")
        os.environ["SECRET_KEY"] = "synthetic-cache-test-key-0123456789-0123456789"
        sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
        import app as production
        from services.auth import create_token
        from services.settings import save_setting

        production.app.config.update(TESTING=True)
        production.BTC_ADDRESS = "SYNTHETIC-OPERATOR-WALLET-NOT-REAL"
        production.WORKER_NAME = "SYNTHETIC-OPERATOR-WORKER"
        for owner in ("synthetic-owner-A", "synthetic-owner-B"):
            save_setting(
                "webhook_url", f"https://{owner.lower()}.invalid/hook", tenant_id=owner
            )
        with production.app.app_context():
            tokens = {
                owner: create_token(subject=owner, extra_claims={"role": "member"})
                for owner in ("synthetic-owner-A", "synthetic-owner-B")
            }

        @production.app.route("/__public-cache-probe")
        def probe_document():
            """Minimal inert fixture document; no production browser code runs."""
            return Response(
                "<!doctype html><html lang=en><title>Public cache fixture</title>"
                "<body>Hermetic service-worker probe</body></html>",
                content_type="text/html",
            )

        with make_server("127.0.0.1", 0, production.app, threaded=True) as server:
            print(
                json.dumps(
                    {
                        "origin": f"http://127.0.0.1:{server.server_port}",
                        "tokens": tokens,
                    }
                ),
                flush=True,
            )
            server.serve_forever()


if __name__ == "__main__":
    main()
