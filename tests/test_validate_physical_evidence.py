import json

from scripts.validate_physical_evidence import main, validate


SCENARIOS = ("online", "offline", "timeout", "reconnect", "firmware_incompatible")


def _record(index, mode, family, firmware):
    record = {
        "run_id": f"run-{index}",
        "timestamp": "2026-08-28T12:00:00Z",
        "mode": mode,
        "device_family": family,
        "firmware_family": firmware,
        "scenario": SCENARIOS[index % len(SCENARIOS)],
        "target_validated": True,
        "passed": True,
        "evidence_ref": f"lab/evidence-{index}.json",
    }
    if mode == "human_command":
        record.update(
            confirmed=True,
            ack=True,
            post_state_verified=True,
            audit_log_id=index + 1,
            pool_reconciled=True,
            firmware_reconciled=True,
        )
    return record


def test_complete_physical_ledger_passes():
    records = [
        _record(
            i,
            "dry_run",
            ("bitaxe", "nerdqaxe", "farm_asic")[i % 3],
            ("esp-miner", "cgminer")[i % 2],
        )
        for i in range(200)
    ]
    records += [
        _record(
            200 + i,
            "human_command",
            ("bitaxe", "nerdqaxe", "farm_asic")[i % 3],
            ("esp-miner", "cgminer")[i % 2],
        )
        for i in range(50)
    ]
    assert validate(records) == []


def test_incomplete_or_unsafe_evidence_fails_closed():
    records = [_record(1, "human_command", "bitaxe", "esp-miner")]
    records[0]["ack"] = False
    errors = validate(records)
    assert any("ack" in error for error in errors)
    assert any("dry_run count" in error for error in errors)
    assert any("missing device families" in error for error in errors)


def test_truthy_strings_do_not_satisfy_human_command_safety_fields():
    record = _record(1, "human_command", "bitaxe", "esp-miner")
    for field in (
        "confirmed",
        "ack",
        "post_state_verified",
        "pool_reconciled",
        "firmware_reconciled",
    ):
        record[field] = "false"

    errors = validate([record])

    for field in (
        "confirmed",
        "ack",
        "post_state_verified",
        "pool_reconciled",
        "firmware_reconciled",
    ):
        assert any(field in error for error in errors)


def test_non_utc_timestamp_is_rejected():
    records = [_record(1, "dry_run", "bitaxe", "esp-miner")]
    records[0]["timestamp"] = "2026-08-28T14:00:00+02:00"

    assert any("timestamp must be ISO-8601 UTC" in error for error in validate(records))


def test_missing_or_non_string_evidence_fields_fail_closed():
    records = [_record(1, "dry_run", "bitaxe", "esp-miner")]
    records[0]["evidence_ref"] = None
    records[0]["run_id"] = " "
    records[0]["firmware_family"] = None

    errors = validate(records)

    assert any("invalid run_id" in error for error in errors)
    assert any("invalid firmware_family" in error for error in errors)
    assert any("has no evidence reference" in error for error in errors)


def test_unhashable_mode_is_rejected_without_crashing():
    record = _record(1, "dry_run", "bitaxe", "esp-miner")
    record["mode"] = []

    assert any("invalid mode" in error for error in validate([record]))


def test_required_scenario_matrix_is_enforced():
    records = [_record(i, "dry_run", "bitaxe", "esp-miner") for i in range(200)]
    for record in records:
        record["scenario"] = "online"

    errors = validate(records)

    assert any("missing scenarios" in error for error in errors)
    assert any("missing device families" in error for error in errors)


def test_unsupported_firmware_labels_do_not_satisfy_matrix():
    records = [
        _record(
            i,
            "dry_run",
            ("bitaxe", "nerdqaxe", "farm_asic")[i % 3],
            ("custom-fw-a", "custom-fw-b")[i % 2],
        )
        for i in range(200)
    ]
    records += [
        _record(
            200 + i,
            "human_command",
            ("bitaxe", "nerdqaxe", "farm_asic")[i % 3],
            ("custom-fw-a", "custom-fw-b")[i % 2],
        )
        for i in range(50)
    ]

    errors = validate(records)

    assert any("unsupported firmware_family" in error for error in errors)


def test_aliases_of_one_firmware_family_count_once():
    records = [
        _record(
            i,
            "dry_run",
            ("bitaxe", "nerdqaxe", "farm_asic")[i % 3],
            ("esp-miner", "axeos")[i % 2],
        )
        for i in range(200)
    ]
    records += [
        _record(
            200 + i,
            "human_command",
            ("bitaxe", "nerdqaxe", "farm_asic")[i % 3],
            ("esp-miner", "axeos")[i % 2],
        )
        for i in range(50)
    ]

    errors = validate(records)

    assert any(
        "fewer than two supported firmware families" in error for error in errors
    )


def test_cli_success_does_not_claim_physical_approval(tmp_path, capsys):
    records = [
        _record(
            i,
            "dry_run",
            ("bitaxe", "nerdqaxe", "farm_asic")[i % 3],
            ("esp-miner", "cgminer")[i % 2],
        )
        for i in range(200)
    ]
    records += [
        _record(
            200 + i,
            "human_command",
            ("bitaxe", "nerdqaxe", "farm_asic")[i % 3],
            ("esp-miner", "cgminer")[i % 2],
        )
        for i in range(50)
    ]
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(records), encoding="utf-8")

    assert main([str(evidence_path)]) == 0
    assert (
        "physical origin still requires human verification" in capsys.readouterr().out
    )
