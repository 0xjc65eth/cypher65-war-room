"""Read-only readiness checks for the traction-gated Postgres migration.

This module does not mutate SQLite, contact a Postgres server, or switch the
application backend. Its job is to make the gate measurable and prevent an
operator from mistaking credentials for a completed migration rehearsal.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import requests

from services.remote_backup import GIST_FILENAME
from services.schema import CURRENT_SCHEMA_VERSION


TRACTION_PAID_LICENSES = 10
PAID_LICENSE_SOURCES = frozenset({"btcpay", "lemon_squeezy", "webln"})
POSTGRES_DSN_ENV = ("POSTGRES_DSN", "DATABASE_URL")

_TYPE_MAP = {
    "INTEGER": "BIGINT",
    "REAL": "DOUBLE PRECISION",
    "TEXT": "TEXT",
    "BLOB": "BYTEA",
    "NUMERIC": "NUMERIC",
}

PORTABILITY_BLOCKERS = (
    "services.db.get_db returns sqlite3.Connection and configures PRAGMA",
    "application SQL uses SQLite '?' placeholders and SQLite date functions",
    "schema bootstrapping is distributed across app.py and service modules",
    "AUTOINCREMENT columns require Postgres identity/sequence mapping",
)


class ReadinessError(RuntimeError):
    """A requested source cannot be inspected safely."""


def _read_only_connection(db_path: str | os.PathLike[str]) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise ReadinessError(f"SQLite database not found: {path}")
    # mode=ro prevents accidental CREATE/UPDATE and still observes committed
    # WAL pages (unlike immutable=1 on a live database).
    try:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        # Force the pager to open now; sqlite3.connect itself is lazy.
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
    except sqlite3.DatabaseError as exc:
        try:
            conn.close()
        except UnboundLocalError:
            pass
        wal_path = Path(f"{path}-wal")
        if wal_path.exists() and wal_path.stat().st_size > 0:
            raise ReadinessError(
                "read-only SQLite open failed while a non-empty WAL exists; "
                "create an online backup before inspecting"
            ) from exc
        # Some managed/sandboxed filesystems reject SQLite's read-only lock
        # probe. With no WAL, immutable mode sees the complete database and
        # cannot create journal/shm files.
        try:
            conn = sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        except sqlite3.DatabaseError as fallback_exc:
            raise ReadinessError(
                "SQLite database cannot be opened read-only"
            ) from fallback_exc
    conn.row_factory = sqlite3.Row
    return conn


def _postgres_type(sqlite_type: str) -> str:
    declared = (sqlite_type or "").strip().upper()
    if "INT" in declared:
        return _TYPE_MAP["INTEGER"]
    if any(token in declared for token in ("CHAR", "CLOB", "TEXT")):
        return _TYPE_MAP["TEXT"]
    if not declared or "BLOB" in declared:
        return _TYPE_MAP["BLOB"]
    if any(token in declared for token in ("REAL", "FLOA", "DOUB")):
        return _TYPE_MAP["REAL"]
    return _TYPE_MAP["NUMERIC"]


def _table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [str(row[0]) for row in rows]


def schema_map(db_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Return a deterministic SQLite-to-Postgres schema inventory.

    Defaults remain source text because expressions such as ``strftime`` need
    review before becoming Postgres DDL. No user rows are included.
    """

    conn = _read_only_connection(db_path)
    try:
        tables: list[dict[str, Any]] = []
        for table in _table_names(conn):
            # Names originate from sqlite_master, never request input.
            quoted_table = table.replace('"', '""')
            columns = conn.execute(f'PRAGMA table_info("{quoted_table}")').fetchall()
            indexes = conn.execute(f'PRAGMA index_list("{quoted_table}")').fetchall()
            index_map = []
            for index in indexes:
                index_name = str(index[1])
                quoted_index = index_name.replace('"', '""')
                index_columns = conn.execute(
                    f'PRAGMA index_info("{quoted_index}")'
                ).fetchall()
                index_map.append(
                    {
                        "name": index_name,
                        "unique": bool(index[2]),
                        "origin": str(index[3]),
                        "partial": bool(index[4]),
                        "columns": [column[2] for column in index_columns],
                    }
                )
            foreign_keys = conn.execute(
                f'PRAGMA foreign_key_list("{quoted_table}")'
            ).fetchall()
            tables.append(
                {
                    "table": table,
                    "columns": [
                        {
                            "name": str(column[1]),
                            "sqlite_type": str(column[2] or ""),
                            "postgres_type": _postgres_type(str(column[2] or "")),
                            "nullable": not bool(column[3]) and not bool(column[5]),
                            "default": column[4],
                            "primary_key_position": int(column[5]),
                        }
                        for column in columns
                    ],
                    "indexes": sorted(index_map, key=lambda item: item["name"]),
                    "foreign_keys": [
                        {
                            "id": int(key[0]),
                            "position": int(key[1]),
                            "target_table": str(key[2]),
                            "source_column": str(key[3]),
                            "target_column": str(key[4]),
                            "on_update": str(key[5]),
                            "on_delete": str(key[6]),
                        }
                        for key in foreign_keys
                    ],
                }
            )
        canonical = json.dumps(tables, sort_keys=True, separators=(",", ":"))
        return {
            "schema_version_expected": CURRENT_SCHEMA_VERSION,
            "schema_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "table_count": len(tables),
            "tables": tables,
            "mapping_notes": [
                "INTEGER PRIMARY KEY AUTOINCREMENT -> BIGINT GENERATED BY DEFAULT AS IDENTITY",
                "SQLite INTEGER booleans -> Postgres BOOLEAN after a 0/1 data check",
                "TEXT timestamps remain TEXT until all producers use one timezone-aware format",
                "SQLite defaults and indexes require review before generated DDL is applied",
            ],
        }
    except sqlite3.DatabaseError as exc:
        raise ReadinessError("SQLite schema inventory failed") from exc
    finally:
        conn.close()


