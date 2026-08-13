"""Tests for the CFO rig-intelligence layer: trust score + per-tenant blacklist.

Covers:
  - compute_rig_trust_score(): median/MAD/worst methodology, grade bands,
    sample-size caps, NO DATA when no measured deliveries.
  - Blacklist CRUD: add/get/remove/is, tenant isolation (default vs named),
    persistence across reads, reject empty ids.
  - Exclusion threshold: the "hide bad rigs" filter the frontend uses
    (blacklisted OR grade F).
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import rental_performance as rp  # noqa: E402


def _pcts(history):
    """Extract percents from a history list the way the trust scorer does."""
    return [h["percent"] for h in history if h.get("percent") is not None]


# ── compute_rig_trust_score ───────────────────────────────────────────────

def test_trust_no_data():
    r = rp.compute_rig_trust_score([])
    assert r["score"] is None
    assert r["grade"] is None
    assert r["label"] == "NO DATA"
    assert r["samples"] == 0


def test_trust_ignores_missing_percent():
    history = [{"percent": None}, {}, {"percent": 96.0}]
    r = rp.compute_rig_trust_score(history)
    assert r["samples"] == 1
    assert r["median_pct"] == 96.0


def test_trust_steady_high_delivery_is_a():
    # A rig that consistently delivers ~98% must earn an A.
    history = [{"percent": 97.0}, {"percent": 98.0}, {"percent": 99.0},
               {"percent": 98.0}, {"percent": 98.5}]
    r = rp.compute_rig_trust_score(history)
    assert r["grade"] == "A"
    assert r["score"] >= 90
    assert r["median_pct"] == 98.0


def test_trust_single_rental_capped_below_a():
    # One excellent rental is not enough for an A (confidence cap).
    history = [{"percent": 100.0}]
    r = rp.compute_rig_trust_score(history)
    assert r["grade"] in ("B", "C")
    assert r["score"] <= 89.0


def test_trust_terrible_worst_penalizes():
    # One 40% disaster must drag the score well down even with a good median.
    history = [{"percent": 96.0}, {"percent": 97.0}, {"percent": 98.0},
               {"percent": 95.0}, {"percent": 40.0}]
    r = rp.compute_rig_trust_score(history)
    assert r["worst_pct"] == 40.0
    assert r["grade"] in ("D", "F")


def test_trust_volatile_rig_penalized_by_mad():
    # Same median, but wild swings → lower score than the steady rig.
    volatile = [{"percent": 60.0}, {"percent": 100.0}, {"percent": 75.0},
                {"percent": 98.0}, {"percent": 65.0}]
    steady = [{"percent": 96.0}, {"percent": 97.0}, {"percent": 98.0},
              {"percent": 97.5}, {"percent": 96.5}]
    rv = rp.compute_rig_trust_score(volatile)
    rs = rp.compute_rig_trust_score(steady)
    assert rs["score"] > rv["score"]


def test_trust_grade_f_flagged_avoid():
    history = [{"percent": 50.0}, {"percent": 55.0}, {"percent": 60.0},
               {"percent": 58.0}, {"percent": 52.0}]
    r = rp.compute_rig_trust_score(history)
    assert r["grade"] == "F"
    assert r["score"] < 60


# ── Mutation-testing survivors (Issue #43): each test below kills a real
#    surviving mutant — the previous suite never exercised these branches. ──

def test_to_float_coercion_matrix():
    """_to_float on the input shapes callers actually pass: numeric string,
    blank, garbage, None, and int 0 — kills the `v == ""` survivor (#11)."""
    assert rp._to_float("96.0") == 96.0
    assert rp._to_float("") is None
    assert rp._to_float("abc") is None
    assert rp._to_float(None) is None
    assert rp._to_float(0) == 0.0


def test_trust_median_odd_distinct_values():
    """Odd sample count where s[n//2] != s[n//3] — kills the n//2→n//3
    survivor (#17): the old A-band test used [97,98,99,98,98.5] whose
    median equals the n//3 index by coincidence, so the mutant lived."""
    history = [{"percent": 90.0}, {"percent": 91.0}, {"percent": 92.0},
               {"percent": 93.0}, {"percent": 99.0}]
    r = rp.compute_rig_trust_score(history)
    assert r["samples"] == 5
    assert r["median_pct"] == 92.0


def test_trust_median_even_averages_centrals():
    """Even sample count → median is the mean of the two central values;
    kills the `(s[n//2-1] + s[n//2]) / 2.0` decomposition survivors."""
    history = [{"percent": 90.0}, {"percent": 95.0},
               {"percent": 100.0}, {"percent": 105.0}]
    r = rp.compute_rig_trust_score(history)
    assert r["samples"] == 4
    assert r["median_pct"] == 97.5


def test_trust_grade_b_label_is_reliable():
    """A solid B-band rig must carry the RELIABLE label — kills the
    RIG_GRADE_LABEL['B'] survivor (label was never asserted)."""
    history = [{"percent": 91.0}, {"percent": 92.0}, {"percent": 93.0},
               {"percent": 92.0}, {"percent": 91.5}]
    r = rp.compute_rig_trust_score(history)
    assert r["grade"] == "B"
    assert r["label"] == "RELIABLE"


def test_trust_grade_f_label_is_avoid():
    """Grade F must carry the AVOID label (frontend hides these rigs) —
    kills the RIG_GRADE_LABEL['F'] survivor."""
    history = [{"percent": 48.0}, {"percent": 52.0}, {"percent": 50.0},
               {"percent": 55.0}, {"percent": 45.0}]
    r = rp.compute_rig_trust_score(history)
    assert r["grade"] == "F"
    assert r["label"] == "AVOID"


def test_trust_confidence_cap_n_lt_5_blocks_a():
    """3 excellent samples must NOT earn an A (confidence cap n<5 → ≤94).
    Kills the `elif n < 5` cap survivor."""
    history = [{"percent": 98.0}, {"percent": 99.0}, {"percent": 100.0}]
    r = rp.compute_rig_trust_score(history)
    assert r["samples"] == 3
    assert r["score"] <= 94.0
    assert r["grade"] != "A"


def test_trust_score_clamped_floor_zero():
    """A rig whose MAD + worst penalty drive the score negative must clamp
    to 0.0, not leak a negative number — kills the `max(0.0, …)` survivor."""
    history = [{"percent": 0.0}, {"percent": 50.0}, {"percent": 100.0}]
    r = rp.compute_rig_trust_score(history)
    assert r["score"] == 0.0
    assert r["grade"] == "F"


# ── Blacklist CRUD (default tenant) ───────────────────────────────────────

@pytest.fixture
def bl_db(tmp_path, monkeypatch):
    """Isolated sqlite with settings + tenant_settings tables."""
    db = tmp_path / "bl.sqlite"
    import sqlite3
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT, updated_ts INTEGER)")
    conn.execute("CREATE TABLE tenant_settings (tenant_id TEXT, key TEXT, value TEXT, updated_ts INTEGER, PRIMARY KEY(tenant_id, key))")
    conn.commit()
    conn.close()

    def _get_db():
        c = sqlite3.connect(str(db))
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(rp, "get_db", _get_db)
    monkeypatch.setattr(rp, "is_default_tenant", lambda t: not t)
    return str(db)


