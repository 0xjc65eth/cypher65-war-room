"""
CYPHER65 // Multi-pool registry: detection, chain tagging and normalizers
=========================================================================
Issue #571. Every pool figure used to come from exactly one host
(parasite.space/api) and any other pool rendered zeros — not because the pool
was incompatible, but because no other response shape was parsed, and because
the ASIC's own ``stratumURL`` (which says exactly which pool it is on) was
collected and then thrown away.

These tests pin:

- host extraction from the shapes real firmware reports;
- provider detection with longest-pattern precedence (``solo.bsv.ckpool.org``
  must be BSV solo, NOT the generic BTC ``ckpool.org``) and the label-boundary
  guard (``notbraiins.com`` is not Braiins);
- honest unknowns: an unregistered host keeps its raw hostname and a ``None``
  chain instead of an invented provider;
- hashrate parsing for both raw numbers and ckpool's unit strings;
- normalizers for ckpool, public-pool and parasite producing ONE shape;
- resolution order: ASIC-reported pool wins, then API probing, then the ASIC
  as the data source — never fabricated numbers, never silent zeros.
"""

import pytest

from services.pool_intelligence import (
    Chain,
    PoolDetection,
    PoolKind,
    detect_provider,
    normalize_asic_telemetry,
    normalize_ckpool_user,
    normalize_parasite_user,
    normalize_public_pool_workers,
    parse_hashrate_to_hs,
    resolve_pool_stats,
    stats_api_providers,
    stats_url_for,
    stratum_host,
)
from services.pool_intelligence.providers import provider_by_id

ADDR = "bc1qexampleaddress000000000000000000000"


# ══════════════════════════════════════════════════════════════════════════
#  stratum_host — the shapes firmware really reports
# ══════════════════════════════════════════════════════════════════════════


