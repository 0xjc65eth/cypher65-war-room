"""Evidence oracle for local miner-to-Fleet simulator runs.

This intentionally compares only fields with explicit source/schema units and
our source-derived virtual ground truth. It cannot certify physical accuracy.
"""

from __future__ import annotations


_FIELDS = (
    "ip_address",
    "model",
    "mac_address",
    "hashrate_hs",
    "shares_accepted",
    "uptime_seconds",
)


def assert_fleet_matches_ground_truth(expected: dict, observed: dict) -> None:
    """Raise with the first field mismatch; never use loose unit tolerances."""
    for field in _FIELDS:
        want = expected.get(field)
        got = observed.get(field)
        if got != want:
            raise AssertionError(
                f"Fleet {field} mismatch: expected {want!r}, observed {got!r}"
            )
