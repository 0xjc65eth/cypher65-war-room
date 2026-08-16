"""Hermetic tests for services/webhook_queue.py — the persistent retry queue.

Covers:
  1. enqueue_webhook: persists a row with the first-retry delay.
  2. dispatch_webhook_or_queue: success → nothing queued; HTTP failure →
     queued for retry; below-threshold → NOT queued (legit skip).
  3. process_due_webhooks: delivers due rows, advances attempts with
     backoff on failure, drops rows past MAX_ATTEMPTS.
  4. queue_depth + ensure_table idempotency.
"""

import sys
import time

import pytest

sys.path.insert(0, ".")

import services.webhook_queue as wq  # noqa: E402


@pytest.fixture(autouse=True)
def clean_queue(monkeypatch):
    """Point at the conftest scratch DB and wipe the queue per test."""
    wq.ensure_table()
    from services.db import get_db
    conn = get_db()
    conn.execute("DELETE FROM webhook_queue")
    conn.commit()
    conn.close()
    yield
    conn = get_db()
    conn.execute("DELETE FROM webhook_queue")
    conn.commit()
    conn.close()


def _kwargs(url="https://discord.com/api/webhooks/x", severity="CRIT",
            category="worker_offline", message="Worker down"):
    return {"url": url, "severity": severity, "category": category,
            "message": message, "ts": int(time.time()), "worker": "w1",
            "address": "bc1qtest"}


def _rows():
    from services.db import get_db
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM webhook_queue ORDER BY id").fetchall()
    conn.close()
    return rows


# ── enqueue ────────────────────────────────────────────────────────────────

def test_enqueue_persists_with_first_retry_delay():
    assert wq.enqueue_webhook(_kwargs()) is True
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["attempts"] == 0
    assert rows[0]["next_retry_ts"] >= int(time.time()) + wq.WEBHOOK_RETRY_BACKOFF[0] - 2
    import json
    assert json.loads(rows[0]["payload"])["category"] == "worker_offline"


def test_enqueue_empty_url_is_noop():
    assert wq.enqueue_webhook({}) is False
    assert wq.enqueue_webhook({"url": ""}) is False
    assert len(_rows()) == 0


# ── dispatch_webhook_or_queue ──────────────────────────────────────────────

def test_dispatch_success_does_not_queue(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(
        wq, "send_webhook_for_alert",
        lambda **kw: calls.__setitem__("n", calls["n"] + 1) or True)
    ok = wq.dispatch_webhook_or_queue(**_kwargs())
    assert ok is True
    assert calls["n"] == 1
    assert len(_rows()) == 0  # success → nothing queued


def test_dispatch_failure_queues_for_retry(monkeypatch):
    monkeypatch.setattr(wq, "send_webhook_for_alert", lambda **kw: False)
    ok = wq.dispatch_webhook_or_queue(**_kwargs())
    assert ok is False
    rows = _rows()
    assert len(rows) == 1  # failed CRIT is persisted, not lost
    assert rows[0]["attempts"] == 0


def test_dispatch_below_threshold_not_queued(monkeypatch):
    """INFO below the WARN threshold is a legit skip — no queue noise."""
    monkeypatch.setattr(wq, "send_webhook_for_alert", lambda **kw: False)
    ok = wq.dispatch_webhook_or_queue(
        severity="INFO", category="uptime", message="uptime crossed",
        url="https://discord.com/api/webhooks/x")
    assert ok is False
    assert len(_rows()) == 0


def test_dispatch_exception_still_queues(monkeypatch):
    def boom(**kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(wq, "send_webhook_for_alert", boom)
    ok = wq.dispatch_webhook_or_queue(**_kwargs())
    assert ok is False
    assert len(_rows()) == 1


# ── process_due_webhooks ───────────────────────────────────────────────────

def test_process_delivers_due_row(monkeypatch):
    wq.enqueue_webhook(_kwargs(), delay_secs=0)
    monkeypatch.setattr(wq, "send_webhook_notification", lambda **kw: True)
    assert wq.process_due_webhooks(now=int(time.time()) + 1) == 1
    assert len(_rows()) == 0  # delivered → removed


def test_process_failure_advances_backoff(monkeypatch):
    wq.enqueue_webhook(_kwargs(), delay_secs=0)
    monkeypatch.setattr(wq, "send_webhook_notification", lambda **kw: False)
    assert wq.process_due_webhooks(now=int(time.time()) + 1) == 1
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["attempts"] == 1
    assert rows[0]["next_retry_ts"] >= int(time.time()) + wq.WEBHOOK_RETRY_BACKOFF[1] - 2


def test_process_drops_row_after_max_attempts(monkeypatch):
    # Simulate a row already at MAX-1 attempts failing once more → dropped.
    import json as _json
    from services.db import get_db
    conn = get_db()
    conn.execute(
        "INSERT INTO webhook_queue (payload, attempts, next_retry_ts, "
        "tenant_id, created_at) VALUES (?, ?, 0, '', ?)",
        (_json.dumps(_kwargs()), wq.WEBHOOK_MAX_ATTEMPTS - 1, int(time.time())))
    conn.commit()
    conn.close()
    monkeypatch.setattr(wq, "send_webhook_notification", lambda **kw: False)
    assert wq.process_due_webhooks(now=int(time.time()) + 1) == 1
    assert len(_rows()) == 0  # exhausted retries → dropped, logged


def test_queue_depth_counts_pending():
    assert wq.queue_depth() == 0
    wq.enqueue_webhook(_kwargs())
    wq.enqueue_webhook(_kwargs(severity="WARN"))
    assert wq.queue_depth() == 2
