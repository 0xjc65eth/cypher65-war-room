"""
Tests for FASE 2 — per-tenant alerts + webhooks in the UserPollingWorker.

Multi-user deployments (1000+ users): every user's session worker must
generate alerts with the USER'S OWN thresholds, persist them tenant-scoped,
and fire the USER'S OWN webhook — never the operator's or another tenant's.

Guarantees pinned here:
  1. evaluate_user_alerts() mirrors _do_poll wallet anomalies but is driven
     by the tenant's settings (stale_share_minutes, hashrate_drop_pct) and
     dedups via a (category, identifier) signature set.
  2. Pool-wide events (new block / pool high diff) are NOT evaluated per
     user — they are global facts and would spam every tenant's webhook.
  3. UserPollingWorker(tenant_id=...) persists alerts with that tenant_id
     and dispatches webhooks to THAT tenant's URL + severity threshold.
  4. /api/connect-wallet threads the caller's tenant_id into the worker.
  5. app._webhook_dispatch resolves the webhook of alert.tenant_id.
"""

import time

import pytest

import app as _app_module
import services.user_polling as _up
from services.db import get_db
from services.session_manager import SessionManager
from core.alerts.alert_engine import Alert


@pytest.fixture(autouse=True)
def _clean_state():
    """Fresh caches + clean alerts/settings tables before EVERY test (the
    scratch DB persists across tests, so rows must not leak)."""
    from services import settings as _settings_mod
    _settings_mod.invalidate_cache()
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM alerts")
        c.execute("DELETE FROM alert_history")
        c.execute("DELETE FROM settings")
        c.execute("DELETE FROM tenant_settings")
        conn.commit()
        conn.close()
    except Exception:
        pass
    yield
    _settings_mod.invalidate_cache()


@pytest.fixture
def sync_webhooks(monkeypatch):
    """Run the worker's fire-and-forget webhook dispatch synchronously (the
    real code spawns a daemon thread per POST; tests need the patched
    send_webhook_for_alert to have run before asserting)."""
    monkeypatch.setattr(
        _up, "_fire_webhook_async",
        lambda kwargs: _up._send_webhook_for_alert(**kwargs))


@pytest.fixture
def rclient():
    _app_module.app.config["TESTING"] = True
    _app_module.app.config["JWT_SECRET_KEY"] = "cypher65-test-secret-key-0123456789"
    with _app_module.app.test_client() as c:
        yield c


def _token(tenant_id: str, role: str = "admin") -> str:
    from services.auth import create_token
    with _app_module.app.app_context():
        return create_token(subject=tenant_id, extra_claims={"role": role})


def _snap(ts, last_submission=None, hashrate=100.0, uptime=None,
          worker_present=True):
    worker = None
    if worker_present:
        worker = {
            "name": "w1",
            "hashrate": hashrate,
            "lastSubmission": last_submission,
            "uptime": uptime,
        }
    return {
        "ts": ts,
        "worker": worker,
        "all_workers": [],
        "alerts_recent": [],
    }


def _settings(**kw):
    s = {
        "stale_share_minutes": "5",
        "hashrate_drop_pct": "50",
        "webhook_url": "",
        "webhook_min_severity": "WARN",
    }
    s.update(kw)
    return s


# ── evaluate_user_alerts: pure logic ────────────────────────────────────────

def test_stale_submission_warn_then_crit_and_dedup():
    now = int(time.time())
    seen = set()

    # 7 min stale with 5 min threshold → WARN.
    out = _up.evaluate_user_alerts(
        _snap(now, last_submission=now - 420, hashrate=100),
        {}, _settings(), seen)
    assert out == [("WARN", "stale_submission", out[0][2])]

    # Same lastSubmission on next poll → deduped (no re-fire).
    assert _up.evaluate_user_alerts(
        _snap(now + 15, last_submission=now - 420, hashrate=100),
        {}, _settings(), seen) == []

    # 12 min stale (> 2x threshold) → CRIT.
    seen2 = set()
    out2 = _up.evaluate_user_alerts(
        _snap(now, last_submission=now - 720, hashrate=100),
        {}, _settings(), seen2)
    assert out2[0][0] == "CRIT"


