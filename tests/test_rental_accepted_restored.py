"""Tests for the 'restored' marker on accepted-recommendation entries.

When the operator RESTORES a blacklisted rig (remove_rig_from_blacklist),
the ledger entry is marked ``restored`` (+ restored_ts) and the verdict
becomes ``revoked`` — the decision was reversed, not evaluated by the
delivery afterwards.

Covers:
  - Restore marks the ledger entry (restored + restored_ts) and the verdict
    flips to 'revoked' — even when new deliveries exist afterwards.
  - Re-blacklist after a restore creates a FRESH entry without the flag
    (the new decision is not revoked).
  - Idempotency: restore without a ledger entry is a safe no-op.
  - Tenant isolation: restoring in one tenant never touches another's.
  - Admin audit: by_verdict aggregates 'revoked'.
"""
import datetime as _dt
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import rental_performance as rp  # noqa: E402

NOW = 1_800_000_000  # fixed "now" — deterministic before/after windows


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Per-test scratch DB (get_db reads DB_PATH at call time)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.sqlite"))


@pytest.fixture(autouse=True)
def _freeze_time(monkeypatch):
    """Deterministic 'now' — ledger ts/restored_ts come from rp.time.time."""
    monkeypatch.setattr(rp.time, "time", lambda: NOW)


def _dt_str(ts):
    """Unix ts → MRR-style start string (UTC)."""
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC")


def _hr(rental_id, rig_id, start, pct, cost=None):
    """A rental_history row shaped like _rental_to_history_row output."""
    return {
        "provider": "mrr", "bucket": "renter", "rental_id": rental_id,
        "rig_id": rig_id, "rig_name": "rig-" + rig_id,
        "start": start, "end": None, "percent": pct,
        "avg_th": 100.0, "advertised_th": 100.0,
        "cost_sats_per_thh": cost, "length_hours": 24.0,
        "delivered_thh": 2400.0, "paid_sats": None,
        "network_hashrate_hs": None,
    }


def _seed(rows, tenant_id=""):
    assert rp.save_rental_history(rows, tenant_id=tenant_id) is True


# ── Restore marks + verdict flips ──────────────────────────────────────────

def test_restore_marks_ledger_and_verdict_revoked(db):
    """Restoring a blacklisted rig marks restored + verdict becomes 'revoked'
    even though deliveries afterwards exist (decision was reversed)."""
    _seed([_hr("r1", "rig-a", _dt_str(NOW - 20 * 86400), 72.0),
           _hr("r2", "rig-a", _dt_str(NOW - 10 * 86400), 78.0)])
    assert rp.add_rig_to_blacklist("rig-a") is True
    # New delivery AFTER the acceptance — would normally read 'improved'.
    _seed([_hr("r3", "rig-a", _dt_str(NOW + 5 * 86400), 95.0)])

    assert rp.remove_rig_from_blacklist("rig-a") is True

    recos = rp.get_accepted_recos()
    assert len(recos) == 1
    e = recos[0]
    assert e["rig_id"] == "rig-a"
    assert e.get("restored") is True
    assert e.get("restored_ts") == NOW
    # The rig is out of the blacklist.
    assert rp.is_rig_blacklisted("rig-a") is False

    outcome = rp.compute_accepted_recos_summary()["accepted"][0]
    assert outcome["verdict"] == "revoked"
    # Delivery-outcome fields still computed for reference.
    assert outcome["delivery_after_pct"] == 95.0


def test_restore_marks_auto_excluded_rig(db):
    """Auto-excluded rigs also carry the ledger entry — restore flips it."""
    _seed([_hr("r1", "rig-b", _dt_str(NOW - 86400), 55.0)])
    assert rp.add_rig_to_auto_blacklist("rig-b") is True
    assert rp.remove_rig_from_blacklist("rig-b") is True
    e = rp.get_accepted_recos()[0]
    assert e["source"] == "auto"
    assert e.get("restored") is True
    assert rp.compute_accepted_recos_summary()["accepted"][0]["verdict"] == "revoked"


# ── Re-blacklist after restore → fresh entry, not revoked ──────────────────

def test_reblacklist_after_restore_clears_flag(db):
    """A NEW blacklist after a restore is a fresh decision — no restored flag,
    verdict derives from delivery again."""
    _seed([_hr("r1", "rig-c", _dt_str(NOW - 10 * 86400), 60.0)])
    rp.add_rig_to_blacklist("rig-c")
    rp.remove_rig_from_blacklist("rig-c")
    # Restored entry present.
    assert rp.get_accepted_recos()[0].get("restored") is True

    # Re-blacklist → NEW entry (oldest dropped by dedup), no restored flag.
    _seed([_hr("r2", "rig-c", _dt_str(NOW - 5 * 86400), 62.0)])
    assert rp.add_rig_to_blacklist("rig-c") is True
    recos = rp.get_accepted_recos()
    assert len(recos) == 1
    assert recos[0]["rig_id"] == "rig-c"
    assert recos[0].get("restored") is None or recos[0].get("restored") is False
    outcome = rp.compute_accepted_recos_summary()["accepted"][0]
    assert outcome["verdict"] != "revoked"


# ── Idempotency / no ledger entry ──────────────────────────────────────────

def test_restore_without_ledger_entry_is_noop(db):
    """Restoring a rig that was never in the ledger must not crash nor create
    a phantom entry."""
    _seed([_hr("r1", "rig-d", _dt_str(NOW - 86400), 90.0)])
    assert rp.remove_rig_from_blacklist("rig-d") is True
    assert rp.get_accepted_recos() == []


# ── Tenant isolation ───────────────────────────────────────────────────────

def test_restore_tenant_isolation(db):
    """Restoring in tenant A never marks tenant B's ledger entry."""
    _seed([_hr("r1", "rig-t", _dt_str(NOW - 86400), 55.0)], tenant_id="tA")
    _seed([_hr("r2", "rig-t", _dt_str(NOW - 86400), 55.0)], tenant_id="tB")
    assert rp.add_rig_to_blacklist("rig-t", tenant_id="tA") is True
    assert rp.add_rig_to_blacklist("rig-t", tenant_id="tB") is True

    assert rp.remove_rig_from_blacklist("rig-t", tenant_id="tA") is True
    assert rp.get_accepted_recos(tenant_id="tA")[0].get("restored") is True
    # Tenant B untouched.
    b_entry = rp.get_accepted_recos(tenant_id="tB")[0]
    assert b_entry.get("restored") is None or b_entry.get("restored") is False


# ── Admin audit aggregates 'revoked' ───────────────────────────────────────

def test_admin_by_verdict_includes_revoked(db):
    """The global admin audit counts revoked decisions in by_verdict."""
    _seed([_hr("r1", "rig-x", _dt_str(NOW - 86400), 58.0)])
    rp.add_rig_to_blacklist("rig-x")
    rp.remove_rig_from_blacklist("rig-x")

    _seed([_hr("r2", "rig-y", _dt_str(NOW - 86400), 96.0)])
    rp.add_rig_to_blacklist("rig-y")  # stays accepted (no restore)

    summary = rp.compute_admin_accepted_recos()
    assert summary["by_verdict"].get("revoked") == 1
    assert summary["by_verdict"].get("avoided") == 1
    revoked = [d for d in summary["decisions"] if d["rig_id"] == "rig-x"]
    assert revoked and revoked[0]["verdict"] == "revoked"
