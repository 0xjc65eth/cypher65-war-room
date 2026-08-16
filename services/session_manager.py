"""
CYPHER65 // Session Manager
============================
Thread-safe session management for multi-user support.

Each session maintains:
  - session_id (str, UUID)
  - btc_address (str)
  - worker_name (str)
  - snapshot (dict) — latest polled data
  - created_at (int) — unix timestamp
  - last_activity (int) — unix timestamp, bumped on each snapshot/request
  - pending_address (str or None) — address waiting for first poll

Sessions expire after SESSION_TTL seconds of inactivity.
"""

import uuid
import time
import threading
import logging

log = logging.getLogger("cypher65.session")

# ── Default TTL: 1 hour ─────────────────────────────────────────────────────
SESSION_TTL = 3600  # seconds

# ── Cleanup interval ─────────────────────────────────────────────────────────
CLEANUP_INTERVAL = 300  # 5 minutes


class UserSession:
    """Data container for a single user session."""

    __slots__ = (
        "session_id",
        "btc_address",
        "worker_name",
        "snapshot",
        "created_at",
        "last_activity",
        "pending_address",
        "pending_worker_name",
    )

    def __init__(self, session_id: str, btc_address: str = "", worker_name: str = ""):
        self.session_id = session_id
        self.btc_address = btc_address
        self.worker_name = worker_name
        self.snapshot = {}
        now = int(time.time())
        self.created_at = now
        self.last_activity = now
        self.pending_address = None
        self.pending_worker_name = ""

    def touch(self):
        """Mark session as recently active."""
        self.last_activity = int(time.time())

    @property
    def has_wallet(self) -> bool:
        return bool(self.btc_address)

    @property
    def is_expired(self) -> bool:
        return (int(time.time()) - self.last_activity) > SESSION_TTL

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "btc_address": self.btc_address,
            "worker_name": self.worker_name,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "has_wallet": self.has_wallet,
        }


class SessionManager:
    """Thread-safe session store with automatic cleanup."""

    def __init__(self, ttl: int = SESSION_TTL):
        self._ttl = ttl
        self._sessions: dict[str, UserSession] = {}
        self._lock = threading.Lock()
        self._cleanup_timer: threading.Timer | None = None
        self._start_cleanup()

    # ── Public API ──────────────────────────────────────────────────────────

    def create_session(
        self, btc_address: str = "", worker_name: str = ""
    ) -> UserSession:
        """Create a new session and return it."""
        sid = uuid.uuid4().hex
        session = UserSession(sid, btc_address, worker_name)
        with self._lock:
            self._sessions[sid] = session
        log.info(
            "[session] created %s (addr=%s)",
            sid[:8],
            btc_address[:10] if btc_address else "none",
        )
        return session

    def get_session(self, session_id: str) -> UserSession | None:
        """Return session or None if missing/expired.

        Expiry honors the manager's configured TTL (self._ttl), not the
        module-level SESSION_TTL — a SessionManager(ttl=...) must behave
        consistently across get/destroy/cleanup."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if (int(time.time()) - session.last_activity) > self._ttl:
                self._sessions.pop(session_id, None)
                log.info("[session] expired %s", session_id[:8])
                return None
            session.touch()
            return session

    def destroy_session(self, session_id: str) -> bool:
        """Remove a session. Returns True if it existed."""
        with self._lock:
            existed = session_id in self._sessions
            self._sessions.pop(session_id, None)
            if existed:
                log.info("[session] destroyed %s", session_id[:8])
            return existed

    def update_wallet(
        self, session_id: str, btc_address: str, worker_name: str = ""
    ) -> bool:
        """Update the wallet address for an existing session."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.btc_address = btc_address
            session.worker_name = worker_name
            session.touch()
            return True

    def update_snapshot(self, session_id: str, snapshot: dict) -> bool:
        """Store a new snapshot for the session."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.snapshot = snapshot
            session.touch()
            return True

    def get_snapshot(self, session_id: str) -> dict | None:
        """Return the session's latest snapshot, or None."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if (int(time.time()) - session.last_activity) > self._ttl:
                self._sessions.pop(session_id, None)
                return None
            session.touch()
            return session.snapshot if session.snapshot else {}

    def get_all_sessions(self) -> list[UserSession]:
        """List all active sessions (for admin/debug)."""
        with self._lock:
            now = int(time.time())
            active = []
            expired_ids = []
            for sid, s in self._sessions.items():
                if (now - s.last_activity) > self._ttl:
                    expired_ids.append(sid)
                else:
                    active.append(s)
            for sid in expired_ids:
                self._sessions.pop(sid, None)
            return active

    def active_count(self) -> int:
        """Return number of non-expired sessions."""
        with self._lock:
            now = int(time.time())
            count = 0
            expired = []
            for sid, s in self._sessions.items():
                if (now - s.last_activity) > self._ttl:
                    expired.append(sid)
                else:
                    count += 1
            for sid in expired:
                self._sessions.pop(sid, None)
            return count

    # ── Cleanup ─────────────────────────────────────────────────────────────

    def _start_cleanup(self):
        """Start the background cleanup loop."""
        self._cleanup_timer = threading.Timer(CLEANUP_INTERVAL, self._cleanup_task)
        self._cleanup_timer.daemon = True
        self._cleanup_timer.start()

    def _cleanup_task(self):
        """Remove expired sessions and reschedule."""
        try:
            removed = 0
            now = int(time.time())
            with self._lock:
                expired = [
                    sid
                    for sid, s in self._sessions.items()
                    if (now - s.last_activity) > self._ttl
                ]
                for sid in expired:
                    self._sessions.pop(sid, None)
                    removed += 1
            if removed:
                log.info("[cleanup] removed %d expired session(s)", removed)
        except Exception as e:
            log.warning("[cleanup] error: %s", e)
        finally:
            self._start_cleanup()

    def stop(self):
        """Cancel the cleanup timer (called on shutdown)."""
        if self._cleanup_timer:
            self._cleanup_timer.cancel()
            self._cleanup_timer = None
