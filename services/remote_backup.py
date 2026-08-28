"""
CYPHER65 — Zero-cost remote backup (GitHub gist)
=================================================
Persistence on Render's FREE tier without paying for a Persistent Disk.

The free-tier filesystem is EPHEMERAL — data/war_room.sqlite is wiped on
every redeploy/restart. That would silently destroy per-user credentials
(tenant_settings), settings, alerts and wallet history built for 1000+
users. This module fixes it at $0:

  - `remote_backup_now()`: snapshots the DB via the crash-safe sqlite online
    backup API, encrypts and authenticates it, then PATCHes the ciphertext into
    a secret GitHub gist. Secret gists are unlisted, not private; encryption is
    therefore mandatory.
  - `remote_restore()`: on boot, if the local DB is missing or has NO user
    data (fresh ephemeral boot), downloads the gist and restores the file
    BEFORE the app starts writing. Never overwrites a DB that already has
    rows (a real deploy with its own data is left untouched).
  - `remote_backup_loop()`: daemon worker mirroring services/db_backup.

Env-gated (all optional — nothing happens without them):
  - GITHUB_TOKEN            — personal access token with `gist` scope.
  - REMOTE_BACKUP_INTERVAL  — seconds between remote snapshots (default 600).
  - REMOTE_BACKUP_GIST_ID   — optional; reuse a known gist id (skips lookup).
  - REMOTE_BACKUP_ENCRYPTION_KEY — stable Fernet key; required.
  - GIST_DESCRIPTION        — optional description used to find/create the gist.

Design notes:
  - Uses the existing sqlite3.Connection.backup() API, so the snapshot is
    consistent even under concurrent writers (same guarantee as
    services/db_backup.py).
  - GitHub gist API: a single authenticated ciphertext stays under the
    per-file size limit for a long time (SQLite of this app is a few MB).
    The 100MB hard per-file limit is far above the
    realistic size here; the restore path tolerates a missing gist.
  - Failures are logged and NEVER raise — a backup outage must not break
    the app (honest telemetry: backup is best-effort, like db_backup).
"""

import logging
import os
import sqlite3
import tempfile
import time

import requests
from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger("cypher65.remote_backup")

GIST_DEFAULT_DESCRIPTION = "cypher65-war-room automatic backup"
GIST_FILENAME = "war_room.sqlite.enc"
ENCRYPTED_PREFIX = "c65-fernet-v1:"
_API = "https://api.github.com"

# Cached discovered gist id — avoids a GET /gists round trip on every cycle
# and the duplicate-gist risk when the backup gist falls off page 1.
_cached_gist_id: str | None = None

# ── Env helpers (read lazily so tests can flip knobs after import) ─────────


def _token():
    return (os.environ.get("GITHUB_TOKEN") or "").strip()


def _interval():
    try:
        return max(0, int(os.environ.get("REMOTE_BACKUP_INTERVAL", "600")))
    except (TypeError, ValueError):
        return 600


def _gist_id_env():
    return (os.environ.get("REMOTE_BACKUP_GIST_ID") or "").strip()


def _encryption_key() -> str:
    return (os.environ.get("REMOTE_BACKUP_ENCRYPTION_KEY") or "").strip()


def _cipher() -> Fernet | None:
    key = _encryption_key()
    if not key:
        return None
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        log.error("[remote_backup] REMOTE_BACKUP_ENCRYPTION_KEY is invalid")
        return None


def remote_backup_enabled() -> bool:
    """True only with GitHub auth, a valid encryption key and interval."""
    return bool(_token()) and _cipher() is not None and _interval() > 0


def _headers():
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _resolve_db_path(db_path=None) -> str:
    return db_path or os.environ.get("DB_PATH", "data/war_room.sqlite")


# ── Gist discovery / creation ───────────────────────────────────────────────


def _find_or_create_gist() -> str | None:
    """Return the gist id holding our backup file, creating it if needed.

    The discovered id is cached in memory: after the first lookup/creation
    this is a pure return — no GitHub API call — and the backup gist can
    never drift out of page-1 range into accidental duplicate creation.
    ``REMOTE_BACKUP_GIST_ID`` (env) is the canonical pin and always wins.
    """
    global _cached_gist_id
    gid = _gist_id_env()
    if gid:
        _cached_gist_id = gid
        return gid
    if _cached_gist_id:
        return _cached_gist_id
    try:
        # Look for an existing unlisted gist with our encrypted filename.
        r = requests.get(f"{_API}/gists", headers=_headers(), timeout=10)
        if r.ok:
            for g in r.json():
                if GIST_FILENAME in g.get("files", {}):
                    _cached_gist_id = g["id"]
                    return g["id"]
        # None found — create an unlisted gist with an empty placeholder.
        r = requests.post(
            f"{_API}/gists",
            headers=_headers(),
            timeout=10,
            json={
                "description": GIST_DEFAULT_DESCRIPTION,
                "public": False,
                "files": {GIST_FILENAME: {"content": ""}},
            },
        )
        if r.ok:
            _cached_gist_id = r.json()["id"]
            return _cached_gist_id
        log.warning(
            "[remote_backup] gist create failed: %s %s", r.status_code, r.text[:160]
        )
    except Exception as e:
        log.warning("[remote_backup] gist lookup/create error: %s", e)
    return None


# ── Backup ──────────────────────────────────────────────────────────────────


