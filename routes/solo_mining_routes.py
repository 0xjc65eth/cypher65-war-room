"""
CYPHER65 // Solo-mining API routes
====================================
Flask Blueprint for /api/solo-mining/* endpoints.
Extracted from app.py.
"""

import json
import time
import logging

from flask import Blueprint, jsonify, request

import services.state as state
import solo_mining
from agents.solo_mining_advisor.tools import mrr_credentials
from services.tenant import require_tenant

log = logging.getLogger("cypher65")

solo_mining_bp = Blueprint("solo_mining", __name__)


@solo_mining_bp.route("/calc")
def api_solo_mining_calc():
    """Calculate solo mining probabilities.
    Params: hashrate (e.g. 225TH), duration (hours), difficulty (optional)
    """
    hashrate = request.args.get("hashrate", "")
    duration = request.args.get("duration", 24)
    difficulty = request.args.get("difficulty", None)
    user = request.args.get("user", "")

    if not hashrate:
        return jsonify({"error": "hashrate required (e.g. 225TH)"}), 400

    try:
        duration = float(duration)
    except ValueError:
        return jsonify({"error": "invalid duration"}), 400

    # Use provided difficulty or fetch from live data
    if difficulty:
        try:
            difficulty = float(difficulty)
        except ValueError:
            difficulty = None

    if not difficulty:
        # Try live data from latest snapshot
        net = state.latest_snapshot.get("network", {})
        difficulty = float(net.get("difficulty") or 0)
        if not difficulty:
            # Fallback: fetch from mempool
            d = solo_mining.get_network_difficulty()
            if d:
                difficulty = d

    if not difficulty or difficulty <= 0:
        return (
            jsonify(
                {
                    "error": "could not determine network difficulty",
                    "hint": "pass ?difficulty=N as query param",
                }
            ),
            400,
        )

    hashrate_hs = solo_mining._parse_hashrate(hashrate)
    result = {
        "hashrate": hashrate,
        "hashrate_hs": hashrate_hs,
        "duration_hours": duration,
        "difficulty": difficulty,
        "probability": solo_mining.calc_block_probability(
            hashrate_hs, difficulty, duration * 3600
        ),
        "expected_time": solo_mining.calc_expected_time(hashrate_hs, difficulty),
        "best_diff": solo_mining.calc_best_diff_expected(hashrate_hs, duration * 3600),
        "terminal_output": solo_mining.format_calc_output(
            hashrate, difficulty, duration, user=user or None
        ),
    }
    return jsonify(result)


@solo_mining_bp.route("/compare")
@require_tenant
def api_solo_mining_compare(tenant_id: str = ""):
    """Compare rental platforms. Auto-fetches Braiins orderbook + MRR listings.
    Params: budget (BTC), duration (hours), braiins_price, mrr_price (optional),
    Credentials are resolved server-side for the authenticated tenant. They
    are never accepted in the URL, where proxies and browser history leak them.
    """
    budget = request.args.get("budget", 0)
    duration = request.args.get("duration", 24)
    user = request.args.get("user", "")
    braiins_price = request.args.get("braiins_price", None)
    mrr_price = request.args.get("mrr_price", None)
    auto_fetch = request.args.get("auto_fetch", "1") != "0"
    if "mrr_api_key" in request.args or "mrr_api_secret" in request.args:
        return (
            jsonify(
                {
                    "error": "credentials must be configured in Settings, never sent in a URL",
                    "code": "CREDENTIALS_IN_URL_REJECTED",
                }
            ),
            400,
        )
    creds = mrr_credentials(tenant_id=tenant_id)
    mrr_api_key = creds["api_key"]
    mrr_api_secret = creds["api_secret"]

    try:
        budget = float(budget)
        duration = float(duration)
    except ValueError:
        return jsonify({"error": "invalid budget or duration"}), 400

    if budget <= 0:
        return jsonify({"error": "budget must be > 0 BTC"}), 400

    # Get difficulty
    net = state.latest_snapshot.get("network", {})
    difficulty = float(net.get("difficulty") or 0)
    if not difficulty:
        d = solo_mining.get_network_difficulty()
        difficulty = d or 110e12  # last resort fallback

    results = solo_mining.compare_rentals(
        budget,
        difficulty,
        duration,
        float(braiins_price) if braiins_price else None,
        float(mrr_price) if mrr_price else None,
        auto_fetch=auto_fetch,
        mrr_api_key=mrr_api_key,
        mrr_api_secret=mrr_api_secret,
    )

    terminal = solo_mining.format_compare_output(
        budget,
        difficulty,
        duration,
        float(braiins_price) if braiins_price else None,
        float(mrr_price) if mrr_price else None,
        auto_fetch=auto_fetch,
        mrr_api_key=mrr_api_key,
        mrr_api_secret=mrr_api_secret,
        user=user or None,
    )

    return jsonify(
        {
            "budget_btc": budget,
            "duration_hours": duration,
            "difficulty": difficulty,
            "options": results,
            "terminal_output": terminal,
        }
    )


@solo_mining_bp.route("/network")
def api_solo_mining_network():
    """Get current network stats for solo mining calculations."""
    difficulty = solo_mining.get_network_difficulty()
    btc_price = solo_mining.get_btc_price()
    pool_stats = solo_mining.get_parasite_best_diff()

    net = state.latest_snapshot.get("network", {})
    return jsonify(
        {
            "difficulty": difficulty or float(net.get("difficulty", 0)),
            "btc_price_usd": btc_price.get("usd", 0),
            "btc_price_brl": btc_price.get("brl", 0),
            "pool_hashrate": pool_stats.get("pool_hashrate", 0),
            "pool_workers": pool_stats.get("pool_workers", 0),
        }
    )