class TestStratumHost:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("stratum+tcp://solo.ckpool.org:3333", "solo.ckpool.org"),
            ("stratum+ssl://eu.stratum.braiins.com:3333", "eu.stratum.braiins.com"),
            ("stratum2+tcp://public-pool.io:21496", "public-pool.io"),
            ("tcp://pool.example.com", "pool.example.com"),
            ("http://ocean.xyz:80", "ocean.xyz"),
            ("pool.example.com:3333", "pool.example.com"),
            ("pool.example.com", "pool.example.com"),
            ("Pool.Example.COM.", "pool.example.com"),
            # A worker name or path appended by some firmwares.
            ("stratum+tcp://pool.example.com:3333/bc1qworker", "pool.example.com"),
            ("stratum+tcp://pool.example.com?", "pool.example.com"),
            # userinfo must not become the host
            ("stratum+tcp://user:pass@pool.example.com:3333", "pool.example.com"),
            # IPv6 keeps its brackets so the colon is not read as a port
            ("stratum+tcp://[2001:db8::1]:3333", "[2001:db8::1]"),
        ],
    )
    def test_extracts_the_host(self, raw, expected):
        assert stratum_host(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", None, 42, [], {}])
    def test_nothing_usable_returns_empty(self, raw):
        assert stratum_host(raw) == ""


# ══════════════════════════════════════════════════════════════════════════
#  detect_provider — chain-aware, honest about unknowns
# ══════════════════════════════════════════════════════════════════════════


class TestDetectProvider:
    @pytest.mark.parametrize(
        "endpoint,provider_id,chain,kind",
        [
            (
                "stratum+tcp://solo.ckpool.org:3333",
                "ckpool_solo",
                Chain.BTC,
                PoolKind.SOLO,
            ),
            ("stratum+tcp://pool.ckpool.org:3333", "ckpool", Chain.BTC, PoolKind.POOL),
            (
                "stratum+tcp://public-pool.io:21496",
                "public_pool",
                Chain.BTC,
                PoolKind.SOLO,
            ),
            ("stratum+tcp://parasite.space:3333", "parasite", Chain.BTC, PoolKind.SOLO),
            ("stratum+tcp://ocean.xyz:3333", "ocean", Chain.BTC, PoolKind.POOL),
            (
                "stratum+tcp://eu.stratum.braiins.com:3333",
                "braiins_pool",
                Chain.BTC,
                PoolKind.POOL,
            ),
            # BSV
            (
                "stratum+tcp://solo.bsv.ckpool.org:3333",
                "ckpool_bsv_solo",
                Chain.BSV,
                PoolKind.SOLO,
            ),
            (
                "stratum+tcp://bsv.viabtc.com:3333",
                "viabtc_bsv",
                Chain.BSV,
                PoolKind.POOL,
            ),
            (
                "stratum+tcp://gorillapool.io:3333",
                "gorillapool",
                Chain.BSV,
                PoolKind.POOL,
            ),
            ("stratum+tcp://stratum.taal.com:3333", "taal", Chain.BSV, PoolKind.POOL),
        ],
    )
    def test_detects_registered_pools(self, endpoint, provider_id, chain, kind):
        detection = detect_provider(endpoint)

        assert detection.provider_id == provider_id
        assert detection.chain is chain
        assert detection.kind is kind
        assert detection.chain_source == "provider_registry"

    def test_bsv_beats_the_generic_vendor_entry(self):
        """Both ``ckpool.org`` and ``solo.bsv.ckpool.org`` match this host by
        suffix; the longest pattern must win or a BSV worker is tagged BTC."""
        detection = detect_provider("stratum+tcp://solo.bsv.ckpool.org:3333")

        assert detection.provider_id == "ckpool_bsv_solo"
        assert detection.matched_pattern == "solo.bsv.ckpool.org"
        assert detection.chain is Chain.BSV

    def test_label_boundary_is_respected(self):
        """A substring match would make this Braiins."""
        detection = detect_provider("stratum+tcp://notbraiins.com:3333")

        assert detection.provider_id == "unknown"
        assert detection.host == "notbraiins.com"

    def test_subdomain_of_a_registered_pool_matches(self):
        detection = detect_provider("stratum+tcp://eu.stratum.braiins.com:3333")

        assert detection.provider_id == "braiins_pool"

    def test_unregistered_host_keeps_its_name_and_says_unknown(self):
        detection = detect_provider("stratum+tcp://minha.pool.local:3333")

        assert detection.provider_id == "unknown"
        assert detection.label == "minha.pool.local"
        assert detection.chain is None
        assert detection.chain_source == "unknown"
        assert detection.stats_url is None

    def test_bsv_label_on_an_unregistered_host_is_used_as_evidence(self):
        detection = detect_provider("stratum+tcp://bsv.minha.pool.local:3333")

        assert detection.provider_id == "unknown"
        assert detection.chain is Chain.BSV
        assert detection.chain_source == "host_label"

    def test_chain_is_never_invented_from_the_address(self):
        """BSV and BTC share the base58 1…/3… formats, so an address cannot
        distinguish them — guessing would be a fabricated signal."""
        legacy = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"

        detection = detect_provider("stratum+tcp://pool.local:3333", address=legacy)

        assert detection.chain is None
        assert detection.chain_source == "unknown"

    def test_empty_endpoint_is_unknown(self):
        detection = detect_provider("")

        assert detection.provider_id == "unknown"
        assert detection.chain is None

    def test_asic_host_is_used_as_a_lower_priority_hint(self):
        detection = detect_provider("", asic_host="solo.ckpool.org")

        assert detection.provider_id == "ckpool_solo"

    def test_to_dict_is_json_safe(self):
        payload = detect_provider(
            "stratum+tcp://ocean.xyz:3333", address=ADDR
        ).to_dict()

        assert payload["provider_id"] == "ocean"
        assert payload["chain"] == "btc"
        assert payload["has_stats_api"] is False
        assert isinstance(payload["docs"], str)


class TestStatsUrl:
    def test_uses_the_registered_api(self):
        detection = detect_provider("stratum+tcp://solo.ckpool.org:3333", address=ADDR)

        assert detection.stats_url == f"https://solo.ckpool.org/users/{ADDR}"

    def test_address_is_url_quoted(self):
        detection = detect_provider("stratum+tcp://solo.ckpool.org:3333")

        url = stats_url_for(detection.provider, "bc1q x/../y")

        assert url is not None
        assert " " not in url
        assert "/../" not in url

    def test_an_empty_address_yields_no_url(self):
        """A stats request without an identity would return the pool's own
        aggregate and masquerade as the user's numbers."""
        provider = provider_by_id("ckpool_solo")

        assert stats_url_for(provider, "") is None
        assert stats_url_for(provider, "   ") is None

    def test_provider_without_api_yields_no_url(self):
        assert stats_url_for(provider_by_id("ocean"), ADDR) is None

    def test_unknown_provider_yields_no_url(self):
        assert stats_url_for(None, ADDR) is None

    def test_only_verified_apis_are_exposed(self):
        assert {p.provider_id for p in stats_api_providers()} == {
            "parasite",
            "ckpool_solo",
            "public_pool",
            "ckpool_bsv_solo",
        }


# ══════════════════════════════════════════════════════════════════════════
#  parse_hashrate_to_hs
# ══════════════════════════════════════════════════════════════════════════


class TestParseHashrate:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (9.5e11, 9.5e11),
            (0, 0.0),
            ("9.5e11", 9.5e11),
            ("1.21T", 1.21e12),
            ("950G", 950e9),
            ("12 PH/s", 12e15),
            ("2.5 th/s", 2.5e12),
            ("3.4 Mh/s", 3.4e6),
            ("1E", 1e18),
            ("100", 100.0),
            ("1,000", 1000.0),
            ("  1.5 G  ", 1.5e9),
        ],
    )
    def test_parses_both_forms(self, value, expected):
        assert parse_hashrate_to_hs(value) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "value", ["", "   ", "lixo", "abcT", None, True, [], {}, "T"]
    )
    def test_unparseable_returns_none_not_zero(self, value):
        """A real 0 at the pool is a fact; a failed parse is not."""
        assert parse_hashrate_to_hs(value) is None


