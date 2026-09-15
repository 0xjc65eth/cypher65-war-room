"""Bind the pool registry to what the hardware actually reports (Issue #574).

``services.pool_intelligence`` knows how to recognise a pool from a stratum
endpoint and how to read its statistics. What it cannot know is *which* pool a
given operator is on — that fact lives in fleet telemetry, where every ASIC
reports its own ``stratumURL``/``stratumUser`` (written by the local agent or by
the server-side poll).

This module is the glue. On each snapshot it:

1. reads the newest pool report for the tenant out of fleet telemetry,
2. turns it into a detected provider,
3. resolves that provider's statistics — from the pool's public API when it has
   one, and from the ASIC's own telemetry when it does not.

Two properties are deliberate:

* **No network request on its own initiative.** With no ASIC reporting a pool
  this returns ``{}`` immediately. Probing the registry's public APIs is an
  explicit, on-demand path (``/api/pool/resolve``, wallet connect) — a 15s
  background poll must not start fanning out to a dozen pool APIs.
* **Never raises.** Detection is enrichment; a missing table, a locked DB or a
  dead pool API degrades to ``{}`` and the snapshot is built exactly as before.
"""

import json
import logging
import threading
import time
from typing import Any, Callable, Mapping

log = logging.getLogger("cypher65.pool_detection")

# How many recent telemetry rows to scan for a pool report. A pool URL only
# changes when the operator reprovisions a miner, so a handful of rows is
# plenty, and the window is bounded on purpose: this runs on every poll.
ASIC_POOL_LOOKBACK = 50

# Cache TTLs (seconds). The ASIC report changes only on reprovisioning; the
# pool statistics move slowly enough that a poll every 15s must not translate
# into a request every 15s.
REPORT_TTL = 60
STATS_TTL = 60

_LOCK = threading.Lock()
_REPORT_CACHE: dict[str, tuple[float, dict]] = {}
_STATS_CACHE: dict[tuple[str, str, str], tuple[float, dict]] = {}


def _default_get_db() -> Callable[[], Any]:
    """The app's ``get_db`` callable. Imported lazily to avoid a cycle."""
    from services.db import get_db

    return get_db


def _row_get(row: Any, key: str, index: int = 0) -> Any:
    """Read a column from a DB row, whichever row type the connection yields.

    The repo configures ``sqlite3.Row``, but tests (and the Postgres readiness
    path) hand back plain tuples, and a lookup that only works for one of them
    would silently return "" instead of the pool URL.
    """
    try:
        return row[key]
    except (TypeError, IndexError, KeyError):
        try:
            return row[index]
        except (TypeError, IndexError, KeyError):
            return None


def clear_cache() -> None:
    """Drop both caches. Used by tests and after a device reprovision."""
    with _LOCK:
        _REPORT_CACHE.clear()
        _STATS_CACHE.clear()


def asic_pool_report(
    tenant_id: str = "",
    *,
    get_db: Callable[[], Any] | None = None,
    now: float | None = None,
) -> dict:
    """Latest ASIC-reported pool for a tenant, with that device's telemetry.

    Returns ``{"pool_url", "pool_user", "telemetry", "device_id"}``, or ``{}``
    when no ASIC has reported a pool. Tenant-scoped: telemetry rows carry their
    own ``tenant_id``, so one tenant can never read another's miner.

    Cached for ``REPORT_TTL`` — this runs on every poll.
    """
    tid = str(tenant_id or "").strip() or "default"
    timestamp = time.time() if now is None else now

    with _LOCK:
        cached = _REPORT_CACHE.get(tid)
        if cached is not None and timestamp - cached[0] < REPORT_TTL:
            return dict(cached[1])

    report: dict = {}
    try:
        get_db_callable = get_db or _default_get_db()
        report = _read_latest_report(get_db_callable, tid)
    except Exception as e:  # noqa: BLE001 — no fleet table is a normal state
        log.debug("[pool_detection] no ASIC pool report for tenant %s: %s", tid, e)
        report = {}

    with _LOCK:
        _REPORT_CACHE[tid] = (timestamp, dict(report))
    return dict(report)


