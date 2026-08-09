"""
CYPHER65 // User Polling Worker
================================
Per-session polling instance. Each connected user gets one worker thread
that polls the Parasite API for their specific BTC address while sharing
global data (pool stats, network, BTC price) via a shared cache.

Architecture
------------
- UserPollingWorker is created per session when the user connects a wallet.
- It runs a background thread that polls every POLL_INTERVAL seconds.
- The worker references the SessionManager to store its snapshot.
- Global data (pool, network, BTC price) is cached in-memory and shared
  across all workers to avoid redundant API calls.
"""

import json
import time
import math
import random
import logging
import threading
import concurrent.futures
from typing import Any

import requests

from helpers import (
    parse_diff_to_float, fmt_diff, fmt_hashrate, fmt_uptime, fmt_age,
    safe_int, safe_num_from_str, coerce_float, coerce_int,
    human_int, human_secs_long, isfinite_v, make_memory_alert,
)
import services.names as _names
from services.settings import load_settings as _load_settings
from services.db import get_db as _get_db
from services.push_notifier import send_webhook_for_alert as _send_webhook_for_alert

log = logging.getLogger("cypher65.user_polling")

# ── Shared global data cache (thread-safe via Lock) ──────────────────────────
# Pool stats, network data, and BTC price are the same for ALL users.
# Bounded: per-ADDRESS keys (user_{addr}/acct_{addr}) grow with distinct
# wallets, so the cache is capped and evicted LRU-style to prevent a slow
# memory leak at 1000+ user scale. Fixed global keys (pool/network/price)
# are naturally few; the cap only prunes the long tail of stale addresses.
_global_cache: dict[str, Any] = {}
_GLOBAL_CACHE_MAX = 2048  # entries — beyond this, oldest are evicted
_global_lock = threading.Lock()
GLOBAL_CACHE_TTL = 15  # seconds — matches POLL_INTERVAL


def _update_global(key: str, value: Any):
    """Cache a value under key, evicting the oldest entry when over cap.

    The shared cache is a plain dict; when it exceeds _GLOBAL_CACHE_MAX the
    oldest key (insertion order) is dropped. Global fixed keys are few and
    constantly refreshed, so they always survive; per-address entries churn
    as workers come and go. Holds the lock for the whole operation (tiny)."""
    with _global_lock:
        if len(_global_cache) >= _GLOBAL_CACHE_MAX and key not in _global_cache:
            try:
                oldest = next(iter(_global_cache))
                del _global_cache[oldest]
            except StopIteration:
                pass
        _global_cache[key] = {"data": value, "ts": int(time.time())}

# ── Per-ADDRESS fetch cache (Phase: 1000+ user scale) ──────────────────────
# Two workers watching the SAME wallet (common: operator + tenant, or two
# tenants sharing a rig) must not double-hit Parasite /user+account. Cache
# the per-address fetches briefly (shorter than POLL_INTERVAL so a single
# worker still sees fresh data every cycle, but a burst of co-polling
# workers on the same address shares one fetch).
USER_FETCH_TTL = 10  # seconds — < POLL_INTERVAL(15): per-worker freshness preserved


def _cached_user_fetch(key: str, fetcher, *args):
    """Short-TTL per-address fetch dedup (address → data).

    Reuses the shared global cache so the same wallet polled by N workers in
    a 10s window results in ONE upstream request instead of N.
    """
    cached = _get_global(key, ttl=USER_FETCH_TTL)
    if cached is not None:
        return cached
    data = fetcher(*args)
    _update_global(key, data)
    return data


def _fire_webhook_async(webhook_kwargs: dict):
    """Fire a webhook POST on a daemon thread (fire-and-forget).

    The poll loop must never block on a slow/unreachable webhook endpoint
    (up to 5s POST timeout) — at 1000+ user scale that would stall every
    worker's 15s cycle. Tests patch this helper to run synchronously.
    """
    threading.Thread(
        target=_send_webhook_for_alert,
        kwargs=webhook_kwargs,
        daemon=True,
        name="cypher65-webhook",
    ).start()


def _get_global(key: str, ttl: int = GLOBAL_CACHE_TTL) -> Any:
    with _global_lock:
        entry = _global_cache.get(key)
        if entry and (int(time.time()) - entry["ts"]) < ttl:
            return entry["data"]
        return None


