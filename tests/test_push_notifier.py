"""
CYPHER65 // Push Notifier — unit tests
======================================
Covers services/push_notifier.py (34% → target ≥90%):
  - notify_alert: severity gate, no subscriptions, pywebpush missing,
    success, WebPushException 404/410 (subscription prune), generic failure
  - notify_if_alert_exists: single/multi alert iteration
  - SEVERITY_TITLES / CATEGORY_CONTEXT coverage via notification build

webpush / WebPushException are imported INSIDE notify_alert, so we inject a
fake `pywebpush` module into sys.modules to control both.
"""
import json
import sys
import types
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock

from services.push_notifier import notify_alert, notify_if_alert_exists


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