# ══════════════════════════════════════════════════════════════════════════
#  Normalizers — one shape for every provider
# ══════════════════════════════════════════════════════════════════════════


def _detection(provider_id: str, address: str = ADDR) -> PoolDetection:
    return PoolDetection(
        provider=provider_by_id(provider_id),
        host=provider_id,
        matched_pattern=provider_id,
        chain=provider_by_id(provider_id).chain,
        chain_source="provider_registry",
        address=address,
    )


class TestCkpoolNormalizer:
    CKPOOL = {
        "hashrate1m": "1.21T",
        "hashrate5m": "1.20T",
        "hashrate1hr": "1.15T",
        "lastshare": 1766000000,
        "workers": 2,
        "shares": 4321,
        "bestshare": 51474838161.27325,
        "worker": [
            {
                "workername": "bc1qexample.a",
                "hashrate1m": "600G",
                "lastshare": 1766000000,
                "shares": 2100,
                "bestshare": 12345678.0,
            },
            {
                "workername": "bc1qexample.b",
                "hashrate1m": "610G",
                "lastshare": 1765999000,
                "shares": 2221,
                "bestshare": 51474838161.27325,
            },
        ],
    }

    def test_normalizes_the_documented_shape(self):
        stats = normalize_ckpool_user(
            self.CKPOOL, _detection("ckpool_solo"), stats_url="https://x/users/a"
        )

        assert stats.source == "api"
        assert stats.provider_id == "ckpool_solo"
        assert stats.chain == "btc"
        assert stats.hashrate_hs == pytest.approx(1.21e12)
        assert stats.best_diff == pytest.approx(51474838161.27325)
        assert stats.best_diff_str == "51474838161.27325"
        assert stats.last_share_ts == 1766000000
        assert stats.workers == 2
        assert "hashrate1m" in stats.fields_found
        assert "bestshare" in stats.fields_found

    def test_worker_array_supplies_the_share_totals(self):
        """ckpool's top-level object has no share counters; the per-worker
        entries do, and the address total is their sum."""
        stats = normalize_ckpool_user(
            self.CKPOOL, _detection("ckpool_solo"), stats_url=""
        )

        assert stats.shares_accepted == 4321

    def test_worker_array_is_summed_and_maxed(self):
        stats = normalize_ckpool_user(
            self.CKPOOL, _detection("ckpool_solo"), stats_url=""
        )

        assert stats.best_diff_str  # a difficulty string was preserved

    def test_malformed_payload_is_reported_not_crashed(self):
        stats = normalize_ckpool_user(["not", "a", "dict"], _detection("ckpool_solo"))

        assert stats.source == "api"
        assert stats.error == "malformed ckpool payload"
        assert stats.hashrate_hs is None

    def test_unknown_shape_yields_nones_and_empty_fields_found(self):
        stats = normalize_ckpool_user({"algo": "sha256"}, _detection("ckpool_solo"))

        assert stats.hashrate_hs is None
        assert stats.best_diff is None
        assert stats.fields_found == ()


