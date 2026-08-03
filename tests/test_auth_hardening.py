"""
CYPHER65 // Security Hardening Regression Tests (Audit C1 · C2 · C4 · C7)
=========================================================================
Locks the audit fixes:

- C1: token blacklist is FIFO-pruned (keeps the most recent _BLACKLIST_KEEP
  revocations) instead of a wholesale clear() — a clear() would silently
  re-validate every previously-revoked token (replay).
- C2: create_token/create_refresh_token raise RuntimeError when no
  SECRET_KEY / JWT_SECRET_KEY is configured instead of silently minting
  tokens with an ephemeral per-call secret (which could never be verified).
- C4: PyJWT roundtrip preserves sub/role/type claims and rejects tampering.
- C7: users-table DDL allowlist regex rejects injection-style identifiers.

Strategy: use the shared Flask app with JWT_SECRET_KEY configured (the same
pattern as test_tenant_auth.py) and manipulate the module-level blacklist
directly for the FIFO assertions. Hermetic by construction: every test that
mints tokens gets the secret from app.config (client fixture) or sets it
explicitly — never from the local .env.
"""
import pytest

from services.auth import (
    _BLACKLIST_MAX,
    _blacklisted_tokens,
    create_refresh_token,
    create_token,
    revoke_token,
    verify_token,
)

import app as _app_module

app = _app_module.app

_TEST_SECRET = "h" * 32


@pytest.fixture
def client(monkeypatch):
    """Test client with a fixed 32-byte JWT secret (avoids the PyJWT
    InsecureKeyLengthWarning and guarantees create/verify use one secret).

    The secret is ALSO exported to the SECRET_KEY env var — repo convention
    (see test_tenant_auth.py / test_rbac_register.py). verify_token() only
    reads app.config JWT_SECRET_KEY while an app context is active; at test
    level `if current_app:` is falsy (werkzeug LocalProxy), so _get_secret()
    falls back to os.environ SECRET_KEY. Without the env var, verification
    would return None for freshly-minted tokens."""
    app.config["TESTING"] = True
    saved = app.config.get("JWT_SECRET_KEY")
    app.config["JWT_SECRET_KEY"] = _TEST_SECRET
    monkeypatch.setenv("SECRET_KEY", _TEST_SECRET)
    with app.test_client() as c:
        yield c
    # Restore any pre-existing config secret so this file doesn't leak its
    # JWT_SECRET_KEY into other test files in the same pytest process
    # (cross-file pollution broke test_rbac_register.py).
    if saved is not None:
        app.config["JWT_SECRET_KEY"] = saved
    else:
        app.config.pop("JWT_SECRET_KEY", None)


@pytest.fixture(autouse=True)
def _clean_blacklist():
    """Every test starts from an empty blacklist (module-level state)."""
    _blacklisted_tokens.clear()
    yield
    _blacklisted_tokens.clear()


def _mint(n: int):
    """Mint n DISTINCT tokens inside an app context.

    Subject varies per token so the JWTs are unique (same-second iat +
    same claims would otherwise produce identical strings, collapsing the
    OrderedDict to one entry and making the FIFO assertions vacuous). The
    secret comes from app.config, set explicitly — no .env dependence.
    The previous config value is restored afterwards so this helper never
    leaks a JWT secret into other test files.
    """
    with app.app_context():
        saved = app.config.get("JWT_SECRET_KEY")
        app.config["JWT_SECRET_KEY"] = _TEST_SECRET
        try:
            return [create_token(subject=f"u{i}", extra_claims={"role": "viewer"})
                    for i in range(n)]
        finally:
            if saved is not None:
                app.config["JWT_SECRET_KEY"] = saved
            else:
                app.config.pop("JWT_SECRET_KEY", None)


# ══════════════════════════════════════════════════════════════════════
#  C1 — Blacklist FIFO pruning (no replay after cap)
# ══════════════════════════════════════════════════════════════════════

class TestBlacklistFifo:
    def test_recent_revocations_stay_rejected_after_cap(self, client):
        """After exceeding the cap, the most recently revoked tokens must
        still be rejected (no replay) — the old clear() allowed this.

        client fixture keeps the secret available so verify_token() is fully
        functional (it needs the secret for the non-blacklisted path)."""
        tokens = _mint(_BLACKLIST_MAX + 10)
        for t in tokens:
            revoke_token(t)

        # FIFO cap respected: the blacklist never grows unbounded. The prune
        # fires only when the cap is EXCEEDED (trimming back to
        # _BLACKLIST_KEEP), so between prunes it may hold up to
        # _BLACKLIST_MAX entries — assert the invariant, not a fixed size.
        assert len(_blacklisted_tokens) <= _BLACKLIST_MAX

        # Recently revoked tokens are still blocked
        for t in tokens[-3:]:
            assert verify_token(t) is None

        # The OLDEST revocations were pruned (they are no longer blacklisted)
        assert tokens[0] not in _blacklisted_tokens
        assert tokens[1] not in _blacklisted_tokens

    def test_revoke_is_idempotent_and_returns_true(self):
        t = _mint(1)[0]
        assert revoke_token(t) is True
        assert revoke_token(t) is True  # re-revoke, no crash

    def test_verify_checks_blacklist_before_decode(self, client):
        """A valid token passes before revoke and is blocked after."""
        t = _mint(1)[0]
        assert verify_token(t) is not None  # valid before revoke
        revoke_token(t)
        assert verify_token(t) is None  # blocked after revoke


