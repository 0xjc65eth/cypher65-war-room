"""
HERMES Context Orchestrator v5
==============================
Builds rich context for each user message — session-isolated.

Combines:
- Conversation history (per-session, isolated)
- User profile (wallet, preferences)
- Current mining state (real data from state.latest_snapshot)
- System data (network, pool stats)
"""

from typing import Dict, Any, Optional, List


class ContextOrchestrator:
    """Builds and manages context for Hermes responses — session-aware."""

    def __init__(self):
        # Per-session conversation history: {session_id: [turns]}
        self._history: Dict[str, List[Dict]] = {}
        self._max_history = 20  # max turns per session

    def _ensure_history(self, session_id: str) -> List[Dict]:
        """Get or create conversation history for a session."""
        if session_id not in self._history:
            self._history[session_id] = []
            # Cleanup old sessions
            if len(self._history) > 500:
                oldest = min(self._history.keys(), key=lambda k: len(self._history[k]))
                del self._history[oldest]
        return self._history[session_id]

    def build_context(
        self,
        session_id: str,
        message: str,
        intent: str,
        user_data: Optional[Dict] = None,
        system_state: Optional[Dict] = None,
        memory_manager=None,
    ) -> Dict[str, Any]:
        """Construct a rich context object for this session.

        Args:
            session_id: Unique session identifier (isolates User A from User B)
            message: The current user message
            intent: Detected intent
            user_data: User-specific data (wallet, profile, preferences)
            system_state: System-level data (network, pool, BTC price)
            memory_manager: Optional MemoryManager for long-term memory access
        """
        history = self._ensure_history(session_id)

        # Get long-term memory if available
        user_profile = {}
        if memory_manager:
            user_profile = memory_manager.get_user_profile(session_id)

        # Get last 5 conversation turns for context
        recent_history = history[-5:] if history else []

        context = {
            "session_id": session_id,
            "message": message,
            "intent": intent,
            "user": {
                **(user_data or {}),
                "profile": user_profile,
            },
            "system": system_state or {},
            "history": recent_history,
            "turn_number": len(history) + 1,
        }

        # Add this turn to history
        history.append({
            "message": message,
            "intent": intent,
            "turn": len(history) + 1,
        })

        # Keep history bounded
        if len(history) > self._max_history:
            self._history[session_id] = history[-self._max_history:]

        return context

    def get_history(self, session_id: str, last_n: int = 5) -> List[Dict]:
        """Get the last N conversation turns for a session."""
        history = self._ensure_history(session_id)
        return history[-last_n:] if history else []

    def clear_history(self, session_id: str):
        """Clear conversation history for a session."""
        if session_id in self._history:
            self._history[session_id].clear()

    def resolve_references(self, message: str, session_id: str) -> str:
        """Resolve pronouns and references using session context.
        e.g., 'ele', 'aquele', 'o worker', 'por quê?' → resolves to last mentioned entity.
        """
        history = self.get_history(session_id, 3)
        if not history:
            return message

        # Simple reference resolution: if message is a follow-up question
        # like "por quê?" or "why?", prepend the last topic
        followup_indicators = [
            "por quê", "por que", "porque", "why",
            "e ele", "and it", "and he",
            "e se eu", "what if",
            "quanto custa", "how much",
            "o que é", "what is",
        ]

        is_followup = any(ind in message.lower() for ind in followup_indicators)
        if is_followup and len(history) >= 1:
            # Resolve to last topic
            last = history[-1]
            last_intent = last.get("intent", "").replace("_", " ").lower()
            # Don't modify — just note that context exists
            # Full resolution would require LLM, this is a foundation

        return message