def _read_latest_report(get_db: Callable[[], Any], tenant_id: str) -> dict:
    """Scan the newest telemetry rows for one that carries a pool URL."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT device_id, payload FROM axe_telemetry "
            "WHERE tenant_id=? ORDER BY ts DESC LIMIT ?",
            (tenant_id, ASIC_POOL_LOOKBACK),
        )
        rows = cursor.fetchall()
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 — closing must never mask the result
            pass

    for row in rows:
        raw = _row_get(row, "payload", 1)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(payload, Mapping):
            continue
        pool_url = str(payload.get("pool_url") or "").strip()
        if not pool_url:
            continue
        # The whole payload travels with the report: it is the source of the
        # numbers for pools that publish no public API.
        return {
            "pool_url": pool_url,
            "pool_user": str(payload.get("pool_user") or "").strip(),
            "telemetry": dict(payload),
            "device_id": str(_row_get(row, "device_id", 0) or ""),
        }
    return {}


def detected_pool_for(
    address: str,
    tenant_id: str = "",
    *,
    get_db: Callable[[], Any] | None = None,
    fetcher: Callable[[str], Any] | None = None,
    now: float | None = None,
) -> dict:
    """Detected pool + normalized statistics for ``address``, or ``{}``.

    ``{}`` means "nothing to report" — no ASIC has told us which pool it is on.
    It does NOT mean the pool is unknown: when an ASIC HAS reported one, a
    result is always produced, with ``stats["source"]`` saying whether the
    numbers came from the pool's API (``"api"``) or from the miner itself
    (``"asic"``).

    Cached per (address, tenant, pool) for ``STATS_TTL`` — except when the pool
    publishes a stats API and that API did not answer. That case is reported (the
    numbers are the miner's own, which is real) but deliberately NOT cached, so
    the next poll retries instead of serving ASIC figures for a whole minute.
    """
    report = asic_pool_report(tenant_id, get_db=get_db, now=now)
    pool_url = str(report.get("pool_url") or "")
    if not pool_url:
        return {}

    tid = str(tenant_id or "").strip() or "default"
    key = (str(address or "").strip(), tid, pool_url)
    timestamp = time.time() if now is None else now

    with _LOCK:
        cached = _STATS_CACHE.get(key)
        if cached is not None and timestamp - cached[0] < STATS_TTL:
            return dict(cached[1])

    result = _resolve(address, pool_url, report, fetcher)
    if not result:
        # Do not cache a failure: the next poll should retry.
        return {}
    if _is_api_miss(result):
        return dict(result)

    with _LOCK:
        _STATS_CACHE[key] = (timestamp, dict(result))
    return dict(result)


def attach_to_snapshot(
    snapshot: dict,
    address: str,
    tenant_id: str = "",
    *,
    get_db: Callable[[], Any] | None = None,
    fetcher: Callable[[str], Any] | None = None,
    now: float | None = None,
) -> dict:
    """Write ``pool_detection``/``pool_worker`` into ``snapshot``, in place.

    **The single place that writes these two keys.** Every producer of a
    snapshot dict calls this — the per-session builder
    (``services.snapshot_assembly._build_snapshot``, served by
    ``/api/session-snapshot`` and ``POST /api/connect-wallet``) and the global
    poll (``app._do_poll``, served by ``/api/snapshot``, which is the route the
    dashboard actually polls).

    Why the explicitness: before this existed, the wiring lived inside the
    session builder only. The dashboard's own ``/api/snapshot`` builds its dict
    elsewhere, so production served a payload without the keys, the pure view
    returned ``None`` and the panel stayed hidden — a feature that passed every
    test (the session builder had the keys; the e2e injected them) and did
    nothing live.

    Both keys are always present afterwards, ``None`` when nothing was
    reported, so the front never has to tell "absent" from "not applicable".
    Never raises: a dead DB, a missing table or a pool API failure leaves the
    snapshot exactly as it was.
    """
    snapshot.setdefault("pool_detection", None)
    snapshot.setdefault("pool_worker", None)
    try:
        detected = detected_pool_for(
            address, tenant_id, get_db=get_db, fetcher=fetcher, now=now
        )
    except Exception as e:  # noqa: BLE001 — enrichment must never break a poll
        log.warning(
            "[pool_detection] attach failed for %s: %s", str(address or "")[:8], e
        )
        return snapshot
    if detected:
        snapshot["pool_detection"] = detected.get("detection") or None
        snapshot["pool_worker"] = detected.get("stats") or None
    return snapshot


def _is_api_miss(result: Mapping[str, Any]) -> bool:
    """True when a pool that HAS a public API fell back to the miner's numbers.

    ``source: "asic"`` is terminal truth for a ``stratum_only`` pool — there is
    no API to retry. For a pool that does publish one, it means the request
    failed, and that distinction is exactly what keeps a transient pool-API blip
    from freezing the panel on ASIC figures for the whole TTL.
    """
    detection = result.get("detection") or {}
    stats = result.get("stats") or {}
    return bool(detection.get("has_stats_api")) and stats.get("source") == "asic"


def _resolve(
    address: str,
    pool_url: str,
    report: Mapping[str, Any],
    fetcher: Callable[[str], Any] | None,
) -> dict:
    """Detection + statistics for an ASIC-reported endpoint. Never raises."""
    try:
        from services.pool_intelligence import detect_provider, resolve_pool_stats

        detection = detect_provider(pool_url, address=address)
        stats = resolve_pool_stats(
            address,
            fetcher=fetcher or _default_fetcher,
            asic_pool_url=pool_url,
            asic_telemetry=report.get("telemetry") or {},
        )
    except Exception as e:  # noqa: BLE001 — enrichment must never break a poll
        log.warning("[pool_detection] resolution failed for %s: %s", pool_url, e)
        return {}
    return {
        "detection": detection.to_dict(),
        "stats": stats.to_dict(),
        "asic_pool_user": str(report.get("pool_user") or ""),
        "device_id": str(report.get("device_id") or ""),
    }


def _default_fetcher(url: str) -> Any:
    """Single-attempt JSON GET, mirroring app._pool_stats_fetcher.

    Kept here (rather than importing it from ``app``) so the polling path does
    not depend on the Flask module. One attempt and no retries: the poll runs
    every 15s, so a slow pool API must not stack up behind the poll loop.
    """
    import requests

    response = requests.get(
        url, timeout=6, headers={"User-Agent": "cypher65-war-room/1.0"}
    )
    response.raise_for_status()
    return response.json()
