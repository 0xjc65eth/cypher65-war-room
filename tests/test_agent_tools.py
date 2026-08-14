"""Tests for the CYPHER Solo Mining Advisor agent tools.
Uses unittest.mock to simulate HTTP responses — no real API calls.
"""

import pytest
from unittest.mock import patch, Mock, MagicMock

from agents.solo_mining_advisor.tools import (
    _mrr_signed_headers,
    get_network_difficulty,
    get_btc_price,
    get_braiins_orderbook,
    get_mrr_listings,
    get_parasite_pool_stats,
    call_tool,
    TOOL_REGISTRY,
    TOOL_SCHEMAS,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. get_network_difficulty — blockchain.info + mempool.space fallback
# ═══════════════════════════════════════════════════════════════════════════


class TestGetNetworkDifficulty:
    """Tests for Bitcoin network difficulty fetching with fallback chain."""

    def test_primary_success_blockchain_info(self):
        """Primary source (blockchain.info) succeeds — returns difficulty."""
        mock_resp = Mock()
        mock_resp.ok = True
        mock_resp.text = "112834572822315\n"

        with patch(
            "agents.solo_mining_advisor.tools.requests.get", return_value=mock_resp
        ) as mock_get:
            result = get_network_difficulty()

        assert result["difficulty"] == pytest.approx(112834572822315.0)
        assert "blockchain.info" in result["source"]
        # Only one call — no fallback needed
        assert mock_get.call_count == 1

    def test_fallback_to_mempool_when_blockchain_fails(self):
        """blockchain.info fails → falls back to mempool.space successfully."""
        mock_bad = Mock()
        mock_bad.ok = False
        mock_bad.status_code = 503

        mock_good = Mock()
        mock_good.ok = True
        mock_good.json.return_value = {"difficulty": 112834572822315}

        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=[Mock(ok=False, status_code=503), mock_good],
        ):
            result = get_network_difficulty()

        assert result["difficulty"] == pytest.approx(112834572822315.0)
        assert "mempool.space" in result["source"]

    def test_fallback_to_mempool_when_blockchain_raises(self):
        """blockchain.info raises an exception → falls back to mempool."""
        mock_good = Mock()
        mock_good.ok = True
        mock_good.json.return_value = {"difficulty": 112834572822315}

        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=[Exception("Connection refused"), mock_good],
        ):
            result = get_network_difficulty()

        assert result["difficulty"] == pytest.approx(112834572822315.0)
        assert "mempool.space" in result["source"]

    def test_both_sources_fail(self):
        """Both blockchain.info and mempool.space fail → returns error."""
        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=[Exception("Refused"), Exception("Timeout")],
        ):
            result = get_network_difficulty()

        assert "error" in result
        assert "unreachable" in result["error"].lower()

    def test_mempool_missing_difficulty_key(self):
        """mempool returns JSON but without 'difficulty' key → still error."""
        mock_bad = Mock(ok=False, status_code=500)
        mock_no_diff = Mock()
        mock_no_diff.ok = True
        mock_no_diff.json.return_value = {"other_field": 123}

        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=[mock_bad, mock_no_diff],
        ):
            result = get_network_difficulty()

        assert "error" in result
        assert "unreachable" in result["error"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# 2. get_btc_price — CoinGecko API
# ═══════════════════════════════════════════════════════════════════════════


class TestGetBtcPrice:
    """Tests for BTC price fetching from CoinGecko."""

    def test_success_with_default_currencies(self):
        """Default call returns USD, BRL, EUR, GBP."""
        mock_resp = Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "bitcoin": {"usd": 67420, "brl": 345000, "eur": 62100, "gbp": 53200}
        }

        with patch(
            "agents.solo_mining_advisor.tools.requests.get", return_value=mock_resp
        ):
            result = get_btc_price()

        assert result["prices"] == {
            "usd": 67420,
            "brl": 345000,
            "eur": 62100,
            "gbp": 53200,
        }
        assert result["source"] == "coingecko.com"

    def test_success_with_custom_currencies(self):
        """Only request USD and BRL."""
        mock_resp = Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"bitcoin": {"usd": 67420, "brl": 345000}}

        with patch(
            "agents.solo_mining_advisor.tools.requests.get", return_value=mock_resp
        ) as mock_get:
            result = get_btc_price("usd,brl")

        assert result["prices"] == {"usd": 67420, "brl": 345000}
        # Verify params were passed correctly
        call_args = mock_get.call_args
        assert call_args[1]["params"]["vs_currencies"] == "usd,brl"

    def test_api_failure(self):
        """CoinGecko is unreachable → returns error."""
        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=Exception("Network error"),
        ):
            result = get_btc_price()

        assert "error" in result
        assert "unreachable" in result["error"].lower()

    def test_http_error_response(self):
        """CoinGecko returns HTTP error (e.g., 429 rate limited)."""
        mock_resp = Mock()
        mock_resp.ok = False
        mock_resp.status_code = 429  # Too Many Requests

        with patch(
            "agents.solo_mining_advisor.tools.requests.get", return_value=mock_resp
        ):
            result = get_btc_price()

        assert "error" in result

    def test_empty_bitcoin_key(self):
        """Response JSON has no 'bitcoin' key."""
        mock_resp = Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {}

        with patch(
            "agents.solo_mining_advisor.tools.requests.get", return_value=mock_resp
        ):
            result = get_btc_price()

        # returns empty prices dict (no error because HTTP succeeded)
        assert result["prices"] == {}
        assert result["source"] == "coingecko.com"

    def test_prices_lowercased(self):
        """CoinGecko returns uppercase keys → tool lowercases them."""
        mock_resp = Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"bitcoin": {"USD": 67420}}

        with patch(
            "agents.solo_mining_advisor.tools.requests.get", return_value=mock_resp
        ):
            result = get_btc_price("usd")

        assert result["prices"] == {"usd": 67420}


