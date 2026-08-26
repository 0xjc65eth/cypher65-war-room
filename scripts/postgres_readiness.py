#!/usr/bin/env python3
"""Print the traction-gated Postgres readiness report as redacted JSON."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.postgres_readiness import (  # noqa: E402
    ReadinessError,
    fetch_pinned_gist_snapshot,
    readiness_report,
    schema_map,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure Postgres readiness without mutating either database."
    )
    parser.add_argument(
        "--db", default=os.environ.get("DB_PATH", "data/war_room.sqlite")
    )
    parser.add_argument(
        "--source-gist",
        action="store_true",
        help="inspect the real, explicitly pinned private Gist snapshot",
    )
    parser.add_argument(
        "--include-schema-map",
        action="store_true",
        help="include the column-level SQLite to Postgres inventory",
    )
    parser.add_argument(
        "--require-rehearsal-ready",
        action="store_true",
        help="exit 2 unless the decision is ready-for-rehearsal",
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    temporary_path = ""
    try:
        db_path = args.db
        if args.source_gist:
            raw = fetch_pinned_gist_snapshot()
            handle = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
            try:
                handle.write(raw)
                temporary_path = handle.name
            finally:
                handle.close()
            db_path = temporary_path
        report = readiness_report(db_path)
        report["source"] = "pinned-private-gist" if args.source_gist else "local-sqlite"
        if args.include_schema_map:
            report["schema_map"] = schema_map(db_path)
        print(json.dumps(report, indent=2, sort_keys=True))
        if args.require_rehearsal_ready and report["decision"] != "ready-for-rehearsal":
            return 2
        return 0
    except ReadinessError as exc:
        print(json.dumps({"decision": "blocked", "error": str(exc)}), file=sys.stderr)
        return 2
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