# ── API fetch helpers ────────────────────────────────────────────────────────
FETCH_MAX_RETRIES = 2
FETCH_BACKOFF_BASE = 1.5
PARASITE_API = "https://parasite.space/api"
MEMPOOL_API = "https://mempool.space/api"
BTC_PRICE_CACHE_TTL = 300  # 5 min for CoinGecko
btc_price_cache: dict = {"ts": 0, "data": None}


def _fetch_json(url: str, timeout: int = 10) -> Any:
    """Fetch JSON with retry + backoff."""
    last_err = None
    for attempt in range(FETCH_MAX_RETRIES + 1):
        try:
            r = requests.get(url, timeout=timeout,
                             headers={"User-Agent": "cypher65-war-room/1.0"})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            if attempt < FETCH_MAX_RETRIES:
                time.sleep(FETCH_BACKOFF_BASE * attempt)
    log.warning("[fetch] %s error: %s", url, last_err)
    return None


def _fetch_text(url: str, timeout: int = 8) -> str | None:
    """Fetch plain text with retry."""
    last_err = None
    for attempt in range(FETCH_MAX_RETRIES + 1):
        try:
            r = requests.get(url, timeout=timeout,
                             headers={"User-Agent": "cypher65-war-room/1.0"})
            r.raise_for_status()
            return r.text.strip()
        except Exception as e:
            last_err = e
            if attempt < FETCH_MAX_RETRIES:
                time.sleep(FETCH_BACKOFF_BASE * attempt)
    log.warning("[fetch_text] %s error: %s", url, last_err)
    return None


# ── Shared global fetchers (called once, cached) ────────────────────────────

def _fetch_global_pool() -> dict:
    """Pool stats — cached globally."""
    cached = _get_global("pool")
    if cached is not None:
        return cached
    data = _fetch_json(f"{PARASITE_API}/pool-stats", timeout=10) or {}
    _update_global("pool", data)
    return data


def _fetch_global_leaderboard(limit: int = 100) -> list:
    """Leaderboard — cached globally."""
    cached = _get_global("leaderboard")
    if cached is not None:
        return cached
    data = _fetch_json(f"{PARASITE_API}/leaderboard?limit={limit}",
                       timeout=10) or []
    _update_global("leaderboard", data)
    return data


def _fetch_global_highest_diffs(address: str, limit: int = 20) -> list:
    """High-diff events — slightly different per address, but the global
    endpoint returns pool-wide events. Cache per address for 60s."""
    cached = _get_global(f"hd_{address}", ttl=60)
    if cached is not None:
        return cached
    data = _fetch_json(
        f"{PARASITE_API}/highest-diff?type=user-diffs&address={address}&limit={limit}",
        timeout=10
    ) or []
    _update_global(f"hd_{address}", data)
    return data


def _fetch_global_network() -> tuple:
    """Network height, difficulty, hashrate — cached globally."""
    cached_diff = _get_global("net_diff", ttl=60)
    cached_hr = _get_global("net_hr", ttl=60)
    cached_height = _get_global("net_height", ttl=15)
    if cached_diff and cached_hr and cached_height:
        return cached_height, cached_diff, cached_hr

    # Fetch in parallel
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        fut_height = ex.submit(_fetch_json,
                               f"{MEMPOOL_API}/blocks/tip/height", 6)
        fut_diff = ex.submit(_fetch_text,
                             "https://blockchain.info/q/getdifficulty", 8)
        fut_hr = ex.submit(_fetch_text,
                           "https://blockchain.info/q/hashrate", 8)
        fut_fees = ex.submit(_fetch_json,
                             f"{MEMPOOL_API}/v1/fees/recommended", 6)

        results["height"] = fut_height.result()
        results["diff"] = fut_diff.result()
        results["hr"] = fut_hr.result()

        # Mempool fees are also global
        fees_raw = fut_fees.result()
        fees = {}
        if isinstance(fees_raw, dict):
            for k in ("fastestFee", "halfHourFee", "hourFee",
                      "minimumFee", "economyFee"):
                v = fees_raw.get(k)
                if isinstance(v, (int, float)):
                    fees[k] = v
        if not fees:
            fees = {"fastestFee": None, "halfHourFee": None,
                    "hourFee": None}
        _update_global("mempool_fees", fees)

    height = results["height"] if isinstance(results["height"], int) else None
    diff_val = safe_num_from_str(results["diff"])
    difficulty = float(diff_val) if diff_val else None
    hr_val = safe_num_from_str(results["hr"])
    hashrate = float(hr_val) * 1e9 if hr_val else None

    if difficulty and (hashrate is None or hashrate == 0):
        hashrate = difficulty * (2 ** 32) / 600

    _update_global("net_height", height)
    _update_global("net_diff", difficulty)
    _update_global("net_hr", hashrate)

    return height, difficulty, hashrate