# ══════════════════════════════════════════════════════════════════════
#  C2 — Fail loud without SECRET_KEY (no ephemeral fallback)
# ══════════════════════════════════════════════════════════════════════

class TestNoEphemeralSecret:
    def test_create_token_raises_without_secret(self, monkeypatch):
        """Without SECRET_KEY and without JWT_SECRET_KEY, create_token must
        raise — the old code silently minted an unverifiable token."""
        monkeypatch.delenv("SECRET_KEY", raising=False)
        with app.app_context():
            saved = app.config.pop("JWT_SECRET_KEY", None)
            try:
                with pytest.raises(RuntimeError, match="SECRET_KEY"):
                    create_token(subject="u")
            finally:
                if saved is not None:
                    app.config["JWT_SECRET_KEY"] = saved

    def test_create_refresh_token_raises_without_secret(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        with app.app_context():
            saved = app.config.pop("JWT_SECRET_KEY", None)
            try:
                with pytest.raises(RuntimeError, match="SECRET_KEY"):
                    create_refresh_token(subject="u")
            finally:
                if saved is not None:
                    app.config["JWT_SECRET_KEY"] = saved

    def test_create_token_works_with_configured_secret(self, client):
        """With JWT_SECRET_KEY set, issuance + verification roundtrip."""
        with app.app_context():
            t = create_token(subject="acme", extra_claims={"role": "viewer"})
        payload = verify_token(t)
        assert payload is not None
        assert payload["sub"] == "acme"
        assert payload["role"] == "viewer"
        assert payload["type"] == "access"

    def test_refresh_token_roundtrip(self, client):
        with app.app_context():
            rt, _ = create_refresh_token(subject="acme", extra_claims={"role": "member"})
        payload = verify_token(rt, expected_type="refresh")
        assert payload is not None
        assert payload["sub"] == "acme"
        assert payload["role"] == "member"
        assert payload["type"] == "refresh"


# ══════════════════════════════════════════════════════════════════════
#  C4 — PyJWT tamper/type rejection
# ══════════════════════════════════════════════════════════════════════

class TestPyJwtSemantics:
    def test_tampered_token_rejected(self, client):
        with app.app_context():
            t = create_token(subject="acme")
        # Flip a character in the payload segment (breaks the HMAC signature,
        # which covers the encoded header.payload string — padding bits are
        # irrelevant, any change to the payload segment invalidates it).
        parts = t.split(".")
        flipped = "A" if parts[1][-1] != "A" else "B"
        tampered = f"{parts[0]}.{parts[1][:-1] + flipped}.{parts[2]}"
        assert verify_token(tampered) is None
        assert verify_token(t) is not None  # original still valid

    def test_wrong_type_rejected(self, client):
        with app.app_context():
            rt, _ = create_refresh_token(subject="acme")
        # Access verification must reject a refresh token
        assert verify_token(rt, expected_type="access") is None
        assert verify_token(rt, expected_type="refresh") is not None

    def test_garbage_token_rejected(self, client):
        # client fixture provides the app context _get_secret() needs
        assert verify_token("not.a.jwt") is None
        assert verify_token("") is None


# ══════════════════════════════════════════════════════════════════════
#  C7 — DDL allowlist regex
# ══════════════════════════════════════════════════════════════════════

class TestDdlAllowlist:
    def test_allows_known_columns(self):
        from services.tenant import _ALLOWED_COLUMN_NAME
        assert _ALLOWED_COLUMN_NAME.fullmatch("role")
        assert _ALLOWED_COLUMN_NAME.fullmatch("password_hash")
        assert _ALLOWED_COLUMN_NAME.fullmatch("tenant_id")

    def test_rejects_injection_style_identifiers(self):
        from services.tenant import _ALLOWED_COLUMN_NAME
        for bad in ("role; DROP TABLE users", "Role", "role x", "1col", "role--"):
            assert not _ALLOWED_COLUMN_NAME.fullmatch(bad), f"{bad!r} should be rejected"
