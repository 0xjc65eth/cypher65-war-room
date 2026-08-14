"""
CYPHER65 // Snapshot Enrichment
================================
Extracted from app.py api_snapshot — the single function that takes a raw
snapshot dict and enriches it with market_data, auto_pilot, command_center,
block_hunt, and affiliate links. Called by both the @app.route handler and
the dashboard_bp blueprint so the payload is identical regardless of which
registration serves /api/snapshot.

Fase 6 · PR2: extracted from app.py to enable the dashboard_bp migration.
"""

import json
import time
import sqlite3
import logging
import threading
from typing import Any, Dict, List, Optional

import services.state as _shared_state
from services.hashrate_market import (
    fetch_all_offers as _fetch_all_offers,
    build_highlights as _build_market_highlights,
    persist_market_history as _persist_market_history,
    market_offer_sort_key as _market_offer_sort_key,
    compute_institutional_view as _compute_institutional_view,
    clear_fetch_cache,
)
from helpers import (
    parse_diff_to_float,
    attach_affiliate,
    affiliate_map_from_env,
    build_command_center,
    AP_PEAK_WINDOW_S,
    AP_TEMP_HIGH_C,
)
from services.probability import calculate_multiple_periods, _seconds_to_human
from config import WORKER_NAME

log = logging.getLogger("cypher65.snapshot_enrichment")

# ── Auto-pilot dependency injection ──────────────────────────────────────
# The automation preview must evaluate against the SAME live in-memory
# devices (with current_telemetry) that the poll loop uses — a cold DB
# reload loses telemetry, so rules would never match. app.py injects the
# boot-initialized AutomationEngine + CoreDeviceRegistry at startup (setter
# pattern like routes/alerts_routes._set_get_db). When not injected (tests,
# standalone) we fall back to a fresh engine + DB-loaded devices — still
# fail-closed, still tenant-scoped.
_auto_pilot_engine = None
_auto_pilot_registry = None


def set_auto_pilot_deps(engine, registry):
    """Inject the app-boot AutomationEngine + live core registry (Fase 6).

    Called by app.py after _init_alert_engines() so /api/snapshot's
    auto_pilot preview sees the same telemetry the poll loop evaluates.
    """
    global _auto_pilot_engine, _auto_pilot_registry
    _auto_pilot_engine = engine
    _auto_pilot_registry = registry


def get_auto_pilot_engine():
    """Return the boot-initialized AutomationEngine (or None).

    Issue #76: the dry-run routes use the LIVE engine so the simulated
    budget reflects the real per-tenant window consumption (a fresh engine
    per request would always report a full budget). Read-only consumer — the
    dry-run never mutates the shared engine's state.
    """
    return _auto_pilot_engine


# ── Hashrate market fetch cache ──────────────────────────────────────────
# Moved from app.py so both app.py and dashboard_bp share the same cache.
_HASHRATE_MARKET_CACHE: Dict[str, Any] = {"ts": 0, "offers": None}
_HASHRATE_MARKET_CACHE_TTL = 60
_HASHRATE_MARKET_EMPTY_CACHE_TTL = 15
_HASHRATE_MARKET_FETCH_LOCK = threading.Lock()


def _sync_market_prices_to_state(offers):
    """Mirror scored offers into _shared_state.last_known_prices."""
    if not offers:
        return
    now = int(time.time())
    for entry in offers:
        if not isinstance(entry, dict):
            continue
        provider = entry.get("provider") or entry.get("source")
        price_per_th = entry.get("price_per_th_day")
        if not provider or price_per_th is None:
            continue
        price_per_ph = float(price_per_th) * 1000.0
        estimated = bool(entry.get("estimated"))
        _shared_state.last_known_prices[provider] = {
            "ts": now,
            "price": price_per_ph,
            "source": entry.get("source", provider),
            "estimated": estimated,
            "label": (entry.get("meta") or {}).get("label", ""),
        }


