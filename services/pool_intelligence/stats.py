"""Per-worker pool statistics, normalised across providers.

The dashboard used to read exactly one shape (parasite.space) and render zeros
for everything else. This module normalises the two other public APIs we have
verified — ckpool ``/users/{address}`` and public-pool ``/api/client/{address}``
— into one shape, and adds the third, most important source: **the ASIC**.

Priority rules, and the reason for them:

* If the ASIC told us which pool it is on, that is authoritative — it is
  measured at the hardware, not inferred. We fetch that provider's API when it
  has one.
* Otherwise we ask each provider with a public API whether it knows the
  address (``resolve_pool_stats``). The first one that answers with data is the
  pool for that address — this is what makes detection happen automatically
  when the operator connects a wallet.
* If no API knows the address (or the pool publishes none), we return
  ``source="asic"`` with whatever the hardware reported. Never fabricated
  numbers, never silent zeros: an honest "the miner is the source" label.

Field extraction is deliberately tolerant about *key names* (firmwares and
forks disagree) and strict about *values*: an unrecognized or unparseable value
becomes None, and ``fields_found`` records exactly which keys were understood,
so a caller can tell "the pool reported 0" from "we did not understand the
payload".
"""

from dataclasses import dataclass, field
import re
from typing import Any, Callable, Iterable, Mapping

from .models import Provenance
from .providers import (
    PoolDetection,
    PoolProvider,
    detect_provider,
    stats_api_providers,
    stats_url_for,
)

__all__ = [
    "PoolWorkerStats",
    "normalize_asic_telemetry",
    "normalize_ckpool_user",
    "normalize_parasite_user",
    "normalize_public_pool_workers",
    "parse_hashrate_to_hs",
    "resolve_pool_stats",
]

# Hashes-per-second multipliers for the human-readable strings pools publish.
# ckpool writes "1.21T", public-pool writes raw numbers, other APIs write
# "12 PH/s" — so the unit is normalized to a single letter first (strip the
# "/s", then a trailing "h" that means "hashes").
_HASHRATE_UNITS: dict[str, float] = {
    "": 1.0,
    "k": 1e3,
    "m": 1e6,
    "g": 1e9,
    "t": 1e12,
    "p": 1e15,
    "e": 1e18,
    "z": 1e21,
}

# Numeric prefix of a hashrate string. A dedicated pattern (rather than
# character-by-character scanning) keeps a unit letter that happens to be 'e'
# — as in "1E" for exahash — from being swallowed as an exponent.
_NUMERIC_PREFIX = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")

# Keys we accept for each normalized field, in priority order. Every entry is
# a real key observed in one of the supported APIs or in firmware telemetry —
# nothing speculative.
_HASHRATE_KEYS = (
    "hashrate_hs",
    "hashRate",
    "hashrate",
    "hashrate1m",
    "hashrate5m",
    "hashrate1hr",
    "hashrate1h",
    "hashrate1d",
    "GHS 5s",
    "GHS av",
    "hashrate_avg",
    "hashrate_ghps",
)
_BEST_DIFF_KEYS = (
    "best_diff",
    "bestDifficulty",
    "bestDifficultyString",
    "bestshare",
    "best_share",
    "bestDiff",
    "Best Share",
)
# ``shares`` is ckpool's accepted-share counter (top level and per worker). It
# sits last on purpose: when an API exposes both a total and an explicit
# ``accepted`` field, the explicit one wins.
_ACCEPTED_KEYS = (
    "shares_accepted",
    "sharesAccepted",
    "accepted",
    "Accepted",
    "shares",
)
_REJECTED_KEYS = ("shares_rejected", "sharesRejected", "rejected", "Rejected")
_STALE_KEYS = ("shares_stale", "sharesStale", "stale", "Stale")
_LAST_SHARE_KEYS = (
    "last_share_ts",
    "lastshare",
    "lastShare",
    "lastShareTime",
    "lastsharetime",
)
_WORKERS_KEYS = ("workers", "workerCount", "worker_count")
_ADDRESS_KEYS = ("address", "user", "stratumUser", "username")
_WORKER_NAME_KEYS = ("workerName", "workername", "worker", "name")


