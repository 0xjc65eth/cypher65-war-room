"""Timezone invariants for persisted UTC instants and UTC reporting buckets.

TIME-001 (Issue #604): the backend stores event times as Unix seconds and must
not reinterpret them through the host's local timezone. The UI may localize
those instants for display; elapsed time and persisted values must stay stable.
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
                "from services.conversion import _iso_to_ts, _month_key; "
                f"ts = _iso_to_ts({iso_utc!r}); "
                f"assert ts == {expected_ts}, (ts, {zone!r}); "
                f"assert _month_key(ts) == {expected_month!r}, (ts, {zone!r})"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr or result.stdout
