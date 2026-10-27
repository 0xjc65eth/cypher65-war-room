"""Hermetic regressions for the shared pool/ASIC numeric boundary (Issue #881)."""

import json
import math

import pytest
from hypothesis import given, settings, strategies as st

from services.pool_intelligence import (
    detect_provider,
    normalize_asic_telemetry,
    normalize_ckpool_user,
    normalize_parasite_user,
    normalize_public_pool_workers,
    parse_hashrate_to_hs,
    resolve_pool_stats,
)

INVALID = [
    float("nan"),
    float("inf"),
    -float("inf"),
    -1,
    "-1",
    "nan",
    "inf",
    "1e309",
    10**400,
]


@pytest.mark.parametrize(
    "value",
    INVALID,
    ids=[
        "nan",
        "inf",
        "-inf",
        "negative",
        "negative-str",
        "nan-str",
        "inf-str",
        "overflow-str",
        "huge-int",
    ],
)
def test_invalid_hashrate_is_unavailable(value):
    assert parse_hashrate_to_hs(value) is None


@pytest.mark.parametrize("value", ["1e308T", "1e308 EH/s"])
def test_scaling_overflow_is_unavailable(value):
    assert parse_hashrate_to_hs(value) is None


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, 0),
        ("0 TH/s", 0),
        ("1.25 TH/s", 1.25e12),
        ("1E", 1e18),
        ("1e3", 1000),
        (5e-324, 5e-324),
    ],
)
def test_finite_supported_hashrate_stays_compatible(value, expected):
    assert parse_hashrate_to_hs(value) == expected


def normalize(source, payload):
    """Exercise production entrypoints without HTTP, DNS or real identities."""
    detection = detect_provider("solo.ckpool.org", address="synthetic-fixture")
    if source == "asic":
        return normalize_asic_telemetry(detection, payload)
    normalizer = {
        "ckpool": normalize_ckpool_user,
        "parasite": normalize_parasite_user,
        "public-pool": normalize_public_pool_workers,
    }[source]
    return normalizer([payload] if source == "public-pool" else payload, detection)


@pytest.mark.parametrize("source", ["asic", "ckpool", "parasite", "public-pool"])
@pytest.mark.parametrize(
    "value",
    INVALID,
    ids=[
        "nan",
        "inf",
        "-inf",
        "negative",
        "negative-str",
        "nan-str",
        "inf-str",
        "overflow-str",
        "huge-int",
    ],
)
def test_normalizers_emit_only_valid_numeric_metrics(source, value):
    result = normalize(
        source,
        {
            "hashrate_hs": value,
            "best_diff": value,
            "shares_accepted": value,
            "shares_rejected": value,
            "shares_stale": value,
            "lastshare": value,
            "workers": value,
        },
    ).to_dict()
    for field in (
        "hashrate_hs",
        "best_diff",
        "shares_accepted",
        "shares_rejected",
        "shares_stale",
        "last_share_ts",
    ):
        assert result[field] is None, (source, field, result[field])
    assert result["best_diff_str"] == ""
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("source", ["asic", "ckpool", "parasite", "public-pool"])
def test_real_zero_beats_conflicting_legacy_alias(source):
    result = normalize(
        source,
        {
            "hashrate_hs": 0,
            "hashrate": 999,
            "best_diff": 0,
            "bestDiff": 999,
            "shares_accepted": 0,
            "shares": 999,
            "shares_rejected": 0,
            "Rejected": 999,
            "shares_stale": 0,
            "Stale": 999,
            "last_share_ts": 0,
            "lastshare": 999,
        },
    ).to_dict()
    for field in ("hashrate_hs", "best_diff", "shares_accepted", "shares_rejected"):
        assert result[field] == 0, (source, field, result[field])
    assert result["best_diff_str"] == "0"


def test_worker_totals_do_not_fabricate_missing_metrics():
    result = normalize("public-pool", {"workerName": "fixture"})
    assert result.workers == 1
    assert result.hashrate_hs is None
    assert result.shares_accepted is None
    assert result.shares_rejected is None
    assert result.shares_stale is None


def test_worker_overflow_is_not_a_partial_or_infinite_total():
    result = normalize_public_pool_workers(
        [{"hashRate": 1e308}, {"hashRate": 1e308}, {"hashRate": 1}],
        detect_provider("public-pool.io", address="synthetic-fixture"),
    )
    assert result.hashrate_hs is None
    assert result.workers == 3
    json.dumps(result.to_dict(), allow_nan=False)