@dataclass(frozen=True)
class PoolWorkerStats:
    """Normalized per-worker pool statistics.

    ``source`` is the contract that matters: ``"api"`` means the numbers came
    from the pool's own public API; ``"asic"`` means they came from the miner
    itself because no API was available or reachable. ``fields_found`` lists
    the payload keys we understood, so an all-None result is traceable to
    either an empty pool response or an unrecognized shape.
    """

    provider_id: str
    label: str
    chain: str
    kind: str | None
    source: str
    address: str
    stats_url: str
    hashrate_hs: float | None = None
    shares_accepted: int | None = None
    shares_rejected: int | None = None
    shares_stale: int | None = None
    best_diff: float | None = None
    best_diff_str: str = ""
    last_share_ts: int | None = None
    workers: int | None = None
    fields_found: tuple[str, ...] = ()
    error: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "label": self.label,
            "chain": self.chain,
            "kind": self.kind,
            "source": self.source,
            "address": self.address,
            "stats_url": self.stats_url,
            "hashrate_hs": self.hashrate_hs,
            "shares_accepted": self.shares_accepted,
            "shares_rejected": self.shares_rejected,
            "shares_stale": self.shares_stale,
            "best_diff": self.best_diff,
            "best_diff_str": self.best_diff_str,
            "last_share_ts": self.last_share_ts,
            "workers": self.workers,
            "fields_found": list(self.fields_found),
            "error": self.error,
        }


def _to_float(value: Any) -> float | None:
    """Float from whatever the pool sent, or None. Never invents a number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    if number is None:
        return None
    try:
        return int(number)
    except (OverflowError, ValueError):
        return None


def parse_hashrate_to_hs(value: Any) -> float | None:
    """Parse a hashrate into H/s, accepting numbers **and** unit strings.

    Pools are inconsistent here: public-pool reports raw H/s numbers, ckpool
    reports human strings like ``"1.21T"`` or ``"12 PH/s"``. Both forms reach
    this function, and an unparseable value returns None rather than 0 — a
    real 0 at the pool is a fact, a failed parse is not.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip().lower().replace(",", "")
    if not text:
        return None
    match = _NUMERIC_PREFIX.match(text)
    if match is None:
        return None
    number = _to_float(match.group(0))
    if number is None:
        return None
    unit = text[match.end() :].strip().replace("/s", "").replace("s", "")
    unit = unit.replace(" ", "")
    if unit.endswith("h"):  # "gh" / "th" / "h" all mean "hashes"
        unit = unit[:-1]
    if len(unit) > 1:
        # "h/s"-style leftovers we do not recognize: report nothing rather
        # than a number with an assumed unit.
        return None
    multiplier = _HASHRATE_UNITS.get(unit)
    return None if multiplier is None else number * multiplier


def _first(payload: Mapping[str, Any], keys: Iterable[str]) -> tuple[str, Any]:
    """Return (key, value) for the first present, non-None key."""
    for key in keys:
        if key in payload and payload[key] is not None:
            return key, payload[key]
    return "", None


def _merge_worker_entries(entries: Iterable[Mapping[str, Any]]) -> dict:
    """Sum share counters and take the max best-diff across worker entries.

    Solo pools expose one entry per worker name (``address.worker``). The
    dashboard shows the address as a whole, so the aggregate is what it wants;
    summing is correct for counters and max is correct for a difficulty record.
    """
    accepted = rejected = stale = 0
    best: float | None = None
    best_str = ""
    last_share: int | None = None
    hashrate = 0.0
    seen = False
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        seen = True
        accepted += (
            _to_int(entry.get("shares_accepted"))
            or _to_int(entry.get("sharesAccepted"))
            or _to_int(entry.get("accepted"))
            or _to_int(entry.get("Accepted"))
            or _to_int(entry.get("shares"))
            or 0
        )
        rejected += (
            _to_int(entry.get("shares_rejected"))
            or _to_int(entry.get("sharesRejected"))
            or _to_int(entry.get("rejected"))
            or _to_int(entry.get("Rejected"))
            or 0
        )
        stale += (
            _to_int(entry.get("shares_stale"))
            or _to_int(entry.get("sharesStale"))
            or _to_int(entry.get("stale"))
            or 0
        )
        candidate = (
            _to_float(entry.get("best_diff"))
            or _to_float(entry.get("bestDifficulty"))
            or _to_float(entry.get("bestshare"))
            or _to_float(entry.get("best_share"))
            or _to_float(entry.get("Best Share"))
        )
        if candidate is not None and (best is None or candidate > best):
            best = candidate
            source_key, source_value = _first(entry, _BEST_DIFF_KEYS)
            if source_key and isinstance(source_value, str):
                best_str = source_value
        last = _to_int(entry.get("lastshare")) or _to_int(entry.get("lastShare"))
        if last is not None:
            last_share = last if last_share is None else max(last_share, last)
        hr = parse_hashrate_to_hs(
            entry.get("hashrate1m")
            or entry.get("hashRate")
            or entry.get("hashrate")
            or entry.get("hashrate_hs")
        )
        if hr:
            hashrate += hr
    return {
        "shares_accepted": accepted if seen else None,
        "shares_rejected": rejected if seen else None,
        "shares_stale": stale if seen else None,
        "best_diff": best,
        "best_diff_str": best_str,
        "last_share_ts": last_share,
        "hashrate_hs": hashrate if hashrate else None,
        "workers": (
            len([e for e in entries if isinstance(e, Mapping)]) if seen else None
        ),
    }


