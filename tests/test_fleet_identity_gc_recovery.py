"""Recovery #799: physical row deletion must not leave identity aliases."""

import sqlite3
import time

import pytest

from axe_fleet.registry import DeviceRegistry


@pytest.fixture
def registry(tmp_path):
    path = tmp_path / "identity-gc.sqlite"

    def get_db():
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        return connection

    instance = DeviceRegistry(get_db)
    instance.ensure_tables()
    return instance


def device(registry, tenant="acme", ip="192.0.2.7"):
    return registry.upsert_agent_device(
        ip, tenant_id=tenant, info={"mac": "02:AB:01:23:45:67"}
    )


def state(registry):
    with registry._get_db() as connection:
        return {
            table: [tuple(row) for row in connection.execute("SELECT * FROM " + table)]
            for table in (
                "axe_devices",
                "axe_device_identity_aliases",
                "axe_telemetry",
                "axe_telemetry_quarantine",
                "axe_agent_commands",
            )
        }


def test_hard_delete_releases_only_own_alias_and_allows_registration(registry):
    removed = device(registry)
    other = device(registry, tenant="other")
    assert registry.remove_device(removed["id"], tenant_id="acme", hard=True)
    with registry._get_db() as connection:
        aliases = [tuple(row) for row in connection.execute(
            "SELECT tenant_id, device_id FROM axe_device_identity_aliases"
        )]
    assert aliases == [("other", other["id"])]
    registered = device(registry, ip="192.0.2.8")
    assert registered["id"] != removed["id"]
    assert registered["mac_address"] == removed["mac_address"]
    assert registry.get_device(other["id"], tenant_id="other")


def test_wrong_tenant_hard_delete_has_no_side_effect(registry):
    original = device(registry)
    before = state(registry)
    assert not registry.remove_device(original["id"], tenant_id="other", hard=True)
    assert state(registry) == before


def test_soft_delete_preserves_alias_and_blocks_agent_resurrection(registry):
    original = device(registry)
    assert registry.remove_device(original["id"], tenant_id="acme")
    before = state(registry)
    assert len(before["axe_device_identity_aliases"]) == 1
    assert device(registry, ip="192.0.2.8") == {}
    assert state(registry) == before


def test_gc_releases_expired_identity_and_preserves_other_tenant(registry):
    expired = device(registry)
    fresh = device(registry, tenant="other")
    for row in (expired, fresh):
        registry.save_telemetry(row["id"], {"hashrate_hs": 42}, tenant_id=row["tenant_id"])
        assert registry.remove_device(row["id"], tenant_id=row["tenant_id"])
    with registry._get_db() as connection:
        connection.execute(
            "UPDATE axe_devices SET removed_at=? WHERE id=? AND tenant_id=?",
            (int(time.time()) - 40 * 86400, expired["id"], "acme"),
        )
    before = state(registry)
    assert registry.gc_tombstones(max_age_days=30) == 1
    after = state(registry)
    assert [row[0] for row in after["axe_devices"]] == [fresh["id"]]
    assert after["axe_device_identity_aliases"] == [
        row for row in before["axe_device_identity_aliases"] if row[0] == "other"
    ]
    assert after["axe_telemetry"] == [
        row for row in before["axe_telemetry"] if row[2] == fresh["id"]
    ]
    assert device(registry, ip="192.0.2.8")["id"] != expired["id"]
    assert device(registry, tenant="other", ip="192.0.2.8") == {}


def test_hard_delete_failure_rolls_back_row_and_alias(registry):
    original = device(registry)
    before = state(registry)
    with registry._get_db() as connection:
        connection.execute(
            "CREATE TRIGGER fail_alias_delete BEFORE DELETE ON axe_device_identity_aliases "
            "BEGIN SELECT RAISE(ABORT, 'fixture alias failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="fixture alias failure"):
        registry.remove_device(original["id"], tenant_id="acme", hard=True)
    assert state(registry) == before


def test_gc_failure_rolls_back_alias_telemetry_and_row(registry):
    original = device(registry)
    registry.save_telemetry(original["id"], {"hashrate_hs": 42}, tenant_id="acme")
    registry.remove_device(original["id"], tenant_id="acme")
    with registry._get_db() as connection:
        connection.execute(
            "UPDATE axe_devices SET removed_at=? WHERE id=?",
            (int(time.time()) - 40 * 86400, original["id"]),
        )
        connection.execute(
            "CREATE TRIGGER fail_gc_delete BEFORE DELETE ON axe_devices "
            "BEGIN SELECT RAISE(ABORT, 'fixture GC failure'); END"
        )
    before = state(registry)
    assert registry.gc_tombstones(max_age_days=30) == 0
    assert state(registry) == before


def test_gc_serializes_restore_before_candidate_read(registry):
    original = device(registry)
    registry.remove_device(original["id"], tenant_id="acme")
    with registry._get_db() as connection:
        connection.execute(
            "UPDATE axe_devices SET removed_at=? WHERE id=?",
            (int(time.time()) - 40 * 86400, original["id"]),
        )
    get_db = registry._get_db
    restore_errors = []

    def interleaved_db():
        connection = get_db()

        def try_restore(statement):
            if not statement.startswith("SELECT id, tenant_id FROM axe_devices"):
                return
            competing = get_db()
            try:
                competing.execute("PRAGMA busy_timeout=1")
                competing.execute(
                    "UPDATE axe_devices SET removed_at=0 WHERE id=? AND tenant_id=?",
                    (original["id"], "acme"),
                )
                competing.commit()
            except sqlite3.OperationalError as error:
                restore_errors.append(str(error))
                competing.rollback()
            finally:
                competing.close()

        connection.set_trace_callback(try_restore)
        return connection

    registry._get_db = interleaved_db
    assert registry.gc_tombstones(max_age_days=30) == 1
    assert restore_errors == ["database is locked"]