def _parse_expiry(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        # Malformed expiry must fail closed, never count as active traction.
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _active_paid_licenses(conn: sqlite3.Connection, now: datetime) -> int:
    if "pro_licenses" not in _table_names(conn):
        return 0
    rows = conn.execute(
        "SELECT plan, source, expires_at FROM pro_licenses WHERE revoked_at IS NULL"
    ).fetchall()
    active = 0
    for row in rows:
        source = str(row["source"] or "").strip().lower()
        plan = str(row["plan"] or "").strip().lower()
        expiry = _parse_expiry(row["expires_at"])
        if (
            source in PAID_LICENSE_SOURCES
            and plan in {"pro", "premium"}
            and (expiry is None or expiry > now)
        ):
            active += 1
    return active


def _schema_version(conn: sqlite3.Connection) -> int | None:
    if "schema_version" not in _table_names(conn):
        return None
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _configured_postgres(env: Mapping[str, str]) -> bool:
    for key in POSTGRES_DSN_ENV:
        value = (env.get(key) or "").strip()
        if value.startswith(("postgres://", "postgresql://")):
            return True
    return False


def readiness_report(
    db_path: str | os.PathLike[str],
    *,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Measure the gate without exposing credentials or database rows."""

    effective_env = os.environ if env is None else env
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    path = Path(db_path).expanduser().resolve()
    conn = _read_only_connection(path)
    try:
        integrity_row = conn.execute("PRAGMA integrity_check").fetchone()
        integrity = str(integrity_row[0] if integrity_row else "unknown")
        version = _schema_version(conn)
        paid = _active_paid_licenses(conn, current_time)
    except sqlite3.DatabaseError as exc:
        raise ReadinessError("SQLite integrity inspection failed") from exc
    finally:
        conn.close()

    traction_met = paid >= TRACTION_PAID_LICENSES
    gist_configured = bool(
        (effective_env.get("GITHUB_TOKEN") or "").strip()
        and (effective_env.get("REMOTE_BACKUP_GIST_ID") or "").strip()
    )
    postgres_configured = _configured_postgres(effective_env)
    source_valid = integrity == "ok" and version == CURRENT_SCHEMA_VERSION

    if not source_valid:
        decision = "blocked"
        reason = "SQLite integrity or schema version is not acceptable"
    elif not traction_met:
        decision = "hold"
        reason = "traction threshold not reached"
    elif not (gist_configured and postgres_configured):
        decision = "rehearsal-required"
        reason = "real Gist source and Postgres target are not both configured"
    else:
        decision = "ready-for-rehearsal"
        reason = "credentials exist; a real migration rehearsal is still required"

    return {
        "decision": decision,
        "reason": reason,
        "traction": {
            "metric": "active_paid_pro_or_premium_licenses",
            "paid_sources": sorted(PAID_LICENSE_SOURCES),
            "current": paid,
            "threshold": TRACTION_PAID_LICENSES,
            "met": traction_met,
        },
        "sqlite": {
            "bytes": path.stat().st_size,
            "integrity": integrity,
            "schema_version": version,
            "expected_schema_version": CURRENT_SCHEMA_VERSION,
            "schema_compatible": source_valid,
        },
        "external_prerequisites": {
            "private_gist_pinned": gist_configured,
            "postgres_dsn_configured": postgres_configured,
            "values_redacted": True,
        },
        "application_portability": {
            "ready": False,
            "blockers": list(PORTABILITY_BLOCKERS),
        },
        "cutover_authorized": False,
    }


def fetch_pinned_gist_snapshot(
    *, env: Mapping[str, str] | None = None, timeout: int = 20
) -> bytes:
    """Download, decode and validate the explicitly pinned private Gist.

    Unlike runtime discovery, this function is read-only and never creates a
    Gist. It returns raw SQLite bytes and never includes the token in errors.
    """

    effective_env = os.environ if env is None else env
    token = (effective_env.get("GITHUB_TOKEN") or "").strip()
    gist_id = (effective_env.get("REMOTE_BACKUP_GIST_ID") or "").strip()
    if not token or not gist_id:
        raise ReadinessError(
            "GITHUB_TOKEN and REMOTE_BACKUP_GIST_ID are required for a real Gist check"
        )
    if not re.fullmatch(r"[0-9a-fA-F]{5,64}", gist_id):
        raise ReadinessError("REMOTE_BACKUP_GIST_ID is not a valid Gist identifier")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        response = requests.get(
            f"https://api.github.com/gists/{gist_id}", headers=headers, timeout=timeout
        )
    except requests.RequestException as exc:
        raise ReadinessError(
            "Gist download failed before receiving a response"
        ) from exc
    if not response.ok:
        raise ReadinessError(f"Gist download failed with HTTP {response.status_code}")
    try:
        response_body = response.json() or {}
    except ValueError as exc:
        raise ReadinessError("Gist API returned invalid JSON") from exc
    if not isinstance(response_body, dict):
        raise ReadinessError("Gist API returned an unexpected JSON payload")
    file_info = (response_body.get("files") or {}).get(GIST_FILENAME) or {}
    if not isinstance(file_info, dict):
        raise ReadinessError("Gist backup file metadata is invalid")
    content = file_info.get("content") or ""
    if file_info.get("truncated"):
        raw_url = file_info.get("raw_url") or ""
        if not raw_url:
            raise ReadinessError("Gist backup is truncated and has no raw URL")
        parsed_raw_url = urlparse(raw_url)
        if (
            parsed_raw_url.scheme != "https"
            or parsed_raw_url.hostname != "gist.githubusercontent.com"
        ):
            raise ReadinessError("Gist raw backup URL has an unexpected origin")
        try:
            raw_response = requests.get(raw_url, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            raise ReadinessError(
                "Gist raw backup download failed before receiving a response"
            ) from exc
        if not raw_response.ok:
            raise ReadinessError(
                f"Gist raw backup download failed with HTTP {raw_response.status_code}"
            )
        content = raw_response.text
    if not isinstance(content, str):
        raise ReadinessError("Gist backup content is invalid")
    try:
        raw = base64.b64decode(content.encode("ascii"), validate=True)
    except (binascii.Error, ValueError, UnicodeError) as exc:
        raise ReadinessError("Gist backup is not valid base64") from exc
    if not raw.startswith(b"SQLite format 3\x00"):
        raise ReadinessError("Gist backup is not a SQLite database")
    return raw