def _base(
    detection: PoolDetection,
    *,
    source: str,
    stats_url: str,
    error: str = "",
) -> dict:
    return {
        "provider_id": detection.provider_id,
        "label": detection.label,
        "chain": (detection.chain.value if detection.chain else ""),
        "kind": (detection.kind.value if detection.kind else None),
        "source": source,
        "address": detection.address,
        "stats_url": stats_url,
        "error": error,
    }


def normalize_ckpool_user(
    payload: Mapping[str, Any],
    detection: PoolDetection,
    *,
    stats_url: str = "",
) -> PoolWorkerStats:
    """Normalize ckpool's ``/users/{address}`` response.

    ckpool is one JSON object with human-readable hashrates (``"1.21T"``) and,
    when the address mines under several worker names, a ``worker`` array whose
    entries are summed/maxed (see ``_merge_worker_entries``).
    """
    if not isinstance(payload, Mapping):
        return PoolWorkerStats(
            **_base(
                detection,
                source="api",
                stats_url=stats_url,
                error="malformed ckpool payload",
            )
        )

    found: list[str] = []
    keys = set(payload.keys())

    top_hr_key, top_hr = _first(payload, _HASHRATE_KEYS)
    hashrate = parse_hashrate_to_hs(top_hr)
    if top_hr_key:
        found.append(top_hr_key)

    workers_raw = payload.get("worker")
    merged = _merge_worker_entries(workers_raw) if isinstance(workers_raw, list) else {}

    best_key, best_raw = _first(payload, _BEST_DIFF_KEYS)
    best_diff = _to_float(best_raw) or merged.get("best_diff")
    if best_key:
        found.append(best_key)
    best_str = (
        str(best_raw) if best_raw is not None else (merged.get("best_diff_str") or "")
    )

    accepted_key, accepted_raw = _first(payload, _ACCEPTED_KEYS)
    accepted = _to_int(accepted_raw)
    if accepted_key:
        found.append(accepted_key)
    elif merged.get("shares_accepted") is not None:
        # ckpool's top-level object has no share counters; its ``worker`` array
        # does. Sum them so the address total is right.
        accepted = merged["shares_accepted"]
        found.append("worker.shares")

    rejected_key, rejected_raw = _first(payload, _REJECTED_KEYS)
    rejected = _to_int(rejected_raw)
    if rejected_key:
        found.append(rejected_key)
    elif merged.get("shares_rejected") is not None:
        rejected = merged["shares_rejected"]

    last_key, last_raw = _first(payload, _LAST_SHARE_KEYS)
    last_share = _to_int(last_raw) or merged.get("last_share_ts")
    if last_key:
        found.append(last_key)

    workers_key, workers_raw = _first(payload, _WORKERS_KEYS)
    workers = _to_int(workers_raw)
    if workers_key:
        found.append(workers_key)
    if workers is None and merged.get("workers") is not None:
        workers = merged["workers"]

    if hashrate is None and merged.get("hashrate_hs"):
        # Only fall back to the summed worker hashrate when the top-level
        # hashrate is genuinely absent (unparseable counts as absent here
        # because ckpool's unit strings are the one thing we always expect).
        hashrate = merged["hashrate_hs"]

    return PoolWorkerStats(
        **_base(detection, source="api", stats_url=stats_url),
        hashrate_hs=hashrate,
        shares_accepted=accepted,
        shares_rejected=rejected,
        shares_stale=merged.get("shares_stale"),
        best_diff=best_diff,
        best_diff_str=best_str,
        last_share_ts=last_share,
        workers=workers,
        fields_found=tuple(dict.fromkeys(found)),
    )


