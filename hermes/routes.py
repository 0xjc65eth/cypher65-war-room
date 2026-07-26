"""
Hermes API Routes
=================
Flask routes to expose Hermes Cognitive Core.
With session-isolated memory and context.
"""

import logging
import uuid
from flask import Blueprint, request, jsonify
from hermes.integration import hermes
from auth import require_api_key
import services.state as state

log = logging.getLogger("hermes.routes")

hermes_bp = Blueprint("hermes", __name__, url_prefix="/api/hermes")

# ── Input validation constants ──────────────────────────────────────────
MAX_MESSAGE_LENGTH = 2000       # characters — truncate longer messages
MAX_PAYLOAD_SIZE = 100 * 1024   # 100KB — reject larger request bodies
MAX_AGENT_NAME_LENGTH = 64      # characters


def _validate_chat_input(data):
    """Validate and sanitize chat input. Returns (message, error).
    One of them will always be None."""
    if not isinstance(data, dict):
        return None, ("Invalid request format", 400)

    message = data.get("message")

    # Check for null/empty/whitespace
    if message is None:
        return None, ("Missing required field: message", 400)
    if not isinstance(message, str):
        return None, ("Field 'message' must be a string", 400)
    if not message.strip():
        return None, ("Message cannot be empty", 400)

    # Truncate very long messages (prevents memory exhaustion)
    if len(message) > MAX_MESSAGE_LENGTH:
        log.warning("[chat] message truncated from %d to %d chars", len(message), MAX_MESSAGE_LENGTH)
        message = message[:MAX_MESSAGE_LENGTH]

    # Strip null bytes and control characters (except newlines/tabs)
    message = message.replace("\x00", "")

    return message.strip(), None


def _validate_agent_input(data):
    """Validate ask-agent input. Returns (agent_name, payload, error).
    Error is a (message, status_code) tuple on failure."""
    if not isinstance(data, dict):
        return None, None, ("Invalid request format", 400)

    agent_name = data.get("agent")

    if agent_name is None:
        return None, None, ("Missing required field: agent", 400)
    if not isinstance(agent_name, str):
        return None, None, ("Field 'agent' must be a string", 400)
    if not agent_name.strip():
        return None, None, ("Agent name cannot be empty", 400)

    # Reject overly long agent names (don't silently truncate)
    agent_name = agent_name.strip()
    if len(agent_name) > MAX_AGENT_NAME_LENGTH:
        return None, None, (f"Agent name exceeds {MAX_AGENT_NAME_LENGTH} character limit", 400)

    # Validate payload
    payload = data.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}

    return agent_name, payload, None