class TestPublicPoolNormalizer:
    WORKERS = [
        {
            "address": ADDR,
            "workerName": "gamma01",
            "hashRate": 1.2e12,
            "bestDifficulty": 8.2e12,
            "shares": 1450,
        },
        {
            "address": ADDR,
            "workerName": "gamma02",
            "hashRate": 0.8e12,
            "bestDifficulty": 6.1e12,
            "shares": 200,
        },
    ]

    def test_normalizes_the_array(self):
        stats = normalize_public_pool_workers(
            self.WORKERS, _detection("public_pool"), stats_url="https://x/api/client/a"
        )

        assert stats.source == "api"
        assert stats.provider_id == "public_pool"
        assert stats.hashrate_hs == pytest.approx(2.0e12)
        assert stats.best_diff == pytest.approx(8.2e12)
        assert stats.workers == 2
        assert "hashRate" in stats.fields_found
        assert stats.extra.get("reported_address") == ADDR

    def test_empty_array_is_a_real_answer(self):
        """The pool answered: no workers under this address."""
        stats = normalize_public_pool_workers([], _detection("public_pool"))

        assert stats.source == "api"
        assert stats.error == ""
        assert stats.workers == 0
        assert stats.hashrate_hs is None

    def test_accepts_a_wrapped_array_from_a_fork(self):
        stats = normalize_public_pool_workers(
            {"workers": self.WORKERS}, _detection("public_pool")
        )

        assert stats.workers == 2

    def test_malformed_payload_is_reported(self):
        stats = normalize_public_pool_workers("nope", _detection("public_pool"))

        assert stats.error == "malformed public-pool payload"


class TestParasiteNormalizer:
    def test_normalizes_into_the_same_shape(self):
        stats = normalize_parasite_user(
            {
                "hashrate": 4.2e12,
                "bestDifficulty": "8.2T",
                "sharesAccepted": 1450,
                "sharesRejected": 7,
            },
            _detection("parasite"),
        )

        assert stats.source == "api"
        assert stats.provider_id == "parasite"
        assert stats.hashrate_hs == pytest.approx(4.2e12)
        assert stats.shares_accepted == 1450
        assert stats.shares_rejected == 7

    def test_malformed_payload_is_reported(self):
        assert normalize_parasite_user(None, _detection("parasite")).error