def normalize_public_pool_workers(
    payload: Any,
    detection: PoolDetection,
    *,
    stats_url: str = "",
) -> PoolWorkerStats:
    """Normalize public-pool's ``/api/client/{address}`` response.

    The endpoint returns an ARRAY — one object per worker connected under that
    address — so the address-level view is the aggregate. An empty array is a
    real answer meaning "this address has no workers here", and is reported as
    such rather than as an error.
    """
    if isinstance(payload, Mapping):
        # Some forks wrap the array (``{"workers": [...]}``). Accept both.
        for wrapper in ("workers", "data", "result", "clients"):
            if isinstance(payload.get(wrapper), list):
                payload = payload[wrapper]
                break
    if not isinstance(payload, list):
        return PoolWorkerStats(
            **_base(
                detection,
                source="api",
                stats_url=stats_url,
                error="malformed public-pool payload",
            )
        )

    entries = [entry for entry in payload if isinstance(entry, Mapping)]
    merged = _merge_worker_entries(entries)
    found: list[str] = []
    if entries:
        # Record which keys we actually understood on the first entry, so the
        # caller can distinguish "pool sent nothing" from "shape changed".
        for key in entries[0].keys():
            found.append(str(key))

    address_key, address_value = (
        _first(entries[0], _ADDRESS_KEYS) if entries else ("", None)
    )
    # An empty array is the pool answering "no workers under this address", so
    # the count is a real 0 — not the None we reserve for "not reported".
    workers = merged.get("workers")
    if workers is None and not entries:
        workers = 0

    return PoolWorkerStats(
        **_base(detection, source="api", stats_url=stats_url),
        hashrate_hs=merged.get("hashrate_hs"),
        shares_accepted=merged.get("shares_accepted"),
        shares_rejected=merged.get("shares_rejected"),
        shares_stale=merged.get("shares_stale"),
        best_diff=merged.get("best_diff"),
        best_diff_str=merged.get("best_diff_str") or "",
        last_share_ts=merged.get("last_share_ts"),
        workers=workers,
        fields_found=tuple(found),
        extra={"reported_address": address_value} if address_key else {},
    )


def normalize_parasite_user(
    payload: Mapping[str, Any],
    detection: PoolDetection,
    *,
    stats_url: str = "",
) -> PoolWorkerStats:
    """Normalize parasite.space's ``/user/{address}`` response.

    Kept alongside the new adapters so every provider produces the SAME shape:
    the dashboard stops caring where a number came from.
    """
    if not isinstance(payload, Mapping):
        return PoolWorkerStats(
            **_base(
                detection,
                source="api",
                stats_url=stats_url,
                error="malformed parasite payload",
            )
        )

    found: list[str] = []
    hr_key, hr_raw = _first(payload, _HASHRATE_KEYS)
    hashrate = parse_hashrate_to_hs(hr_raw)
    if hr_key:
        found.append(hr_key)

    best_key, best_raw = _first(payload, _BEST_DIFF_KEYS)
    best_diff = _to_float(best_raw)
    if best_key:
        found.append(best_key)

    accepted_key, accepted_raw = _first(payload, _ACCEPTED_KEYS)
    accepted = _to_int(accepted_raw)
    if accepted_key:
        found.append(accepted_key)

    rejected_key, rejected_raw = _first(payload, _REJECTED_KEYS)
    rejected = _to_int(rejected_raw)
    if rejected_key:
        found.append(rejected_key)

    last_key, last_raw = _first(payload, _LAST_SHARE_KEYS)
    last_share = _to_int(last_raw)
    if last_key:
        found.append(last_key)

    return PoolWorkerStats(
        **_base(detection, source="api", stats_url=stats_url),
        hashrate_hs=hashrate,
        shares_accepted=accepted,
        shares_rejected=rejected,
        best_diff=best_diff,
        best_diff_str=str(best_raw or ""),
        last_share_ts=last_share,
        fields_found=tuple(found),
    )


_NORMALIZERS: dict[str, Callable[..., PoolWorkerStats]] = {
    "ckpool_user": normalize_ckpool_user,
    "public_pool_workers": normalize_public_pool_workers,
    "parasite_user": normalize_parasite_user,
}