# ═══════════════════════════════════════════════════════════════════════════
# 3. get_braiins_orderbook — Braiins Hashpower market
# ═══════════════════════════════════════════════════════════════════════════


class TestGetBraiinsOrderbook:
    """Tests for Braiins Hashpower orderbook fetching."""

    def test_success_with_asks_sats_pricing(self):
        """Normal case: settings return sats/PH/day, orderbook has asks."""
        mock_settings = Mock()
        mock_settings.ok = True
        mock_settings.json.return_value = {"price_unit": "sats/PH/day"}

        mock_orderbook = Mock()
        mock_orderbook.ok = True
        mock_orderbook.json.return_value = {
            "asks": [
                {"price_sat": "2847"},
                {"price_sat": "3200"},
                {"price_sat": "2900"},
            ],
            "bids": [],
        }

        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=[mock_settings, mock_orderbook],
        ):
            result = get_braiins_orderbook()

        assert result["price_raw"] == 2847.0
        assert result["price_btc_per_ph_day"] == pytest.approx(0.00002847)
        assert result["price_unit"] == "sats/PH/day"
        assert result["available_asks"] == 3
        assert result["available_bids"] == 0
        assert "hashpower.braiins.com" in result["source"]

    def test_success_with_btc_pricing(self):
        """Settings return BTC/PH/day pricing."""
        mock_settings = Mock()
        mock_settings.ok = True
        mock_settings.json.return_value = {"price_unit": "BTC/PH/day"}

        mock_orderbook = Mock()
        mock_orderbook.ok = True
        mock_orderbook.json.return_value = {
            "asks": [{"price_sat": "2847"}],
            "bids": [],
        }

        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=[mock_settings, mock_orderbook],
        ):
            result = get_braiins_orderbook()

        assert result["price_btc_per_ph_day"] == pytest.approx(0.00002847)

    def test_fallback_to_bids_when_no_asks(self):
        """No asks → use highest bid as proxy for market rate."""
        mock_settings = Mock(ok=False)  # settings fail → use default

        mock_orderbook = Mock()
        mock_orderbook.ok = True
        mock_orderbook.json.return_value = {
            "asks": [],
            "bids": [
                {"price_sat": "2500"},
                {"price_sat": "2800"},  # highest bid
                {"price_sat": "2600"},
            ],
        }

        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=[mock_settings, mock_orderbook],
        ):
            result = get_braiins_orderbook()

        assert result["price_raw"] == 2800.0

    def test_empty_orderbook(self):
        """No asks and no bids → error."""
        mock_settings = Mock(ok=False)

        mock_orderbook = Mock()
        mock_orderbook.ok = True
        mock_orderbook.json.return_value = {"asks": [], "bids": []}

        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=[mock_settings, mock_orderbook],
        ):
            result = get_braiins_orderbook()

        assert "error" in result
        assert "empty" in result["error"].lower()

    def test_settings_failure_uses_default_unit(self):
        """Settings API fails → assumes sats/PH/day as default."""
        mock_settings = Mock(ok=False)

        mock_orderbook = Mock()
        mock_orderbook.ok = True
        mock_orderbook.json.return_value = {
            "asks": [{"price_sat": "5000"}],
            "bids": [],
        }

        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=[mock_settings, mock_orderbook],
        ):
            result = get_braiins_orderbook()

        # 5000 sats = 0.00005 BTC
        assert result["price_btc_per_ph_day"] == pytest.approx(0.00005)

    def test_orderbook_http_error(self):
        """Orderbook endpoint returns HTTP error."""
        mock_settings = Mock(ok=False)

        mock_orderbook = Mock()
        mock_orderbook.ok = False
        mock_orderbook.status_code = 500

        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=[mock_settings, mock_orderbook],
        ):
            result = get_braiins_orderbook()

        assert "error" in result
        assert "500" in result["error"]

    def test_network_error(self):
        """Complete network failure."""
        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=Exception("DNS resolution failed"),
        ):
            result = get_braiins_orderbook()

        assert "error" in result
        assert "unreachable" in result["error"].lower()

    def test_zero_price_rejected(self):
        """All prices are 0 → error."""
        mock_settings = Mock(ok=False)

        mock_orderbook = Mock()
        mock_orderbook.ok = True
        mock_orderbook.json.return_value = {
            "asks": [{"price": "0"}],
            "bids": [],
        }

        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=[mock_settings, mock_orderbook],
        ):
            result = get_braiins_orderbook()

        assert "error" in result
        assert "valid prices" in result["error"].lower()

    def test_settings_probe_sends_apikey_header_when_configured(self, monkeypatch):
        """With BRAIINS_API_KEY configured (env or Settings), the /spot/settings
        probe must send the `apikey` header so the caller gets their individual
        pricing layer (the endpoint 401s without it)."""
        import services.settings as _settings_mod

        monkeypatch.setenv("BRAIINS_API_KEY", "owner-token")
        monkeypatch.setattr(_settings_mod, "load_settings", lambda: {})

        mock_settings = Mock()
        mock_settings.ok = True
        mock_settings.json.return_value = {"price_unit": "sats/TH/day"}
        mock_orderbook = Mock()
        mock_orderbook.ok = True
        mock_orderbook.json.return_value = {
            "asks": [{"price_sat": "2847"}],
            "bids": [],
        }

        captured = {}

        def _fake_get(url, timeout=None, headers=None):
            if "/spot/settings" in url:
                captured["headers"] = headers
                return mock_settings
            return mock_orderbook

        with patch(
            "agents.solo_mining_advisor.tools.requests.get", side_effect=_fake_get
        ):
            result = get_braiins_orderbook()

        assert result["price_raw"] == 2847.0
        assert captured["headers"].get("apikey") == "owner-token"

    def test_settings_probe_no_apikey_without_key(self, monkeypatch):
        """Without a configured key, the settings probe has no `apikey` header
        and the fetch still works (degrades to default price unit)."""
        import services.settings as _settings_mod

        monkeypatch.delenv("BRAIINS_API_KEY", raising=False)
        monkeypatch.setattr(_settings_mod, "load_settings", lambda: {})

        mock_settings = Mock(ok=False)  # 401 without key → fallback unit
        mock_orderbook = Mock()
        mock_orderbook.ok = True
        mock_orderbook.json.return_value = {
            "asks": [{"price_sat": "2847"}],
            "bids": [],
        }

        captured = {}

        def _fake_get(url, timeout=None, headers=None):
            if "/spot/settings" in url:
                captured["headers"] = headers
                return mock_settings
            return mock_orderbook

        with patch(
            "agents.solo_mining_advisor.tools.requests.get", side_effect=_fake_get
        ):
            result = get_braiins_orderbook()

        assert result["price_raw"] == 2847.0
        assert "apikey" not in (captured["headers"] or {})


