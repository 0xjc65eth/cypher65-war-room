"""
CYPHER65 // Pool detected from the hardware's own report (Issue #574)
=====================================================================
The ASIC already tells us which pool it is on: every device reports its own
``stratumURL``/``stratumUser``, and the agent/fleet poll writes that into
``axe_telemetry.payload.pool_url``. Nothing read it back — so the snapshot only
ever showed parasite.space figures, and every other pool rendered empty unless
someone called ``/api/pool/resolve`` by hand.

These tests pin the glue in ``services.pool_detection`` and its wiring into
``_build_snapshot``:

- the report is read from real SQL, tenant-scoped (one tenant can never see
  another's miner), from the NEWEST row that actually carries a pool URL;
- malformed/absent data degrades to ``{}`` instead of raising;
- with no ASIC report there is NO network request at all — probing the public
  pool APIs stays an explicit, on-demand path;
- a pool WITH a public API is read from the API (``source: "api"``); a pool
  WITHOUT one falls back to the ASIC's own numbers (``source: "asic"``) rather
  than rendering empty;
- both caches honour their TTL, and a failure is never cached, so the next poll
  retries.
"""

import json
import os
import sqlite3
import tempfile

import pytest

import services.pool_detection as pd

ADDR = "bc1qexampleaddress000000000000000000000"
TENANT = "tenant-a"

_TEMP_FILES: list[str] = []


@pytest.fixture(autouse=True)
def _clear_caches():
    """Both caches are process-wide; a leak between tests would hide the TTL
    assertions (a cached {} would look like a working code path)."""
    pd.clear_cache()
    yield
    pd.clear_cache()
    while _TEMP_FILES:
        try:
            os.unlink(_TEMP_FILES.pop())
        except OSError:  # pragma: no cover — best-effort cleanup
            pass


def _db(payloads):
    """A real ``axe_telemetry`` table that hands out a NEW connection per call.

    ``payloads`` is a list of ``(ts, device_id, tenant_id, payload_or_raw)``.
    Using real SQL keeps the test honest about the query, the ordering and the
    tenant filter instead of asserting against a stub that agrees with the code.

    The connection-per-call shape is not incidental: ``_read_latest_report``
    closes what it opens, exactly like the rest of the repo closes its
    ``get_db()`` connection. A helper that recycled one connection would make
    the SECOND read (i.e. every read after the report TTL expires) fail with
    "Cannot operate on a closed database" — a test artifact that would look
    like a code bug. That is why this is a file, not ``:memory:``.
    """
    handle, path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    _TEMP_FILES.append(path)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE axe_telemetry ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, device_id TEXT, "
        "payload TEXT, tenant_id TEXT)"
    )
    for ts, device_id, tenant_id, payload in payloads:
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        conn.execute(
            "INSERT INTO axe_telemetry (ts, device_id, payload, tenant_id) "
            "VALUES (?, ?, ?, ?)",
            (ts, device_id, raw, tenant_id),
        )
    conn.commit()
    conn.close()

    def connect():
        fresh = sqlite3.connect(path)
        fresh.row_factory = sqlite3.Row
        return fresh

    return connect


def _telemetry(pool_url, **overrides):
    payload = {
        "hashrate_hs": 912345678901,
        "best_diff": "8.2T",
        "shares_accepted": 1450,
        "shares_rejected": 7,
        "pool_url": pool_url,
        "pool_user": "bc1qexample.w1",
        "model": "Gamma 900",
    }
    payload.update(overrides)
    return payload


# ══════════════════════════════════════════════════════════════════════════
#  asic_pool_report — reading what the hardware reported
# ══════════════════════════════════════════════════════════════════════════


