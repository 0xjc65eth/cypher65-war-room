"""Encrypted, tenant-bound rollback targets for pool mutations.

Pool endpoint and worker identity are operational secrets.  The command ledger
therefore keeps only hashes, while this store keeps the previous complete pool
configuration authenticated-encrypted for a short, bounded rollback window.
Public callers receive only controlled reason codes and availability metadata.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
import sqlite3
import time
from typing import Any, Mapping, Optional

from cryptography.fernet import Fernet, InvalidToken

from .configuration import PoolConfigurationError, validate_pool_configuration


_KEY_DOMAIN = b"cypher65:pool-rollback:v1\x00"
_DEFAULT_TTL_SECONDS = 86_400
_MIN_TTL_SECONDS = 300
_MAX_TTL_SECONDS = 604_800


class PoolRollbackError(RuntimeError):
    """A rollback target cannot be stored or recovered safely."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PoolRollbackTarget:
    """Decrypted target for immediate internal use only."""

    source_operation_id: str
    tenant_id: str
    device_id: str
    target_hash: str
    parameters: dict[str, Any]
    expires_at: int


def _db_path() -> str:
    return os.environ.get("DB_PATH", "data/war_room.sqlite")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=3)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def _cipher() -> Fernet:
    secret = (os.environ.get("SECRET_KEY") or "").strip()
    if not secret:
        raise PoolRollbackError("rollback_encryption_unavailable")
    digest = hashlib.sha256(_KEY_DOMAIN + secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def rollback_encryption_ready() -> bool:
    """Return whether a stable environment key can seal a rollback target."""
    try:
        _cipher()
    except PoolRollbackError:
        return False
    return True


def _ttl_seconds() -> int:
    try:
        configured = int(
            os.environ.get("POOL_ROLLBACK_TARGET_TTL_SECONDS", _DEFAULT_TTL_SECONDS)
        )
    except (TypeError, ValueError):
        configured = _DEFAULT_TTL_SECONDS
    return max(_MIN_TTL_SECONDS, min(configured, _MAX_TTL_SECONDS))


def _canonical_parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return validate_pool_configuration(parameters).to_adapter_parameters()
    except (PoolConfigurationError, TypeError, ValueError) as exc:
        raise PoolRollbackError("rollback_target_invalid") from exc


def _payload_hash(parameters: dict[str, Any]) -> str:
    canonical = json.dumps(
        parameters, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def ensure_table(conn: Optional[sqlite3.Connection] = None) -> None:
    own_connection = conn is None
    connection = conn or _connect()
    try:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS pool_rollback_targets (
                source_operation_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                target_hash TEXT NOT NULL,
                sealed_payload TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                claimed_at INTEGER,
                claimed_by_operation_id TEXT
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_pool_rollback_target_scope "
            "ON pool_rollback_targets(tenant_id, device_id, expires_at)"
        )
        if own_connection:
            connection.commit()
    finally:
        if own_connection:
            connection.close()


def _purge_expired(connection: sqlite3.Connection, now: int) -> None:
    connection.execute("DELETE FROM pool_rollback_targets WHERE expires_at < ?", (now,))


def store_pool_rollback_target(
    source_operation_id: str,
    tenant_id: str,
    device_id: str,
    parameters: Mapping[str, Any],
    *,
    now: Optional[int] = None,
) -> PoolRollbackTarget:
    """Seal and persist one previous pool configuration.

    An operation id is single-assignment.  Replacing an existing target could
    redirect an already approved rollback, so conflicts fail closed.
    """
    created_at = int(time.time() if now is None else now)
    expires_at = created_at + _ttl_seconds()
    tenant = tenant_id or "default"
    canonical = _canonical_parameters(parameters)
    target_hash = _payload_hash(canonical)
    payload = json.dumps(
        {
            "version": 1,
            "source_operation_id": source_operation_id,
            "tenant_id": tenant,
            "device_id": device_id,
            "target_hash": target_hash,
            "parameters": canonical,
            "expires_at": expires_at,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    sealed = _cipher().encrypt(payload).decode("ascii")

    conn = _connect()
    try:
        ensure_table(conn)
        _purge_expired(conn, created_at)
        conn.execute(
            """INSERT INTO pool_rollback_targets
            (source_operation_id, tenant_id, device_id, target_hash,
             sealed_payload, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                source_operation_id,
                tenant,
                device_id,
                target_hash,
                sealed,
                created_at,
                expires_at,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise PoolRollbackError("rollback_target_conflict") from exc
    finally:
        conn.close()
    return PoolRollbackTarget(
        source_operation_id=source_operation_id,
        tenant_id=tenant,
        device_id=device_id,
        target_hash=target_hash,
        parameters=canonical,
        expires_at=expires_at,
    )


def _decode_row(row: sqlite3.Row, *, now: int) -> PoolRollbackTarget:
    if row["expires_at"] < now:
        raise PoolRollbackError("rollback_target_expired")
    if row["claimed_by_operation_id"]:
        raise PoolRollbackError("rollback_target_already_claimed")
    try:
        raw = _cipher().decrypt(row["sealed_payload"].encode("ascii"))
        payload = json.loads(raw)
    except (InvalidToken, UnicodeError, ValueError, TypeError) as exc:
        raise PoolRollbackError("rollback_target_invalid") from exc
    if not isinstance(payload, dict):
        raise PoolRollbackError("rollback_target_invalid")
    identity = (
        payload.get("version") == 1
        and payload.get("source_operation_id") == row["source_operation_id"]
        and payload.get("tenant_id") == row["tenant_id"]
        and payload.get("device_id") == row["device_id"]
        and payload.get("target_hash") == row["target_hash"]
        and payload.get("expires_at") == row["expires_at"]
    )
    if not identity:
        raise PoolRollbackError("rollback_target_invalid")
    canonical = _canonical_parameters(payload.get("parameters"))
    if _payload_hash(canonical) != row["target_hash"]:
        raise PoolRollbackError("rollback_target_invalid")
    return PoolRollbackTarget(
        source_operation_id=row["source_operation_id"],
        tenant_id=row["tenant_id"],
        device_id=row["device_id"],
        target_hash=row["target_hash"],
        parameters=canonical,
        expires_at=row["expires_at"],
    )


def load_pool_rollback_target(
    source_operation_id: str,
    tenant_id: str,
    device_id: str,
    *,
    now: Optional[int] = None,
) -> PoolRollbackTarget:
    checked_at = int(time.time() if now is None else now)
    conn = _connect()
    try:
        ensure_table(conn)
        row = conn.execute(
            """SELECT * FROM pool_rollback_targets
               WHERE source_operation_id = ? AND tenant_id = ? AND device_id = ?""",
            (source_operation_id, tenant_id or "default", device_id),
        ).fetchone()
        if not row:
            raise PoolRollbackError("rollback_target_unavailable")
        if row["expires_at"] < checked_at:
            conn.execute(
                "DELETE FROM pool_rollback_targets WHERE source_operation_id = ?",
                (source_operation_id,),
            )
            conn.commit()
            raise PoolRollbackError("rollback_target_expired")
        return _decode_row(row, now=checked_at)
    finally:
        conn.close()


def claim_pool_rollback_target(
    source_operation_id: str,
    tenant_id: str,
    device_id: str,
    rollback_operation_id: str,
    *,
    now: Optional[int] = None,
) -> PoolRollbackTarget:
    """Atomically reserve a target before the only allowed rollback dispatch."""
    claimed_at = int(time.time() if now is None else now)
    conn = _connect()
    try:
        ensure_table(conn)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT * FROM pool_rollback_targets
               WHERE source_operation_id = ? AND tenant_id = ? AND device_id = ?""",
            (source_operation_id, tenant_id or "default", device_id),
        ).fetchone()
        if not row:
            raise PoolRollbackError("rollback_target_unavailable")
        if row["expires_at"] < claimed_at:
            conn.execute(
                "DELETE FROM pool_rollback_targets WHERE source_operation_id = ?",
                (source_operation_id,),
            )
            conn.commit()
            raise PoolRollbackError("rollback_target_expired")
        target = _decode_row(row, now=claimed_at)
        updated = conn.execute(
            """UPDATE pool_rollback_targets
               SET claimed_at = ?, claimed_by_operation_id = ?
               WHERE source_operation_id = ? AND claimed_by_operation_id IS NULL""",
            (claimed_at, rollback_operation_id, source_operation_id),
        )
        if updated.rowcount != 1:
            raise PoolRollbackError("rollback_target_already_claimed")
        conn.commit()
        return target
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