def test_incomplete_worker_totals_are_unavailable_not_partial():
    result = normalize_public_pool_workers(
        [{"hashRate": 2, "shares": 3}, {"workerName": "missing-metrics"}],
        detect_provider("public-pool.io", address="synthetic-fixture"),
    )
    assert result.hashrate_hs is None
    assert result.shares_accepted is None


def test_resolver_preserves_provider_and_safe_serializable_contract():
    calls = []

    def fetcher(url):
        calls.append(url)
        return {"hashrate1m": "1e308T", "bestshare": float("nan")}

    result = resolve_pool_stats(
        "synthetic-fixture", fetcher=fetcher, asic_pool_url="solo.ckpool.org"
    )
    assert len(calls) == 1
    assert result.source == "api"
    assert result.provider_id == "ckpool_solo"
    assert result.hashrate_hs is None
    assert result.best_diff is None
    assert result.best_diff_str == ""
    assert all(
        not isinstance(v, float) or math.isfinite(v) for v in result.to_dict().values()
    )
    json.dumps(result.to_dict(), allow_nan=False)


@given(st.floats(allow_nan=True, allow_infinity=True))
@settings(max_examples=200, derandomize=True)
def test_arbitrary_ieee_hashrates_never_escape_the_numeric_boundary(value):
    result = parse_hashrate_to_hs(value)
    if math.isfinite(value) and value >= 0:
        assert result == value
    else:
        assert result is None
    json.dumps({"hashrate_hs": result}, allow_nan=False)


def test_ckpool_top_level_zero_is_not_replaced_by_worker_records():
    result = normalize_ckpool_user(
        {
            "hashrate_hs": 0,
            "best_diff": 0,
            "last_share_ts": 0,
            "worker": [{"hashrate_hs": 99, "best_diff": 99, "lastshare": 99}],
        },
        detect_provider("solo.ckpool.org", address="synthetic-fixture"),
    )
    assert (result.hashrate_hs, result.best_diff, result.last_share_ts) == (0, 0, 0)
    assert result.best_diff_str == "0"


def test_ckpool_zero_worker_aggregate_is_available_when_top_level_is_missing():
    result = normalize_ckpool_user(
        {"worker": [{"hashrate_hs": 0, "shares": 0, "best_diff": 0}]},
        detect_provider("solo.ckpool.org", address="synthetic-fixture"),
    )
    assert result.hashrate_hs == 0
    assert result.shares_accepted == 0
    assert result.best_diff == 0
    assert result.best_diff_str == "0"


@pytest.mark.parametrize("source", ["asic", "ckpool", "parasite", "public-pool"])
def test_invalid_canonical_value_is_not_replaced_by_a_legacy_alias(source):
    result = normalize(source, {"hashrate_hs": float("nan"), "hashrate": 99})
    assert result.hashrate_hs is None


def test_snapshot_serializes_real_normalized_pool_metrics(monkeypatch):
    """Real Flask route/serializer; only unrelated snapshot inputs are stubbed."""
    from app import app

    stats = normalize("ckpool", {"hashrate_hs": "1e308T", "best_diff": float("nan")})
    monkeypatch.setattr(
        "services.state.latest_snapshot",
        {
            "ts": 1,
            "btc_address": "synthetic-fixture",
            "pool": {},
            "worker": {},
            "network": {},
            "pool_worker": stats.to_dict(),
            "pool_detection": None,
        },
    )
    monkeypatch.setattr(
        "services.snapshot_enrichment._get_hashrate_market_offers", lambda *_: []
    )
    monkeypatch.setattr(
        "services.hashrate_market.build_highlights", lambda *_a, **_kw: []
    )
    response = app.test_client().get("/api/snapshot")
    assert response.status_code == 200

    # A browser-compatible parser must not receive NaN/Infinity extensions.
    def reject_constant(value):
        raise AssertionError(f"Non-JSON numeric constant: {value}")

    payload = json.loads(response.data, parse_constant=reject_constant)
    assert payload["pool_worker"]["hashrate_hs"] is None
    assert payload["pool_worker"]["best_diff"] is None