class TestAsicPoolReport:
    def test_reads_the_newest_report_with_a_pool_url(self):
        get_db = _db(
            [
                (100, "dev-old", TENANT, _telemetry("stratum+tcp://ocean.xyz:3333")),
                (200, "dev-new", TENANT, _telemetry("stratum+tcp://solo.ckpool.org:3333")),
            ]
        )

        report = pd.asic_pool_report(TENANT, get_db=get_db)

        assert report["pool_url"] == "stratum+tcp://solo.ckpool.org:3333"
        assert report["pool_user"] == "bc1qexample.w1"
        assert report["device_id"] == "dev-new"
        # The whole payload travels along: it is the data source for a pool
        # with no public API.
        assert report["telemetry"]["best_diff"] == "8.2T"

    def test_skips_rows_without_a_pool_url(self):
        """A device that reported only a heartbeat must not shadow an older
        row that actually knew the pool."""
        get_db = _db(
            [
                (100, "dev-1", TENANT, _telemetry("stratum+tcp://ocean.xyz:3333")),
                (200, "dev-2", TENANT, {"hashrate_hs": 0, "pool_url": ""}),
            ]
        )

        report = pd.asic_pool_report(TENANT, get_db=get_db)

        assert report["pool_url"] == "stratum+tcp://ocean.xyz:3333"
        assert report["device_id"] == "dev-1"

    def test_is_tenant_scoped(self):
        get_db = _db(
            [
                (100, "dev-1", "tenant-b", _telemetry("stratum+tcp://ocean.xyz:3333")),
                (200, "dev-2", TENANT, _telemetry("stratum+tcp://stratum.taal.com:3333")),
            ]
        )

        report = pd.asic_pool_report(TENANT, get_db=get_db)

        assert report["pool_url"] == "stratum+tcp://stratum.taal.com:3333"

    def test_a_tenant_without_devices_gets_nothing(self):
        get_db = _db(
            [(100, "dev-1", "tenant-b", _telemetry("stratum+tcp://ocean.xyz:3333"))]
        )

        assert pd.asic_pool_report(TENANT, get_db=get_db) == {}

    def test_malformed_payload_is_skipped_not_crashed(self):
        get_db = _db(
            [
                (100, "dev-bad", TENANT, "{not json"),
                (50, "dev-ok", TENANT, _telemetry("stratum+tcp://ocean.xyz:3333")),
            ]
        )

        report = pd.asic_pool_report(TENANT, get_db=get_db)

        assert report["pool_url"] == "stratum+tcp://ocean.xyz:3333"

    def test_a_missing_table_is_a_normal_state(self):
        """Self-hosted deploys and unit tests have no fleet tables at all."""
        conn = sqlite3.connect(":memory:")

        assert pd.asic_pool_report(TENANT, get_db=lambda: conn) == {}

    def test_a_broken_db_never_raises(self):
        def explode():
            raise RuntimeError("database is locked")

        assert pd.asic_pool_report(TENANT, get_db=explode) == {}

    def test_report_is_cached_until_the_ttl_expires(self):
        calls = {"n": 0}
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE axe_telemetry (id INTEGER PRIMARY KEY, ts INTEGER, "
            "device_id TEXT, payload TEXT, tenant_id TEXT)"
        )
        conn.execute(
            "INSERT INTO axe_telemetry (ts, device_id, payload, tenant_id) "
            "VALUES (1, 'd', ?, ?)",
            (json.dumps(_telemetry("stratum+tcp://ocean.xyz:3333")), TENANT),
        )
        conn.commit()

        def counting_get_db():
            calls["n"] += 1
            return conn

        pd.asic_pool_report(TENANT, get_db=counting_get_db, now=1000.0)
        pd.asic_pool_report(TENANT, get_db=counting_get_db, now=1030.0)

        assert calls["n"] == 1  # still inside REPORT_TTL

        pd.asic_pool_report(TENANT, get_db=counting_get_db, now=2000.0)

        assert calls["n"] == 2  # TTL expired → re-read

    def test_tenant_id_defaults_to_the_default_scope(self):
        get_db = _db([(1, "d", "default", _telemetry("stratum+tcp://ocean.xyz:3333"))])

        assert pd.asic_pool_report("", get_db=get_db)["pool_url"].endswith(":3333")
        assert pd.asic_pool_report("   ", get_db=get_db)["pool_url"].endswith(":3333")


# ══════════════════════════════════════════════════════════════════════════
#  detected_pool_for — evidence order and the honest data source
# ══════════════════════════════════════════════════════════════════════════


