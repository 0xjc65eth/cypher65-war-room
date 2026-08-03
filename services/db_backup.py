"""
CYPHER65 — Automatic SQLite backup & integrity (C4)
====================================================
Root-cause hardening for the recurring DB corruption incident
(idx_maintenance_records_ts / idx_audit_logs_tenant_ts).

Design decisions:
- Online backup API (``sqlite3.Connection.backup``) is crash-safe with
  concurrent writers — unlike a raw file copy, it never produces a torn
  snapshot, so the periodic backup itself can never corrupt the DB.
- Env-gated and ON by default: ``AUTO_BACKUP_INTERVAL`` (seconds, default
  3600) with ``AUTO_BACKUP_INTERVAL=0`` disabling the worker entirely.
  ``AUTO_BACKUP_KEEP`` (default 5) controls retention.
- The boot-time integrity check is a *warning*, never an auto-restore:
  restoring over a possibly-live writer (Docker/Colima volume mount) would
  be destructive, so we log CRITICAL and point at the newest backup.
"""

import logging
import os
import re
import sqlite3
import time
from pathlib import Path

log = logging.getLogger("cypher65.backup")

DEFAULT_INTERVAL = 3600  # 1h — matches Docker/Colima telemetry cadence
DEFAULT_KEEP = 5


def _env_interval() -> int:
    """AUTO_BACKUP_INTERVAL in seconds (0 disables). Read lazily so tests
    can flip the knob after import."""
    try:
        return int(os.environ.get("AUTO_BACKUP_INTERVAL", str(DEFAULT_INTERVAL)))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL


def _env_keep() -> int:
    try:
        return int(os.environ.get("AUTO_BACKUP_KEEP", str(DEFAULT_KEEP)))
    except (TypeError, ValueError):
        return DEFAULT_KEEP


def backup_enabled() -> bool:
    return _env_interval() > 0


def _resolve_db_path(db_path=None) -> str:
    return db_path or os.environ.get("DB_PATH", "data/war_room.sqlite")


def _default_backup_dir(db_path=None) -> str:
    return str(Path(_resolve_db_path(db_path)).parent / "backups")


def backup_now(db_path=None, dest_dir=None, keep=None):
    """Snapshot the SQLite DB via the online backup API.

    Returns the destination path. Safe to run while the app is writing
    (WAL mode) — ``Connection.backup`` produces a consistent snapshot even
    under concurrent writers. Old backups beyond ``keep`` are pruned.
    """
    db_path = _resolve_db_path(db_path)
    dest_dir = dest_dir or _default_backup_dir(db_path)
    keep = _env_keep() if keep is None else keep

    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    # Microsecond suffix — a raw int(time.time()) collides when snapshots
    # happen within the same second (e.g. rapid test loops or a boot + early
    # retry), silently overwriting the previous backup.
    ts_us = time.time_ns() // 1000
    dest = os.path.join(dest_dir, "war_room.sqlite.bak.%d" % ts_us)

    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    prune_backups(dest_dir, keep=keep)
    log.info("[backup] snapshot -> %s (%.0f KB)", dest, Path(dest).stat().st_size / 1024)
    return dest


_BACKUP_RE = re.compile(r"war_room\.sqlite\.bak\.(\d+)$")


def _backup_sort_key(path):
    """Sort by the microsecond timestamp embedded in the filename — more
    deterministic than mtime (ties are impossible across rapid snapshots)."""
    m = _BACKUP_RE.search(path.name)
    return int(m.group(1)) if m else 0


def prune_backups(dest_dir, keep=None):
    """Keep the ``keep`` newest backups in dest_dir, delete the rest."""
    keep = _env_keep() if keep is None else keep
    if keep <= 0:
        return
    files = sorted(
        Path(dest_dir).glob("war_room.sqlite.bak.*"),
        key=_backup_sort_key,
        reverse=True,
    )
    for old in files[keep:]:
        try:
            old.unlink()
            log.info("[backup] pruned %s", old.name)
        except OSError as e:
            log.warning("[backup] prune failed %s: %s", old.name, e)


def latest_backup(db_path=None, dest_dir=None):
    """Path of the newest backup, or None if none exist."""
    dest_dir = dest_dir or _default_backup_dir(db_path)
    files = sorted(
        Path(dest_dir).glob("war_room.sqlite.bak.*"),
        key=_backup_sort_key,
        reverse=True,
    )
    return str(files[0]) if files else None


def integrity_ok(db_path=None) -> bool:
    """PRAGMA integrity_check — True only when the DB reports 'ok'.

    Returns True for a missing file (nothing to check) so a fresh boot
    doesn't log a false alarm before init_db() runs.
    """
    db_path = _resolve_db_path(db_path)
    if not Path(db_path).exists():
        return True
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            return bool(row and row[0] == "ok")
        finally:
            conn.close()
    except sqlite3.Error as e:
        log.error("[backup] integrity_check error on %s: %s", db_path, e)
        return False


def backup_loop(db_path=None, stop_event=None):
    """Periodic backup worker: snapshot immediately, then every interval.

    Reads AUTO_BACKUP_INTERVAL at each iteration so an operator can change
    the cadence live; returns if the interval becomes <= 0 (disabled) or the
    stop_event is set (checked before the first snapshot too, so a cancelled
    loop never writes an unwanted snapshot).
    """
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            backup_now(db_path=db_path)
        except Exception as e:  # noqa: BLE001 — worker must never die
            log.error("[backup] snapshot failed: %s", e)
        if stop_event is not None and stop_event.is_set():
            return
        interval = _env_interval()
        if interval <= 0:
            return
        time.sleep(interval)