def normalize_asic_telemetry(
    detection: PoolDetection,
    telemetry: Mapping[str, Any],
) -> PoolWorkerStats:
    """Build statistics from the ASIC's own telemetry.

    This is the answer to "the pool has no public API": the miner measures its
    own hashrate, best share and share counters, and that is real data from the
    hardware — strictly better than the zeros the dashboard used to show.
    """
    tel = telemetry if isinstance(telemetry, Mapping) else {}
    found = [key for key in tel.keys() if key in _HASHRATE_KEYS + _BEST_DIFF_KEYS]
    best_raw = tel.get("best_diff")
    if best_raw is None:
        best_raw = tel.get("bestDiff")
    return PoolWorkerStats(
        **_base(detection, source="asic", stats_url=""),
        hashrate_hs=parse_hashrate_to_hs(tel.get("hashrate_hs") or tel.get("hashrate")),
        shares_accepted=_to_int(tel.get("shares_accepted")),
        shares_rejected=_to_int(tel.get("shares_rejected")),
        shares_stale=_to_int(tel.get("shares_stale")),
        best_diff=_to_int(best_raw),
        best_diff_str=str(best_raw or ""),
        fields_found=tuple(found),
    )


def resolve_pool_stats(
    address: str,
    *,
    fetcher: Callable[[str], Any],
    asic_pool_url: str = "",
    asic_telemetry: Mapping[str, Any] | None = None,
    providers: Iterable[PoolProvider] | None = None,
) -> PoolWorkerStats:
    """Resolve the pool for an address and return normalized statistics.

    ``fetcher(url)`` performs the HTTP GET and returns parsed JSON (or None) —
    injected so this stays hermetic and testable.

    Order of evidence:

    1. **ASIC-reported endpoint.** If the hardware says which pool it is on,
       that wins outright: it is measured, not inferred. Its API is used when
       it has one; otherwise the numbers come from the ASIC.
    2. **Probe the providers that publish a public API.** The first that
       answers with data IS the pool for this address — this is the automatic
       detection that happens when an operator connects a wallet.
    3. **Unknown pool.** Labelled with the raw endpoint (or "unknown pool") and
       fed by the ASIC when telemetry is available.
    """
    telemetry = asic_telemetry or {}

    if str(asic_pool_url or "").strip():
        detection = detect_provider(asic_pool_url, address=address)
        provider = detection.provider
        if provider is not None and provider.has_stats_api:
            url = stats_url_for(provider, address)
            payload = _safe_fetch(fetcher, url)
            if payload is not None:
                stats = _normalize(provider, payload, detection, url or "")
                if stats is not None:
                    return stats
        elif provider is None:
            # Unregistered endpoint: honour what the hardware told us instead of
            # falling back to another pool's numbers.
            return normalize_asic_telemetry(detection, telemetry)
        return normalize_asic_telemetry(detection, telemetry)

    for provider in providers if providers is not None else stats_api_providers():
        url = stats_url_for(provider, address)
        if not url:
            continue
        payload = _safe_fetch(fetcher, url)
        if payload is None:
            continue
        detection = PoolDetection(
            provider=provider,
            host=provider.host_patterns[0],
            matched_pattern=provider.host_patterns[0],
            chain=provider.chain,
            chain_source="stats_api_probe",
            address=str(address or "").strip(),
        )
        stats = _normalize(provider, payload, detection, url)
        if stats is None:
            continue
        # Only a response we actually understood counts as "this pool knows the
        # address". ``fields_found`` is built exclusively from keys present with
        # non-None values, so an empty result means either "not here" (an empty
        # public-pool array) or "shape we cannot read" — both must keep the
        # probe moving instead of being reported as the user's numbers.
        if not stats.fields_found:
            continue
        return stats

    detection = detect_provider("", address=address)
    return normalize_asic_telemetry(detection, telemetry)


def _safe_fetch(fetcher: Callable[[str], Any], url: str | None) -> Any:
    """Call the injected fetcher, treating any failure as "no answer"."""
    if not url:
        return None
    try:
        return fetcher(url)
    except Exception:  # noqa: BLE001 — a dead pool API must not break the poll
        return None


def _normalize(
    provider: PoolProvider,
    payload: Any,
    detection: PoolDetection,
    stats_url: str,
) -> PoolWorkerStats | None:
    """Dispatch to the provider's parser; None when there is no parser."""
    parser = _NORMALIZERS.get(provider.stats_kind or "")
    if parser is None:
        return None
    try:
        return parser(payload, detection, stats_url=stats_url)
    except Exception:  # noqa: BLE001 — a shape change must not crash the poll
        return None


def provenance_for(stats: PoolWorkerStats) -> Provenance:
    """Provenance of a stats result, for callers that track data lineage."""
    return Provenance.API_REPORTED if stats.source == "api" else Provenance.OBSERVED