class TestDetectedPoolFor:
    def test_no_asic_report_means_no_network_at_all(self):
        """Probing the registry's public APIs is an explicit, on-demand path —
        a 15s background poll must not fan out to a dozen pool APIs."""

        def fetcher(url):  # pragma: no cover — must not be called
            raise AssertionError("no request may be issued without an ASIC report")

        result = pd.detected_pool_for(
            ADDR, TENANT, get_db=_db([]), fetcher=fetcher
        )

        assert result == {}

    def test_pool_with_public_api_is_read_from_the_api(self):
        urls = []

        def fetcher(url):
            urls.append(url)
            return {"hashrate1m": "1.21T", "bestshare": 42.0, "workers": 1}

        get_db = _db(
            [(1, "d", TENANT, _telemetry("stratum+tcp://solo.ckpool.org:3333"))]
        )

        result = pd.detected_pool_for(ADDR, TENANT, get_db=get_db, fetcher=fetcher)

        assert result["detection"]["provider_id"] == "ckpool_solo"
        assert result["detection"]["chain"] == "btc"
        assert result["stats"]["source"] == "api"
        assert result["stats"]["hashrate_hs"] == pytest.approx(1.21e12)
        assert urls == [f"https://solo.ckpool.org/users/{ADDR}"]

    def test_pool_without_api_falls_back_to_the_asic_numbers(self):
        """OCEAN publishes no JSON per-worker API. The miner's own telemetry is
        real data — strictly better than the empty panel this used to render."""

        def fetcher(url):  # pragma: no cover — OCEAN has no API to call
            raise AssertionError("no API should be requested for OCEAN")

        get_db = _db([(1, "d", TENANT, _telemetry("stratum+tcp://ocean.xyz:3333"))])

        result = pd.detected_pool_for(ADDR, TENANT, get_db=get_db, fetcher=fetcher)

        assert result["detection"]["provider_id"] == "ocean"
        assert result["stats"]["source"] == "asic"
        assert result["stats"]["hashrate_hs"] == pytest.approx(912345678901)
        assert result["stats"]["best_diff_str"] == "8.2T"
        assert result["stats"]["shares_accepted"] == 1450

    def test_bsv_pool_is_tagged_with_the_right_chain(self):
        get_db = _db(
            [(1, "d", TENANT, _telemetry("stratum+tcp://solo.bsv.ckpool.org:3333"))]
        )

        result = pd.detected_pool_for(ADDR, TENANT, get_db=get_db, fetcher=lambda u: None)

        assert result["detection"]["provider_id"] == "ckpool_bsv_solo"
        assert result["detection"]["chain"] == "bsv"

    def test_unregistered_pool_keeps_its_host_and_does_not_invent_a_provider(self):
        get_db = _db([(1, "d", TENANT, _telemetry("stratum+tcp://minha.pool.local:3333"))])

        result = pd.detected_pool_for(ADDR, TENANT, get_db=get_db, fetcher=lambda u: None)

        assert result["detection"]["provider_id"] == "unknown"
        assert result["detection"]["label"] == "minha.pool.local"
        assert result["stats"]["source"] == "asic"

    def test_asics_pool_user_is_surfaced(self):
        get_db = _db(
            [
                (
                    1,
                    "d",
                    TENANT,
                    _telemetry(
                        "stratum+tcp://ocean.xyz:3333", pool_user="bc1qworker.rig7"
                    ),
                )
            ]
        )

        result = pd.detected_pool_for(ADDR, TENANT, get_db=get_db, fetcher=lambda u: None)

        assert result["asic_pool_user"] == "bc1qworker.rig7"

    def test_a_dying_pool_api_never_raises_and_still_reports_the_asic(self):
        def fetcher(url):
            raise ConnectionError("pool api down")

        get_db = _db(
            [(1, "d", TENANT, _telemetry("stratum+tcp://solo.ckpool.org:3333"))]
        )

        result = pd.detected_pool_for(ADDR, TENANT, get_db=get_db, fetcher=fetcher)

        assert result["stats"]["source"] == "asic"
        assert result["stats"]["hashrate_hs"] == pytest.approx(912345678901)

    def test_stats_are_cached_until_the_ttl_expires(self):
        calls = {"n": 0}

        def fetcher(url):
            calls["n"] += 1
            return {"hashrate1m": "1T", "workers": 1}

        get_db = _db(
            [(1, "d", TENANT, _telemetry("stratum+tcp://solo.ckpool.org:3333"))]
        )

        first = pd.detected_pool_for(ADDR, TENANT, get_db=get_db, fetcher=fetcher, now=1000.0)
        second = pd.detected_pool_for(ADDR, TENANT, get_db=get_db, fetcher=fetcher, now=1030.0)
        third = pd.detected_pool_for(ADDR, TENANT, get_db=get_db, fetcher=fetcher, now=2000.0)

        assert calls["n"] == 2
        assert first["stats"]["source"] == second["stats"]["source"] == "api"
        assert third["stats"]["source"] == "api"

    def test_a_failed_resolution_is_not_cached(self):
        """Caching a failure would freeze the panel until the process restarts."""
        attempts = {"n": 0}

        def flaky_fetcher(url):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ConnectionError("pool api down")
            return {"hashrate1m": "1T", "workers": 1}

        get_db = _db(
            [(1, "d", TENANT, _telemetry("stratum+tcp://solo.ckpool.org:3333"))]
        )

        first = pd.detected_pool_for(
            ADDR, TENANT, get_db=get_db, fetcher=flaky_fetcher, now=1000.0
        )
        second = pd.detected_pool_for(
            ADDR, TENANT, get_db=get_db, fetcher=flaky_fetcher, now=1001.0
        )

        assert first["stats"]["source"] == "asic"
        assert second["stats"]["source"] == "api"
        assert attempts["n"] == 2

    def test_clear_cache_forces_a_fresh_read(self):
        get_db = _db(
            [(1, "d", TENANT, _telemetry("stratum+tcp://ocean.xyz:3333"))]
        )

        assert pd.detected_pool_for(ADDR, TENANT, get_db=get_db, fetcher=lambda u: None)
        pd.clear_cache()
        conn2 = sqlite3.connect(":memory:")
        conn2.row_factory = sqlite3.Row

        assert pd.detected_pool_for(ADDR, TENANT, get_db=lambda: conn2) == {}