def _snapshot_bytes(db_path: str) -> bytes:
    """Crash-safe SQLite snapshot to a temp file, returned as bytes.

    sqlite3.Connection.backup() needs a real file destination (a BytesIO is
    not a valid connection target), so we snapshot into a tempfile and read
    it back — the tempfile is unlinked immediately after.
    """
    src = sqlite3.connect(db_path)
    fd, tmp = tempfile.mkstemp(suffix=".sqlite")
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        src.close()
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _encrypt_snapshot(raw: bytes) -> str:
    cipher = _cipher()
    if cipher is None:
        raise ValueError("remote backup encryption key unavailable")
    return ENCRYPTED_PREFIX + cipher.encrypt(raw).decode("ascii")


def _decrypt_snapshot(content: str) -> bytes:
    if not content.startswith(ENCRYPTED_PREFIX):
        raise ValueError("legacy plaintext remote backup rejected")
    cipher = _cipher()
    if cipher is None:
        raise ValueError("remote backup encryption key unavailable")
    try:
        return cipher.decrypt(content[len(ENCRYPTED_PREFIX) :].encode("ascii"))
    except InvalidToken as exc:
        raise ValueError("remote backup authentication failed") from exc


def _write_validated_snapshot(raw: bytes, db_path: str) -> None:
    """Validate decrypted SQLite bytes before atomically replacing the DB."""
    target_dir = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(target_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".restore.sqlite", dir=target_dir)
    try:
        with os.fdopen(fd, "wb") as restored:
            restored.write(raw)
            restored.flush()
            os.fsync(restored.fileno())
        conn = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        try:
            check = conn.execute("PRAGMA quick_check").fetchone()
            if not check or check[0] != "ok":
                raise ValueError("restored SQLite snapshot failed integrity check")
        finally:
            conn.close()
        os.replace(tmp, db_path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def remote_backup_now(db_path=None) -> bool:
    """Snapshot, encrypt and PATCH the DB into an unlisted gist.

    Returns True on success, False on any failure (never raises).
    """
    if not remote_backup_enabled():
        return False
    db_path = _resolve_db_path(db_path)
    try:
        raw = _snapshot_bytes(db_path)
        encrypted = _encrypt_snapshot(raw)
        gid = _find_or_create_gist()
        if not gid:
            return False
        r = requests.patch(
            f"{_API}/gists/{gid}",
            headers=_headers(),
            timeout=20,
            json={"files": {GIST_FILENAME: {"content": encrypted}}},
        )
        if not r.ok:
            log.warning(
                "[remote_backup] PATCH failed: %s %s", r.status_code, r.text[:160]
            )
            return False
        log.info(
            "[remote_backup] snapshot pushed (%.0f KB raw) -> gist %s",
            len(raw) / 1024,
            gid,
        )
        return True
    except Exception as e:
        log.warning("[remote_backup] backup error: %s", e)
        return False


# ── Restore ────────────────────────────────────────────────────────────────


def _db_has_user_data(db_path: str) -> bool:
    """True when the local DB already contains meaningful user rows.

    Guards the boot restore: we only restore onto a FRESH ephemeral boot
    (missing file or zero rows). A DB that already has settings/users/
    alerts/tenant rows is a real deployment — never clobber it.
    """
    if not os.path.exists(db_path):
        return False
    try:
        conn = sqlite3.connect(db_path)
        try:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            checks = [
                ("settings", "SELECT COUNT(*) FROM settings WHERE value <> ''"),
                ("users", "SELECT COUNT(*) FROM users"),
                ("tenant_settings", "SELECT COUNT(*) FROM tenant_settings"),
                ("alerts", "SELECT COUNT(*) FROM alerts"),
            ]
            for table, q in checks:
                if table in tables:
                    row = conn.execute(q).fetchone()
                    if row and row[0] > 0:
                        return True
        finally:
            conn.close()
    except Exception as e:
        log.warning("[remote_backup] user-data probe error: %s", e)
        return False
    return False


def remote_restore(db_path=None) -> bool:
    """Restore the gist snapshot onto a fresh/ephemeral local DB.

    No-op unless: enabled (token+interval), a gist is found, and the local
    DB is empty of user data. Returns True when a restore happened.
    """
    if not remote_backup_enabled():
        return False
    db_path = _resolve_db_path(db_path)
    if _db_has_user_data(db_path):
        log.info("[remote_backup] local DB has data — skipping restore")
        return False
    try:
        gid = _find_or_create_gist()
        if not gid:
            return False
        r = requests.get(f"{_API}/gists/{gid}", headers=_headers(), timeout=10)
        if not r.ok:
            return False
        files = (r.json() or {}).get("files", {})
        content = (files.get(GIST_FILENAME) or {}).get("content") or ""
        if not content.strip():
            log.info("[remote_backup] gist empty — nothing to restore")
            return False
        raw = _decrypt_snapshot(content)
        _write_validated_snapshot(raw, db_path)
        log.info(
            "[remote_backup] restored %.0f KB from gist %s -> %s",
            len(raw) / 1024,
            gid,
            db_path,
        )
        return True
    except Exception as e:
        log.warning("[remote_backup] restore error: %s", e)
        return False


# ── Worker loop ─────────────────────────────────────────────────────────────


def remote_backup_loop(stop_event=None):
    """Periodic remote backup worker (daemon).

    Snapshots immediately, then every REMOTE_BACKUP_INTERVAL. Reads the
    interval + token at each iteration so the operator can flip the knob
    live; exits when disabled or the stop_event is set.
    """
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            remote_backup_now()
        except Exception as e:
            log.error("[remote_backup] loop error: %s", e)
        if stop_event is not None and stop_event.is_set():
            return
        interval = _interval()
        if interval <= 0:
            return
        time.sleep(interval)
