"""Hermetic tests for the Learning FAQ loop (Issue #19, services/doc_feedback.py).

Covers:
  1. is_valid_section: shape guard (rejects junk / non-strings).
  2. record_doc_feedback: persists, upserts per (tenant, section) — a re-vote
     overwrites instead of duplicating, and a fresh comment is merged.
  3. my_doc_feedback: only the tenant's own votes, bool-normalized.
  4. doc_feedback_summary: per-section totals/helpful %, ordering by votes
     desc, recurring questions (newest first), tenant masked, honest None
     when there are no votes.
  5. Routes: POST /api/docs/feedback (valid/invalid), GET mine,
     /api/admin/docs-feedback gate (403 remote, 200 with operator key).
"""

import sys

import pytest

sys.path.insert(0, ".")

import services.doc_feedback as fb  # noqa: E402


@pytest.fixture
def isolated_client():
    """Flask test client against the conftest-owned SCRATCH DB."""
    import app as _app_module

    _app_module.app.config["TESTING"] = True
    return _app_module.app.test_client()


@pytest.fixture()
def clean_feedback(monkeypatch):
    """Ensure the table exists and wipe it per test."""
    from services.db import get_db

    fb.ensure_table()
    conn = get_db()
    conn.execute("DELETE FROM doc_feedback")
    conn.commit()
    conn.close()
    yield
    conn = get_db()
    conn.execute("DELETE FROM doc_feedback")
    conn.commit()
    conn.close()


# ── is_valid_section ───────────────────────────────────────────────────────


def test_is_valid_section_shape_guard():
    assert fb.is_valid_section("docs-faq") is True
    assert fb.is_valid_section("docs_fleet") is True
    assert fb.is_valid_section("docs-probability") is True
    assert fb.is_valid_section("") is False
    assert fb.is_valid_section("docs faq") is False  # space
    assert fb.is_valid_section("docs/../../etc") is False  # traversal
    assert fb.is_valid_section(42) is False  # non-string
    assert fb.is_valid_section("x" * 65) is False  # too long


# ── record_doc_feedback ────────────────────────────────────────────────────


def test_record_persists_and_upserts(clean_feedback):
    from services.db import get_db

    assert fb.record_doc_feedback("docs-faq", True, tenant_id="acme") is True
    # Same tenant + section re-votes → still ONE row, updated value.
    assert fb.record_doc_feedback("docs-faq", False, tenant_id="acme") is True
    # Different section → separate row.
    assert fb.record_doc_feedback("docs-market", True, tenant_id="acme") is True
    # Different tenant → separate row.
    assert fb.record_doc_feedback("docs-faq", True, tenant_id="zeta") is True

    conn = get_db()
    rows = conn.execute(
        "SELECT tenant_id, section_id, helpful FROM doc_feedback"
    ).fetchall()
    conn.close()
    assert len(rows) == 3
    by_key = {(r["tenant_id"], r["section_id"]): r["helpful"] for r in rows}
    assert by_key[("acme", "docs-faq")] == 0  # overwritten by the re-vote
    assert by_key[("acme", "docs-market")] == 1
    assert by_key[("zeta", "docs-faq")] == 1


def test_record_merges_comment_on_revote(clean_feedback):
    from services.db import get_db

    fb.record_doc_feedback(
        "docs-latency", False, "latency numbers missing", tenant_id="acme"
    )
    fb.record_doc_feedback(
        "docs-latency", False, "also want ping tool", tenant_id="acme"
    )
    conn = get_db()
    row = conn.execute(
        "SELECT comment FROM doc_feedback WHERE section_id = 'docs-latency'"
    ).fetchone()
    conn.close()
    assert "latency numbers missing" in row["comment"]
    assert "also want ping tool" in row["comment"]


def test_record_rejects_invalid_section(clean_feedback):
    from services.db import get_db

    assert fb.record_doc_feedback("bad section!", True, tenant_id="acme") is False
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) AS n FROM doc_feedback").fetchone()["n"]
    conn.close()
    assert n == 0


# ── my_doc_feedback ────────────────────────────────────────────────────────


def test_my_doc_feedback_scoped_and_bool(clean_feedback):
    fb.record_doc_feedback("docs-faq", True, tenant_id="acme")
    fb.record_doc_feedback("docs-fleet", False, tenant_id="acme")
    fb.record_doc_feedback("docs-faq", True, tenant_id="zeta")

    mine = fb.my_doc_feedback("acme")
    assert {v["section_id"]: v["helpful"] for v in mine} == {
        "docs-faq": True,
        "docs-fleet": False,
    }
    assert fb.my_doc_feedback("nobody") == []


