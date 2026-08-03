"""
CYPHER65 // Session Manager — unit tests
========================================
Covers services/session_manager.py (28% → target ≥90%):
  - UserSession: touch, has_wallet, is_expired, to_dict
  - SessionManager: create/get/destroy/update_wallet/update_snapshot,
    get_snapshot, get_all_sessions, active_count, cleanup task, stop
  - Expiry handling (TTL + is_expired edge)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import time

from services.session_manager import UserSession, SessionManager, SESSION_TTL


# ═══════════════════════════════════════════════════════════════════════════
# 1. UserSession
# ═══════════════════════════════════════════════════════════════════════════

class TestUserSession:
    def test_defaults(self):
        s = UserSession("sid-1")
        assert s.session_id == "sid-1"
        assert s.btc_address == ""
        assert s.worker_name == ""
        assert s.snapshot == {}
        assert s.pending_address is None
        assert s.pending_worker_name == ""
        assert s.created_at == s.last_activity

    def test_has_wallet(self):
        assert UserSession("s", btc_address="bc1q").has_wallet is True
        assert UserSession("s").has_wallet is False

    def test_touch_updates_last_activity(self, monkeypatch):
        s = UserSession("s")
        old = s.last_activity
        monkeypatch.setattr(s, "last_activity", old - 50)
        s.touch()
        assert s.last_activity == int(time.time())

    def test_is_expired_within_ttl(self):
        s = UserSession("s")
        s.last_activity = int(time.time()) - 100
        assert s.is_expired is False  # 100s < 3600s

    def test_is_expired_beyond_ttl(self):
        s = UserSession("s")
        s.last_activity = int(time.time()) - SESSION_TTL - 10
        assert s.is_expired is True

    def test_to_dict(self):
        s = UserSession("sid-1", btc_address="bc1q", worker_name="w1")
        d = s.to_dict()
        assert d["session_id"] == "sid-1"
        assert d["btc_address"] == "bc1q"
        assert d["worker_name"] == "w1"
        assert d["has_wallet"] is True
        assert "created_at" in d and "last_activity" in d


# ═══════════════════════════════════════════════════════════════════════════
# 2. SessionManager — CRUD
# ═══════════════════════════════════════════════════════════════════════════

class TestSessionManagerCrud:
    def test_create_and_get(self):
        m = SessionManager()
        try:
            s = m.create_session("bc1q", "w1")
            got = m.get_session(s.session_id)
            assert got is not None
            assert got.btc_address == "bc1q"
        finally:
            m.stop()

    def test_get_missing_returns_none(self):
        m = SessionManager()
        try:
            assert m.get_session("nope") is None
        finally:
            m.stop()

    def test_destroy_existing_and_missing(self):
        m = SessionManager()
        try:
            s = m.create_session()
            assert m.destroy_session(s.session_id) is True
            assert m.destroy_session(s.session_id) is False
        finally:
            m.stop()

    def test_update_wallet_existing_and_missing(self):
        m = SessionManager()
        try:
            s = m.create_session()
            assert m.update_wallet(s.session_id, "bc1new", "w2") is True
            got = m.get_session(s.session_id)
            assert got.btc_address == "bc1new"
            assert got.worker_name == "w2"
            assert m.update_wallet("nope", "x") is False
        finally:
            m.stop()

    def test_update_and_get_snapshot(self):
        m = SessionManager()
        try:
            s = m.create_session()
            assert m.update_snapshot(s.session_id, {"hashrate": 15}) is True
            snap = m.get_snapshot(s.session_id)
            assert snap == {"hashrate": 15}
            assert m.get_snapshot("nope") is None
        finally:
            m.stop()

    def test_get_snapshot_empty_returns_dict(self):
        m = SessionManager()
        try:
            s = m.create_session()
            assert m.get_snapshot(s.session_id) == {}
        finally:
            m.stop()

    def test_get_all_sessions(self):
        m = SessionManager()
        try:
            a = m.create_session()
            b = m.create_session()
            active = m.get_all_sessions()
            ids = {s.session_id for s in active}
            assert {a.session_id, b.session_id} <= ids
            assert m.active_count() >= 2
        finally:
            m.stop()

    def test_get_all_sessions_prunes_expired(self):
        m = SessionManager(ttl=1)
        try:
            s = m.create_session()
            s.last_activity = int(time.time()) - 100  # expired vs ttl=1
            active = m.get_all_sessions()
            assert s.session_id not in {x.session_id for x in active}
        finally:
            m.stop()

    def test_active_count_prunes_expired(self):
        m = SessionManager(ttl=1)
        try:
            s = m.create_session()
            s.last_activity = int(time.time()) - 100
            assert m.active_count() == 0
        finally:
            m.stop()


# ═══════════════════════════════════════════════════════════════════════════
# 3. SessionManager — expiry + cleanup
# ═══════════════════════════════════════════════════════════════════════════

class TestSessionExpiryCleanup:
    def test_get_expired_session_returns_none_and_prunes(self):
        m = SessionManager(ttl=1)
        try:
            s = m.create_session()
            s.last_activity = int(time.time()) - 100
            assert m.get_session(s.session_id) is None
        finally:
            m.stop()

    def test_cleanup_task_removes_expired(self):
        m = SessionManager(ttl=1)
        try:
            s1 = m.create_session()
            s1.last_activity = int(time.time()) - 100
            s2 = m.create_session()  # fresh
            m._cleanup_task()
            assert m.active_count() == 1
            assert m.get_session(s2.session_id) is not None
        finally:
            m.stop()

    def test_cleanup_task_no_expired_keeps_all(self):
        m = SessionManager()
        try:
            s = m.create_session()
            m._cleanup_task()
            assert m.get_session(s.session_id) is not None
        finally:
            m.stop()

    def test_stop_cancels_timer(self):
        m = SessionManager()
        m.stop()
        assert m._cleanup_timer is None