# ═══════════════════════════════════════════════════════════════════════════
# 4. get_mrr_listings — MiningRigRentals with HMAC-SHA1 auth
# ═══════════════════════════════════════════════════════════════════════════


class TestMrrNonce:
    """MRR exige nonce estritamente crescente por chave. O bug real: o nonce
    era time.time()*1000 — duas chamadas no mesmo ms geravam o MESMO nonce e
    o MRR respondia 'Not Authenticated - Invalid Key - Bad Nonce' (ex.: o
    fetch de detail dispara 3 GETs concorrentes — colisão sob carga)."""

    @pytest.fixture(autouse=True)
    def _reset_nonce_state(self):
        """Hermeticidade: o contador de nonce é um singleton do processo.
        Sem o reset, os testes dependem da ordem de execução (o teste do
        relógio congelado só passava porque testes anteriores elevavam o
        contador — falhava rodado isolado)."""
        import agents.solo_mining_advisor.tools as tools_mod

        tools_mod._mrr_last_nonce = 0
        yield
        tools_mod._mrr_last_nonce = 0

    def _headers_nonce(self, key="k", secret="s", ep="/rental"):
        return _mrr_signed_headers(key, secret, ep)["x-api-nonce"]

    def test_sequential_nonces_strictly_increasing(self):
        nonces = [int(self._headers_nonce()) for _ in range(5)]
        assert all(b > a for a, b in zip(nonces, nonces[1:]))

    def test_concurrent_nonces_all_unique(self):
        import threading

        results = []
        lock = threading.Lock()

        def _worker():
            for _ in range(5):
                n = int(self._headers_nonce())
                with lock:
                    results.append(n)

        threads = [threading.Thread(target=_worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 50
        assert len(set(results)) == 50  # zero colisões de nonce

    def test_clock_backwards_still_increasing(self, monkeypatch):
        """Relógio parado/voltando não pode gerar nonce menor que o último."""
        import agents.solo_mining_advisor.tools as tools_mod

        def _frozen_clock():
            return 1_700_000_000.0  # fixo — toda chamada no mesmo ms

        monkeypatch.setattr(tools_mod.time, "time", _frozen_clock)
        nonces = [int(self._headers_nonce()) for _ in range(3)]
        assert all(b > a for a, b in zip(nonces, nonces[1:]))


class TestGetMrrListings:
    """Tests for MiningRigRentals listing fetching."""

    def test_missing_credentials(self):
        """No API key/secret → returns needs_auth=True."""
        with patch.dict("os.environ", {}, clear=True):
            result = get_mrr_listings()

        assert result["needs_auth"] is True
        assert "not configured" in result["error"]

    def test_success_with_credentials(self):
        """Valid credentials → returns cheapest listing."""
        mock_resp = Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "success": True,
            "data": {
                "records": [
                    {
                        "name": "Antminer S21 Pro",
                        "hashrate": {"advertised": {"hash": 100}},
                        "price": {"BTC": {"price": "0.0000005"}},
                    },
                    {
                        "name": "Whatsminer M60",
                        "hashrate": {"advertised": {"hash": 100}},
                        "price": {"BTC": {"price": "0.0000006"}},
                    },
                ]
            },
        }

        with patch(
            "agents.solo_mining_advisor.tools.requests.get", return_value=mock_resp
        ):
            result = get_mrr_listings(api_key="test_key", api_secret="test_secret")

        # (price/hour 0.0000005 * 24 / 100 TH) = 1.2e-7 BTC/TH/day
        # per-PH/day = per-TH/day × PH_TO_TH(1000) = 1.2e-4 BTC/PH/day
        assert result["price_btc_per_th_day"] == pytest.approx(1.2e-7)
        assert result["price_btc_per_ph_day"] == pytest.approx(1.2e-4)
        assert result["total_listings"] == 2
        assert result["best_rig_name"] == "Antminer S21 Pro"
        assert "miningrigrentals.com" in result["source"]

    def test_gh_unit_pricing(self):
        """Rig hashrate from advertised.hash (TH) is used for the conversion."""
        mock_resp = Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "success": True,
            "data": {
                "records": [
                    {
                        "name": "Old Rig",
                        "hashrate": {"advertised": {"hash": 100}},
                        "price": {"BTC": {"price": "0.0000005"}},
                    },
                ]
            },
        }

        with patch(
            "agents.solo_mining_advisor.tools.requests.get", return_value=mock_resp
        ):
            result = get_mrr_listings(api_key="k", api_secret="s")

        # price/hour 0.0000005 * 24 / 100 TH → 1.2e-7 BTC/TH/day → per-PH ×1000 = 1.2e-4
        assert result["price_btc_per_th_day"] == pytest.approx(1.2e-7)
        assert result["price_btc_per_ph_day"] == pytest.approx(1.2e-4)
        assert result["best_rig_hash_th"] == 100

    def test_ph_unit_pricing(self):
        """Higher hashrate rig with the same hourly price is cheaper per TH/day."""
        mock_resp = Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "success": True,
            "data": {
                "records": [
                    {
                        "name": "Farm Rig",
                        "hashrate": {"advertised": {"hash": 200}},
                        "price": {"BTC": {"price": "0.0000005"}},
                    },
                ]
            },
        }

        with patch(
            "agents.solo_mining_advisor.tools.requests.get", return_value=mock_resp
        ):
            result = get_mrr_listings(api_key="k", api_secret="s")

        # price/hour 0.0000005 * 24 / 200 TH → 6e-8 BTC/TH/day → per-PH ×1000 = 6e-5
        assert result["price_btc_per_th_day"] == pytest.approx(6e-8)
        assert result["price_btc_per_ph_day"] == pytest.approx(6e-5)
        assert result["best_rig_hash_th"] == 200

    def test_api_not_success(self):
        """MRR API returns success=False."""
        mock_resp = Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "success": False,
            "message": "Invalid API key",
        }

        with patch(
            "agents.solo_mining_advisor.tools.requests.get", return_value=mock_resp
        ):
            result = get_mrr_listings(api_key="bad_key", api_secret="bad_secret")

        assert "error" in result
        assert "Invalid API key" in result["error"]

    def test_no_listings(self):
        """API returns success but no listings."""
        mock_resp = Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"success": True, "data": []}

        with patch(
            "agents.solo_mining_advisor.tools.requests.get", return_value=mock_resp
        ):
            result = get_mrr_listings(api_key="k", api_secret="s")

        assert "error" in result
        assert "No active" in result["error"]

    def test_cannot_parse_prices(self):
        """Listings exist but all have zero/invalid prices."""
        mock_resp = Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "success": True,
            "data": [
                {
                    "name": "Broken Rig",
                    "hash": 0,
                    "price": {"amount": "0", "currency": "BTC"},
                },
            ],
        }

        with patch(
            "agents.solo_mining_advisor.tools.requests.get", return_value=mock_resp
        ):
            result = get_mrr_listings(api_key="k", api_secret="s")

        assert "error" in result
        assert "parse" in result["error"].lower() or "Could not" in result["error"]

    def test_http_error(self):
        """MRR API returns HTTP error."""
        mock_resp = Mock()
        mock_resp.ok = False
        mock_resp.status_code = 403

        with patch(
            "agents.solo_mining_advisor.tools.requests.get", return_value=mock_resp
        ):
            result = get_mrr_listings(api_key="k", api_secret="s")

        assert "error" in result
        assert "403" in result["error"]

    def test_network_exception(self):
        """Network failure during API call."""
        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=Exception("Connection timeout"),
        ):
            result = get_mrr_listings(api_key="k", api_secret="s")

        assert "error" in result
        assert "unreachable" in result["error"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# 5. get_parasite_pool_stats — parasite.space pool + worker data
# ═══════════════════════════════════════════════════════════════════════════


class TestGetParasitePoolStats:
    """Tests for parasite.space pool stats fetching."""

    def test_full_success(self):
        """Both pool-stats and user endpoints succeed."""
        mock_pool = Mock()
        mock_pool.ok = True
        mock_pool.json.return_value = {
            "hashrate": 1500000000000000,
            "workers": 42,
            "users": 15,
            "highestDifficulty": "87.1 T",
            "lastBlockHeight": 870123,
            "workSinceLastBlock": 55000000000000,
        }

        mock_user = Mock()
        mock_user.ok = True
        mock_user.json.return_value = {
            "workerData": [
                {
                    "hashrate": 225000000000000,
                    "bestDifficulty": "25.73 T",
                    "lastSubmission": 1711500000,
                    "uptime": 1209600,
                }
            ],
            "account": {"total_diff": 1500000000000000},
        }

        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=[mock_pool, mock_user],
        ):
            result = get_parasite_pool_stats()

        assert result["pool_hashrate"] == 1500000000000000
        assert result["pool_workers"] == 42
        assert result["worker_hashrate"] == 225000000000000
        assert result["worker_best_diff"] == "25.73 T"
        assert result["pool_status"] == "full"
        assert "parasite.space" in result["source"]

    def test_pool_only_worker_fails(self):
        """Pool succeeds, user endpoint fails → partial_pool_only."""
        mock_pool = Mock()
        mock_pool.ok = True
        mock_pool.json.return_value = {
            "hashrate": 1.5e15,
            "workers": 42,
        }

        mock_user = Mock(ok=False, status_code=500)

        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=[mock_pool, mock_user],
        ):
            result = get_parasite_pool_stats()

        assert result["pool_status"] == "partial_pool_only"
        assert "pool_hashrate" in result
        # Worker fields should be absent
        assert "worker_hashrate" not in result

    def test_worker_only_pool_fails(self):
        """User endpoint succeeds, pool fails → partial_worker_only."""
        mock_pool = Mock(ok=False, status_code=500)

        mock_user = Mock()
        mock_user.ok = True
        mock_user.json.return_value = {
            "workerData": [{"hashrate": 225e12, "bestDifficulty": "25.73 T"}],
            "account": {},
        }

        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=[mock_pool, mock_user],
        ):
            result = get_parasite_pool_stats()

        assert result["pool_status"] == "partial_worker_only"
        assert "worker_hashrate" in result
        assert "pool_hashrate" not in result

    def test_both_fail(self):
        """Both endpoints fail → error."""
        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=[Exception("Timeout"), Exception("Timeout")],
        ):
            result = get_parasite_pool_stats()

        assert "error" in result
        assert "unreachable" in result["error"].lower()

    def test_worker_not_found(self):
        """Pool succeeds, but no workerData for this address."""
        mock_pool = Mock()
        mock_pool.ok = True
        mock_pool.json.return_value = {"hashrate": 1.5e15, "workers": 42}

        mock_user = Mock()
        mock_user.ok = True
        mock_user.json.return_value = {"workerData": [], "account": {}}

        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=[mock_pool, mock_user],
        ):
            result = get_parasite_pool_stats()

        assert result["pool_status"] == "full"  # both succeeded
        assert result["worker_status"] == "not_found"

    def test_pool_both_succeed_but_no_worker_data_fields(self):
        """Pool ok, user ok but workerData has no hashrate field → still full."""
        mock_pool = Mock()
        mock_pool.ok = True
        mock_pool.json.return_value = {"hashrate": 1.5e15, "workers": 42}

        mock_user = Mock()
        mock_user.ok = True
        mock_user.json.return_value = {
            "workerData": [{}],  # empty worker object
            "account": {},
        }

        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=[mock_pool, mock_user],
        ):
            result = get_parasite_pool_stats()

        assert result["pool_status"] == "full"
        assert result["worker_status"] == "online"
        # hashrate comes back as None from .get() on empty dict
        assert result.get("worker_hashrate") is None

    def test_default_worker_address_used(self):
        """When worker_id is None, uses DEFAULT_WORKER env var."""
        mock_pool = Mock()
        mock_pool.ok = True
        mock_pool.json.return_value = {"hashrate": 1.5e15, "workers": 42}

        mock_user = Mock()
        mock_user.ok = True
        mock_user.json.return_value = {"workerData": [], "account": {}}

        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=[mock_pool, mock_user],
        ) as mock_get:
            result = get_parasite_pool_stats()

        # Verify the second call used the default worker address
        user_call_url = mock_get.call_args_list[1][0][0]
        assert "bc1qpc3832" in user_call_url


