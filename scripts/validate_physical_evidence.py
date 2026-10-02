#!/usr/bin/env python3
"""Validate the physical beta evidence ledger without reading credentials."""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_DEVICE_FAMILIES = {"bitaxe", "nerdqaxe", "farm_asic"}
SUPPORTED_FIRMWARE_ALIASES = {
    "esp-miner": "esp-miner/axeos",
    "axeos": "esp-miner/axeos",
    "cgminer": "cgminer/bmminer",
    "bmminer": "cgminer/bmminer",
    "braiins os": "braiins os",
    "braiins-os": "braiins os",
}
MIN_DRY_RUNS = 200
MIN_HUMAN_COMMANDS = 50
REQUIRED_SCENARIOS = {
    "online",
    "offline",
    "timeout",
    "reconnect",
    "firmware_incompatible",
}


def _is_utc_timestamp(value: object) -> bool:
    """Return whether value is an ISO-8601 timestamp explicitly expressed in UTC."""
    if not isinstance(value, str) or not (
        value.endswith("Z") or value.endswith("+00:00")
    ):
        return False
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(
        None
    )


def validate(records: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(records, list):
        return ["evidence root must be a JSON array"]
    ids: set[str] = set()
    families: set[str] = set()
    firmwares: set[str] = set()
    scenarios: set[str] = set()
    counts = Counter()
    required = {
        "run_id",
        "timestamp",
        "mode",
        "device_family",
        "firmware_family",
        "scenario",
        "target_validated",
        "passed",
        "evidence_ref",
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
        run_id = record["run_id"]
        if not isinstance(run_id, str) or not run_id.strip():
            errors.append(f"{prefix} invalid run_id")
        elif run_id in ids:
            errors.append(f"{prefix} duplicate run_id: {run_id}")
        else:
            ids.add(run_id)
        mode = record["mode"]
        if not isinstance(mode, str) or mode not in {"dry_run", "human_command"}:
            errors.append(f"{prefix} invalid mode")
            continue
        counts[mode] += 1
        device_family = record["device_family"]
        if not isinstance(device_family, str) or not device_family.strip():
            errors.append(f"{prefix} invalid device_family")
        else:
            families.add(device_family.strip().lower())
        firmware_family = record["firmware_family"]
        if not isinstance(firmware_family, str) or not firmware_family.strip():
            errors.append(f"{prefix} invalid firmware_family")
        else:
            firmware_key = " ".join(firmware_family.strip().lower().split())
            canonical_firmware = SUPPORTED_FIRMWARE_ALIASES.get(firmware_key)
            if canonical_firmware is None:
                errors.append(f"{prefix} unsupported firmware_family")
            else:
                firmwares.add(canonical_firmware)
        scenario = record["scenario"]
        if not isinstance(scenario, str) or scenario not in REQUIRED_SCENARIOS:
            errors.append(f"{prefix} invalid scenario")
        else:
            scenarios.add(scenario)
        if not _is_utc_timestamp(record["timestamp"]):
            errors.append(f"{prefix} timestamp must be ISO-8601 UTC")
        if record["target_validated"] is not True:
            errors.append(f"{prefix} target was not validated")
        if record["passed"] is not True:
            errors.append(f"{prefix} did not pass")
        evidence_ref = record["evidence_ref"]
        if not isinstance(evidence_ref, str) or not evidence_ref.strip():
            errors.append(f"{prefix} has no evidence reference")
        if mode == "human_command":
            for field in (
                "confirmed",
                "ack",
                "post_state_verified",
                "pool_reconciled",
                "firmware_reconciled",
            ):
                if record.get(field) is not True:
                    errors.append(f"{prefix} human command missing {field}")
            audit_log_id = record.get("audit_log_id")
            valid_audit_log_id = (
                isinstance(audit_log_id, str) and bool(audit_log_id.strip())
            ) or (
                isinstance(audit_log_id, int)
                and not isinstance(audit_log_id, bool)
                and audit_log_id > 0
            )
            if not valid_audit_log_id:
                errors.append(f"{prefix} human command missing audit_log_id")
    if counts["dry_run"] < MIN_DRY_RUNS:
        errors.append(f"dry_run count {counts['dry_run']} < {MIN_DRY_RUNS}")
    if counts["human_command"] < MIN_HUMAN_COMMANDS:
        errors.append(
            f"human_command count {counts['human_command']} < {MIN_HUMAN_COMMANDS}"
        )
    missing_families = sorted(REQUIRED_DEVICE_FAMILIES - families)
    if missing_families:
        errors.append("missing device families: " + ", ".join(missing_families))
    if len(firmwares) < 2:
        errors.append("fewer than two supported firmware families validated")
    missing_scenarios = sorted(REQUIRED_SCENARIOS - scenarios)
    if missing_scenarios:
        errors.append("missing scenarios: " + ", ".join(missing_scenarios))
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
    print(
        "PASS: evidence ledger checks passed; physical origin still requires human verification"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
