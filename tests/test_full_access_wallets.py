"""
CYPHER65 // FULL & FREE community wallets — backend regression tests
=====================================================================
Locks the /api/set-address whitelist for the exact DIGO GARABELI wallets
(BTC + DOGE + LTC). Policy: every wallet with a welcome message holds
FULL & FREE access — so the 3 exact addresses bypass the strict BTC
prefix/checksum validation, while ANY other non-BTC address is still
rejected (security stays intact).
"""
import pytest

import app as _app_module


@pytest.fixture
def client():
    """Return a Flask test client."""
    _app_module.app.testing = True
    return _app_module.app.test_client()


@pytest.fixture(autouse=True)
def _restore_globals():
    """Snapshot/restore module globals mutated by /api/set-address.

    The route executes ``global BTC_ADDRESS; BTC_ADDRESS = new_addr`` inside
    the handler, so monkeypatch.setattr cannot survive the rebinding. Without
    a restore, the 200-path tests would leave app.BTC_ADDRESS (and WORKER_NAME)
    pointing at the last connected wallet for the whole pytest session,
    potentially breaking unrelated tests that read the module default.
    """
    saved = {"btc": _app_module.BTC_ADDRESS, "worker": _app_module.WORKER_NAME}
    yield
    _app_module.BTC_ADDRESS = saved["btc"]
    _app_module.WORKER_NAME = saved["worker"]


def _setup(monkeypatch):
    """Isolate the endpoint: no real DB writes, no polling side effects."""
    class _FakeConn:
        """Minimal sqlite3-like row factory so get_db() consumers work."""
        row_factory = None

        def cursor(self):
            return self

        def execute(self, *a, **k):
            return self

        def fetchone(self):
            return None

        def fetchall(self):
            return []

        def commit(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(_app_module, "get_db", lambda: _FakeConn())
    monkeypatch.setattr(_app_module, "_log_wallet_change", lambda *a, **kw: None)
    monkeypatch.setattr(_app_module, "poll_once", lambda: None)


# ── Whitelist membership ──────────────────────────────────────────────

class TestFullAccessWalletWhitelist:
    def test_whitelist_contains_the_3_digo_wallets(self):
        assert "bc1q029y2atdtvth4puv2mm5w49m32n278jtz2sxqn" in _app_module._FULL_ACCESS_WALLETS
        assert "dhr7a2ihqou5w5r5cpvsuvcnw4jg32qlwx" in _app_module._FULL_ACCESS_WALLETS  # DOGE
        assert "1473pql42jvtwxaaxcvsocrf6ytb8teted" in _app_module._FULL_ACCESS_WALLETS  # LTC


# ── Endpoint acceptance / rejection ───────────────────────────────────

class TestSetAddressFullAccessBypass:
    def test_doge_wallet_accepted(self, client, monkeypatch):
        """The exact DOGE wallet bypasses the strict BTC prefix check."""
        _setup(monkeypatch)
        res = client.post("/api/set-address", json={"address": "DHr7a2iHQoU5w5R5cpvsuvCNw4Jg32qLWX"})
        assert res.status_code == 200

    def test_ltc_wallet_accepted(self, client, monkeypatch):
        """The exact LTC wallet bypasses the strict BTC prefix check."""
        _setup(monkeypatch)
        res = client.post("/api/set-address", json={"address": "1473PqL42JVTwXaAXcVsocRF6ytB8tETeD"})
        assert res.status_code == 200

    def test_btc_wallet_accepted(self, client, monkeypatch):
        """The exact BTC wallet is accepted (valid Bech32 + whitelisted)."""
        _setup(monkeypatch)
        res = client.post("/api/set-address", json={"address": "bc1q029y2atdtvth4puv2mm5w49m32n278jtz2sxqn"})
        assert res.status_code == 200

    def test_other_doge_address_rejected(self, client, monkeypatch):
        """A NON-whitelisted D-prefixed address is still rejected — the
        bypass is exact-match only, security never loosens for strangers."""
        _setup(monkeypatch)
        res = client.post("/api/set-address", json={"address": "DShrt5ad0A4nQpJSpK9zQT9HpZR6gU1KfB"})
        assert res.status_code == 400
        body = res.get_json()
        assert "bc1" in (body.get("error") or "")

    def test_other_ltc_like_address_rejected(self, client, monkeypatch):
        """A non-whitelisted address starting with 1 that fails checksum is
        still rejected — only the exact wallets bypass."""
        _setup(monkeypatch)
        # Same shape as the whitelisted LTC but not the exact string.
        res = client.post("/api/set-address", json={"address": "1473PqL42JVTwXaAXcVsocRF6ytB8tETeF"})
        assert res.status_code == 400

    def test_empty_address_rejected(self, client, monkeypatch):
        _setup(monkeypatch)
        res = client.post("/api/set-address", json={"address": ""})
        assert res.status_code == 400