def test_hashrate_drop_uses_tenant_threshold():
    seen = set()
    # Prev poll had 100; now 40 → 60% drop > 50% threshold → WARN.
    out = _up.evaluate_user_alerts(
        _snap(int(time.time()), hashrate=40),
        _snap(int(time.time()) - 15, hashrate=100),
        _settings(), seen)
    assert out and out[0][0:2] == ("WARN", "hashrate_drop")

    # Below threshold → no alert.
    seen2 = set()
    out2 = _up.evaluate_user_alerts(
        _snap(int(time.time()), hashrate=80),
        _snap(int(time.time()) - 15, hashrate=100),
        _settings(hashrate_drop_pct="50"), seen2)
    assert out2 == []

    # Tenant tuned threshold tighter (10%): a 20% drop now fires.
    seen3 = set()
    out3 = _up.evaluate_user_alerts(
        _snap(int(time.time()), hashrate=80),
        _snap(int(time.time()) - 15, hashrate=100),
        _settings(hashrate_drop_pct="10"), seen3)
    assert out3 and out3[0][0:2] == ("WARN", "hashrate_drop")


def test_worker_offline_fires_once_per_transition():
    now = int(time.time())
    seen = set()
    # No worker, no previous worker → nothing (baseline poll).
    assert _up.evaluate_user_alerts(_snap(now, worker_present=False),
                                    {}, _settings(), seen) == []
    # Previously present → CRIT once.
    out = _up.evaluate_user_alerts(
        _snap(now, worker_present=False),
        _snap(now - 15, hashrate=100), _settings(), seen)
    assert out == [("CRIT", "worker_offline", out[0][2])]
    # Still offline → deduped.
    assert _up.evaluate_user_alerts(
        _snap(now + 15, worker_present=False),
        _snap(now, worker_present=False), _settings(), seen) == []
    # Back online clears the sig → next offline re-fires.
    _up.evaluate_user_alerts(_snap(now + 30, hashrate=100),
                             {}, _settings(), seen)
    out2 = _up.evaluate_user_alerts(
        _snap(now + 45, worker_present=False),
        _snap(now + 30, hashrate=100), _settings(), seen)
    assert out2 == [("CRIT", "worker_offline", out2[0][2])]


def test_uptime_milestone_fires_once_per_day():
    seen = set()
    out = _up.evaluate_user_alerts(
        _snap(int(time.time()), hashrate=100, uptime=86400),
        {}, _settings(), seen)
    assert out == [("INFO", "uptime", out[0][2])]
    assert _up.evaluate_user_alerts(
        _snap(int(time.time()) + 15, hashrate=100, uptime=86405),
        {}, _settings(), seen) == []


def test_pool_events_are_not_per_user():
    """Pool facts (new block / high diff) must NOT fire per tenant."""
    seen = set()
    snap = _snap(int(time.time()), hashrate=100)
    snap["pool"] = {"lastBlockHash": "abc", "highestDifficulty": "87.1T"}
    prev = _snap(int(time.time()) - 15, hashrate=100)
    prev["pool"] = {"lastBlockHash": "old", "highestDifficulty": "80T"}
    assert _up.evaluate_user_alerts(snap, prev, _settings(), seen) == []


# ── UserPollingWorker: tenant-scoped dispatch ───────────────────────────────

def test_worker_dispatches_tenant_webhook(monkeypatch, sync_webhooks):
    tenant = "tenant-aaa"
    now = int(time.time())
    snap = _snap(now, last_submission=now - 420, hashrate=100)  # stale → WARN

    monkeypatch.setattr(_up, "_build_snapshot", lambda a, w: snap)
    monkeypatch.setattr(
        _up, "_load_settings",
        lambda tid: _settings(
            webhook_url="https://discord.com/api/webhooks/tenant-aaa",
            webhook_min_severity="WARN"))

    calls = []
    monkeypatch.setattr(
        _up, "_send_webhook_for_alert",
        lambda **kw: calls.append(kw) or True)

    sm = SessionManager()
    session = sm.create_session("bc1qtest", "w1")
    worker = _up.UserPollingWorker(session.session_id, sm, "bc1qtest",
                                   "w1", tenant_id=tenant)
    worker.poll_now()

    # Webhook fired to the TENANT's URL with the tenant's threshold + wallet.
    assert len(calls) == 1
    assert calls[0]["url"] == "https://discord.com/api/webhooks/tenant-aaa"
    assert calls[0]["min_severity"] == "WARN"
    assert calls[0]["category"] == "stale_submission"
    assert calls[0]["address"] == "bc1qtest"

    # Alert persisted tenant-scoped (visible to that tenant's /api/alerts).
    conn = get_db()
    row = conn.execute(
        "SELECT tenant_id, severity, category FROM alerts WHERE tenant_id=?",
        (tenant,)).fetchone()
    hist = conn.execute(
        "SELECT tenant_id FROM alert_history WHERE tenant_id=?",
        (tenant,)).fetchone()
    conn.close()
    assert row is not None and row["severity"] == "WARN"
    assert hist is not None

    # Snapshot feed surfaces the alert for the user's dashboard.
    stored = sm.get_snapshot(session.session_id)
    assert stored and stored.get("alerts_recent")
    assert stored["alerts_recent"][0]["severity"] == "WARN"

    sm.stop()


