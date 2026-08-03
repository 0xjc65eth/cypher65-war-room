"""
CYPHER65 // DONATION DEDUP — regression suite
==============================================
Locks the E2E-caught fix: `_record_donation` dedupes by txid/preimage, but
the legacy query `WHERE txid=? OR preimage=?` matched EMPTY proof fields —
so any row with txid='' (or preimage='') collided with EVERY subsequent
preimage-only / txid-only donation, returning 409 for legitimate payments.

The fixed query only matches when BOTH the incoming value and the stored
value are non-empty:

    WHERE (COALESCE(txid,'') <> '' AND txid=?)
       OR (COALESCE(preimage,'') <> '' AND preimage=?)

Hermetic: the shared conftest redirects DB_PATH to a scratch dir BEFORE any
module import (no module-level env override here — that would pollute every
other test in the process). Each test wipes only the donations table.
"""

import time

import pytest

import app as _app_module


@pytest.fixture(autouse=True)
def _clean_donations():
    """Wipe donations between tests (each test owns its own rows)."""
    yield
    conn = _app_module.get_db()
    c = conn.cursor()
    c.execute("DELETE FROM donations")
    conn.commit()
    conn.close()


def _seed(txid="", preimage=""):
    conn = _app_module.get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO donations (ts, method, amount_sat, txid, preimage, note, source) "
        "VALUES (?,?,?,?,?,?,?)",
        (int(time.time()), "btc", 100000, txid, preimage, "seed", "onchain"),
    )
    conn.commit()
    conn.close()


def test_preimage_only_donation_not_blocked_by_txid_row():
    """A WebLN lightning donation (preimage only, txid='') must NOT be seen
    as a duplicate of an on-chain row that has a real txid."""
    _seed(txid="a" * 64)  # onchain watcher row: txid set, preimage empty
    row = _app_module._record_donation(method="lightning", amount_sat=5000,
                                       preimage="pre1", source="webln")
    assert row is not None, "preimage-only donation wrongly rejected (txid-row collision)"
    assert row["preimage"] == "pre1"


def test_duplicate_preimage_still_rejected():
    """The dedup must still work for genuinely repeated preimages."""
    assert _app_module._record_donation(method="lightning", amount_sat=1,
                                        preimage="dup-pre", source="webln") is not None
    assert _app_module._record_donation(method="lightning", amount_sat=1,
                                        preimage="dup-pre", source="webln") is None


def test_txid_only_donation_not_blocked_by_preimage_row():
    """On-chain donation (txid only) must not collide with a preimage row."""
    _seed(preimage="pre1")  # preimage set, txid empty
    row = _app_module._record_donation(method="btc", amount_sat=7000,
                                       txid="b" * 64, source="onchain")
    assert row is not None, "txid-only donation wrongly rejected (preimage-row collision)"
    assert row["txid"] == "b" * 64


def test_duplicate_txid_still_rejected():
    """The dedup must still work for genuinely repeated txids."""
    assert _app_module._record_donation(method="btc", amount_sat=1,
                                        txid="dup-txid", source="onchain") is not None
    assert _app_module._record_donation(method="btc", amount_sat=1,
                                        txid="dup-txid", source="onchain") is None


def test_missing_proof_rejected():
    """No txid AND no preimage is still a hard reject (honest telemetry)."""
    assert _app_module._record_donation(method="lightning", amount_sat=1,
                                        source="webln") is None


def test_preimage_only_not_blocked_by_empty_proof_rows():
    """Rows with BOTH txid='' and preimage='' (manual-log edge) must not
    shadow a new preimage-only donation."""
    _seed(txid="", preimage="")  # degenerate row
    row = _app_module._record_donation(method="lightning", amount_sat=250,
                                       preimage="edge-pre", source="manual")
    assert row is not None, "preimage-only donation wrongly rejected (empty-proof-row collision)"