# ══════════════════════════════════════════════════════════════════════════
#  Wiring into _build_snapshot
# ══════════════════════════════════════════════════════════════════════════


class TestSnapshotWiring:
    def _patch_fetchers(self, monkeypatch, sa):
        monkeypatch.setattr(sa, "_fetch_user_data", lambda address: {"workerData": []})
        monkeypatch.setattr(sa, "_fetch_account", lambda address: None)
        monkeypatch.setattr(sa, "_fetch_global_pool", lambda: {})
        monkeypatch.setattr(sa, "_fetch_global_leaderboard", lambda limit=100: [])
        monkeypatch.setattr(
            sa, "_fetch_global_highest_diffs", lambda address, limit=20: []
        )
        monkeypatch.setattr(sa, "_fetch_global_network", lambda: (1, 1.0, 1.0))
        monkeypatch.setattr(sa, "_fetch_global_btc_price", lambda: {})
        monkeypatch.setattr(sa, "_fetch_global_mempool_fees", lambda: {})

    def test_schema_carries_both_keys_even_without_detection(self, monkeypatch):
        """Absent must never be ambiguous with not-applicable for the front."""
        import services.snapshot_assembly as sa

        self._patch_fetchers(monkeypatch, sa)
        monkeypatch.setattr(pd, "detected_pool_for", lambda a, t="", **kw: {})

        snap = sa._build_snapshot(ADDR, "w1", TENANT)

        assert "pool_detection" in snap
        assert "pool_worker" in snap
        assert snap["pool_detection"] is None
        assert snap["pool_worker"] is None

    def test_detection_is_written_into_the_snapshot(self, monkeypatch):
        import services.snapshot_assembly as sa

        self._patch_fetchers(monkeypatch, sa)
        seen = {}

        def fake_detect(address, tenant_id="", **kw):
            seen["address"] = address
            seen["tenant"] = tenant_id
            return {
                "detection": {"provider_id": "ocean", "chain": "btc"},
                "stats": {"source": "asic", "hashrate_hs": 5e11, "provider_id": "ocean"},
            }

        monkeypatch.setattr(pd, "detected_pool_for", fake_detect)

        snap = sa._build_snapshot(ADDR, "w1", TENANT)

        assert snap["pool_detection"]["provider_id"] == "ocean"
        assert snap["pool_worker"]["source"] == "asic"
        # The tenant must reach the detection boundary, or telemetry would be
        # read from the wrong scope.
        assert seen == {"address": ADDR, "tenant": TENANT}

    def test_tenant_defaults_to_empty_for_legacy_callers(self, monkeypatch):
        import services.snapshot_assembly as sa

        self._patch_fetchers(monkeypatch, sa)
        seen = {}
        monkeypatch.setattr(
            pd,
            "detected_pool_for",
            lambda address, tenant_id="", **kw: seen.setdefault("tenant", tenant_id) or {},
        )

        sa._build_snapshot(ADDR, "w1")

        assert seen["tenant"] == ""

    def test_a_raising_detection_never_breaks_the_snapshot(self, monkeypatch):
        import services.snapshot_assembly as sa

        self._patch_fetchers(monkeypatch, sa)

        def explode(address, tenant_id="", **kw):
            raise RuntimeError("detection exploded")

        monkeypatch.setattr(pd, "detected_pool_for", explode)

        snap = sa._build_snapshot(ADDR, "w1", TENANT)

        # The snapshot is still complete; only the enrichment is missing.
        assert snap["btc_address"] == ADDR
        assert snap["pool_detection"] is None
        assert snap["pool_worker"] is None