@hermes_bp.route("/chat", methods=["POST"])
@require_api_key
def chat():
    """
    Main conversational endpoint for Hermes.
    Validates and sanitizes input before processing.
    """
    # Check request body size (use actual body size, not just Content-Length header)
    body_bytes = request.get_data(cache=True)
    if len(body_bytes) > MAX_PAYLOAD_SIZE:
        return jsonify({"error": "Request body too large"}), 413

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON body"}), 400

    message, err = _validate_chat_input(data)
    if err:
        return jsonify({"error": err[0]}), err[1]

    # ── Session management ────────────────────────────────────────────
    session_id = (data.get("session_id") or "").strip()[:64]
    if not session_id:
        session_id = str(uuid.uuid4())

    # ── Extract real mining data FIRST (used by both context and payload) ──
    snap = state.latest_snapshot or {}
    worker_data = snap.get("worker") or {}
    network_data = snap.get("network") or {}
    all_workers = snap.get("all_workers") or []
    btc_price = snap.get("btc_price") or {}

    def _safe_float(val, default=0.0):
        """Coerce to float safely — handles None, strings, and non-numeric values."""
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def _safe_int(val, default=0):
        """Coerce to int safely — handles None, 'N/A', strings, and non-numeric values."""
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    # Build user identity from the connected wallet (if available)
    user_data = {
        "wallet_address": snap.get("address", ""),
        "session_id": session_id,
    }

    # Store/update user profile in long-term memory
    if hermes.memory_manager:
        hermes.memory_manager.update_user_profile(session_id, user_data)

    intent_result = hermes.intent_engine.detect(message) if hermes.intent_engine else {"intent": "UNKNOWN"}
    intent = intent_result.get("intent")

    response_data = {
        "session_id": session_id,
        "message": message,
        "intent": intent,
        "response": "",
        "turn_number": 0,
    }

    # ── Build session-aware context ──────────────────────────────────
    if hermes.context_orchestrator:
        ctx = hermes.context_orchestrator.build_context(
            session_id=session_id,
            message=message,
            intent=intent,
            user_data=user_data,
            system_state={
                "network_difficulty": _safe_float(network_data.get("difficulty")),
                "btc_usd": _safe_float(btc_price.get("usd")),
                "pool_hashrate": _safe_float(snap.get("pool_hashrate")),
            },
            memory_manager=hermes.memory_manager,
        )
        response_data["turn_number"] = ctx.get("turn_number", 0)

    # Store this turn in short-term memory
    if hermes.memory_manager:
        hermes.memory_manager.add_to_short_term(session_id, {
            "role": "user",
            "message": message,
            "intent": intent,
        })

    # ── Build payload from REAL mining data ─────────────────────────────

    payload = {
        "intent": intent,
        # Real worker data
        "user_hashrate": _safe_float(worker_data.get("hashrate")),
        "worker_name": worker_data.get("name", "unknown"),
        "worker_status": worker_data.get("status", "unknown"),
        "worker_best_diff": worker_data.get("bestDifficulty", "—"),
        "worker_last_submit": _safe_int(worker_data.get("lastSubmission", 0)),
        "worker_uptime": _safe_int(worker_data.get("uptime", 0)),
        "all_workers": all_workers,
        # Real network data
        "network_hashrate": _safe_float(network_data.get("hashrate"), 6e20),
        "network_difficulty": _safe_float(network_data.get("difficulty")),
        "network_height": network_data.get("height"),
        # Real pool data
        "pool_hashrate": _safe_float(snap.get("pool_hashrate")),
        "pool_workers": snap.get("pool_workers", 0),
        # Real price data
        "btc_usd": _safe_float(btc_price.get("usd")),
        "btc_brl": _safe_float(btc_price.get("brl")),
        # Session data
        "session_share_count": getattr(state, "session_share_count", 0),
        "duration": 86400,
    }

    # Mark data provenance — REAL if we have ANY meaningful data (not just hashrate)
    has_real_data = (
        payload["user_hashrate"] > 0
        or len(payload.get("all_workers", [])) > 0
        or (isinstance(payload.get("worker_best_diff"), (int, float)) and payload["worker_best_diff"] > 0)
        or (isinstance(payload.get("worker_best_diff"), str) and payload["worker_best_diff"] not in ("", "—", "0"))
        or payload.get("session_share_count", 0) > 0
    )
    payload["_data_source"] = "REAL" if has_real_data else "NO_DATA"

    if intent == "PROBABILITY":
        agent_result = hermes.agent_orchestrator.call_agent("ProbabilityAgent", payload)
        response_data["probability"] = agent_result.get("probability")
        response_data["response"] = "Calculando probabilidade de encontrar bloco..."

    elif intent == "MINING_STATUS":
        agent_result = hermes.agent_orchestrator.call_agent("MiningAgent", payload)
        response_data["analysis"] = agent_result.get("analysis")
        response_data["response"] = agent_result.get("summary", "Analisando seu status de mineração...")

    elif intent == "FINANCIAL":
        agent_result = hermes.agent_orchestrator.call_agent("FinancialAgent", payload)
        response_data["analysis"] = agent_result.get("analysis")
        response_data["response"] = "Calculando análise financeira..."

    else:
        core_response = hermes.process_message(message, {"intent": intent, "session_id": session_id})
        response_data["response"] = core_response.get("response", "Entendido.")

    # Store agent response in short-term memory
    if hermes.memory_manager:
        hermes.memory_manager.add_to_short_term(session_id, {
            "role": "assistant",
            "message": response_data["response"][:200],
            "intent": intent,
        })

    return jsonify(response_data)


@hermes_bp.route("/agents", methods=["GET"])
@require_api_key
def list_agents():
    """List all registered agents."""
    agents = hermes.agent_orchestrator.list_agents() if hermes.agent_orchestrator else []
    return jsonify({
        "agents": agents,
        "count": len(agents)
    })


@hermes_bp.route("/ask-agent", methods=["POST"])
@require_api_key
def ask_agent():
    """
    Directly call a specific agent.

    Body:
        {"agent": "ProbabilityAgent", "payload": {...}}
    """
    # Check request body size (use actual body size, not just Content-Length header)
    body_bytes = request.get_data(cache=True)
    if len(body_bytes) > MAX_PAYLOAD_SIZE:
        return jsonify({"error": "Request body too large"}), 413

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON body"}), 400

    agent_name, payload, err = _validate_agent_input(data)
    if err:
        return jsonify({"error": err[0]}), err[1]

    if not hermes.agent_orchestrator:
        return jsonify({"error": "Agent orchestrator not available"}), 500

    result = hermes.agent_orchestrator.call_agent(agent_name, payload)
    return jsonify(result)


@hermes_bp.route("/health", methods=["GET"])
def hermes_health():
    """Enhanced health check for Hermes Core with agent status."""
    health_data = {
        "status": "healthy",
        "version": "4.0.0",
        "components": {},
        "agents": {}
    }

    if hasattr(hermes, "health"):
        health_data["components"] = hermes.health().get("components", {})

    if hermes.agent_orchestrator:
        for agent_name in hermes.agent_orchestrator.list_agents():
            health_data["agents"][agent_name] = "registered"

    return jsonify(health_data)