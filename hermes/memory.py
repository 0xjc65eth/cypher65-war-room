"""
HERMES Memory Manager v5
========================
Handles short-term, long-term and semantic memory with SESSION ISOLATION.

CRITICAL: Each session_id gets its own isolated memory store.
Session A cannot access Session B's data.
"""

import time
import threading
from typing import Dict, Any, List, Optional
from datetime import datetime


# Maximum number of active sessions before we evict the oldest
MAX_SESSIONS = 1000
# Sessions older than this (seconds) are eligible for eviction
SESSION_TTL = 3600  # 1 hour of inactivity


class MemoryManager:
    """Manages different layers of memory — isolated per session."""

    def __init__(self):
        # Per-session memory stores: {session_id: {...}}
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ── Session management ───────────────────────────────────────────

    def _ensure_session(self, session_id: str) -> Dict[str, Any]:
        """Get or create a session store. Thread-safe."""
        if not session_id:
            session_id = "__default__"

        with self._lock:
            if session_id not in self._sessions:
                # Evict oldest sessions if we're over the limit
                if len(self._sessions) >= MAX_SESSIONS:
                    self._evict_oldest()
                self._sessions[session_id] = {
                    "created_at": time.time(),
                    "last_access": time.time(),
                    "short_term": [],
                    "long_term": {},
                    "semantic": {},
                }
            else:
                self._sessions[session_id]["last_access"] = time.time()

            return self._sessions[session_id]

    def _evict_oldest(self):
        """Remove the least recently accessed session that's past TTL."""
        now = time.time()
        candidates = [
            (sid, s["last_access"])
            for sid, s in self._sessions.items()
            if now - s["last_access"] > SESSION_TTL
        ]
        if candidates:
            oldest = min(candidates, key=lambda x: x[1])
            del self._sessions[oldest[0]]
        elif self._sessions:
            # No sessions past TTL — evict the least recently used anyway
            oldest = min(self._sessions.items(), key=lambda x: x[1]["last_access"])
            del self._sessions[oldest[0]]

    def session_exists(self, session_id: str) -> bool:
        """Check if a session exists and is active."""
        with self._lock:
            if session_id not in self._sessions:
                return False
            age = time.time() - self._sessions[session_id]["last_access"]
            return age < SESSION_TTL

    def session_count(self) -> int:
        """Return the number of active sessions."""
        with self._lock:
            return len(self._sessions)

    # ── Short-term memory (conversation turns) ───────────────────────

    def add_to_short_term(self, session_id: str, entry: Dict[str, Any]):
        """Add a conversation turn to this session's short-term memory."""
        s = self._ensure_session(session_id)
        s["short_term"].append({
            **entry,
            "timestamp": datetime.utcnow().isoformat(),
        })
        # Keep only last 10 turns
        if len(s["short_term"]) > 10:
            s["short_term"].pop(0)

    def get_short_term(self, session_id: str, last_n: int = 5) -> List[Dict]:
        """Get the last N conversation turns for this session."""
        s = self._ensure_session(session_id)
        return s["short_term"][-last_n:] if s["short_term"] else []

    def clear_short_term(self, session_id: str):
        """Clear conversation history for this session (user said /clear)."""
        s = self._ensure_session(session_id)
        s["short_term"].clear()

    # ── Long-term memory (user preferences, profile) ─────────────────

    def save_long_term(self, session_id: str, key: str, value: Any):
        """Save a persistent preference for this session's user."""
        s = self._ensure_session(session_id)
        s["long_term"][key] = value

    def get_long_term(self, session_id: str, key: str, default=None):
        """Retrieve a persistent preference."""
        s = self._ensure_session(session_id)
        return s["long_term"].get(key, default)

    def update_user_profile(self, session_id: str, profile: Dict[str, Any]):
        """Store or update the user profile for this session."""
        s = self._ensure_session(session_id)
        s["long_term"]["user_profile"] = {
            **(s["long_term"].get("user_profile") or {}),
            **profile,
        }

    def get_user_profile(self, session_id: str) -> Dict[str, Any]:
        """Get the user profile for this session."""
        return self.get_long_term(session_id, "user_profile", {})

    # ── Semantic memory (relationships, entities) ────────────────────

    def save_semantic(self, session_id: str, key: str, value: Any):
        """Store a semantic relationship (e.g., 'favorite_worker': 'worker04')."""
        s = self._ensure_session(session_id)
        s["semantic"][key] = value

    def get_semantic(self, session_id: str, key: str, default=None):
        """Retrieve a semantic relationship."""
        s = self._ensure_session(session_id)
        return s["semantic"].get(key, default)

    # ── Summary ──────────────────────────────────────────────────────

    def get_context_summary(self, session_id: str) -> Dict[str, Any]:
        """Return a summary of this session's memory state."""
        s = self._ensure_session(session_id)
        return {
            "session_id": session_id,
            "short_term_turns": len(s["short_term"]),
            "long_term_keys": list(s["long_term"].keys()),
            "has_profile": "user_profile" in s["long_term"],
            "session_age_s": round(time.time() - s["created_at"], 1),
            "total_sessions": len(self._sessions),
        }