def test_blacklist_add_get_remove(bl_db):
    assert rp.get_rig_blacklist() == []
    assert rp.add_rig_to_blacklist("rig-42") is True
    assert rp.get_rig_blacklist() == ["rig-42"]
    assert rp.is_rig_blacklisted("rig-42") is True
    assert rp.is_rig_blacklisted("rig-43") is False
    assert rp.remove_rig_from_blacklist("rig-42") is True
    assert rp.get_rig_blacklist() == []
    assert rp.is_rig_blacklisted("rig-42") is False


def test_blacklist_ignores_empty_id(bl_db):
    assert rp.add_rig_to_blacklist(None) is False
    assert rp.add_rig_to_blacklist("") is False
    assert rp.get_rig_blacklist() == []


def test_blacklist_idempotent(bl_db):
    rp.add_rig_to_blacklist("x")
    rp.add_rig_to_blacklist("x")
    assert rp.get_rig_blacklist() == ["x"]


# ── Tenant isolation ──────────────────────────────────────────────────────

def test_blacklist_tenant_isolated(bl_db, monkeypatch):
    monkeypatch.setattr(rp, "is_default_tenant", lambda t: t == "")
    rp.add_rig_to_blacklist("shared-rig", tenant_id="tenant-a")
    rp.add_rig_to_blacklist("other-rig", tenant_id="tenant-b")

    # Each named tenant sees ONLY its own blacklist; default sees none of them.
    assert rp.get_rig_blacklist(tenant_id="tenant-a") == ["shared-rig"]
    assert rp.get_rig_blacklist(tenant_id="tenant-b") == ["other-rig"]
    assert rp.get_rig_blacklist() == []
    assert rp.is_rig_blacklisted("shared-rig", tenant_id="tenant-a") is True
    assert rp.is_rig_blacklisted("shared-rig", tenant_id="tenant-b") is False


def test_blacklist_persists_rows(bl_db):
    rp.add_rig_to_blacklist("rig-persist")
    rp.add_rig_to_blacklist("rig-persist-2", tenant_id="t1")
    # Re-read through a fresh connection (simulates a restart).
    assert rp.get_rig_blacklist() == ["rig-persist"]
    assert rp.get_rig_blacklist(tenant_id="t1") == ["rig-persist-2"]


# ── Exclusion threshold (frontend "hide bad rigs" contract) ──────────────

def _is_bad(history, blacklisted=False, tenant_id=""):
    """Mirror of the frontend _rentalIsBad: blacklisted OR grade F."""
    trust = rp.compute_rig_trust_score(history)
    if blacklisted:
        return True
    return trust["grade"] == "F"


def test_exclusion_blacklisted_rig():
    assert _is_bad([{"percent": 99.0}], blacklisted=True) is True


def test_exclusion_grade_f_rig():
    history = [{"percent": 48.0}, {"percent": 52.0}, {"percent": 50.0},
               {"percent": 55.0}, {"percent": 45.0}]
    assert _is_bad(history) is True


def test_exclusion_good_rig_not_excluded():
    history = [{"percent": 96.0}, {"percent": 97.0}, {"percent": 98.0},
               {"percent": 97.0}, {"percent": 96.0}]
    assert _is_bad(history) is False
