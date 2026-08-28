from scripts.validate_physical_evidence import validate


def _record(index, mode, family, firmware):
    record = {
        "run_id": f"run-{index}",
        "timestamp": "2026-08-28T12:00:00Z",
        "mode": mode,
        "device_family": family,
        "firmware_family": firmware,
        "scenario": "online",
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
        _record(i, "dry_run", ("bitaxe", "nerdqaxe", "farm_asic")[i % 3],
                ("esp-miner", "cgminer")[i % 2])
        for i in range(200)
    ]
    records += [
        _record(200 + i, "human_command", ("bitaxe", "nerdqaxe", "farm_asic")[i % 3],
                ("esp-miner", "cgminer")[i % 2])
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