def test_worker_no_webhook_when_tenant_has_none(monkeypatch, sync_webhooks):
    now = int(time.time())
    snap = _snap(now, last_submission=now - 420, hashrate=100)
    monkeypatch.setattr(_up, "_build_snapshot", lambda a, w: snap)
    monkeypatch.setattr(_up, "_load_settings",
                        lambda tid: _settings(webhook_url=""))

    calls = []
    monkeypatch.setattr(_up, "_send_webhook_for_alert",
                        lambda **kw: calls.append(kw) or True)

    sm = SessionManager()
    session = sm.create_session("bc1qtest", "w1")
    worker = _up.UserPollingWorker(session.session_id, sm, "bc1qtest",
                                   "w1", tenant_id="tenant-bbb")
    worker.poll_now()

    # Alert still persisted for the tenant, but NO webhook fired.
    assert calls == []
    conn = get_db()
    row = conn.execute(
        "SELECT tenant_id FROM alerts WHERE tenant_id='tenant-bbb'").fetchone()
    conn.close()
    assert row is not None
    sm.stop()


def test_worker_settings_and_webhook_are_isolated_between_tenants(monkeypatch, sync_webhooks):
    """Tenant A's webhook must never fire for tenant B — even when B has no
    webhook configured and A does. Each worker reads ONLY its own settings."""
    now = int(time.time())
    snap = _snap(now, last_submission=now - 420, hashrate=100)

    monkeypatch.setattr(_up, "_build_snapshot", lambda a, w: snap)

    settings_by_tenant = {
        "tenant-aaa": _settings(
            webhook_url="https://discord.com/api/webhooks/AAA"),
        "tenant-bbb": _settings(webhook_url=""),
    }
    monkeypatch.setattr(_up, "_load_settings",
                        lambda tid: settings_by_tenant[tid])

    calls = []
    monkeypatch.setattr(_up, "_send_webhook_for_alert",
                        lambda **kw: calls.append(kw) or True)

    sm = SessionManager()
    sa = sm.create_session("bc1qaaa", "w1")
    sb = sm.create_session("bc1qbbb", "w1")
    wa = _up.UserPollingWorker(sa.session_id, sm, "bc1qaaa", "w1",
                               tenant_id="tenant-aaa")
    wb = _up.UserPollingWorker(sb.session_id, sm, "bc1qbbb", "w1",
                               tenant_id="tenant-bbb")
    wa.poll_now()
    wb.poll_now()

    assert len(calls) == 1
    assert calls[0]["url"].endswith("/AAA")
    assert calls[0]["address"] == "bc1qaaa"
    sm.stop()


def test_worker_delta_baseline_advances(monkeypatch, sync_webhooks):
    """hashrate_drop compares against the PREVIOUS poll of the same worker."""
    now = int(time.time())
    snaps = [
        _snap(now, last_submission=now - 10, hashrate=100.0),
        _snap(now + 15, last_submission=now - 10, hashrate=40.0),
    ]
    state = {"i": 0}
    monkeypatch.setattr(_up, "_build_snapshot",
                        lambda a, w: snaps[state["i"] % len(snaps)])
    monkeypatch.setattr(_up, "_load_settings",
                        lambda tid: _settings(
                            webhook_url="https://discord.com/api/webhooks/delta"))

    calls = []
    monkeypatch.setattr(_up, "_send_webhook_for_alert",
                        lambda **kw: calls.append(kw) or True)

    sm = SessionManager()
    session = sm.create_session("bc1qtest", "w1")
    worker = _up.UserPollingWorker(session.session_id, sm, "bc1qtest",
                                   "w1", tenant_id="tenant-aaa")
    worker.poll_now()  # baseline (fresh share, hr 100) → nothing
    assert calls == []
    state["i"] += 1
    worker.poll_now()  # hr dropped to 40 → WARN hashrate_drop
    assert len(calls) == 1
    assert calls[0]["category"] == "hashrate_drop"
    sm.stop()