def _fetch_global_btc_price() -> dict:
    """BTC price — cached for 5 min (CoinGecko rate limit)."""
    global btc_price_cache
    now = int(time.time())
    if now - btc_price_cache["ts"] < BTC_PRICE_CACHE_TTL \
       and btc_price_cache["data"]:
        return btc_price_cache["data"]

    quote = _fetch_json(
        "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&"
        "vs_currencies=usd,brl,eur,gbp,jpy,krw,cny",
        timeout=6
    )
    if isinstance(quote, dict) and quote.get("bitcoin"):
        btc_price_cache["data"] = quote
        btc_price_cache["ts"] = now
        return quote
    # Fallback to stale cache
    if btc_price_cache["data"]:
        return btc_price_cache["data"]
    return {}


def _fetch_global_mempool_fees() -> dict:
    """Mempool fee recommendations — cached globally."""
    cached = _get_global("mempool_fees")
    if cached is not None:
        return cached
    # fees were fetched in _fetch_global_network; retry if not cached
    return {"fastestFee": None, "halfHourFee": None, "hourFee": None}


# ── Per-user fetchers ────────────────────────────────────────────────────────

def _fetch_user_data(address: str) -> dict | None:
    """Fetch worker data for a specific BTC address (deduped per address)."""
    return _cached_user_fetch(f"user_{address}", _fetch_json,
                              f"{PARASITE_API}/user/{address}", 10)


def _fetch_account(address: str) -> dict | None:
    """Fetch account data for a specific BTC address (deduped per address)."""
    return _cached_user_fetch(f"acct_{address}", _fetch_json,
                              f"{PARASITE_API}/account/{address}", 10)


# ── Snapshot builder ─────────────────────────────────────────────────────────