# ═══════════════════════════════════════════════════════════════════════════
# 6. call_tool — tool dispatcher
# ═══════════════════════════════════════════════════════════════════════════


class TestCallTool:
    """Tests for the call_tool dispatcher."""

    def test_unknown_tool(self):
        """Calling an unregistered tool returns error."""
        result = call_tool("nonexistent_tool")
        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_known_tool_no_params(self):
        """Call a known tool without params — it should execute."""
        with patch("agents.solo_mining_advisor.tools.requests.get") as mock_get:
            mock_resp = Mock()
            mock_resp.ok = True
            mock_resp.text = "112834572822315\n"
            mock_get.return_value = mock_resp

            result = call_tool("get_network_difficulty")

        assert "difficulty" in result

    def test_known_tool_with_params(self):
        """Call a known tool with params — params are forwarded."""
        with patch("agents.solo_mining_advisor.tools.requests.get") as mock_get:
            mock_resp = Mock()
            mock_resp.ok = True
            mock_resp.json.return_value = {"bitcoin": {"usd": 67420}}
            mock_get.return_value = mock_resp

            result = call_tool("get_btc_price", {"currencies": "usd"})

        assert result["prices"] == {"usd": 67420}

    def test_tool_raises_exception(self):
        """Tool raises an exception → call_tool catches and returns error."""
        with patch(
            "agents.solo_mining_advisor.tools.requests.get",
            side_effect=RuntimeError("Unexpected crash"),
        ):
            result = call_tool("get_network_difficulty")

        assert "error" in result
        assert "unreachable" in result["error"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# 7. Registry integrity
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistryIntegrity:
    """Verify the tool registry and schemas are correctly configured."""

    def test_all_five_tools_registered(self):
        assert len(TOOL_REGISTRY) == 6
        expected = {
            "get_network_difficulty",
            "get_btc_price",
            "get_braiins_orderbook",
            "get_mrr_listings",
            "get_nicehash_orderbook",
            "get_parasite_pool_stats",
        }
        assert set(TOOL_REGISTRY.keys()) == expected

    def test_all_tools_callable(self):
        for name, fn in TOOL_REGISTRY.items():
            assert callable(fn), f"{name} is not callable"

    def test_all_tools_have_docstrings(self):
        for name, fn in TOOL_REGISTRY.items():
            assert fn.__doc__, f"{name} has no docstring"

    def test_all_tool_schemas_have_descriptions(self):
        assert len(TOOL_SCHEMAS) == 6
        for name, schema in TOOL_SCHEMAS.items():
            assert "description" in schema, f"{name} schema missing description"
            assert "parameters" in schema, f"{name} schema missing parameters"
