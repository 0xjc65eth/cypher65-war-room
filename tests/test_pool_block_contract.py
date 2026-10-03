import pytest
from helpers import pool_last_block


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"lastBlockTime": 958527}, (958527, None)),
        (
            {"lastBlockHeight": 958527, "lastBlockTime": 1799999940},
            (958527, 1799999940),
        ),
        (
            {"lastBlockHeight": 958527, "lastBlockTime": 1799999940000},
            (958527, 1799999940),
        ),
        ({"lastBlockTime": 1799999940}, (None, 1799999940)),
        ({"lastBlockTimestamp": 1800000001}, (None, None)),
        ({"lastBlockTimestamp": float("inf")}, (None, None)),
        ({"lastBlockHeight": True, "lastBlockTime": False}, (None, None)),
        ({"lastBlockHeight": -1, "lastBlockTime": "bad"}, (None, None)),
        ({}, (None, None)),
        (None, (None, None)),
    ],
)
def test_pool_block_contract(payload, expected):
    assert pool_last_block(payload, now=1800000000) == expected
