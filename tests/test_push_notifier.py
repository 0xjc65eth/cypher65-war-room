"""
CYPHER65 // Push Notifier — unit tests
======================================
Covers services/push_notifier.py (34% → target ≥90%):
  - notify_alert: severity gate, no subscriptions, pywebpush missing,
    success, WebPushException 404/410 (subscription prune), generic failure
  - notify_if_alert_exists: single/multi alert iteration
  - SEVERITY_TITLES / CATEGORY_CONTEXT coverage via notification build
  - send_webhook_notification: Discord embed, Telegram MarkdownV2,
    generic fallback, network error, _tg_escape
  - AlertEngine.dispatch_webhook integration

webpush / WebPushException are imported INSIDE notify_alert, so we inject a
fake `pywebpush` module into sys.modules to control both.
"""
import json
import sys
import types
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock, ANY

from services.push_notifier import (
    notify_alert, notify_if_alert_exists,
    send_webhook_notification, send_webhook_for_alert,
    severity_meets_threshold,
)


class FakeWebPushException(Exception):
    """Mirrors pywebpush.WebPushException with a .response attribute."""

    def __init__(self, msg, response=None):
        super().__init__(msg)
        self.response = response


def _fake_pywebpush(webpush_impl=None):
    """Build a fake `pywebpush` module with a configurable webpush()."""
    mod = types.ModuleType("pywebpush")
    mod.webpush = webpush_impl if webpush_impl is not None else MagicMock()
    mod.WebPushException = FakeWebPushException
    return mod


