"""Timezone contract for subscription conversion and UTC reporting buckets.

``services.conversion._iso_to_ts`` parses explicit offsets to Unix seconds and
``_month_key`` formats those instants in UTC. Fleet relative-age UI likewise
uses epoch arithmetic (``static/src/10-core-fmt.js``). This file tests the
conversion contract under named host zones; it does not claim every timestamp
producer in the application has been audited for end-to-end UTC behavior.
"""

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    ("zone", "iso_utc", "expected_ts", "expected_month"),
    [
        # Includes both sides of Sao Paulo's 2017 DST boundary.
        ("America/Sao_Paulo", "2017-10-15T02:59:59Z", 1508036399, "2017-10"),
        ("America/Sao_Paulo", "2017-10-15T03:00:00Z", 1508036400, "2017-10"),
        # Europe/Brussels spring-forward boundary in 2026.
        ("Europe/Brussels", "2026-03-29T00:59:59Z", 1774745999, "2026-03"),
        ("Europe/Brussels", "2026-03-29T01:00:00Z", 1774746000, "2026-03"),
    ],
)
def test_iso_and_utc_month_bucket_ignore_host_timezone(
    zone, iso_utc, expected_ts, expected_month
):
    """The same explicit UTC instant must parse identically in named zones."""
    env = os.environ.copy()
    env["TZ"] = zone
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os, tempfile; "
                "scratch = tempfile.TemporaryDirectory(); "
                "os.environ['DB_PATH'] = scratch.name + '/timezone.sqlite'; "
                "from services.conversion import ("
                "_iso_to_ts, _month_key, record_subscription_event); "
                "from services.db import get_db; "
                f"ts = _iso_to_ts({iso_utc!r}); "
                f"assert ts == {expected_ts}, (ts, {zone!r}); "
                f"assert _month_key(ts) == {expected_month!r}, (ts, {zone!r}); "
                f"assert record_subscription_event('tz', 'subscription_created', ts, created_at={iso_utc!r}); "
                "conn = get_db(); "
                "row = conn.execute('SELECT ts, created_at_ts FROM subscription_events').fetchone(); "
                "conn.close(); "
                "assert tuple(row) == (ts, ts), tuple(row)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize(
    ("zone", "before_iso", "after_iso"),
    [
        (
            "America/Sao_Paulo",
            "2017-10-15T02:30:00Z",
            "2017-10-15T03:30:00Z",
        ),
        (
            "Europe/Brussels",
            "2026-03-29T00:30:00Z",
            "2026-03-29T01:30:00Z",
        ),
    ],
)
def test_dst_boundary_elapsed_time_and_epoch_order_are_timezone_independent(
    zone, before_iso, after_iso
):
    """Elapsed time and ordering use UTC epochs, not local wall-clock time."""
    env = os.environ.copy()
    env["TZ"] = zone
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from services.conversion import _iso_to_ts; "
                f"before = _iso_to_ts({before_iso!r}); "
                f"after = _iso_to_ts({after_iso!r}); "
                "assert after > before; "
                "assert after - before == 3600, (before, after)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr or result.stdout

    ui_result = subprocess.run(
        [
            "node",
            "-e",
            (
                "const fs = require('node:fs'); "
                "const vm = require('node:vm'); "
                "const source = fs.readFileSync('static/src/10-core-fmt.js', 'utf8'); "
                f"const now = Date.parse({after_iso!r}); "
                "const FixedDate = class extends Date { "
                "static now() { return now; } }; "
                "const fmt = vm.runInNewContext("
                "'(function () {\\n' + source + "
                "'\\n; return fmt; })()', { Date: FixedDate }); "
                f"if (fmt.age(Date.parse({before_iso!r}) / 1000) !== '1h ago') "
                "process.exit(1);"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert ui_result.returncode == 0, ui_result.stderr or ui_result.stdout