def _get_hashrate_market_offers(snapshot: dict) -> list:
    """Fetch live hashrate offers, caching them for a short TTL."""
    now = int(time.time())
    cache = _HASHRATE_MARKET_CACHE
    ttl = (
        _HASHRATE_MARKET_CACHE_TTL
        if cache["offers"]
        else _HASHRATE_MARKET_EMPTY_CACHE_TTL
    )
    if (now - cache["ts"] < ttl) and cache["offers"] is not None:
        _sync_market_prices_to_state(cache["offers"])
        return cache["offers"]

    with _HASHRATE_MARKET_FETCH_LOCK:
        now = int(time.time())
        ttl = (
            _HASHRATE_MARKET_CACHE_TTL
            if cache["offers"]
            else _HASHRATE_MARKET_EMPTY_CACHE_TTL
        )
        if (now - cache["ts"] < ttl) and cache["offers"] is not None:
            _sync_market_prices_to_state(cache["offers"])
            return cache["offers"]

        network_hashrate = (snapshot.get("network") or {}).get("hashrate")
        offers = _fetch_all_offers(network_hashrate=network_hashrate)
        if offers:
            try:
                from services.db import get_db

                conn = get_db()
                _persist_market_history(conn, offers)
                conn.close()
            except Exception as e:
                log.warning("[market] persist failed: %s", e)

        _HASHRATE_MARKET_CACHE["ts"] = int(time.time())
        _HASHRATE_MARKET_CACHE["offers"] = offers if offers else []
        _sync_market_prices_to_state(offers if offers else [])
        return offers if offers else []


def _hashrate_market_health() -> dict:
    """Expose warmup/cache health for market_data."""
    cache = _HASHRATE_MARKET_CACHE
    now = int(time.time())
    ts = cache.get("ts") or 0
    offers = cache.get("offers")
    count = len(offers) if offers else 0
    ttl = _HASHRATE_MARKET_CACHE_TTL if offers else _HASHRATE_MARKET_EMPTY_CACHE_TTL
    return {
        "last_fetch_ts": ts,
        "age_s": now - ts if ts else None,
        "offers_count": count,
        "stale": (now - ts) > ttl if ts else True,
    }


# ── Block Hunt computation ──────────────────────────────────────────────


def _compute_block_hunt(snap: dict) -> dict:
    """Compute the Block Hunt payload from a snapshot (pure, no I/O)."""
    net = snap.get("network") or {}
    worker = snap.get("worker") or {}

    user_hr = float(worker.get("hashrate") or 0)
    net_hr = float(net.get("hashrate") or 0)
    net_diff = float(net.get("difficulty") or 0)
    block_height = net.get("height")

    best_diff_str = worker.get("bestDifficulty") or ""
    best_diff_raw = parse_diff_to_float(best_diff_str) if best_diff_str else 0.0

    prob_periods = {}
    expected_time = None
    expected_time_human = None
    if user_hr > 0 and net_hr > 0:
        try:
            prob_result = calculate_multiple_periods(user_hr, net_hr)
            prob_periods = prob_result.get("periods", {})
            expected_time = prob_periods.get("24h", {}).get(
                "expected_time_to_block_seconds"
            )
            if expected_time is not None:
                expected_time_human = _seconds_to_human(expected_time)
        except Exception as e:
            log.warning("[block-hunt] probability calculation failed: %s", e)

    hashrate_pct = 0.0
    if user_hr > 0 and net_hr > 0:
        hashrate_pct = user_hr / net_hr * 100.0

    distance_to_block = None
    if net_diff and best_diff_raw:
        distance_to_block = net_diff / best_diff_raw

    all_time_best = (snap.get("proximity") or {}).get("all_time_best_diff_raw") or 0.0
    if all_time_best and best_diff_raw:
        distance_to_all_time_best = all_time_best / best_diff_raw
    else:
        distance_to_all_time_best = None

    leaderboard_entry = snap.get("leaderboard_entry") or {}
    approx_diff_rank = (
        leaderboard_entry.get("diffRank")
        or leaderboard_entry.get("rankDifficulty")
        or leaderboard_entry.get("rank")
    )

    cumulative_p_block = None
    try:
        cumulative_p_block = (
            (snap.get("proximity") or {})
            .get("live_calc", {})
            .get("session_totals", {})
            .get("cum_p_block")
        )
    except Exception:
        cumulative_p_block = None

    return {
        "network_difficulty": net_diff,
        "best_difficulty": best_diff_raw,
        "p_block_per_share": (
            (best_diff_raw / net_diff) if net_diff and best_diff_raw else None
        ),
        "expected_time_seconds": expected_time,
        "cumulative_p_block": cumulative_p_block,
        "best_diff_worker": worker.get("name") or WORKER_NAME or "",
        "network": {
            "hashrate": net_hr,
            "difficulty": net_diff,
            "block_height": block_height,
        },
        "user": {
            "hashrate": user_hr,
            "best_difficulty": best_diff_raw,
            "best_difficulty_str": best_diff_str,
        },
        "probability": {
            "chance_1h": prob_periods.get("1h", {}).get("probability_at_least_one"),
            "chance_24h": prob_periods.get("24h", {}).get("probability_at_least_one"),
            "chance_7d": prob_periods.get("7d", {}).get("probability_at_least_one"),
            "expected_time_to_block_seconds": expected_time,
            "expected_time_to_block_human": expected_time_human,
        },
        "network_comparison": {
            "hashrate_pct_of_network": round(hashrate_pct, 8),
            "distance_to_block_factor": distance_to_block,
            "distance_to_all_time_best_factor": distance_to_all_time_best,
            "approx_difficulty_rank": approx_diff_rank,
        },
    }