# ══════════════════════════════════════════════════════════════════════════
#  attach_to_snapshot — o ÚNICO escritor das duas chaves (Issue #576)
# ══════════════════════════════════════════════════════════════════════════
#
# O #574 escreveu as chaves dentro do `_build_snapshot` (caminho de SESSÃO) e
# ninguém notou que o painel polla `/api/snapshot`, servido pelo dict do poll
# GLOBAL. Todo teste passava (o e2e injetava as chaves no fixture) e a faixa
# nunca aparecia em produção. Estas asserções são sobre o contrato do helper
# que os DOIS produtores usam.


class TestAttachToSnapshot:
    def test_writes_both_keys_and_reports_what_was_detected(self, monkeypatch):
        monkeypatch.setattr(
            pd,
            "detected_pool_for",
            lambda a, t="", **kw: {
                "detection": {"provider_id": "ocean"},
                "stats": {"source": "asic"},
            },
        )
        snap = {}

        pd.attach_to_snapshot(snap, ADDR, TENANT)

        assert snap["pool_detection"] == {"provider_id": "ocean"}
        assert snap["pool_worker"] == {"source": "asic"}

    def test_always_leaves_both_keys_present(self, monkeypatch):
        """`None` is a fact (nothing reported); a missing key is a bug."""
        monkeypatch.setattr(pd, "detected_pool_for", lambda a, t="", **kw: {})

        for snap in ({}, {"ts": 1}):
            pd.attach_to_snapshot(snap, ADDR, TENANT)
            assert "pool_detection" in snap and snap["pool_detection"] is None
            assert "pool_worker" in snap and snap["pool_worker"] is None

    def test_keeps_the_existing_keys_when_nothing_is_detected(self, monkeypatch):
        """A poll with no report must not wipe what a previous one found."""
        monkeypatch.setattr(pd, "detected_pool_for", lambda a, t="", **kw: {})
        snap = {"pool_detection": {"provider_id": "ocean"}, "pool_worker": {"source": "api"}}

        pd.attach_to_snapshot(snap, ADDR, TENANT)

        assert snap["pool_detection"] == {"provider_id": "ocean"}
        assert snap["pool_worker"] == {"source": "api"}

    def test_a_raising_detection_never_raises(self, monkeypatch):
        def explode(a, t="", **kw):
            raise RuntimeError("detection exploded")

        monkeypatch.setattr(pd, "detected_pool_for", explode)
        snap = {"ts": 1}

        pd.attach_to_snapshot(snap, ADDR, TENANT)

        assert snap["pool_detection"] is None
        assert snap["pool_worker"] is None

    def test_empty_detection_dicts_normalize_to_none(self, monkeypatch):
        """`{}` from the resolver must not reach the front as an empty object."""
        monkeypatch.setattr(
            pd,
            "detected_pool_for",
            lambda a, t="", **kw: {"detection": {}, "stats": {}},
        )
        snap = {}

        pd.attach_to_snapshot(snap, ADDR, TENANT)

        assert snap["pool_detection"] is None
        assert snap["pool_worker"] is None

    def test_one_writer_for_both_producers(self):
        """`_build_snapshot` e `_do_poll` têm de chamar O MESMO helper.

        Guard de fonte: o defeito do #576 foi exatamente uma segunda
        implementação de "põe as duas chaves" num produtor só. Se alguém
        voltar a escrever `snapshot["pool_detection"] = ...` fora do helper, o
        acesso tem de ser exclusivo do módulo de detecção.
        """
        import inspect

        import app as app_module
        import services.snapshot_assembly as sa

        assert "attach_to_snapshot" in inspect.getsource(sa._build_snapshot)
        assert "attach_to_snapshot" in inspect.getsource(app_module._do_poll)
        # Nenhum dos dois escreve a chave por conta própria.
        for src in (inspect.getsource(sa._build_snapshot), inspect.getsource(app_module._do_poll)):
            assert '["pool_detection"] =' not in src.replace("'", '"')
