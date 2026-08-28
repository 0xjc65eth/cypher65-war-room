#!/usr/bin/env python3
"""Validate the physical beta evidence ledger without reading credentials."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


REQUIRED_DEVICE_FAMILIES = {"bitaxe", "nerdqaxe", "farm_asic"}
MIN_DRY_RUNS = 200
MIN_HUMAN_COMMANDS = 50


def validate(records: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(records, list):
        return ["evidence root must be a JSON array"]
    ids: set[str] = set()
    families: set[str] = set()
    firmwares: set[str] = set()
    counts = Counter()
    required = {
        "run_id", "timestamp", "mode", "device_family", "firmware_family",
        "scenario", "target_validated", "passed", "evidence_ref",
    }
    for index, record in enumerate(records):
        prefix = f"record[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{prefix} must be an object")
            continue
        missing = sorted(required - record.keys())
        if missing:
            errors.append(f"{prefix} missing: {', '.join(missing)}")
            continue
        run_id = str(record["run_id"])
        if run_id in ids:
            errors.append(f"{prefix} duplicate run_id: {run_id}")
        ids.add(run_id)
        mode = record["mode"]
        if mode not in {"dry_run", "human_command"}:
            errors.append(f"{prefix} invalid mode")
            continue
        counts[mode] += 1
        families.add(str(record["device_family"]).lower())
        firmwares.add(str(record["firmware_family"]).lower())
        if record["target_validated"] is not True:
            errors.append(f"{prefix} target was not validated")
        if record["passed"] is not True:
            errors.append(f"{prefix} did not pass")
        if not str(record["evidence_ref"]).strip():
            errors.append(f"{prefix} has no evidence reference")
        if mode == "human_command":
            for field in ("confirmed", "ack", "post_state_verified", "audit_log_id"):
                if not record.get(field):
                    errors.append(f"{prefix} human command missing {field}")
            if not (record.get("pool_reconciled") and record.get("firmware_reconciled")):
                errors.append(f"{prefix} lacks pool/firmware reconciliation")
    if counts["dry_run"] < MIN_DRY_RUNS:
        errors.append(f"dry_run count {counts['dry_run']} < {MIN_DRY_RUNS}")
    if counts["human_command"] < MIN_HUMAN_COMMANDS:
        errors.append(f"human_command count {counts['human_command']} < {MIN_HUMAN_COMMANDS}")
    missing_families = sorted(REQUIRED_DEVICE_FAMILIES - families)
    if missing_families:
        errors.append("missing device families: " + ", ".join(missing_families))
    if len(firmwares) < 2:
        errors.append("fewer than two firmware families validated")
    return errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args(argv)
    records = json.loads(args.evidence.read_text(encoding="utf-8"))
    errors = validate(records)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: physical validation gate satisfied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