# ── Auto-pilot context ──────────────────────────────────────────────────


def build_auto_pilot_context() -> dict:
    """P1 Auto-Pilot advisory context block (read-only, never executes).

    Feeds the advisory Command Center rules with REAL data.
    Tenant-scoped + fail-closed.
    """
    try:
        tenant_id = "default"
        try:
            from services.tenant import get_tenant_id as _resolve_tenant

            tenant_id = _resolve_tenant() or "default"
        except Exception:
            tenant_id = "default"

        peak_7d = 0.0
        conn = None
        try:
            from services.db import get_db

            conn = get_db()
            row = conn.execute(
                "SELECT MAX(worker_hashrate) FROM proximity_history " "WHERE ts >= ?",
                (int(time.time()) - AP_PEAK_WINDOW_S,),
            ).fetchone()
            if row and row[0]:
                peak_7d = float(row[0])
        except Exception as e:
            log.warning("[auto-pilot] peak query failed: %s", e)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        automation_preview = []
        armed = False
        try:
            if _auto_pilot_engine is not None:
                # Preferred: the boot-initialized engine + LIVE core registry
                # (in-memory devices carry current_telemetry, so rule
                # conditions actually match — same as the pre-migration
                # app.py build_auto_pilot_context).
                _ap_devices = (
                    _auto_pilot_registry.list_devices()
                    if _auto_pilot_registry is not None
                    else []
                )
                # is_armed is optional on the injected engine (test fakes /
                # older engines) — treat absence as False, never crash the
                # preview block over an advisory flag.
                _is_armed = getattr(_auto_pilot_engine, "is_armed", None)
                if callable(_is_armed):
                    armed = bool(_is_armed(tenant_id))
                preview = _auto_pilot_engine.preview_rules(
                    _ap_devices, tenant_id=tenant_id
                )
            else:
                # Fallback (tests/standalone): fresh engine + DB-loaded
                # devices. Telemetry is in-memory only, so conditions may not
                # match — acceptable fallback, never a crash.
                from config import DB_PATH as _ap_db_path
                from core.safety.safety_engine import SafetyEngine
                from core.alerts.automation_engine import AutomationEngine
                from core.registry.device_registry import (
                    DeviceRegistry as CoreDeviceRegistry,
                )

                _ap_reg = CoreDeviceRegistry(_ap_db_path)
                _ap_reg.load_from_db()
                _ap_devices = _ap_reg.list_devices()
                _ap_eng = AutomationEngine(_ap_db_path, SafetyEngine())
                armed = bool(_ap_eng.is_armed(tenant_id))
                preview = _ap_eng.preview_rules(_ap_devices, tenant_id=tenant_id)
            if isinstance(preview, list):
                automation_preview = preview[:3]
        except Exception as e:
            log.warning("[auto-pilot] preview failed: %s", e)

        return {
            "peak_hashrate_7d": peak_7d,
            "automation_preview": automation_preview,
            "armed": armed,
            "temp_high_c": AP_TEMP_HIGH_C,
        }
    except Exception as e:
        log.warning("[auto-pilot] context failed: %s", e)
        return {
            "peak_hashrate_7d": 0.0,
            "automation_preview": [],
            "armed": False,
            "temp_high_c": AP_TEMP_HIGH_C,
        }


# ── Main enrichment ─────────────────────────────────────────────────────