# ── Route: /api/connect-wallet threads tenant_id ────────────────────────────

def test_connect_wallet_threads_tenant_id(rclient, monkeypatch):
    captured = {}

    class FakeWorker:
        def __init__(self, sid, sm, address, worker_name="", tenant_id=""):
            captured["tenant_id"] = tenant_id
            captured["address"] = address
            captured["worker_name"] = worker_name

        def start(self):
            pass

        def poll_now(self):
            return {"ts": int(time.time()), "alerts_recent": [],
                    "all_workers": []}

    monkeypatch.setattr(_app_module, "UserPollingWorker", FakeWorker)

    resp = rclient.post(
        "/api/connect-wallet",
        headers={"Authorization": "Bearer " + _token("tenant-aaa")},
        json={"address": "bc1q" + "a" * 39, "worker": "w1"},
    )
    assert resp.status_code == 200
    assert captured["tenant_id"] == "tenant-aaa"
    assert captured["address"] == "bc1q" + "a" * 39
    sid = resp.get_json()["session_id"]
    assert _app_module._session_manager.get_session(sid).tenant_id == "tenant-aaa"


def test_session_id_cannot_cross_tenant_boundary(rclient):
    session = _app_module._session_manager.create_session(
        "bc1q" + "a" * 39, "w1", tenant_id="tenant-aaa"
    )
    _app_module._session_manager.update_snapshot(session.session_id, {"private": 65})
    headers = {"Authorization": "Bearer " + _token("tenant-bbb")}

    snapshot = rclient.get(
        "/api/session-snapshot", query_string={"session_id": session.session_id}, headers=headers
    )
    status = rclient.get(
        "/api/session-status", query_string={"session_id": session.session_id}, headers=headers
    )
    disconnect = rclient.post(
        "/api/disconnect", json={"session_id": session.session_id}, headers=headers
    )

    assert snapshot.status_code == 404
    assert status.get_json()["valid"] is False
    assert disconnect.status_code == 404
    assert _app_module._session_manager.get_session(session.session_id) is not None


def test_connect_wallet_anonymous_default_tenant(rclient, monkeypatch):
    captured = {}

    class FakeWorker:
        def __init__(self, sid, sm, address, worker_name="", tenant_id=""):
            captured["tenant_id"] = tenant_id

        def start(self):
            pass

        def poll_now(self):
            return {"ts": int(time.time()), "alerts_recent": [],
                    "all_workers": []}

    monkeypatch.setattr(_app_module, "UserPollingWorker", FakeWorker)
    resp = rclient.post(
        "/api/connect-wallet",
        json={"address": "bc1q" + "a" * 39},
    )
    assert resp.status_code == 200
    assert captured["tenant_id"] == "default"


# ── app._webhook_dispatch resolves alert.tenant_id ──────────────────────────

def test_webhook_dispatch_uses_alert_tenant(monkeypatch):
    from services import settings as _settings_mod
    _settings_mod.save_setting("webhook_url", "https://operator.example/hook")
    _settings_mod.save_setting("webhook_url",
                               "https://discord.com/api/webhooks/tenant-x",
                               tenant_id="tenant-x")

    calls = []
    # _webhook_dispatch now routes through dispatch_webhook_or_queue, which
    # calls services.webhook_queue.send_webhook_for_alert (top-level import)
    # — patch there so the real dispatch path is exercised.
    monkeypatch.setattr(
        "services.webhook_queue.send_webhook_for_alert",
        lambda **kw: calls.append(kw) or True)

    alert = Alert(ts=int(time.time()), severity="WARN", category="x",
                  message="m", tenant_id="tenant-x")
    _app_module._webhook_dispatch(alert)
    assert len(calls) == 1
    assert calls[0]["url"] == "https://discord.com/api/webhooks/tenant-x"

    # No tenant_id → operator's global webhook (legacy behavior).
    calls.clear()
    alert2 = Alert(ts=int(time.time()), severity="WARN", category="x",
                   message="m")
    _app_module._webhook_dispatch(alert2)
    assert len(calls) == 1
    assert calls[0]["url"] == "https://operator.example/hook"
