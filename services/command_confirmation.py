"""One-time, tenant-scoped confirmations for physical miner commands.

The confirmation token is intentionally persisted in SQLite rather than kept
only in memory: command preparation and execution may reach different WSGI
processes. Tokens are stored as SHA-256 digests, are bound to the exact
tenant/device/command/parameters tuple, expire quickly, and are consumed with
one atomic UPDATE.
"""

import hashlib
import json
import os
import secrets
import sqlite3
import time
from typing import Any, Dict, Optional


CONFIRMATION_TTL_SECONDS = 120
CONFIRMABLE_COMMANDS = frozenset({"restart", "pause"})


def requires_confirmation(command: str) -> bool:
    """Return whether this physical command requires a server confirmation."""
    return str(command or "").strip().lower() in CONFIRMABLE_COMMANDS


def _db_path() -> str:
    """Resolve the database path at call time so tests can isolate it."""
    return os.environ.get("DB_PATH", "data/war_room.sqlite")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=3)
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def ensure_table(conn: Optional[sqlite3.Connection] = None) -> None:
    """Create the confirmation store idempotently.

    The optional connection lets callers include the DDL in their existing
    startup transaction. Runtime calls are still safe for legacy databases.
    """
    own_connection = conn is None
    connection = conn or _connect()
    try:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS command_confirmations (
                token_hash TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                command TEXT NOT NULL,
                parameters_hash TEXT NOT NULL,
                issued_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                consumed_at INTEGER
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_command_confirmations_expiry "
            "ON command_confirmations(expires_at)"
        )
        if own_connection:
            connection.commit()
    finally:
        if own_connection:
            connection.close()


def _parameters_hash(parameters: Dict[str, Any]) -> str:
    canonical = json.dumps(
        parameters, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_confirmation(
    tenant_id: str,
    device_id: str,
    command: str,
    parameters: Optional[Dict[str, Any]] = None,
    *,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """Issue a one-time confirmation for an already validated operation."""
    normalized_command = str(command or "").strip().lower()
    normalized_parameters = parameters or {}
    if not isinstance(normalized_parameters, dict):
        raise ValueError("parameters must be an object")
    if not requires_confirmation(normalized_command):
        raise ValueError("command does not require confirmation")

    issued_at = int(time.time() if now is None else now)
    expires_at = issued_at + CONFIRMATION_TTL_SECONDS
    token = secrets.token_urlsafe(32)
    conn = _connect()
    try:
        ensure_table(conn)
        # Expired confirmations cannot authorize anything and need not remain
        # in the operational database forever.
        conn.execute(
            "DELETE FROM command_confirmations WHERE expires_at < ?", (issued_at,)
        )
        conn.execute(
            """INSERT INTO command_confirmations
            (token_hash, tenant_id, device_id, command, parameters_hash, issued_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                _token_hash(token),
                tenant_id or "default",
                device_id,
                normalized_command,
                _parameters_hash(normalized_parameters),
                issued_at,
                expires_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {"confirmation_token": token, "expires_at": expires_at}


def consume_confirmation(
    token: object,
    tenant_id: str,
    device_id: str,
    command: str,
    parameters: Optional[Dict[str, Any]] = None,
    *,
    now: Optional[int] = None,
) -> bool:
    """Consume a confirmation once, returning ``False`` for every mismatch.

    A single conditional UPDATE makes concurrent/replayed consumes fail closed:
    only the first valid request can change ``consumed_at`` from NULL.
    """
    if not isinstance(token, str) or len(token) < 32:
        return False
    normalized_parameters = parameters or {}
    if not isinstance(normalized_parameters, dict):
        return False

    consumed_at = int(time.time() if now is None else now)
    conn = _connect()
    try:
        ensure_table(conn)
        cursor = conn.execute(
            """UPDATE command_confirmations
               SET consumed_at = ?
             WHERE token_hash = ?
               AND tenant_id = ?
               AND device_id = ?
               AND command = ?
               AND parameters_hash = ?
               AND expires_at >= ?
               AND consumed_at IS NULL""",
            (
                consumed_at,
                _token_hash(token),
                tenant_id or "default",
                device_id,
                str(command or "").strip().lower(),
                _parameters_hash(normalized_parameters),
                consumed_at,
            ),
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()
