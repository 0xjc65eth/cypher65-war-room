"""Persistent safety ledger for external side effects.

The ledger separates dispatch, provider/device acknowledgement and observed
reconciliation.  It also provides one-time, payload-bound confirmations and
an atomic idempotency claim.  Raw payloads and credentials are never stored.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
from typing import Any, Dict, Optional


CONFIRMATION_TTL_SECONDS = 120
FINAL_STATES = frozenset({"reconciled", "rejected", "dispatch_failed"})


def _db_path() -> str:
    return os.environ.get("DB_PATH", "data/war_room.sqlite")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=3)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def payload_hash(payload: Dict[str, Any]) -> str:
    """Return a stable digest without retaining the payload itself."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def ensure_tables(conn: Optional[sqlite3.Connection] = None) -> None:
    own = conn is None
    connection = conn or _connect()
    try:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS external_operations (
                operation_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                target TEXT NOT NULL,
                action TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                idempotency_key TEXT,
                state TEXT NOT NULL,
                ack_state TEXT NOT NULL DEFAULT 'not_received',
                reconciliation_state TEXT NOT NULL DEFAULT 'pending',
                provider_reference TEXT,
                safe_result_json TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                ack_at INTEGER,
                reconciled_at INTEGER,
                UNIQUE(tenant_id, kind, idempotency_key)
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS operation_confirmations (
                token_hash TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                target TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                issued_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                consumed_at INTEGER
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_external_operations_tenant "
            "ON external_operations(tenant_id, kind, created_at DESC)"
        )
        if own:
            connection.commit()
    finally:
        if own:
            connection.close()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_confirmation(
    tenant_id: str,
    kind: str,
    target: str,
    payload: Dict[str, Any],
    *,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    issued_at = int(time.time() if now is None else now)
    expires_at = issued_at + CONFIRMATION_TTL_SECONDS
    token = secrets.token_urlsafe(32)
    conn = _connect()
    try:
        ensure_tables(conn)
        conn.execute(
            "DELETE FROM operation_confirmations WHERE expires_at < ?", (issued_at,)
        )
        conn.execute(
            """INSERT INTO operation_confirmations
            (token_hash, tenant_id, kind, target, request_hash, issued_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                _token_hash(token),
                tenant_id or "default",
                kind,
                target,
                payload_hash(payload),
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
    kind: str,
    target: str,
    payload: Dict[str, Any],
    *,
    now: Optional[int] = None,
) -> bool:
    """Atomically burn a token, including on a binding mismatch."""
    if not isinstance(token, str) or len(token) < 32:
        return False
    consumed_at = int(time.time() if now is None else now)
    conn = _connect()
    try:
        ensure_tables(conn)
        token_digest = _token_hash(token)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT tenant_id, kind, target, request_hash, expires_at, consumed_at
               FROM operation_confirmations WHERE token_hash = ?""",
            (token_digest,),
        ).fetchone()
        valid = bool(
            row
            and row["tenant_id"] == (tenant_id or "default")
            and row["kind"] == kind
            and row["target"] == target
            and row["request_hash"] == payload_hash(payload)
            and row["expires_at"] >= consumed_at
            and row["consumed_at"] is None
        )
        if row and row["consumed_at"] is None:
            conn.execute(
                "UPDATE operation_confirmations SET consumed_at = ? WHERE token_hash = ?",
                (consumed_at, token_digest),
            )
        conn.commit()
        return valid
    finally:
        conn.close()


def claim_operation(
    tenant_id: str,
    kind: str,
    target: str,
    action: str,
    payload: Dict[str, Any],
    *,
    idempotency_key: str = "",
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """Atomically claim an operation or return the existing claim."""
    ts = int(time.time() if now is None else now)
    tenant = tenant_id or "default"
    key = str(idempotency_key or "").strip() or None
    digest = payload_hash(payload)
    operation_id = uuid.uuid4().hex
    conn = _connect()
    try:
        ensure_tables(conn)
        conn.execute("BEGIN IMMEDIATE")
        existing = None
        if key:
            existing = conn.execute(
                """SELECT * FROM external_operations
                   WHERE tenant_id = ? AND kind = ? AND idempotency_key = ?""",
                (tenant, kind, key),
            ).fetchone()
        if existing:
            conn.commit()
            record = _row_to_dict(existing)
            record["created"] = False
            record["payload_matches"] = existing["request_hash"] == digest
            return record
        conn.execute(
            """INSERT INTO external_operations
            (operation_id, tenant_id, kind, target, action, request_hash,
             idempotency_key, state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'submitting', ?, ?)""",
            (
                operation_id,
                tenant,
                kind,
                target,
                action,
                digest,
                key,
                ts,
                ts,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "operation_id": operation_id,
        "tenant_id": tenant,
        "kind": kind,
        "target": target,
        "action": action,
        "request_hash": digest,
        "idempotency_key": key,
        "state": "submitting",
        "ack_state": "not_received",
        "reconciliation_state": "pending",
        "created_at": ts,
        "updated_at": ts,
        "created": True,
        "payload_matches": True,
    }


def update_operation(
    operation_id: str,
    *,
    state: str,
    ack_state: Optional[str] = None,
    reconciliation_state: Optional[str] = None,
    provider_reference: str = "",
    safe_result: Optional[Dict[str, Any]] = None,
    now: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    ts = int(time.time() if now is None else now)
    result_json = json.dumps(safe_result or {}, separators=(",", ":"), sort_keys=True)
    conn = _connect()
    try:
        ensure_tables(conn)
        current = conn.execute(
            "SELECT * FROM external_operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if not current:
            return None
        ack = ack_state or current["ack_state"]
        reconciliation = reconciliation_state or current["reconciliation_state"]
        ack_at = (
            ts
            if ack == "acknowledged" and current["ack_at"] is None
            else current["ack_at"]
        )
        reconciled_at = (
            ts
            if reconciliation in {"confirmed", "failed"}
            and current["reconciled_at"] is None
            else current["reconciled_at"]
        )
        conn.execute(
            """UPDATE external_operations
               SET state = ?, ack_state = ?, reconciliation_state = ?,
                   provider_reference = ?, safe_result_json = ?, updated_at = ?,
                   ack_at = ?, reconciled_at = ?
               WHERE operation_id = ?""",
            (
                state,
                ack,
                reconciliation,
                str(provider_reference or "")[:128],
                result_json,
                ts,
                ack_at,
                reconciled_at,
                operation_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_operation(operation_id)


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    record = dict(row)
    try:
        record["safe_result"] = json.loads(record.pop("safe_result_json") or "{}")
    except (TypeError, ValueError):
        record["safe_result"] = {}
        record.pop("safe_result_json", None)
    return record


def get_operation(operation_id: str) -> Optional[Dict[str, Any]]:
    conn = _connect()
    try:
        ensure_tables(conn)
        row = conn.execute(
            "SELECT * FROM external_operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def get_by_idempotency(
    tenant_id: str, kind: str, idempotency_key: str
) -> Optional[Dict[str, Any]]:
    conn = _connect()
    try:
        ensure_tables(conn)
        row = conn.execute(
            """SELECT * FROM external_operations
               WHERE tenant_id = ? AND kind = ? AND idempotency_key = ?""",
            (tenant_id or "default", kind, idempotency_key),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()
