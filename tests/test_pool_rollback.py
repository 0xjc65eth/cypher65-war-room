"""Hermetic security tests for encrypted pool rollback targets."""

import os
import sqlite3

import pytest

from services.pool_intelligence import (
    PoolRollbackError,
    claim_pool_rollback_target,
    load_pool_rollback_target,
    rollback_encryption_ready,
    store_pool_rollback_target,
)


PARAMETERS = {
    "stratumURL": "stratum+tcp://prior-pool.example.test",
    "stratumPort": 3333,
    "stratumUser": "private-wallet.prior-worker",
}


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "rollback.sqlite"))
    monkeypatch.setenv("SECRET_KEY", "rollback-test-secret-0123456789")
    monkeypatch.setenv("POOL_ROLLBACK_TARGET_TTL_SECONDS", "300")


def test_target_is_encrypted_at_rest_and_round_trips():
    stored = store_pool_rollback_target(
        "source-op", "tenant-a", "device-a", PARAMETERS, now=100
    )

    conn = sqlite3.connect(os.environ["DB_PATH"])
    row = conn.execute(
        "SELECT sealed_payload, target_hash FROM pool_rollback_targets"
    ).fetchone()
    conn.close()
    database_values = " ".join(row)

    assert "prior-pool.example.test" not in database_values
    assert "private-wallet.prior-worker" not in database_values
    assert row[1] == stored.target_hash
    loaded = load_pool_rollback_target("source-op", "tenant-a", "device-a", now=101)
    assert loaded.parameters == PARAMETERS


def test_missing_key_fails_closed_before_storage(monkeypatch):
    monkeypatch.delenv("SECRET_KEY")

    assert rollback_encryption_ready() is False
    with pytest.raises(PoolRollbackError, match="rollback_encryption_unavailable"):
        store_pool_rollback_target(
            "source-op", "tenant-a", "device-a", PARAMETERS, now=100
        )


def test_target_is_tenant_device_and_operation_bound():
    store_pool_rollback_target("source-op", "tenant-a", "device-a", PARAMETERS, now=100)

    for operation, tenant, device in (
        ("other-op", "tenant-a", "device-a"),
        ("source-op", "tenant-b", "device-a"),
        ("source-op", "tenant-a", "device-b"),
    ):
        with pytest.raises(PoolRollbackError, match="rollback_target_unavailable"):
            load_pool_rollback_target(operation, tenant, device, now=101)


def test_expired_target_fails_closed():
    target = store_pool_rollback_target(
        "source-op", "tenant-a", "device-a", PARAMETERS, now=100
    )

    with pytest.raises(PoolRollbackError, match="rollback_target_expired"):
        load_pool_rollback_target(
            "source-op", "tenant-a", "device-a", now=target.expires_at + 1
        )
    conn = sqlite3.connect(os.environ["DB_PATH"])
    remaining = conn.execute("SELECT COUNT(*) FROM pool_rollback_targets").fetchone()[0]
    conn.close()
    assert remaining == 0


def test_tampered_ciphertext_and_rotated_key_fail_closed(monkeypatch):
    store_pool_rollback_target("source-op", "tenant-a", "device-a", PARAMETERS, now=100)
    conn = sqlite3.connect(os.environ["DB_PATH"])
    sealed = conn.execute(
        "SELECT sealed_payload FROM pool_rollback_targets"
    ).fetchone()[0]
    conn.execute(
        "UPDATE pool_rollback_targets SET sealed_payload = ?",
        (sealed[:-1] + ("A" if sealed[-1] != "A" else "B"),),
    )
    conn.commit()
    conn.close()

    with pytest.raises(PoolRollbackError, match="rollback_target_invalid"):
        load_pool_rollback_target("source-op", "tenant-a", "device-a", now=101)

    monkeypatch.setenv("DB_PATH", os.environ["DB_PATH"] + ".rotated")
    monkeypatch.setenv("SECRET_KEY", "original-key")
    store_pool_rollback_target("source-op", "tenant-a", "device-a", PARAMETERS, now=100)
    monkeypatch.setenv("SECRET_KEY", "rotated-key")
    with pytest.raises(PoolRollbackError, match="rollback_target_invalid"):
        load_pool_rollback_target("source-op", "tenant-a", "device-a", now=101)


def test_target_can_be_claimed_only_once():
    store_pool_rollback_target("source-op", "tenant-a", "device-a", PARAMETERS, now=100)

    claimed = claim_pool_rollback_target(
        "source-op", "tenant-a", "device-a", "rollback-op-1", now=101
    )
    assert claimed.parameters == PARAMETERS
    with pytest.raises(PoolRollbackError, match="rollback_target_already_claimed"):
        claim_pool_rollback_target(
            "source-op", "tenant-a", "device-a", "rollback-op-2", now=102
        )


def test_source_operation_is_single_assignment():
    store_pool_rollback_target("source-op", "tenant-a", "device-a", PARAMETERS, now=100)

    with pytest.raises(PoolRollbackError, match="rollback_target_conflict"):
        store_pool_rollback_target(
            "source-op", "tenant-a", "device-a", PARAMETERS, now=101
        )
