#!/usr/bin/env python3
"""Verify the $0 GitHub-gist backup is LIVE (Issue #14).

Run it in the Render shell (or anywhere with GITHUB_TOKEN in the env):

    python scripts/verify_remote_backup.py              # read-only probe
    python scripts/verify_remote_backup.py --roundtrip  # + safe upload test

Checks:
  1. env-gating: GITHUB_TOKEN set + REMOTE_BACKUP_INTERVAL > 0
  2. remote_backup_enabled()
  3. gist discovery (the exact path services/remote_backup uses)
  4. read-only: the backup file exists in the gist → size + updated_at
  5. --roundtrip: pushes a tiny scratch DB to a SEPARATE verify file
     (war_room.verify.sqlite.b64) — the production war_room.sqlite.b64 is
     NEVER touched, so this is safe to run against the live gist.

Exit codes: 0 verified · 1 not enabled/misconfigured · 2 probe/push failed
"""
import base64
import os
import sqlite3
import sys
import tempfile
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import services.remote_backup as rb  # noqa: E402

VERIFY_FILENAME = "war_room.verify.sqlite.b64"
_API = rb._API


def _probe_gist() -> dict | None:
    """Read-only: {id, size, updated_at} of the backup file, or None."""
    gid = rb._find_or_create_gist()
    if not gid:
        return None
    r = requests.get(f"{_API}/gists/{gid}", headers=rb._headers(), timeout=10)
    if not r.ok:
        return None
    f = (r.json().get("files") or {}).get(rb.GIST_FILENAME)
    if not f:
        return None
    return {"id": gid, "size": f.get("size") or 0,
            "updated_at": f.get("updated_at") or "?"}


def _roundtrip_scratch() -> bool:
    """Push a tiny scratch DB to a SEPARATE verify file (never the prod one)."""
    fd, tmp = tempfile.mkstemp(suffix=".sqlite")
    try:
        conn = sqlite3.connect(tmp)
        conn.execute("CREATE TABLE verify (ts INTEGER)")
        conn.execute("INSERT INTO verify VALUES (?)", (int(time.time()),))
        conn.commit()
        conn.close()
        with open(tmp, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    gid = rb._find_or_create_gist()
    if not gid:
        return False
    r = requests.patch(f"{_API}/gists/{gid}", headers=rb._headers(),
                       timeout=20,
                       json={"files": {VERIFY_FILENAME: {"content": b64}}})
    return bool(r.ok)


def run(argv=None) -> int:
    """Execute the verification. Returns the process exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    roundtrip = "--roundtrip" in argv
    print("CYPHER65 — remote gist backup verification")

    tok = rb._token()
    if not tok:
        print("✗ GITHUB_TOKEN not set — remote backup is DISABLED (no snapshots).")
        print("  Set it in the Render dashboard (gist scope).")
        print("  Guide: docs/DEPLOYMENT_OPS.md → 'Persistência no Render'.")
        return 1
    print(f"✓ GITHUB_TOKEN set (len={len(tok)})")

    interval = rb._interval()
    print(f"✓ REMOTE_BACKUP_INTERVAL={interval}s")
    if not rb.remote_backup_enabled():
        print("✗ remote_backup_enabled()=False — fix the env vars above.")
        return 1
    print("✓ remote_backup_enabled()=True")

    probe = _probe_gist()
    if not probe:
        print("✗ could not find/open the backup gist "
              "(token scope 'gist'? network blocked?)")
        return 2
    print(f"✓ backup gist {probe['id']}")
    print(f"✓ last snapshot on gist: {probe['size']} bytes, "
          f"updated {probe['updated_at']}")

    empty = int(probe["size"] or 0) == 0
    if empty:
        # Fresh token / service not yet cycled: the gist may only hold the
        # empty placeholder. Be honest instead of claiming snapshots flow.
        print("⚠ backup file is empty (0 bytes) — the app pushes on its next "
              f"REMOTE_BACKUP_INTERVAL cycle (up to {interval}s) or right "
              "after a redeploy. Run with --roundtrip to prove upload "
              "end-to-end now.")
        if not roundtrip:
            return 0  # config verified live; the first snapshot is pending

    if roundtrip:
        if _roundtrip_scratch():
            print(f"✓ round-trip upload OK — {VERIFY_FILENAME} patched "
                  f"(small disposable file; production file untouched)")
        else:
            print(f"✗ round-trip upload FAILED (PATCH to {VERIFY_FILENAME})")
            return 2
        if empty:
            print("✔ upload verified end-to-end — the first real snapshot "
                  "lands within REMOTE_BACKUP_INTERVAL.")
            return 0

    print("✔ verified — the gist is receiving backups and the boot restore "
          "will run whenever the local DB is empty.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
