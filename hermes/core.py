"""
HERMES COGNITIVE CORE — Foundation
==================================
This is the brain of the Cypher Mining Intelligence Platform.

The HermesCore is responsible for:
- Receiving user messages
- Detecting intent
- Building context
- Orchestrating tools and agents
- Generating responses
"""

from typing import Dict, Any, Optional
import logging

try:
    import services.state as state
except ImportError:
    state = None

log = logging.getLogger("hermes.core")


def _safe_float(val, default=0.0):
    """Coerce to float safely."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _get_real_data():
    """Extract real mining data from the polling loop snapshot.
    Returns empty defaults if state module is unavailable."""
    if state is None:
        return {}
    snap = getattr(state, "latest_snapshot", None) or {}
    worker = snap.get("worker") or {}
    network = snap.get("network") or {}
    btc_price = snap.get("btc_price") or {}
    return {
        "user_hashrate": _safe_float(worker.get("hashrate")),
        "worker_status": worker.get("status", "unknown"),
        "worker_best_diff": worker.get("bestDifficulty", "—"),
        "worker_last_submit": worker.get("lastSubmission", 0),
        "worker_uptime": worker.get("uptime", 0),
        "all_workers": snap.get("all_workers") or [],
        "network_hashrate": _safe_float(network.get("hashrate"), 6e20),
        "network_difficulty": _safe_float(network.get("difficulty")),
        "network_height": network.get("height"),
        "pool_hashrate": _safe_float(snap.get("pool_hashrate")),
        "pool_workers": snap.get("pool_workers", 0),
        "btc_usd": _safe_float(btc_price.get("usd")),
        "btc_brl": _safe_float(btc_price.get("brl")),
        "btc_eur": _safe_float(btc_price.get("eur")),
        "btc_gbp": _safe_float(btc_price.get("gbp")),
        "session_share_count": getattr(state, "session_share_count", 0),
        "address": snap.get("address", ""),
        "_data_source": "REAL" if _safe_float(worker.get("hashrate")) > 0 else "NO_DATA",
    }


class HermesCore:
    """
    Main orchestrator for all Hermes intelligence.
    """

    def __init__(self):
        self.version = "4.0.0-foundation"
        self.initialized = True

        # Components (injected later via integration)
        self.intent_engine = None
        self.context_orchestrator = None
        self.memory_manager = None
        self.tool_registry = None
        self.agent_orchestrator = None

        log.info("[HermesCore] Initialized v%s", self.version)

    def process_message(self, message: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Main entry point for user messages.

        Detects intent, extracts real mining data, calls the right agent,
        and returns a contextual response with actual operation data.
        """
        ctx = context or {}
        session_id = ctx.get("session_id", "unknown")
        log.info("[HermesCore] Processing message [%s]: %s", session_id[:8], message[:80])

        # ── 1. Detect intent ──
        intent_result = {"intent": "UNKNOWN", "confidence": 0.3}
        if self.intent_engine:
            intent_result = self.intent_engine.detect(message)
        intent = intent_result.get("intent", "UNKNOWN")

        # ── 2. Get real data ──
        real_data = ctx.get("_real_data", {})
        if not real_data:
            real_data = _get_real_data()
        data_source = real_data.get("_data_source", "NO_DATA")

        # ── 3. Build payload with real data ──
        payload = {
            **real_data,
            "intent": intent,
            "duration": ctx.get("duration", 86400),
            "_data_source": data_source,
        }

        # ── 4. Route to appropriate agent ──
        response = ""
        agent_name = None

        intent_agent_map = {
            "MINING_STATUS": "MiningAgent",
            "HASHRATE_ANALYSIS": "MiningAgent",
            "PROBABILITY": "ProbabilityAgent",
            "FINANCIAL": "FinancialAgent",
            "WORKER_HEALTH": "PerformanceAgent",
            "RENTAL_COMPARISON": "RentalAgent",
            "ALERTS": "SecurityAgent",
        }

        agent_name = intent_agent_map.get(intent)

        if agent_name and self.agent_orchestrator:
            try:
                agent_result = self.agent_orchestrator.call_agent(agent_name, payload)
                if agent_result.get("status") == "success":
                    # Extract natural-language summary if available
                    response = (
                        agent_result.get("summary")
                        or agent_result.get("analysis", {}).get("message", "")
                        or self._build_fallback_response(intent, data_source, real_data)
                    )
                else:
                    response = agent_result.get("error") or agent_result.get("message", "")
            except Exception as e:
                log.warning("[HermesCore] Agent %s failed: %s", agent_name, e)
                response = f"[ERROR] {agent_name} unavailable: {str(e)[:120]}"
        else:
            response = self._handle_unknown(intent, data_source, real_data)

        return {
            "response": response,
            "intent": intent,
            "confidence": intent_result.get("confidence", 0.3),
            "message": message,
            "session_id": session_id,
            "context": {
                "data_source": data_source,
                "agent_called": agent_name,
            },
        }

    def _build_fallback_response(self, intent: str, data_source: str,
                                  data: Dict[str, Any]) -> str:
        """Build a fallback response when an agent returns no summary."""
        if data_source != "REAL":
            return (
                "No real mining data available right now. "
                "Connect a wallet address in Settings to see your operation data."
            )
        hr_ths = data.get("user_hashrate", 0) / 1e12
        status = data.get("worker_status", "unknown").upper()
        best = data.get("worker_best_diff", "—")
        if intent == "MINING_STATUS":
            return (
                f"Hashrate: {hr_ths:.2f} TH/s | Status: {status} | "
                f"Best difficulty: {best} | Active workers: {len(data.get('all_workers', []))}"
            )
        return f"Received your message (intent: {intent}). Hashrate: {hr_ths:.2f} TH/s."

    def _handle_unknown(self, intent: str, data_source: str,
                        data: Dict[str, Any]) -> str:
        """Handle unknown/general intents with real data context."""
        if data_source == "REAL":
            hr_ths = data.get("user_hashrate", 0) / 1e12
            status = data.get("worker_status", "unknown")
            return (
                f"I see your operation is {status} with {hr_ths:.2f} TH/s. "
                f"You can ask me about: mining status, block probability, "
                f"financial estimates, or worker performance."
            )
        return (
            "I don't have mining data loaded yet. Connect your wallet address "
            "in Settings to unlock real-time mining intelligence. "
            "You can ask me about: mining status, block probability, "
            "financial estimates, worker performance, or rental comparisons."
        )

    def health(self) -> Dict[str, Any]:
        """Return health status of the cognitive core."""
        return {
            "status": "healthy",
            "version": self.version,
            "components": {
                "intent_engine": "active" if self.intent_engine else "pending",
                "context_orchestrator": "active" if self.context_orchestrator else "pending",
                "memory_manager": "active" if self.memory_manager else "pending",
                "tool_registry": "active" if self.tool_registry else "pending",
                "agent_orchestrator": "active" if self.agent_orchestrator else "pending",
            }
        }