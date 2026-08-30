"""Safety and persistence tests for the external operation ledger."""

from concurrent.futures import ThreadPoolExecutor

from services import operation_ledger as ledger


PAYLOAD = {"amount_sat": 50000, "speed_limit_ph": 0.1}


def test_confirmation_is_one_time_and_bound_to_exact_payload():
    confirmation = ledger.issue_confirmation("acme", "braiins_bid", "spot", PAYLOAD)

    assert (
        ledger.consume_confirmation(
            confirmation["confirmation_token"],
            "acme",
            "braiins_bid",
            "spot",
            {**PAYLOAD, "amount_sat": 50001},
        )
        is False
    )
    assert (
        ledger.consume_confirmation(
            confirmation["confirmation_token"],
            "acme",
            "braiins_bid",
            "spot",
            PAYLOAD,
        )
        is False
    )


def test_confirmation_expires():
    confirmation = ledger.issue_confirmation(
        "acme", "braiins_bid", "spot", PAYLOAD, now=100
    )
    assert (
        ledger.consume_confirmation(
            confirmation["confirmation_token"],
            "acme",
            "braiins_bid",
            "spot",
            PAYLOAD,
            now=100 + ledger.CONFIRMATION_TTL_SECONDS + 1,
        )
        is False
    )


def test_idempotency_claim_is_atomic_across_concurrent_requests():
    def claim():
        return ledger.claim_operation(
            "acme",
            "braiins_bid",
            "spot",
            "create",
            PAYLOAD,
            idempotency_key="order-1",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: claim(), range(2)))

    assert sum(1 for result in results if result["created"]) == 1
    assert len({result["operation_id"] for result in results}) == 1


def test_same_key_with_changed_payload_is_detected_without_new_claim():
    first = ledger.claim_operation(
        "acme", "braiins_bid", "spot", "create", PAYLOAD, idempotency_key="same"
    )
    replay = ledger.claim_operation(
        "acme",
        "braiins_bid",
        "spot",
        "create",
        {**PAYLOAD, "amount_sat": 99999},
        idempotency_key="same",
    )

    assert first["created"] is True
    assert replay["created"] is False
    assert replay["payload_matches"] is False
    assert replay["operation_id"] == first["operation_id"]


def test_ack_and_reconciliation_are_distinct_and_persisted():
    claimed = ledger.claim_operation(
        "acme", "physical_command", "miner-1", "restart", {}
    )
    acknowledged = ledger.update_operation(
        claimed["operation_id"],
        state="acknowledged",
        ack_state="acknowledged",
        reconciliation_state="pending",
        safe_result={"success": True},
        now=200,
    )

    assert acknowledged["ack_state"] == "acknowledged"
    assert acknowledged["reconciliation_state"] == "pending"
    assert acknowledged["ack_at"] == 200

    confirmed = ledger.update_operation(
        claimed["operation_id"],
        state="reconciled",
        reconciliation_state="confirmed",
        safe_result={"observed": "online"},
        now=220,
    )
    reloaded = ledger.get_operation(claimed["operation_id"])

    assert confirmed["state"] == "reconciled"
    assert reloaded["reconciliation_state"] == "confirmed"
    assert reloaded["reconciled_at"] == 220


def test_ledger_stores_only_hash_not_sensitive_payload():
    sensitive = {
        "upstream_url": "stratum+tcp://secret.example:3333",
        "upstream_identity": "wallet.worker",
    }
    claimed = ledger.claim_operation("acme", "braiins_bid", "spot", "create", sensitive)
    serialized = str(ledger.get_operation(claimed["operation_id"]))

    assert "secret.example" not in serialized
    assert "wallet.worker" not in serialized