# ── doc_feedback_summary ───────────────────────────────────────────────────


def test_summary_aggregates_and_orders(clean_feedback):
    fb.record_doc_feedback("docs-faq", True, tenant_id="acme")
    fb.record_doc_feedback("docs-faq", True, tenant_id="zeta")
    # Upsert semantics: acme re-votes docs-faq → overwrites, no duplicate row.
    fb.record_doc_feedback("docs-faq", False, "what about mobile?", tenant_id="acme")
    fb.record_doc_feedback("docs-market", True, tenant_id="zeta")

    s = fb.doc_feedback_summary()
    assert s["total_votes"] == 3  # acme×1 + zeta×1 on faq + zeta×1 on market
    assert s["sections_with_feedback"] == 2
    assert s["overall_helpful_pct"] == 66.7
    by_sec = {x["section_id"]: x for x in s["sections"]}
    # Ordering: votes desc → docs-faq (2) first, docs-market (1) second.
    assert s["sections"][0]["section_id"] == "docs-faq"
    assert by_sec["docs-faq"]["total"] == 2
    assert by_sec["docs-faq"]["helpful"] == 1
    assert by_sec["docs-faq"]["not_helpful"] == 1
    assert by_sec["docs-faq"]["helpful_pct"] == 50.0
    assert by_sec["docs-market"]["helpful_pct"] == 100.0
    # Recurring questions: only non-empty comments, newest first, tenant masked.
    assert len(s["recurring_questions"]) == 1
    q = s["recurring_questions"][0]
    assert q["section_id"] == "docs-faq"
    assert q["comment"] == "what about mobile?"
    assert "acme" in q["tenant"]  # masked but recognizable prefix


def test_summary_empty_is_honest(clean_feedback):
    s = fb.doc_feedback_summary()
    assert s["total_votes"] == 0
    assert s["overall_helpful_pct"] is None  # never fabricate 0% without data
    assert s["sections"] == []
    assert s["recurring_questions"] == []


# ── Routes ─────────────────────────────────────────────────────────────────


def test_post_feedback_valid(isolated_client, clean_feedback):
    resp = isolated_client.post(
        "/api/docs/feedback",
        json={"section_id": "docs-faq", "helpful": True},
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["ok"] is True and data["section_id"] == "docs-faq"


def test_post_feedback_invalid_payloads(isolated_client, clean_feedback):
    # helpful must be a boolean.
    r1 = isolated_client.post(
        "/api/docs/feedback", json={"section_id": "docs-faq", "helpful": "yes"}
    )
    assert r1.status_code == 400
    # section_id shape guard.
    r2 = isolated_client.post(
        "/api/docs/feedback", json={"section_id": "docs faq", "helpful": True}
    )
    assert r2.status_code == 400


def test_get_my_feedback(isolated_client, clean_feedback):
    isolated_client.post(
        "/api/docs/feedback",
        json={"section_id": "docs-faq", "helpful": False, "comment": "no examples"},
    )
    resp = isolated_client.get("/api/docs/feedback")
    assert resp.status_code == 200
    votes = resp.get_json()["votes"]
    assert votes[0]["section_id"] == "docs-faq"
    assert votes[0]["helpful"] is False


def test_admin_docs_feedback_requires_admin(isolated_client, clean_feedback):
    # Simulate a remote caller with no operator key → 403.
    resp = isolated_client.get(
        "/api/admin/docs-feedback",
        environ_base={"REMOTE_ADDR": "203.0.113.5"},
    )
    assert resp.status_code == 403


def test_admin_docs_feedback_with_operator_key(
    isolated_client, clean_feedback, monkeypatch
):
    monkeypatch.setenv("API_KEY", "operator-key-123")
    fb.record_doc_feedback("docs-faq", True, tenant_id="acme")
    fb.record_doc_feedback(
        "docs-faq", False, "how do I add a smart plug?", tenant_id="zeta"
    )
    resp = isolated_client.get(
        "/api/admin/docs-feedback",
        headers={"X-API-Key": "operator-key-123"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_votes"] == 2
    assert data["sections"][0]["section_id"] == "docs-faq"
    # Full loop end-to-end: comment seeded → surfaces in the admin list.
    assert len(data["recurring_questions"]) == 1
    assert data["recurring_questions"][0]["comment"] == "how do I add a smart plug?"
