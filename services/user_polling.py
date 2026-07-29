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

log = logging.getLogger("cypher65.user_polling")

# ── Shared global data cache (thread-safe via Lock) ──────────────────────────
# Pool stats, network data, and BTC price are the same for ALL users.
_global_cache: dict[str, Any] = {}
_global_lock = threading.Lock()
GLOBAL_CACHE_TTL = 15  # seconds — matches POLL_INTERVAL


def _update_global(key: str, value: Any):
    with _global_lock:
        _global_cache[key] = {"data": value, "ts": int(time.time())}


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


def _fetch_global_leaderboard(limit: int = 30) -> list:
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
        "vs_currencies=usd,brl,eur,gbp",
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
    """Fetch worker data for a specific BTC address."""
    return _fetch_json(f"{PARASITE_API}/user/{address}", timeout=10)


def _fetch_account(address: str) -> dict | None:
    """Fetch account data for a specific BTC address."""
    return _fetch_json(f"{PARASITE_API}/account/{address}", timeout=10)


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
        "network": {"height": None, "difficulty": None, "hashrate": None},
        "btc_price": {"usd": None, "brl": None, "eur": None, "gbp": None},
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
        leaderboard = _fetch_global_leaderboard(30)
        highest = _fetch_global_highest_diffs(address, 20)
        height, difficulty, hashrate = _fetch_global_network()
        btc_quote = _fetch_global_btc_price()
        mempool_fees = _fetch_global_mempool_fees()

        # ── BTC price ──
        btc_usd = (btc_quote or {}).get("bitcoin", {}).get("usd")
        btc_brl = (btc_quote or {}).get("bitcoin", {}).get("brl")
        btc_eur = (btc_quote or {}).get("bitcoin", {}).get("eur")
        btc_gbp = (btc_quote or {}).get("bitcoin", {}).get("gbp")

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
        }

        # ── BTC price ──
        btc_price_data = {
            "usd": btc_usd, "brl": btc_brl,
            "eur": btc_eur, "gbp": btc_gbp,
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


# ── UserPollingWorker ────────────────────────────────────────────────────────

POLL_INTERVAL = 15  # seconds


class UserPollingWorker:
    """Background polling worker for a single user session.

    Runs a daemon thread that calls _build_snapshot() every POLL_INTERVAL
    seconds and stores the result in the SessionManager.
    """

    def __init__(self, session_id: str, session_manager, address: str,
                 worker_name: str = ""):
        self.session_id = session_id
        self._sm = session_manager
        self.address = address
        self.worker_name = worker_name
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

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
        self._sm.update_snapshot(self.session_id, snapshot)
        return snapshot

    def update_address(self, address: str, worker_name: str = ""):
        """Change the address this worker polls."""
        self.address = address
        self.worker_name = worker_name
        log.info("[worker %s] address updated to %s",
                 self.session_id[:8], address[:10])

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        """Main polling loop."""
        # First poll immediately
        try:
            snapshot = _build_snapshot(self.address, self.worker_name)
            self._sm.update_snapshot(self.session_id, snapshot)
            log.info("[worker %s] initial poll complete (%d workers)",
                     self.session_id[:8],
                     len(snapshot.get("all_workers", [])))
        except Exception as e:
            log.error("[worker %s] initial poll error: %s",
                      self.session_id[:8], e)

        while not self._stop_event.is_set():
            self._stop_event.wait(POLL_INTERVAL)
            if self._stop_event.is_set():
                break
            try:
                snapshot = _build_snapshot(self.address, self.worker_name)
                self._sm.update_snapshot(self.session_id, snapshot)
            except Exception as e:
                log.error("[worker %s] poll error: %s",
                          self.session_id[:8], e)