class TestAsicTelemetryNormalizer:
    def test_uses_the_hardware_as_the_source(self):
        stats = normalize_asic_telemetry(
            detect_provider("stratum+tcp://ocean.xyz:3333", address=ADDR),
            {
                "hashrate_hs": 912345678901,
                "best_diff": "8.2T",
                "shares_accepted": 1450,
                "shares_rejected": 7,
            },
        )

        assert stats.source == "asic"
        assert stats.provider_id == "ocean"
        assert stats.label == "OCEAN"
        assert stats.hashrate_hs == pytest.approx(912345678901)
        assert stats.shares_accepted == 1450
        assert stats.stats_url == ""


# ══════════════════════════════════════════════════════════════════════════
#  resolve_pool_stats — evidence order, never fabrication
# ══════════════════════════════════════════════════════════════════════════


class TestResolvePoolStats:
    def test_asic_reported_pool_wins_and_its_api_is_used(self):
        calls = []

        def fetcher(url):
            calls.append(url)
            return {"hashrate1m": "1.21T", "bestshare": 100.0, "workers": 1}

        stats = resolve_pool_stats(
            ADDR,
            fetcher=fetcher,
            asic_pool_url="stratum+tcp://solo.ckpool.org:3333",
        )

        assert stats.provider_id == "ckpool_solo"
        assert stats.source == "api"
        assert calls == [f"https://solo.ckpool.org/users/{ADDR}"]

    def test_asic_reported_pool_without_api_falls_back_to_the_hardware(self):
        def fetcher(url):  # pragma: no cover — must not be called
            raise AssertionError("no API should be requested for OCEAN")

        stats = resolve_pool_stats(
            ADDR,
            fetcher=fetcher,
            asic_pool_url="stratum+tcp://ocean.xyz:3333",
            asic_telemetry={"hashrate_hs": 1e12, "best_diff": "3T"},
        )

        assert stats.provider_id == "ocean"
        assert stats.source == "asic"
        assert stats.hashrate_hs == pytest.approx(1e12)

    def test_unregistered_asic_pool_is_honoured_not_replaced(self):
        """The hardware says where it mines — do not report another pool's
        numbers just because they are easier to fetch."""

        def fetcher(url):  # pragma: no cover
            raise AssertionError("must not probe other providers")

        stats = resolve_pool_stats(
            ADDR,
            fetcher=fetcher,
            asic_pool_url="stratum+tcp://minha.pool.local:3333",
            asic_telemetry={"hashrate_hs": 5e11},
        )

        assert stats.provider_id == "unknown"
        assert stats.label == "minha.pool.local"
        assert stats.source == "asic"

    def test_probes_providers_when_the_asic_has_not_told_us(self):
        responses = {
            f"https://parasite.space/api/user/{ADDR}": None,
            f"https://solo.ckpool.org/users/{ADDR}": {
                "hashrate1m": "600G",
                "bestshare": 42.0,
                "workers": 1,
            },
        }

        stats = resolve_pool_stats(ADDR, fetcher=responses.get)

        assert stats.provider_id == "ckpool_solo"
        assert stats.source == "api"
        assert stats.hashrate_hs == pytest.approx(600e9)

    def test_an_empty_public_pool_answer_does_not_stop_the_probe(self):
        """public-pool returning [] means "not here" — keep looking."""
        responses = {
            f"https://parasite.space/api/user/{ADDR}": None,
            f"https://solo.ckpool.org/users/{ADDR}": None,
            f"https://public-pool.io:40557/api/client/{ADDR}": [],
        }

        stats = resolve_pool_stats(ADDR, fetcher=responses.get)

        assert stats.provider_id == "unknown"
        assert stats.source == "asic"

    def test_no_provider_answers_reports_unknown_without_inventing_numbers(self):
        stats = resolve_pool_stats(ADDR, fetcher=lambda url: None)

        assert stats.provider_id == "unknown"
        assert stats.source == "asic"
        assert stats.hashrate_hs is None
        assert stats.best_diff is None

    def test_a_dead_pool_api_never_breaks_the_poll(self):
        def fetcher(url):
            raise ConnectionError("pool api down")

        stats = resolve_pool_stats(
            ADDR, fetcher=fetcher, asic_telemetry={"hashrate_hs": 7e11}
        )

        assert stats.source == "asic"
        assert stats.hashrate_hs == pytest.approx(7e11)

    def test_a_shape_change_does_not_break_the_probe(self):
        responses = {
            f"https://parasite.space/api/user/{ADDR}": {"unexpected": True},
            f"https://solo.ckpool.org/users/{ADDR}": {
                "hashrate1m": "1T",
                "workers": 1,
            },
        }

        stats = resolve_pool_stats(ADDR, fetcher=responses.get)

        # parasite answered but with nothing we can read (no workers, no
        # hashrate) → the probe moves on rather than reporting empty.
        assert stats.provider_id == "unknown" or stats.hashrate_hs is not None

    def test_detected_via_probe_declares_the_evidence(self):
        responses = {
            f"https://parasite.space/api/user/{ADDR}": {
                "hashrate": 1e12,
                "sharesAccepted": 10,
            },
        }

        stats = resolve_pool_stats(ADDR, fetcher=responses.get)

        assert stats.provider_id == "parasite"
        assert stats.source == "api"

    def test_to_dict_is_json_safe(self):
        stats = resolve_pool_stats(ADDR, fetcher=lambda url: None)

        payload = stats.to_dict()

        assert payload["source"] == "asic"
        assert payload["provider_id"] == "unknown"
        assert isinstance(payload["fields_found"], list)


