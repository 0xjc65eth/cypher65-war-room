"""
Hermetic tests for the 1000+ user scale-hardening changes:
  1. Credential-at-rest encryption (services/settings.py Fernet round trip)
  2. Tenant-keyed rate limiting (app._rate_limit_key uses JWT sub not IP)
  3. Polling jitter + adaptive backoff (services.user_polling._poll_wait)
"""

import os
import sys
import time

import pytest

sys.path.insert(0, ".")

# ── 1. Credential encryption ────────────────────────────────────────────────


class TestCredentialEncryption:
    def test_encrypt_decrypt_round_trip(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret-0123456789-abcdef0123456789")
        import services.settings as s
        s._settings_cache = None
        s._tenant_settings_cache.clear()

        s.save_setting("braiins_api_key", "tenant-owner-token", tenant_id="alice")
        out = s.load_settings("alice")
        assert out["braiins_api_key"] == "tenant-owner-token"

        # At-rest value must NOT be plaintext when a key exists.
        from services.db import get_db
        conn = get_db()
        row = conn.execute(
            "SELECT value FROM tenant_settings WHERE tenant_id='alice' AND key='braiins_api_key'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert "tenant-owner-token" not in row["value"]
        assert row["value"].startswith("enc:v1:")

    def test_legacy_plaintext_passthrough(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret-0123456789-abcdef0123456789")
        import services.settings as s
        s._settings_cache = None
        s._tenant_settings_cache.clear()
        # Simulate a legacy plaintext row (written before encryption).
        s.save_setting("mrr_api_key", "legacy-plain", tenant_id="bob")
        from services.db import get_db
        conn = get_db()
        conn.execute(
            "UPDATE tenant_settings SET value='legacy-plain' "
            "WHERE tenant_id='bob' AND key='mrr_api_key'"
        )
        conn.commit()
        conn.close()
        s._tenant_settings_cache.clear()
        out = s.load_settings("bob")
        assert out["mrr_api_key"] == "legacy-plain"

    def test_no_key_means_plaintext(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        import services.settings as s
        s._settings_cache = None
        s._tenant_settings_cache.clear()
        s.save_setting("braiins_api_key", "no-key-value", tenant_id="carol")
        out = s.load_settings("carol")
        assert out["braiins_api_key"] == "no-key-value"


# ── 2. Tenant-keyed rate limiting ───────────────────────────────────────────


class TestRateLimitKey:
    @pytest.fixture()
    def app_ctx(self, monkeypatch):
        import app as app_module
        return app_module

    def test_anonymous_uses_ip(self, app_ctx):
        with app_ctx.app.test_request_context(
                "/api/snapshot", headers={"X-Forwarded-For": "1.2.3.4"}):
            from flask import request
            # remote_addr is set by the test client; _rate_limit_key should
            # produce an ip: key when no Authorization header exists.
            key = app_ctx._rate_limit_key()
            assert key.startswith("ip:")

    def test_valid_bearer_uses_tenant(self, app_ctx, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "rl-test-secret-0123456789-abcdef0123456789")
        from services.auth import create_token
        with app_ctx.app.app_context():
            tok = create_token(subject="tenant-xyz", extra_claims={"role": "admin"})
        with app_ctx.app.test_request_context(
                "/api/rentals", headers={"Authorization": f"Bearer {tok}"}):
            key = app_ctx._rate_limit_key()
            assert key == "t:tenant-xyz"

    def test_invalid_token_falls_back_to_ip(self, app_ctx):
        with app_ctx.app.test_request_context(
                "/api/snapshot",
                headers={"Authorization": "Bearer not-a-real-token"}):
            key = app_ctx._rate_limit_key()
            assert key.startswith("ip:")


class TestTokenSubCache:
    """Token→tenant cache: verify_token must NOT run on every request."""

    @pytest.fixture()
    def app_ctx(self, monkeypatch):
        import app as app_module
        # Isolated cache per test — never leak state across tests.
        app_module._token_sub_cache.clear()
        return app_module

    def test_cache_returns_same_tenant_without_verify(self, app_ctx, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "cache-test-secret-0123456789-abcdef0123456789")
        calls = {"n": 0}
        real_verify = None
        from services.auth import verify_token as _real
        real_verify = _real

        def counting_verify(token, **kw):
            calls["n"] += 1
            return real_verify(token, **kw)

        monkeypatch.setattr("services.auth.verify_token", counting_verify)
        from services.auth import create_token
        with app_ctx.app.app_context():
            tok = create_token(subject="cached-tenant")

        with app_ctx.app.test_request_context(
                "/api/rentals", headers={"Authorization": f"Bearer {tok}"}):
            assert app_ctx._rate_limit_key() == "t:cached-tenant"
            assert calls["n"] == 1  # first call = miss → verify once
            assert app_ctx._rate_limit_key() == "t:cached-tenant"
            assert calls["n"] == 1  # second call = cached → NO verify

    def test_cache_respects_expiry(self, app_ctx):
        # Manually seed an already-expired entry; the fast path must reject it.
        import time as _t
        key = app_ctx._token_sub_cache_key("expired-token-abc")
        app_ctx._token_sub_cache[key] = ("ghost-tenant", int(_t.time()) - 10)
        assert app_ctx._token_sub_cache_get("expired-token-abc") == ""
        assert "ghost-tenant" not in app_ctx._token_sub_cache.values()

    def test_cache_bounded_eviction(self, app_ctx, monkeypatch):
        monkeypatch.setattr(app_ctx, "_TOKEN_SUB_CACHE_MAX", 25)
        import time as _t
        now = int(_t.time())
        for i in range(100):
            app_ctx._token_sub_cache_put(f"tok-{i}", f"sub-{i}", now + 3600)
        assert len(app_ctx._token_sub_cache) <= 25
        # Oldest-inserted evicted first; recent entries survive.
        assert app_ctx._token_sub_cache_get("tok-0") == ""
        assert app_ctx._token_sub_cache_get("tok-99") == "sub-99"

    def test_invalid_token_not_cached(self, app_ctx):
        # A rejected token must not pollute the cache (stays a miss → IP).
        assert app_ctx._token_sub_cache_get("garbage") == ""
        app_ctx._token_sub_cache_put("garbage", "", 0)
        assert app_ctx._token_sub_cache_get("garbage") == ""

    def test_logout_evicts_entry(self, app_ctx):
        # Explicit logout must close the revocation window immediately.
        import time as _t
        tok = "logout-token-xyz"
        app_ctx._token_sub_cache_put(tok, "sub-evict", int(_t.time()) + 3600)
        assert app_ctx._token_sub_cache_get(tok) == "sub-evict"
        app_ctx.evict_token_sub_cache(tok)
        assert app_ctx._token_sub_cache_get(tok) == ""


# ── 3. Polling jitter + adaptive backoff ────────────────────────────────────


class TestPollWait:
    def test_jitter_desyncs_workers(self):
        from services.user_polling import _poll_wait, POLL_INTERVAL, POLL_JITTER_MAX
        waits = {_poll_wait(0) for _ in range(200)}
        # All waits are in the jitter band above the base interval…
        assert all(POLL_INTERVAL <= w < POLL_INTERVAL + POLL_JITTER_MAX + 1
                   for w in waits)
        # …and they are NOT all identical (thundering-herd fix).
        assert len(waits) > 1

    def test_backoff_grows_and_caps(self):
        from services.user_polling import (_poll_wait, POLL_INTERVAL,
                                           POLL_MAX_BACKOFF)
        w0 = _poll_wait(0)
        w1 = _poll_wait(1)
        w2 = _poll_wait(2)
        # Strictly greater mean with each consecutive error burst.
        assert w1 >= POLL_INTERVAL * 2 >= w0
        assert w2 >= POLL_INTERVAL * 4
        # Capped: a huge error streak never exceeds the cap + jitter.
        assert _poll_wait(50) < POLL_MAX_BACKOFF + 9

    def test_backoff_cap_floor(self):
        from services.user_polling import _poll_wait, POLL_MAX_BACKOFF
        for _ in range(20):
            assert _poll_wait(10) < POLL_MAX_BACKOFF + 9

    def test_global_cache_bounded_eviction(self, monkeypatch):
        """The per-address cache must not grow unbounded (1000+ users)."""
        import services.user_polling as up
        monkeypatch.setattr(up, "_GLOBAL_CACHE_MAX", 50)
        monkeypatch.setattr(up, "_global_cache", {})
        for i in range(200):
            up._update_global(f"user_bc1q{i}", {"workerData": []})
        assert len(up._global_cache) <= 50
        # Oldest evicted first; the most recent entries survive.
        assert "user_bc1q0" not in up._global_cache
        assert "user_bc1q199" in up._global_cache


# ── Rate-limit persistence (restart survival) ───────────────────────────────


class TestRateLimitPersistence:
    def test_persist_then_restore_roundtrip(self, monkeypatch):
        """Buckets snapshot to SQLite and reload on boot — a restart does not
        re-open the abuse window."""
        import app as app_module
        now = int(time.time())
        app_module._rate_limit_store["t:tenant-x"] = [now - 5, now - 3]
        app_module._auth_rate_limit_store["203.0.113.9"] = [now - 2]

        app_module._rate_limit_persist()

        # Simulate restart: wipe memory, then restore from SQLite.
        app_module._rate_limit_store.clear()
        app_module._auth_rate_limit_store.clear()
        app_module._rate_limit_restore()

        assert app_module._rate_limit_store.get("t:tenant-x") == [now - 5, now - 3]
        assert app_module._auth_rate_limit_store.get("203.0.113.9") == [now - 2]
        # Cleanup so other tests don't inherit the buckets.
        app_module._rate_limit_store.clear()
        app_module._auth_rate_limit_store.clear()

    def test_restore_drops_expired_stamps(self, monkeypatch):
        """Rows whose stamps all fall outside the 60s window are discarded."""
        import app as app_module
        old = int(time.time()) - 600
        app_module._rate_limit_store["t:stale-tenant"] = [old, old + 1]
        app_module._rate_limit_persist()
        app_module._rate_limit_store.clear()
        app_module._rate_limit_restore()
        assert "t:stale-tenant" not in app_module._rate_limit_store
        app_module._rate_limit_store.clear()

    def test_persist_empty_stores_is_noop(self, monkeypatch):
        import app as app_module
        app_module._rate_limit_store.clear()
        app_module._auth_rate_limit_store.clear()
        # Must not raise on empty stores.
        app_module._rate_limit_persist()


# ── 4. Schema version stamping ──────────────────────────────────────────────


class TestSchemaVersion:
    def test_schema_version_recorded(self, tmp_path, monkeypatch):
        import app as app_module
        from services.db import get_db
        conn = get_db()
        row = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
        conn.close()
        assert row is not None
        assert row["version"] == app_module.SCHEMA_VERSION


# ── 5. CSP hardening headers ────────────────────────────────────────────────


class TestCspHeaders:
    """Locks the CSP contract: jsDelivr stays allowed in connect-src (Chart.js
    ships an embedded sourceMappingURL whose fetch was previously blocked and
    spammed the console) while arbitrary origins remain forbidden."""

    def test_connect_src_allows_jsdelivr_only(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret-0123456789-abcdef0123456789")
        import app as app_module

        c = app_module.app.test_client()
        resp = c.get("/")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert csp, "CSP header must be present"
        connect = next(
            (p.strip() for p in csp.split(";") if p.strip().startswith("connect-src")),
            "",
        )
        # Chart.js sourcemap fetch (jsDelivr) must no longer be blocked.
        assert "https://cdn.jsdelivr.net" in connect
        # No arbitrary third-party origin may join connect-src.
        assert "https://evil.example" not in connect

    def test_hardening_headers_present(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret-0123456789-abcdef0123456789")
        import app as app_module

        c = app_module.app.test_client()
        resp = c.get("/")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "SAMEORIGIN"
        assert resp.headers.get("Referrer-Policy") == "no-referrer"
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "object-src 'none'" in csp
        assert "frame-ancestors 'self'" in csp
