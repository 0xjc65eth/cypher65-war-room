"""
CYPHER65 // Snapshot assembly — RFC #478 · PR B3 (Issue #501)
=============================================================
Montagem do snapshot de uma wallet e a camada de fetch global que a alimenta,
extraídas verbatim de `services/user_polling.py` (1.605 linhas). Mesmos corpos,
mesma cache, mesmos TTLs, mesmo schema de retorno — nada aqui é comportamento
novo.

Peças movidas:

  * cache global LRU compartilhada (`_global_cache` + lock + `_update_global`
    + `_cached_user_fetch`), incluindo o dedup de fetch por ADDRESS;
  * `_get_global` (leitura com TTL);
  * constantes de fetch (`PARASITE_API`, `MEMPOOL_API`, `FETCH_MAX_RETRIES`,
    `FETCH_BACKOFF_BASE`), `btc_price_cache` e `_fetch_json`/`_fetch_text`;
  * os 6 fetchers globais cacheados (`_fetch_global_*`), os per-address
    `_fetch_user_data`/`_fetch_account` e `_build_snapshot` (240 linhas) —
    a função que monta o dict consumido pelo dashboard.

O cluster é auto-contido: os únicos usos da cache e dos fetchers estão aqui,
então a dependência é unidirecional — este módulo NÃO importa
`services.user_polling` nem `app`, e `user_polling` re-exporta os nomes movidos
para os consumidores existentes (`app.py`, `tests/`).

⚠️ Alvo de monkeypatch: quem faz `setattr(services.user_polling, "_fetch_json",
...)` NÃO intercepta mais o fetch — o código resolve os nomes nos globals DESTE
módulo. Patche `services.snapshot_assembly` quando o alvo for o fetch layer.
"""

import concurrent.futures
import logging
import threading
import time
from typing import Any

import requests

import services.names as _names
from helpers import safe_num_from_str

log = logging.getLogger("cypher65.snapshot_assembly")


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
            r = requests.get(
                url, timeout=timeout, headers={"User-Agent": "cypher65-war-room/1.0"}
            )
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
            r = requests.get(
                url, timeout=timeout, headers={"User-Agent": "cypher65-war-room/1.0"}
            )
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
    data = _fetch_json(f"{PARASITE_API}/leaderboard?limit={limit}", timeout=10) or []
    _update_global("leaderboard", data)
    return data


def _fetch_global_highest_diffs(address: str, limit: int = 20) -> list:
    """High-diff events — slightly different per address, but the global
    endpoint returns pool-wide events. Cache per address for 60s."""
    cached = _get_global(f"hd_{address}", ttl=60)
    if cached is not None:
        return cached
    data = (
        _fetch_json(
            f"{PARASITE_API}/highest-diff?type=user-diffs&address={address}&limit={limit}",
            timeout=10,
        )
        or []
    )
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
        fut_height = ex.submit(_fetch_json, f"{MEMPOOL_API}/blocks/tip/height", 6)
        fut_diff = ex.submit(_fetch_text, "https://blockchain.info/q/getdifficulty", 8)
        fut_hr = ex.submit(_fetch_text, "https://blockchain.info/q/hashrate", 8)
        fut_fees = ex.submit(_fetch_json, f"{MEMPOOL_API}/v1/fees/recommended", 6)

        results["height"] = fut_height.result()
        results["diff"] = fut_diff.result()
        results["hr"] = fut_hr.result()

        # Mempool fees are also global
        fees_raw = fut_fees.result()
        fees = {}
        if isinstance(fees_raw, dict):
            for k in (
                "fastestFee",
                "halfHourFee",
                "hourFee",
                "minimumFee",
                "economyFee",
            ):
                v = fees_raw.get(k)
                if isinstance(v, (int, float)):
                    fees[k] = v
        if not fees:
            fees = {"fastestFee": None, "halfHourFee": None, "hourFee": None}
        _update_global("mempool_fees", fees)

    height = results["height"] if isinstance(results["height"], int) else None
    diff_val = safe_num_from_str(results["diff"])
    difficulty = float(diff_val) if diff_val else None
    hr_val = safe_num_from_str(results["hr"])
    hashrate = float(hr_val) * 1e9 if hr_val else None

    if difficulty and (hashrate is None or hashrate == 0):
        hashrate = difficulty * (2**32) / 600

    _update_global("net_height", height)
    _update_global("net_diff", difficulty)
    _update_global("net_hr", hashrate)

    return height, difficulty, hashrate


def _fetch_global_btc_price() -> dict:
    """BTC price — cached for 5 min (CoinGecko rate limit)."""
    global btc_price_cache
    now = int(time.time())
    if now - btc_price_cache["ts"] < BTC_PRICE_CACHE_TTL and btc_price_cache["data"]:
        return btc_price_cache["data"]

    quote = _fetch_json(
        "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&"
        "vs_currencies=usd,brl,eur,gbp,jpy,krw,cny",
        timeout=6,
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
    return _cached_user_fetch(
        f"user_{address}", _fetch_json, f"{PARASITE_API}/user/{address}", 10
    )


def _fetch_account(address: str) -> dict | None:
    """Fetch account data for a specific BTC address (deduped per address)."""
    return _cached_user_fetch(
        f"acct_{address}", _fetch_json, f"{PARASITE_API}/account/{address}", 10
    )


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
        "network": {
            "height": None,
            "difficulty": None,
            "hashrate": None,
            "stale": False,
        },
        "btc_price": {
            "usd": None,
            "brl": None,
            "eur": None,
            "gbp": None,
            "jpy": None,
            "krw": None,
            "cny": None,
            "stale": False,
        },
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
            "usd": btc_usd,
            "brl": btc_brl,
            "eur": btc_eur,
            "gbp": btc_gbp,
            "jpy": btc_jpy,
            "krw": btc_krw,
            "cny": btc_cny,
            "stale": False,
        }

        # ── Account ──
        account = (account_data or {}).get("account")
        lightning = (
            (account_data or {}).get("lightning")
            if isinstance(account_data, dict)
            else None
        )
        meta = (account or {}).get("metadata", {})

        # ── Leaderboard ──
        lb_entry = None
        for entry in leaderboard or []:
            if entry.get("address") == address:
                lb_entry = entry
                break
        # Fallback: substring match
        if not lb_entry:
            addr_short = address[-8:].lower()
            for entry in leaderboard or []:
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
                        _names.normalize(raw_name) == _names.normalize(worker_name)
                    )
                    or (_names.normalize(raw_id) == _names.normalize(worker_name)),
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
                    if (entry.get("hashrate") or 0) > (existing.get("hashrate") or 0):
                        deduped[existing_idx] = entry
                else:
                    seen[key] = len(deduped)
                    deduped.append(entry)
            all_workers = deduped
            if _orig_count != len(all_workers):
                log.info(
                    "[dedup] %s: %d→%d workers",
                    address[:8],
                    _orig_count,
                    len(all_workers),
                )

        # ── Halving countdown ──
        halving = {
            "height": height,
            "blocks_remaining": None,
            "estimated_seconds_remaining": None,
            "next_reward_btc": None,
            "epoch_label": "",
        }
        if isinstance(height, int):
            next_h = ((height // 210000) + 1) * 210000
            blocks_left = max(0, next_h - height)
            secs_left = blocks_left * 600
            epoch_idx = (next_h // 210000) - 1
            cur_reward = 50.0 * (0.5**epoch_idx) if epoch_idx >= 0 else 50.0
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
        snapshot.update(
            {
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
            }
        )

    except Exception as e:
        log.error("[poll] error for %s: %s", address[:8], e)

    return snapshot