def enrich_snapshot(snapshot: dict, axe_registry=None) -> dict:
    """Take a raw snapshot dict and enrich it with market_data, auto_pilot,
    command_center, block_hunt, and affiliate links. Returns a NEW dict
    (does not mutate the input).

    Called by both app.py's @app.route(\"/api/snapshot\") and the
    dashboard_bp blueprint — ensures identical payload regardless of
    which registration serves the route.
    """
    resp = dict(snapshot)

    # ── Tenant-scope axe_fleet ──
    try:
        from services.tenant import get_tenant_id as _resolve_tenant

        _fleet = resp.get("axe_fleet") or []
        # Auto-discover the axe registry: use the caller-supplied one, or
        # import from axe_fleet.routes (set by init_routes() at boot).
        _reg = axe_registry
        if _reg is None and _fleet:
            try:
                from axe_fleet.routes import _registry as _axe_mod_registry

                _reg = _axe_mod_registry
            except Exception:
                _reg = None
        if _fleet and _reg is not None:
            _tenant_ids = {
                _d["id"] for _d in _reg.list_devices(tenant_id=_resolve_tenant())
            }
            resp["axe_fleet"] = [
                _t
                for _t in _fleet
                if _t.get("device_id") in _tenant_ids or _t.get("id") in _tenant_ids
            ]
    except Exception:
        resp["axe_fleet"] = []

    # ── Block Hunt ──
    resp["block_hunt"] = _compute_block_hunt(snapshot)

    # ── Market data ──
    _get_hashrate_market_offers(snapshot)
    highlights = _build_market_highlights(
        snapshot, _shared_state.last_known_prices, max_age_seconds=120
    )
    resp["market_highlights"] = highlights

    # HashratePulse Enterprise institutional view
    # Real-user audit: btc_usd lives in the top-level btc_price block — the
    # network block never carried it, so the institutional snapshot showed
    # "—" for BTC/USD and Rent-vs-Own forever. Read btc_price.usd first,
    # keep the legacy network.btc_usd fallback for old payloads.
    network_hr = (snapshot.get("network") or {}).get("hashrate")
    btc_usd = (snapshot.get("btc_price") or {}).get("usd") or (
        snapshot.get("network") or {}
    ).get("btc_usd")
    all_offers = _fetch_all_offers(network_hr)
    resp["institutional"] = _compute_institutional_view(all_offers, network_hr, btc_usd)
    cache = _shared_state.market_data_cache
    if highlights and len(highlights) > 0:
        sorted_hl = sorted(highlights, key=_market_offer_sort_key)
        market_hl = [x for x in sorted_hl if not x.get("estimated")]
        best_offer = min(
            market_hl or sorted_hl, key=lambda x: x.get("price_per_th_day", 999)
        )
        best_price_raw = best_offer.get("price_per_th_day")
        if best_price_raw and best_price_raw >= 0.001:
            best_price_str = "{:.6f} BTC/TH/d".format(best_price_raw)
        elif best_price_raw:
            best_price_str = "{:.2f} sats/TH/d".format(best_price_raw * 1e8)
        else:
            best_price_str = None
        resp["market_data"] = {
            "offers": sorted_hl,
            "best_price": best_price_str,
            "updated_at": int(time.time()),
            "provider_count": len(sorted_hl),
            "health": _hashrate_market_health(),
            "institutional": resp.get("institutional"),
        }
        attach_affiliate(resp, sorted_hl, affiliate_map_from_env())
        cache["offers"] = sorted_hl
        cache["best_price"] = best_price_str
        cache["updated_at"] = int(time.time())
        cache["loading"] = False
        cache["error"] = None
    else:
        if cache["offers"] and cache["offers"] != []:
            resp["market_data"] = {
                "offers": cache["offers"],
                "best_price": cache["best_price"],
                "updated_at": cache["updated_at"],
                "provider_count": len(cache["offers"]),
                "cached": True,
                "institutional": resp.get("institutional"),
            }
            attach_affiliate(resp, cache["offers"], affiliate_map_from_env())
        else:
            resp["market_data"] = {
                "offers": [],
                "best_price": None,
                "updated_at": 0,
                "provider_count": 0,
                "loading": True,
                "affiliate": None,
                "institutional": resp.get("institutional"),
            }

    # ── Auto-pilot + Command Center ──
    resp["auto_pilot"] = build_auto_pilot_context()
    resp["command_center"] = build_command_center(resp)

    return resp
