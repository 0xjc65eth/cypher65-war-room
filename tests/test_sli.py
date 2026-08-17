"""
Tests for Issue #204/#206 — data-completeness SLIs + honest dropped-sample
counter.

Coverage:
  - SLITracker unit: compute_rentals_completude (expected vs received),
    market freshness, 30-min breach alert (once per episode), recovery,
    window age-out, unknown-when-no-data.
  - Route: /api/snapshot exposes health.sli (both SLIs + targets + breach).
  - Route: /api/automation/dry-run/replay reports dropped_ts_samples instead
    of silently dropping ts=0 samples (Issue #204).
"""

import time

import pytest

from app import app
from services.sli import SLITracker, sli as _shared_sli


def _bad_completude():
    """90% de completude — abaixo do target de 99%."""
    return {"rentals": [{}] * 90, "rendered": 90, "total": 100}


def _good_completude():
    return {"rentals": [{}] * 100, "rendered": 100, "total": 100}


@pytest.fixture(autouse=True)
def _reset_shared_sli():
    """Rota tests usam o singleton do app — resetar entre testes."""
    for kind in _shared_sli._samples:
        _shared_sli._samples[kind].clear()
    _shared_sli._bad_since.clear()
    _shared_sli._alerted.clear()
    _shared_sli._last_log = 0
    yield
    for kind in _shared_sli._samples:
        _shared_sli._samples[kind].clear()
    _shared_sli._bad_since.clear()
    _shared_sli._alerted.clear()


class TestRentalsCompletude:
    def test_full_coverage_is_100(self):
        assert SLITracker.compute_rentals_completude(_good_completude(), {}, {}) == 1.0

    def test_truncated_coverage_is_honest(self):
        assert (
            SLITracker.compute_rentals_completude(
                {"rentals": [1, 2, 3], "rendered": 3, "total": 5}, {}, {}
            )
            == 0.6
        )

    def test_rendered_fallback_to_len(self):
        """Sem `rendered` (payload antigo) cai no len(rentals) — nunca explode."""
        assert (
            SLITracker.compute_rentals_completude(
                {"rentals": [1, 2, 3], "total": 3}, {}, {}
            )
            == 1.0
        )

    def test_sums_across_three_buckets(self):
        assert (
            SLITracker.compute_rentals_completude(
                {"rentals": [1], "rendered": 1, "total": 2},
                {"rentals": [1, 2], "rendered": 2, "total": 2},
                {"rentals": [1], "rendered": 1, "total": 1},
            )
            == 4 / 5
        )

    def test_no_data_returns_none(self):
        assert SLITracker.compute_rentals_completude({}, {}, {}) is None
        assert (
            SLITracker.compute_rentals_completude({"error": "key rejected"}, {}, {})
            is None
        )

    def test_caps_at_100(self):
        assert (
            SLITracker.compute_rentals_completude(
                {"rentals": [1], "rendered": 10, "total": 5}, {}, {}
            )
            == 1.0
        )


class TestMarketFreshness:
    def test_fresh_stale_and_never_fetched(self):
        t = SLITracker()
        now = 50000
        t.record_market(now - 60, now=now)  # age < 5min → fresca
        t.record_market(now - 4000, now=now)  # age > 5min → stale
        t.record_market(None, now=now)  # nunca fetched → stale (nunca epoch-0)
        s = t.summary(now=now)
        assert s["frescura_market"]["value"] == round(1 / 3, 4)
        assert s["frescura_market"]["status"] == "below"
        assert s["frescura_market"]["samples"] == 3
        assert s["frescura_market"]["target"] == 0.98

    def test_all_fresh_is_ok(self):
        t = SLITracker()
        now = 50000
        for i in range(5):
            t.record_market(now - 60 + i, now=now)
        s = t.summary(now=now)
        assert s["frescura_market"]["value"] == 1.0
        assert s["frescura_market"]["status"] == "ok"