def _build_snapshot(address: str, worker_name: str) -> dict:
    """Build a complete snapshot dict for one BTC address.

    This is the core polling logic, isolated per-session. It fetches:
    - User-specific: worker data, account data, leaderboard entry
    - Shared global: pool stats, network, BTC price, mempool fees

    Returns a dict with the same schema as the original latest_snapshot.
    """
    ts = int(time.time())
    snapshot: dict = {
        "ts": ts,
        "btc_address": address,
        "worker": None,
        "worker_index": None,
        "user_aggregate": None,
        "pool": None,
        "account": None,
        "account_meta": {},
        "lightning": None,
        "leaderboard_entry": None,
        "leaderboard_total": 0,
        "highest_diffs": [],
        "network": {"height": None, "difficulty": None, "hashrate": None, "stale": False},
        "btc_price": {"usd": None, "brl": None, "eur": None, "gbp": None,
                      "jpy": None, "krw": None, "cny": None, "stale": False},
        "luck_estimate": {},
        "halving": {},
        "mempool_fees": {},
        "profitability": {},
        "milestones": [],
        "proximity": {},
        "network_share_gauge": {},
        "alerts_recent": [],
        "timeline_recent": [],
        "event_stats": {},
        "leaderboard_table_top_30": [],
        "all_workers": [],
    }

    if not address:
        return snapshot

    try:
        # ── Fetch per-user data ──
        user = _fetch_user_data(address)
        account_data = _fetch_account(address)

        # ── Fetch global data ──
        pool = _fetch_global_pool()
        leaderboard = _fetch_global_leaderboard(100)
        highest = _fetch_global_highest_diffs(address, 20)
        height, difficulty, hashrate = _fetch_global_network()
        btc_quote = _fetch_global_btc_price()
        mempool_fees = _fetch_global_mempool_fees()

        # ── BTC price ──
        btc_usd = (btc_quote or {}).get("bitcoin", {}).get("usd")
        btc_brl = (btc_quote or {}).get("bitcoin", {}).get("brl")
        btc_eur = (btc_quote or {}).get("bitcoin", {}).get("eur")
        btc_gbp = (btc_quote or {}).get("bitcoin", {}).get("gbp")
        btc_jpy = (btc_quote or {}).get("bitcoin", {}).get("jpy")
        btc_krw = (btc_quote or {}).get("bitcoin", {}).get("krw")
        btc_cny = (btc_quote or {}).get("bitcoin", {}).get("cny")

        # ── Pool state ──
        pool_stale = False
        if not isinstance(pool, dict) or not pool.get("hashrate"):
            pool = {}
            pool_stale = True

        # ── Network state ──
        network = {
            "height": height,
            "difficulty": difficulty,
            "hashrate": hashrate,
            "stale": False,
        }

        # ── BTC price ──
        btc_price_data = {
            "usd": btc_usd, "brl": btc_brl,
            "eur": btc_eur, "gbp": btc_gbp,
            "jpy": btc_jpy, "krw": btc_krw, "cny": btc_cny,
            "stale": False,
        }

        # ── Account ──
        account = (account_data or {}).get("account")
        lightning = (account_data or {}).get("lightning") \
            if isinstance(account_data, dict) else None
        meta = (account or {}).get("metadata", {})

        # ── Leaderboard ──
        lb_entry = None
        for entry in (leaderboard or []):
            if entry.get("address") == address:
                lb_entry = entry
                break
        # Fallback: substring match
        if not lb_entry:
            addr_short = address[-8:].lower()
            for entry in (leaderboard or []):
                if addr_short in str(entry.get("address", "")).lower():
                    lb_entry = entry
                    break

        # ── Workers ──
        all_workers: list = []
        worker: dict | None = None
        worker_index: int | None = None

        if user and isinstance(user.get("workerData"), list):
            for idx, w in enumerate(user["workerData"]):
                raw_name = str(w.get("name", ""))
                raw_id = str(w.get("id", ""))
                clean_name = _names.sanitize(raw_name)
                clean_id = _names.sanitize(raw_id)
                entry = {
                    "id": clean_id,
                    "name": clean_name,
                    "hashrate": w.get("hashrate"),
                    "bestDifficulty": w.get("bestDifficulty", ""),
                    "lastSubmission": w.get("lastSubmission"),
                    "uptime": w.get("uptime"),
                    "is_primary": (
                        _names.normalize(raw_name)
                        == _names.normalize(worker_name)
                    ) or (
                        _names.normalize(raw_id)
                        == _names.normalize(worker_name)
                    ),
                }
                all_workers.append(entry)
                if entry["is_primary"]:
                    worker = w
                    worker_index = idx

        # ── Dedup workers ──
        _orig_count = len(all_workers)
        if all_workers:
            seen: dict = {}
            deduped: list = []
            for entry in all_workers:
                key = _names.dedup_key(entry.get("name", "") or "")
                if not key:
                    deduped.append(entry)
                    continue
                if key in seen:
                    existing_idx = seen[key]
                    existing = deduped[existing_idx]
                    if (entry.get("hashrate") or 0) \
                       > (existing.get("hashrate") or 0):
                        deduped[existing_idx] = entry
                else:
                    seen[key] = len(deduped)
                    deduped.append(entry)
            all_workers = deduped
            if _orig_count != len(all_workers):
                log.info("[dedup] %s: %d→%d workers", address[:8],
                         _orig_count, len(all_workers))

        # ── Halving countdown ──
        halving = {"height": height, "blocks_remaining": None,
                   "estimated_seconds_remaining": None,
                   "next_reward_btc": None, "epoch_label": ""}
        if isinstance(height, int):
            next_h = ((height // 210000) + 1) * 210000
            blocks_left = max(0, next_h - height)
            secs_left = blocks_left * 600
            epoch_idx = (next_h // 210000) - 1
            cur_reward = 50.0 * (0.5 ** epoch_idx) if epoch_idx >= 0 else 50.0
            next_reward = cur_reward * 0.5
            halving = {
                "next_height": next_h,
                "current_height": height,
                "blocks_remaining": blocks_left,
                "estimated_seconds_remaining": secs_left,
                "estimated_days_remaining": secs_left / 86400.0,
                "current_reward_btc": cur_reward,
                "next_reward_btc": next_reward,
                "epoch_label": f"#{epoch_idx + 1}/33",
            }

        # ── Assemble snapshot ──
        snapshot.update({
            "ts": ts,
            "btc_address": address,
            "worker": worker,
            "worker_index": worker_index,
            "user_aggregate": user,
            "pool": pool if pool else None,
            "account": account,
            "account_meta": meta,
            "lightning": lightning,
            "leaderboard_entry": lb_entry,
            "leaderboard_total": len(leaderboard or []),
            "highest_diffs": (highest or [])[:20],
            "network": network,
            "btc_price": btc_price_data,
            "mempool_fees": mempool_fees,
            "halving": halving,
            "all_workers": all_workers,
        })

    except Exception as e:
        log.error("[poll] error for %s: %s", address[:8], e)

    return snapshot


# ── Per-tenant wallet alert evaluation ────────────────────────────────────────

def evaluate_user_alerts(snapshot: dict, prev_snapshot: dict, settings: dict,
                         alert_seen: set) -> list:
    """Generate per-wallet alerts for one polled snapshot.

    Mirrors the operator's ``_do_poll`` wallet-anomaly detection but
    parameterized by the tenant's OWN thresholds (stale_share_minutes,
    hashrate_drop_pct). Returns a list of ``(severity, category, message)``
    tuples. ``alert_seen`` is a set of ``(category, identifier)`` signatures
    mutated in place for dedup — the same pattern ``_do_poll`` uses, so an
    event never fires twice per worker.

    Pool-wide events (new block, pool high diff) are intentionally NOT
    evaluated here: they are global facts shared by every tenant, so
    generating them per-user would spam every webhook. The operator's own
    ``_do_poll`` already covers them once.
    """
    alerts: list = []
    ts = int(snapshot.get("ts") or time.time())
    worker = snapshot.get("worker")
    prev_worker = (prev_snapshot or {}).get("worker") or {}

    stale_min = coerce_int(settings.get("stale_share_minutes"), 5)
    hr_drop_pct = coerce_float(settings.get("hashrate_drop_pct"), 50.0)

    if worker:
        # ── Stale submission ──
        ls = worker.get("lastSubmission")
        if ls and (ts - int(ls)) > stale_min * 60:
            sev = "WARN" if (ts - int(ls)) <= stale_min * 120 else "CRIT"
            sig = ("stale_submission", str(ls))
            if sig not in alert_seen:
                alerts.append((sev, "stale_submission",
                    f"Worker last submit {int((ts - int(ls)) / 60)}min ago "
                    f"(threshold {stale_min}m)"))
                alert_seen.add(sig)

        # ── Hashrate drop vs previous poll ──
        prev_hr = float(prev_worker.get("hashrate") or 0)
        cur_hr = float(worker.get("hashrate") or 0)
        if prev_hr > 0 and cur_hr < (1 - hr_drop_pct / 100.0) * prev_hr:
            sig = ("hashrate_drop", f"{prev_hr:.0f}->{cur_hr:.0f}")
            if sig not in alert_seen:
                alerts.append(("WARN", "hashrate_drop",
                    f"Worker hashrate dropped from {fmt_hashrate(prev_hr)} "
                    f"to {fmt_hashrate(cur_hr)} (-{hr_drop_pct:.0f}%)"))
                alert_seen.add(sig)

        # ── Uptime day-boundary milestone (fire once per day) ──
        if isinstance(worker.get("uptime"), int):
            up = worker["uptime"]
            if up > 0 and up % 86400 < 90:
                day_num = up // 86400
                sig = ("uptime_milestone", str(day_num))
                if sig not in alert_seen:
                    alerts.append(("INFO", "uptime",
                        f"Worker uptime crossed {fmt_uptime(up)}"))
                    alert_seen.add(sig)

        # Worker present → clear the offline sig so it can re-fire next time.
        alert_seen.discard(("worker_offline", "1"))
    else:
        # ── Online → offline transition (fire once per transition) ──
        sig = ("worker_offline", "1")
        was_present = bool(prev_snapshot and prev_snapshot.get("worker"))
        if sig not in alert_seen and was_present:
            alerts.append(("CRIT", "worker_offline",
                           "Worker not found in workerData"))
            alert_seen.add(sig)

    # GC old signatures (keep last 500) — same policy as _do_poll. Trim
    # in place (callers hold the same set object) so a persistent condition's
    # signature survives unless it is genuinely old.
    if len(alert_seen) > 1000:
        kept = list(alert_seen)[-500:]
        alert_seen.clear()
        alert_seen.update(kept)

    return alerts


# ── UserPollingWorker ────────────────────────────────────────────────────────

POLL_INTERVAL = 15  # seconds
# ── Phase: 1000+ user scale ──
# Jitter + adaptive backoff. With N workers all sleeping POLL_INTERVAL
# exactly, they re-poll in lockstep — a thundering herd of N simultaneous
# Parasite requests every cycle. Jitter desynchronizes them (same mean,
# spread out); adaptive backoff stretches the interval when the pool is
# erroring so a provider outage doesn't amplify into a self-inflicted
# request storm.
POLL_JITTER_MAX = 8          # seconds added: wait = interval + uniform(0, jitter)
POLL_MAX_BACKOFF = 120       # seconds cap on the error backoff
POLL_ERROR_BACKOFF_MULT = 2  # double the interval per consecutive error burst


def _poll_wait(consecutive_errors: int) -> float:
    """Compute the next poll wait: interval + jitter, stretched by backoff.

    consecutive_errors > 0 doubles the interval per burst (capped at
    POLL_MAX_BACKOFF), so a Parasite outage degrades gracefully instead of
    hammering the API with retries every 15s.
    """
    base = POLL_INTERVAL
    if consecutive_errors > 0:
        for _ in range(consecutive_errors):
            base *= POLL_ERROR_BACKOFF_MULT
            if base >= POLL_MAX_BACKOFF:
                base = POLL_MAX_BACKOFF
                break
    return base + random.uniform(0, POLL_JITTER_MAX)


class UserPollingWorker:
    """Background polling worker for a single user session.

    Runs a daemon thread that calls _build_snapshot() every POLL_INTERVAL
    seconds and stores the result in the SessionManager.
    """

    def __init__(self, session_id: str, session_manager, address: str,
                 worker_name: str = "", tenant_id: str = ""):
        self.session_id = session_id
        self._sm = session_manager
        self.address = address
        self.worker_name = worker_name
        # Fase 2: per-tenant alerts. Each session's worker evaluates wallet
        # anomalies against the USER'S OWN settings and fires THEIR webhook.
        self.tenant_id = tenant_id or "default"
        # Delta baseline for hashrate-drop / online→offline detection.
        self._prev_snapshot: dict = {}
        # (category, identifier) dedup signatures — per-worker, so alerts
        # never re-fire across polls while the condition persists.
        self._alert_seen: set = set()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        # Consecutive failed polls — drives adaptive backoff so provider
        # outages never amplify into a request storm at 1000+ user scale.
        self._consecutive_errors = 0

    def start(self):
        """Start the polling thread."""
        if self._thread and self._thread.is_alive():
            log.warning("[worker %s] already running", self.session_id[:8])
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"poll-{self.session_id[:8]}",
            daemon=True,
        )
        self._thread.start()
        log.info("[worker %s] started polling for %s",
                 self.session_id[:8], self.address[:10])

    def stop(self):
        """Signal the polling thread to stop."""
        self._stop_event.set()
        log.info("[worker %s] stop signal sent", self.session_id[:8])

    def poll_now(self) -> dict:
        """Force an immediate poll and return the snapshot."""
        snapshot = _build_snapshot(self.address, self.worker_name)
        self._dispatch_tenant_alerts(snapshot)
        self._sm.update_snapshot(self.session_id, snapshot)
        return snapshot

    def update_address(self, address: str, worker_name: str = ""):
        """Change the address this worker polls."""
        self.address = address
        self.worker_name = worker_name
        # New wallet = fresh delta baseline + dedup state.
        self._prev_snapshot = {}
        self._alert_seen.clear()
        log.info("[worker %s] address updated to %s",
                 self.session_id[:8], address[:10])

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Per-tenant alert + webhook dispatch ──────────────────────────────

    def _persist_alerts(self, ts: int, alerts: list):
        """Insert all alerts of one poll (plus history mirrors) scoped to this
        tenant in a SINGLE connection/transaction. The /api/alerts and
        /api/alerts/history routes filter by tenant_id, so each user only
        ever sees their own alerts."""
        if not alerts:
            return
        try:
            conn = _get_db()
            c = conn.cursor()
            for sev, cat, msg in alerts:
                c.execute(
                    "INSERT INTO alerts (ts, severity, category, message, "
                    "device_id, alert_type, is_acknowledged, active, meta, tenant_id) "
                    "VALUES (?, ?, ?, ?, '', 'snapshot', 0, 1, '{}', ?)",
                    (ts, sev, cat, msg, self.tenant_id),
                )
                c.execute(
                    "INSERT INTO alert_history (ts, alert_type, device_id, "
                    "severity, action_taken, tenant_id) "
                    "VALUES (?, 'snapshot', '', ?, ?, ?)",
                    (ts, sev, msg, self.tenant_id),
                )
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning("[worker %s] alert persist error: %s",
                        self.session_id[:8], e)

    def _dispatch_tenant_alerts(self, snapshot: dict):
        """Evaluate wallet alerts with THIS tenant's settings, persist them
        tenant-scoped, surface them in the snapshot's ``alerts_recent`` feed,
        and fire the tenant's webhook (Discord/Telegram) for severities at or
        above their configured threshold."""
        prev = self._prev_snapshot
        self._prev_snapshot = snapshot  # always advance the delta baseline
        try:
            settings = _load_settings(self.tenant_id)
            alerts = evaluate_user_alerts(snapshot, prev, settings,
                                          self._alert_seen)
            if not alerts:
                return

            ts = int(snapshot.get("ts") or time.time())
            webhook_url = (settings.get("webhook_url") or "").strip()
            min_sev = settings.get("webhook_min_severity", "WARN")
            recent = snapshot.setdefault("alerts_recent", [])

            # Persist all alerts in one transaction.
            self._persist_alerts(ts, alerts)
            for sev, cat, msg in alerts:
                recent.append(make_memory_alert(ts, sev, cat, msg))
                if webhook_url:
                    _fire_webhook_async({
                        "url": webhook_url,
                        "severity": sev,
                        "category": cat,
                        "message": msg,
                        "ts": ts,
                        "worker": self.worker_name,
                        "address": self.address,
                        "min_severity": min_sev,
                    })
            snapshot["alerts_recent"] = recent[-10:]
        except Exception as e:
            log.warning("[worker %s] tenant alert dispatch error: %s",
                        self.session_id[:8], e)

    def _run(self):
        """Main polling loop (jittered, adaptively backed off)."""
        # First poll immediately
        try:
            snapshot = _build_snapshot(self.address, self.worker_name)
            self._dispatch_tenant_alerts(snapshot)
            self._sm.update_snapshot(self.session_id, snapshot)
            log.info("[worker %s] initial poll complete (%d workers)",
                     self.session_id[:8],
                     len(snapshot.get("all_workers", [])))
            self._consecutive_errors = 0
        except Exception as e:
            self._consecutive_errors += 1
            log.error("[worker %s] initial poll error: %s",
                      self.session_id[:8], e)

        while not self._stop_event.is_set():
            wait = _poll_wait(self._consecutive_errors)
            self._stop_event.wait(wait)
            if self._stop_event.is_set():
                break
            try:
                snapshot = _build_snapshot(self.address, self.worker_name)
                self._dispatch_tenant_alerts(snapshot)
                self._sm.update_snapshot(self.session_id, snapshot)
                self._consecutive_errors = 0
            except Exception as e:
                self._consecutive_errors += 1
                log.error("[worker %s] poll error: %s",
                          self.session_id[:8], e)