def _subs():
    return {
        "https://push.example/1": {"keys": {"p256dh": "k1", "auth": "k2"}},
        "https://push.example/2": {"keys": {"p256dh": "k3", "auth": "k4"}},
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1. notify_alert — early returns
# ═══════════════════════════════════════════════════════════════════════════

class TestNotifyEarlyReturns:
    def test_info_severity_skipped(self):
        assert notify_alert("INFO", "worker_offline", "msg") is False

    def test_unknown_severity_skipped(self):
        assert notify_alert("FOO", "worker_offline", "msg") is False

    def test_no_subscriptions_returns_false(self):
        with patch("services.push_notifier._get_push_subscriptions", return_value={}):
            assert notify_alert("CRIT", "worker_offline", "msg") is False


# ═══════════════════════════════════════════════════════════════════════════
# 2. notify_alert — pywebpush not installed
# ═══════════════════════════════════════════════════════════════════════════

class TestNoPywebpush:
    def test_missing_library_returns_false(self):
        with patch("services.push_notifier._get_push_subscriptions", return_value=_subs()), \
             patch.dict("sys.modules", {"pywebpush": None}):
            assert notify_alert("CRIT", "worker_offline", "msg") is False


# ═══════════════════════════════════════════════════════════════════════════
# 3. notify_alert — success path
# ═══════════════════════════════════════════════════════════════════════════

class TestNotifySuccess:
    def test_sends_to_each_subscription(self):
        webpush_impl = MagicMock()
        with patch("services.push_notifier._get_push_subscriptions",
                   return_value=_subs()), \
             patch.dict("sys.modules",
                        {"pywebpush": _fake_pywebpush(webpush_impl)}):
            ok = notify_alert("CRIT", "worker_offline", "O worker caiu", url="/fleet")
        assert ok is True
        assert webpush_impl.call_count == 2
        payload = json.loads(webpush_impl.call_args_list[0].kwargs["data"])
        assert payload["title"] == "🚨 CRITICAL: Mining Alert"
        assert "O worker caiu" in payload["body"]
        assert payload["data"]["url"] == "/fleet"
        assert payload["requireInteraction"] is True
        # dedup tag within 5 min
        assert payload["tag"].startswith("cypher65-worker_offline-")

    def test_warn_builds_context_body(self):
        webpush_impl = MagicMock()
        with patch("services.push_notifier._get_push_subscriptions",
                   return_value=_subs()), \
             patch.dict("sys.modules",
                        {"pywebpush": _fake_pywebpush(webpush_impl)}):
            notify_alert("WARN", "stale_share", "sem shares")
        payload = json.loads(webpush_impl.call_args_list[0].kwargs["data"])
        assert payload["title"] == "⚠️ WARNING: Mining Alert"
        assert payload["body"].startswith("Share not submitted recently: ")
        assert payload["requireInteraction"] is False

    def test_gold_title(self):
        webpush_impl = MagicMock()
        with patch("services.push_notifier._get_push_subscriptions",
                   return_value=_subs()), \
             patch.dict("sys.modules",
                        {"pywebpush": _fake_pywebpush(webpush_impl)}):
            notify_alert("GOLD", "best_diff_bump", "novo recorde")
        payload = json.loads(webpush_impl.call_args_list[0].kwargs["data"])
        assert payload["title"] == "🏆 GOLD: Mining Milestone"
        assert "Best difficulty improved" in payload["body"]

    def test_unknown_category_uses_raw_message(self):
        webpush_impl = MagicMock()
        with patch("services.push_notifier._get_push_subscriptions",
                   return_value=_subs()), \
             patch.dict("sys.modules",
                        {"pywebpush": _fake_pywebpush(webpush_impl)}):
            notify_alert("CRIT", "totally_unknown_cat", "só a mensagem")
        payload = json.loads(webpush_impl.call_args_list[0].kwargs["data"])
        assert payload["body"] == "só a mensagem"

    def test_long_message_truncated_to_200(self):
        webpush_impl = MagicMock()
        with patch("services.push_notifier._get_push_subscriptions",
                   return_value=_subs()), \
             patch.dict("sys.modules",
                        {"pywebpush": _fake_pywebpush(webpush_impl)}):
            notify_alert("CRIT", "worker_offline", "x" * 500)
        payload = json.loads(webpush_impl.call_args_list[0].kwargs["data"])
        assert len(payload["body"]) <= 200


# ═══════════════════════════════════════════════════════════════════════════
# 4. notify_alert — failure paths
# ═══════════════════════════════════════════════════════════════════════════

class TestNotifyFailures:
    def test_410_prunes_subscription(self):
        app_mod = MagicMock()
        app_mod._push_subscriptions = dict(_subs())

        def raising_webpush(*args, **kwargs):
            raise FakeWebPushException("gone",
                                       response=MagicMock(status_code=410))

        with patch("services.push_notifier._get_push_subscriptions",
                   return_value=_subs()), \
             patch.dict("sys.modules",
                        {"pywebpush": _fake_pywebpush(raising_webpush),
                         "app": app_mod}):
            ok = notify_alert("CRIT", "worker_offline", "msg")
        assert ok is False
        assert "https://push.example/1" not in app_mod._push_subscriptions

    def test_404_prunes_subscription(self):
        app_mod = MagicMock()
        app_mod._push_subscriptions = dict(_subs())

        def raising_webpush(*args, **kwargs):
            raise FakeWebPushException("gone",
                                       response=MagicMock(status_code=404))

        with patch("services.push_notifier._get_push_subscriptions",
                   return_value=_subs()), \
             patch.dict("sys.modules",
                        {"pywebpush": _fake_pywebpush(raising_webpush),
                         "app": app_mod}):
            notify_alert("CRIT", "worker_offline", "msg")
        assert "https://push.example/1" not in app_mod._push_subscriptions

    def test_webpush_exception_without_410(self):
        app_mod = MagicMock()
        app_mod._push_subscriptions = dict(_subs())

        def raising_webpush(*args, **kwargs):
            raise FakeWebPushException("rate limited",
                                       response=MagicMock(status_code=429))

        with patch("services.push_notifier._get_push_subscriptions",
                   return_value=_subs()), \
             patch.dict("sys.modules",
                        {"pywebpush": _fake_pywebpush(raising_webpush),
                         "app": app_mod}):
            ok = notify_alert("CRIT", "worker_offline", "msg")
        assert ok is False
        # 429 does NOT prune the subscription
        assert "https://push.example/1" in app_mod._push_subscriptions

    def test_generic_exception_counts_failure(self):
        def raising_webpush(*args, **kwargs):
            raise RuntimeError("nope")

        with patch("services.push_notifier._get_push_subscriptions",
                   return_value=_subs()), \
             patch.dict("sys.modules",
                        {"pywebpush": _fake_pywebpush(raising_webpush)}):
            assert notify_alert("CRIT", "worker_offline", "msg") is False

    def test_partial_success_returns_true(self):
        # 2 subs: one succeeds, one raises → sent > 0 → True
        calls = {"n": 0}

        def mixed_webpush(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("second fails")
            return None

        with patch("services.push_notifier._get_push_subscriptions",
                   return_value=_subs()), \
             patch.dict("sys.modules",
                        {"pywebpush": _fake_pywebpush(mixed_webpush)}):
            assert notify_alert("CRIT", "worker_offline", "msg") is True


# ═══════════════════════════════════════════════════════════════════════════
# 5. notify_if_alert_exists
# ═══════════════════════════════════════════════════════════════════════════

class TestNotifyIfAlertExists:
    def test_no_alerts(self):
        assert notify_if_alert_exists([]) is False

    def test_sends_for_matching_alerts(self):
        alerts = [
            {"severity": "CRIT", "category": "worker_offline", "message": "m1"},
            {"severity": "INFO", "category": "x", "message": "m2"},
        ]
        with patch("services.push_notifier.notify_alert",
                   side_effect=lambda sev, cat, msg: sev == "CRIT"):
            assert notify_if_alert_exists(alerts) is True

    def test_none_sent_returns_false(self):
        alerts = [
            {"severity": "INFO", "category": "x", "message": "m2"},
        ]
        with patch("services.push_notifier.notify_alert", return_value=False):
            assert notify_if_alert_exists(alerts) is False


# ═══════════════════════════════════════════════════════════════════════════
# 6. send_webhook_notification — Phase D (Discord + Telegram + generic)
# ═══════════════════════════════════════════════════════════════════════════

_WEBHOOK_ARGS = dict(
    severity="CRIT", category="hashrate_drop",
    message="Garage Bitaxe hashrate=0 == 0",
    ts=1735689600, worker="parasite-worker", address="bc1qtest1234567890abcdefgh",
)


class TestSendWebhookNotification:
    def test_empty_url_returns_false(self):
        assert send_webhook_notification(url="", **_WEBHOOK_ARGS) is False

    def test_discord_url_detected_and_formats_embed(self):
        """Discord URL → _send_discord_webhook → embed payload."""
        mock_post = MagicMock()
        mock_post.return_value.ok = True
        mock_post.return_value.status_code = 200

        url = "https://discord.com/api/webhooks/123/abc"
        with patch("services.push_notifier.requests") as mock_r:
            mock_r.post = mock_post
            ok = send_webhook_notification(url=url, **_WEBHOOK_ARGS)

        assert ok is True
        assert mock_post.call_count == 1
        call_args = mock_post.call_args
        assert call_args[0][0] == url

        # Check embed structure
        payload = call_args[1]["json"]
        embed = payload["embeds"][0]
        assert "CYPHER65" in embed["title"]
        assert "CRIT" in embed["title"]
        assert "hashrate_drop" in embed["description"] or \
            _WEBHOOK_ARGS["message"] in embed["description"]
        assert embed["color"] == 0xFF1744  # CRIT red

    def test_discord_embed_includes_worker_and_address(self):
        mock_post = MagicMock()
        mock_post.return_value.ok = True

        url = "https://discord.com/api/webhooks/456/xyz"
        with patch("services.push_notifier.requests") as mock_r:
            mock_r.post = mock_post
            send_webhook_notification(url=url, **_WEBHOOK_ARGS)

        payload = mock_post.call_args[1]["json"]
        embed = payload["embeds"][0]
        field_names = [f["name"] for f in embed["fields"]]
        assert "Worker" in field_names
        assert "Address" in field_names

    def test_telegram_url_detected_and_formats_markdown(self):
        """Telegram URL → _send_telegram_webhook → MarkdownV2 payload."""
        mock_post = MagicMock()
        mock_post.return_value.ok = True

        url = "https://api.telegram.org/botTOKEN/sendMessage?chat_id=123456"
        with patch("services.push_notifier.requests") as mock_r:
            mock_r.post = mock_post
            ok = send_webhook_notification(url=url, **_WEBHOOK_ARGS)

        assert ok is True
        payload = mock_post.call_args[1]["json"]
        assert payload["parse_mode"] == "MarkdownV2"
        assert "CYPHER65" in payload["text"]
        assert "CRIT" in payload["text"]
        assert payload["chat_id"] == "123456"

    def test_telegram_no_chat_id_still_sends(self):
        mock_post = MagicMock()
        mock_post.return_value.ok = True

        url = "https://api.telegram.org/botTOKEN/sendMessage"
        with patch("services.push_notifier.requests") as mock_r:
            mock_r.post = mock_post
            ok = send_webhook_notification(url=url, **_WEBHOOK_ARGS)

        assert ok is True
        payload = mock_post.call_args[1]["json"]
        assert "chat_id" not in payload  # no query param → no chat_id
        assert payload["parse_mode"] == "MarkdownV2"

    def test_generic_url_sends_legacy_payload(self):
        """Non-Discord, non-Telegram URL → generic JSON payload."""
        mock_post = MagicMock()
        mock_post.return_value.ok = True

        url = "https://hooks.example.com/custom"
        with patch("services.push_notifier.requests") as mock_r:
            mock_r.post = mock_post
            ok = send_webhook_notification(url=url, **_WEBHOOK_ARGS)

        assert ok is True
        payload = mock_post.call_args[1]["json"]
        assert payload["event"] == "cypher65_war_room_alert"
        assert payload["severity"] == "CRIT"
        assert payload["category"] == "hashrate_drop"

    def test_network_error_returns_false(self):
        mock_post = MagicMock(side_effect=ConnectionError("refused"))
        url = "https://discord.com/api/webhooks/xxx"
        with patch("services.push_notifier.requests") as mock_r:
            mock_r.post = mock_post
            ok = send_webhook_notification(url=url, **_WEBHOOK_ARGS)

        assert ok is False

    def test_discord_non_200_returns_false(self):
        mock_post = MagicMock()
        mock_post.return_value.ok = False
        mock_post.return_value.status_code = 429

        url = "https://discord.com/api/webhooks/xxx"
        with patch("services.push_notifier.requests") as mock_r:
            mock_r.post = mock_post
            ok = send_webhook_notification(url=url, **_WEBHOOK_ARGS)

        assert ok is False

    def test_warn_severity_uses_orange_color(self):
        mock_post = MagicMock()
        mock_post.return_value.ok = True

        url = "https://discord.com/api/webhooks/123"
        with patch("services.push_notifier.requests") as mock_r:
            mock_r.post = mock_post
            send_webhook_notification(url=url, severity="WARN", category="temp_high",
                                       message="temp high", ts=1735689600,
                                       worker="w", address="a")

        payload = mock_post.call_args[1]["json"]
        assert payload["embeds"][0]["color"] == 0xFFA000  # WARN amber


# ═══════════════════════════════════════════════════════════════════════════
# 6b. severity_meets_threshold + send_webhook_for_alert — Phase D helpers
# ═══════════════════════════════════════════════════════════════════════════

class TestSeverityThreshold:
    def test_ordering(self):
        assert severity_meets_threshold("CRIT", "WARN") is True
        assert severity_meets_threshold("WARN", "WARN") is True
        assert severity_meets_threshold("GOLD", "WARN") is True
        assert severity_meets_threshold("SUCCESS", "WARN") is True
        assert severity_meets_threshold("INFO", "WARN") is False
        assert severity_meets_threshold("WARN", "CRIT") is False
        assert severity_meets_threshold("CRITICAL", "WARN") is True  # legacy alias

    def test_unknown_severity_ranks_as_info(self):
        assert severity_meets_threshold("MYSTERY", "INFO") is True
        assert severity_meets_threshold("MYSTERY", "WARN") is False

    def test_unknown_threshold_defaults_to_warn(self):
        assert severity_meets_threshold("WARN", "DEBUG") is True
        assert severity_meets_threshold("INFO", "DEBUG") is False


class TestSendWebhookForAlert:
    def test_empty_url_returns_false(self):
        assert send_webhook_for_alert(url="", **_WEBHOOK_ARGS) is False

    def test_below_threshold_filtered_without_http(self):
        """INFO alert + WARN threshold → filtered before any HTTP call."""
        with patch("services.push_notifier.send_webhook_notification") as mock_send:
            ok = send_webhook_for_alert(
                url="https://discord.com/api/webhooks/1/2",
                severity="INFO", category="info", message="m",
                min_severity="WARN",
            )
        assert ok is False
        mock_send.assert_not_called()

    def test_above_threshold_delegates_with_min_severity(self):
        with patch("services.push_notifier.send_webhook_notification", return_value=True) as mock_send:
            ok = send_webhook_for_alert(
                url="https://discord.com/api/webhooks/1/2",
                severity="CRIT", category="hashrate_drop", message="m",
                ts=123, worker="w", address="a",
                min_severity="CRIT",
            )
        assert ok is True
        mock_send.assert_called_once_with(
            url="https://discord.com/api/webhooks/1/2", severity="CRIT",
            category="hashrate_drop", message="m", ts=123, worker="w",
            address="a", timeout=5,
        )

    def test_failure_propagates_false(self):
        with patch("services.push_notifier.send_webhook_notification", return_value=False) as mock_send:
            ok = send_webhook_for_alert(url="https://discord.com/x", severity="CRIT",
                                        category="c", message="m")
        assert ok is False


# ═══════════════════════════════════════════════════════════════════════════
# 7. AlertEngine.dispatch_webhook — integration
# ═══════════════════════════════════════════════════════════════════════════

class TestAlertEngineDispatchWebhook:
    def test_no_callback_noop(self):
        """dispatch_webhook with no callback should not raise."""
        from core.alerts.alert_engine import AlertEngine, Alert
        engine = AlertEngine(":memory:", webhook_callback=None)
        alerts = [Alert(ts=0, severity="CRIT", category="x", message="m")]
        # Should not raise
        engine.dispatch_webhook(alerts)

    def test_callback_called_for_each_alert(self):
        from core.alerts.alert_engine import AlertEngine, Alert

        calls = []
        def cb(a):
            calls.append(a)

        engine = AlertEngine(":memory:", webhook_callback=cb)
        alerts = [
            Alert(ts=100, severity="CRIT", category="hashrate_drop",
                  message="hashrate 0", device_id="d1"),
            Alert(ts=101, severity="WARN", category="temp_high",
                  message="temp 80", device_id="d2"),
        ]
        engine.dispatch_webhook(alerts)
        assert len(calls) == 2
        assert calls[0].severity == "CRIT"
        assert calls[1].category == "temp_high"

    def test_callback_exception_does_not_propagate(self):
        from core.alerts.alert_engine import AlertEngine, Alert

        def cb(a):
            if a.severity == "CRIT":
                raise RuntimeError("network error")
            return True

        engine = AlertEngine(":memory:", webhook_callback=cb)
        alerts = [
            Alert(ts=100, severity="CRIT", category="hashrate_drop",
                  message="boom", device_id="d1"),
            Alert(ts=101, severity="WARN", category="temp_high",
                  message="ok", device_id="d2"),
        ]
        # Should not raise — exception in first callback caught, second runs
        engine.dispatch_webhook(alerts)


# ═══════════════════════════════════════════════════════════════════════════
# 8. _tg_escape — Telegram MarkdownV2 special-char escaping
# ═══════════════════════════════════════════════════════════════════════════

class TestTgEscape:
    def test_escapes_all_special_chars(self):
        from services.push_notifier import _tg_escape
        raw = "Hello _world_ [link](url) ~strike~ `code` >quote"
        escaped = _tg_escape(raw)
        # Every special char must be backslash-escaped
        assert "\\_" in escaped
        assert "\\[" in escaped
        assert "\\]" in escaped
        assert "\\(" in escaped
        assert "\\)" in escaped
        assert "\\~" in escaped
        assert "\\`" in escaped
        assert "\\>" in escaped

    def test_preserves_normal_text(self):
        from services.push_notifier import _tg_escape
        assert _tg_escape("hello world") == "hello world"
        assert _tg_escape("BTC: 65000") == "BTC: 65000"


# ═══════════════════════════════════════════════════════════════════════════
# 9. Persistent per-tenant push subscriptions + notify_tenant_alert
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def clean_push_table():
    from services.push_notifier import _ensure_subscriptions_table
    from services.db import get_db
    _ensure_subscriptions_table()
    conn = get_db()
    conn.execute("DELETE FROM push_subscriptions")
    conn.commit()
    conn.close()
    yield
    conn = get_db()
    conn.execute("DELETE FROM push_subscriptions")
    conn.commit()
    conn.close()


from services.push_notifier import (  # noqa: E402
    save_subscription, remove_subscription, get_subscriptions_for_tenant,
    notify_tenant_alert,
)


class TestTenantPushSubscriptions:
    def test_save_and_get_scoped_to_tenant(self):
        assert save_subscription("https://push.example/t1",
                                 {"p256dh": "k1", "auth": "a1"},
                                 tenant_id="tenant-a") is True
        assert save_subscription("https://push.example/t2",
                                 {"p256dh": "k2", "auth": "a2"},
                                 tenant_id="tenant-b") is True
        a = get_subscriptions_for_tenant("tenant-a")
        b = get_subscriptions_for_tenant("tenant-b")
        assert [s["endpoint"] for s in a] == ["https://push.example/t1"]
        assert [s["endpoint"] for s in b] == ["https://push.example/t2"]
        assert a[0]["keys"]["p256dh"] == "k1"

    def test_upsert_same_endpoint_updates_tenant(self):
        save_subscription("https://push.example/x", {}, tenant_id="t1")
        # Same endpoint re-registered by a different tenant → ownership moves.
        save_subscription("https://push.example/x", {"p256dh": "k9"},
                          tenant_id="t2")
        assert len(get_subscriptions_for_tenant("t1")) == 0
        subs = get_subscriptions_for_tenant("t2")
        assert len(subs) == 1
        assert subs[0]["keys"]["p256dh"] == "k9"

    def test_remove_subscription(self):
        save_subscription("https://push.example/del", {}, tenant_id="t1")
        assert remove_subscription("https://push.example/del") is True
        assert len(get_subscriptions_for_tenant("t1")) == 0

    def test_save_empty_endpoint_noop(self):
        assert save_subscription("", {}) is False

    def test_notify_tenant_requires_vapid(self, monkeypatch):
        """Without VAPID keys → degrades silently (0 devices), no crash."""
        import services.push_notifier as pn
        monkeypatch.setattr(pn, "VAPID_PRIVATE_KEY", "")
        monkeypatch.setattr(pn, "VAPID_PUBLIC_KEY", "")
        save_subscription("https://push.example/v", {}, tenant_id="t")
        assert notify_tenant_alert("t", "CRIT", "worker_offline", "down") == 0

    def test_notify_tenant_sends_to_own_devices(self, monkeypatch):
        """Only the tenant's own devices get notified — tenant isolation."""
        import services.push_notifier as pn
        monkeypatch.setattr(pn, "VAPID_PRIVATE_KEY", "priv")
        monkeypatch.setattr(pn, "VAPID_PUBLIC_KEY", "pub")
        save_subscription("https://push.example/a", {"p256dh": "k1"},
                          tenant_id="tenant-a")
        save_subscription("https://push.example/b", {"p256dh": "k2"},
                          tenant_id="tenant-b")

        sent_endpoints = []
        fake = MagicMock()

        def webpush_impl(subscription_info=None, data=None, **kw):
            sent_endpoints.append(subscription_info["endpoint"])

        fake.side_effect = webpush_impl
        sys.modules["pywebpush"] = _fake_pywebpush(fake)
        try:
            n = notify_tenant_alert("tenant-a", "WARN", "hashrate_drop",
                                    "dropped")
        finally:
            sys.modules.pop("pywebpush", None)
        assert n == 1
        assert sent_endpoints == ["https://push.example/a"]

    def test_notify_tenant_prunes_expired(self, monkeypatch):
        """404/410 subscriptions are removed (prune) so dead devices don't
        accumulate."""
        import services.push_notifier as pn
        monkeypatch.setattr(pn, "VAPID_PRIVATE_KEY", "priv")
        monkeypatch.setattr(pn, "VAPID_PUBLIC_KEY", "pub")
        save_subscription("https://push.example/gone", {}, tenant_id="t")

        class FakeResp:
            status_code = 410

        def boom_impl(subscription_info=None, data=None, **kw):
            raise FakeWebPushException("gone", response=FakeResp())

        sys.modules["pywebpush"] = _fake_pywebpush(MagicMock(side_effect=boom_impl))
        try:
            n = notify_tenant_alert("t", "CRIT", "worker_offline", "down")
        finally:
            sys.modules.pop("pywebpush", None)
        assert n == 0
        assert len(get_subscriptions_for_tenant("t")) == 0

    def test_notify_tenant_info_severity_skipped(self, monkeypatch):
        import services.push_notifier as pn
        monkeypatch.setattr(pn, "VAPID_PRIVATE_KEY", "priv")
        monkeypatch.setattr(pn, "VAPID_PUBLIC_KEY", "pub")
        save_subscription("https://push.example/i", {}, tenant_id="t")
        assert notify_tenant_alert("t", "INFO", "uptime", "crossed") == 0


# ═══════════════════════════════════════════════════════════════════════════
# 6. VAPID configuration (Issue #15) — env-gated keys + subject
# ═══════════════════════════════════════════════════════════════════════════

class TestVapidConfig:
    def test_claims_subject_env_gated(self, monkeypatch):
        """VAPID_SUBJECT env must control VAPID_CLAIMS['sub'] (never hardcoded)."""
        import importlib
        import services.push_notifier as pn

        monkeypatch.setenv("VAPID_SUBJECT", "mailto:ops@cypher65.dev")
        reloaded = importlib.reload(pn)
        assert reloaded.VAPID_CLAIMS["sub"] == "mailto:ops@cypher65.dev"

        monkeypatch.delenv("VAPID_SUBJECT", raising=False)
        reloaded = importlib.reload(pn)
        assert reloaded.VAPID_CLAIMS["sub"] == "mailto:admin@cypher65.local"

        # Restore the module to its env-less default so later tests are clean.
        importlib.reload(pn)

    def test_claims_always_has_sub(self):
        import services.push_notifier as pn
        assert pn.VAPID_CLAIMS.get("sub")
        assert pn.VAPID_CLAIMS["sub"] == pn.VAPID_SUBJECT