class TestBreachPolicy:
    def test_alert_fires_after_30min_below_once(self):
        t = SLITracker()
        sink_calls = []
        t.set_degradation_sink(
            lambda kind, metric, msg: sink_calls.append((kind, metric))
        )
        t.record_completude(_bad_completude(), {}, {}, now=1000)
        t.record_completude(_bad_completude(), {}, {}, now=1500)
        assert t._bad_since.get("completude_rentals") == 1000
        assert not sink_calls  # 500s de degradação — ainda não é breach
        t.record_completude(_bad_completude(), {}, {}, now=2800)  # 1800s
        assert len(sink_calls) == 1
        assert sink_calls[0][0] == "completude_rentals"
        s = t.summary(now=2800)
        assert s["breach"]["completude_rentals"] is True
        assert s["completude_rentals"]["status"] == "below"
        # sem re-disparo enquanto continua abaixo
        t.record_completude(_bad_completude(), {}, {}, now=3000)
        assert len(sink_calls) == 1

    def test_recovery_clears_breach_and_resets_countdown(self):
        t = SLITracker()
        sink_calls = []
        t.set_degradation_sink(
            lambda kind, metric, msg: sink_calls.append((kind, metric))
        )
        t.record_completude(_bad_completude(), {}, {}, now=1000)
        t.record_completude(_bad_completude(), {}, {}, now=2800)
        assert len(sink_calls) == 1
        # amostras boas até as ruins saírem da janela (30min)
        t.record_completude(_good_completude(), {}, {}, now=4000)
        t.record_completude(_good_completude(), {}, {}, now=5000)
        s = t.summary(now=5000)
        assert s["breach"]["completude_rentals"] is False
        assert s["completude_rentals"]["status"] == "ok"
        # novo ciclo de degradação pode disparar de novo
        t.record_completude(_bad_completude(), {}, {}, now=6000)
        t.record_completude(_bad_completude(), {}, {}, now=7900)
        assert len(sink_calls) == 2

    def test_window_ages_out_to_unknown(self):
        t = SLITracker()
        t.record_completude(_bad_completude(), {}, {}, now=1000)
        s = t.summary(now=1000 + 3600)  # 1h depois — amostra fora da janela
        assert s["completude_rentals"]["status"] == "unknown"
        assert s["completude_rentals"]["value"] is None
        assert s["breach"]["completude_rentals"] is False

    def test_no_data_never_breaches(self):
        t = SLITracker()
        t.record_completude({}, {}, {}, now=1000)  # sem total → sem amostra
        t.record_completude({}, {}, {}, now=3000)
        assert t._bad_since == {}
        assert not t.summary(now=3000)["breach"]["completude_rentals"]


class TestSnapshotHealthSli:
    @pytest.fixture
    def client(self):
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    @pytest.fixture
    def netless_market(self, monkeypatch):
        """Sem rede no teste: market_data vem do cache seedado (updated_at now)."""
        import services.snapshot_enrichment as se

        monkeypatch.setattr(se, "_fetch_all_offers", lambda network_hr: [])
        monkeypatch.setattr(se, "_get_hashrate_market_offers", lambda snap: None)
        now = int(time.time())
        monkeypatch.setattr(
            se._shared_state,
            "market_data_cache",
            {
                "offers": [{"price_per_th_day": 0.0001, "provider": "mrr"}],
                "best_price": None,
                "updated_at": now,
                "ts": now,
                "loading": False,
                "error": None,
            },
        )
        return now

    def test_snapshot_exposes_sli_health(self, client, netless_market):
        r = client.get("/api/snapshot")
        assert r.status_code == 200
        data = r.get_json()
        health = data.get("health") or {}
        sli_block = health.get("sli") or {}
        assert "completude_rentals" in sli_block
        assert "frescura_market" in sli_block
        assert sli_block["completude_rentals"]["target"] == 0.99
        assert sli_block["frescura_market"]["target"] == 0.98
        assert sli_block["window_s"] == 1800
        # cache seedado fresco → amostra de frescura ok
        assert sli_block["frescura_market"]["status"] in ("ok", "unknown")


class TestReplayDroppedTsCounter:
    class _FakeEngine:
        def __init__(self, *args, **kwargs):
            pass  # AutomationEngine(db_path, SafetyEngine()) — aceita os args

        def load_rules(self, tenant_id=""):
            return []

        def simulate_replay_window(self, rules, history, window_seconds=0):
            return {"simulated": True, "per_rule": [], "rule_count": len(rules)}

        def is_armed(self, tenant_id=""):
            return False

    class _FakeRegistry:
        def __init__(self, rows):
            self._rows = rows

        def list_devices(self, tenant_id="", **kw):
            return [{"id": "dev-1"}]

        def get_recent_telemetry(self, dev_id, limit=288, tenant_id=""):
            return self._rows

    @pytest.fixture
    def client(self):
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_replay_counts_dropped_ts_samples(self, client, monkeypatch):
        rows = [
            {"payload": {"ts": 0, "hashrate_hs": 1e12}},  # dropado (epoch/0)
            {"payload": {"ts": 100, "hashrate_hs": 2e12}},  # mantido
            {"payload": {"ts": None, "power_watts": 10}},  # dropado (ausente)
        ]
        monkeypatch.setattr("axe_fleet.routes._registry", self._FakeRegistry(rows))
        monkeypatch.setattr(
            "core.alerts.automation_engine.AutomationEngine", self._FakeEngine
        )
        monkeypatch.setattr(
            "services.snapshot_enrichment.get_auto_pilot_engine", lambda: None
        )
        r = client.get("/api/automation/dry-run/replay")
        assert r.status_code == 200
        data = r.get_json()
        assert data["dropped_ts_samples"] == 2

    def test_replay_zero_dropped_when_all_valid(self, client, monkeypatch):
        rows = [
            {"payload": {"ts": 100, "hashrate_hs": 1e12}},
            {"payload": {"ts": 200, "hashrate_hs": 2e12}},
        ]
        monkeypatch.setattr("axe_fleet.routes._registry", self._FakeRegistry(rows))
        monkeypatch.setattr(
            "core.alerts.automation_engine.AutomationEngine", self._FakeEngine
        )
        monkeypatch.setattr(
            "services.snapshot_enrichment.get_auto_pilot_engine", lambda: None
        )
        r = client.get("/api/automation/dry-run/replay")
        assert r.status_code == 200
        assert r.get_json()["dropped_ts_samples"] == 0