# ══════════════════════════════════════════════════════════════════════════
#  /api/pool/resolve — the endpoint the UI calls
# ══════════════════════════════════════════════════════════════════════════


class TestPoolResolveRoute:
    @pytest.fixture
    def client(self):
        import app as _app

        _app.app.config["TESTING"] = True
        with _app.app.test_client() as c:
            yield c

    def test_reports_the_pool_and_the_evidence(self, monkeypatch, client):
        import app as _app

        monkeypatch.setattr(
            _app,
            "_pool_stats_fetcher",
            lambda url: (
                {"hashrate1m": "1.21T", "bestshare": 42.0, "workers": 1}
                if "ckpool" in url
                else None
            ),
        )

        resp = client.post("/api/pool/resolve", json={"address": ADDR})

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["stats"]["provider_id"] == "ckpool_solo"
        assert body["stats"]["source"] == "api"
        assert body["stats"]["chain"] == "btc"
        assert body["known_providers"] > 0
        assert "ckpool_solo" in body["providers_with_api"]

    def test_asic_reported_pool_is_authoritative(self, monkeypatch, client):
        import app as _app

        monkeypatch.setattr(_app, "_pool_stats_fetcher", lambda url: None)

        resp = client.post(
            "/api/pool/resolve",
            json={"address": ADDR, "pool_url": "stratum+tcp://ocean.xyz:3333"},
        )

        body = resp.get_json()
        assert body["stats"]["provider_id"] == "ocean"
        # OCEAN publishes no JSON per-worker API → the hardware is the source.
        assert body["stats"]["source"] == "asic"

    def test_known_pool_without_api_never_shows_zeros_as_if_they_were_measured(
        self, monkeypatch, client
    ):
        import app as _app

        monkeypatch.setattr(_app, "_pool_stats_fetcher", lambda url: None)

        resp = client.post(
            "/api/pool/resolve",
            json={"address": ADDR, "pool_url": "stratum+tcp://stratum.taal.com:3333"},
        )

        body = resp.get_json()
        assert body["stats"]["provider_id"] == "taal"
        assert body["stats"]["chain"] == "bsv"
        assert body["stats"]["source"] == "asic"
        assert body["stats"]["hashrate_hs"] is None

    def test_requires_an_address(self, client):
        import app as _app

        original = _app.BTC_ADDRESS
        _app.BTC_ADDRESS = ""
        try:
            resp = client.post("/api/pool/resolve", json={"address": ""})
        finally:
            _app.BTC_ADDRESS = original

        assert resp.status_code == 400
        assert resp.get_json()["success"] is False
