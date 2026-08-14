"""
CYPHER65 // Portfolio 21-A — consolidated P/L (Issue #144)
===========================================================
Tests for compute_own_mining_ev + compute_global_portfolio (pure EV math +
consolidation) and the app-side _own_hashrate_for_portfolio dedup rule
(fleet física vs worker do pool — never sum) + the /api/rentals block.
"""

import pytest

import services.rental_performance as rp

NET = 100e18  # 100 EH/s em H/s (mesmo pin do test_compute_expected_yield)
OWN = 100e12  # 100 TH/s em H/s → share 1e-6 → 45000 sats/dia → 1.35M/30d


# ═════════════════════════════════════════════════════════════════════════
#  compute_own_mining_ev — EV puro
# ═════════════════════════════════════════════════════════════════════════


class TestOwnMiningEv:
    def test_ev_formula_pinned(self):
        ev = rp.compute_own_mining_ev(OWN, NET, days=30)
        assert ev["hashrate_th"] == pytest.approx(100.0)
        # share 1e-6 × 144 blocks × 3.125 BTC × 1e8 sats = 45000 sats/dia
        assert ev["daily_revenue_sats"] == 45000
        assert ev["month_revenue_sats"] == 45000 * 30
        assert ev["estimate"] is True

    def test_ev_scales_with_hashrate(self):
        assert rp.compute_own_mining_ev(2 * OWN, NET)["daily_revenue_sats"] == 90000
        # network double → EV half
        assert rp.compute_own_mining_ev(OWN, 2 * NET)["daily_revenue_sats"] == 22500

    def test_ev_null_safe(self):
        empty = rp.compute_own_mining_ev(None, NET)
        assert empty["daily_revenue_sats"] is None
        assert empty["month_revenue_sats"] is None
        assert empty["estimate"] is False
        assert empty["hashrate_hs"] is None
        assert rp.compute_own_mining_ev(OWN, None)["estimate"] is False
        assert rp.compute_own_mining_ev(0, NET)["estimate"] is False
        assert rp.compute_own_mining_ev("garbage", NET)["estimate"] is False


# ═════════════════════════════════════════════════════════════════════════
#  compute_global_portfolio — consolidação
# ═════════════════════════════════════════════════════════════════════════


class TestGlobalPortfolio:
    def test_combined_net_math(self):
        gp = rp.compute_global_portfolio(
            own_hashrate_hs=OWN,
            network_hashrate_hs=NET,
            rentals_pl_30d_sats=4000.0,
            rentals_30d_count=4,
            rentals_pl_all_sats=-12000.0,
            rentals_spent_sats=200000.0,
            rentals_count=40,
        )
        assert gp["own"]["month_revenue_sats"] == 45000 * 30
        assert gp["rentals"]["pl_30d_sats"] == 4000.0
        assert gp["rentals"]["count_30d"] == 4
        assert gp["rentals"]["pl_all_sats"] == -12000.0
        comb = gp["combined"]
        assert comb["pl_30d_sats"] == 45000 * 30 + 4000
        assert comb["own_ev_30d_sats"] == 45000 * 30
        assert comb["rentals_pl_30d_sats"] == 4000.0
        assert comb["estimate"] is True

    def test_combined_none_when_rentals_unknown(self):
        # rentals P/L desconhecido → combined None (nunca um 0 falso que lê
        # como "sem prejuízo").
        gp = rp.compute_global_portfolio(
            own_hashrate_hs=OWN, network_hashrate_hs=NET, rentals_pl_30d_sats=None
        )
        assert gp["combined"] is None
        # sem hashrate próprio → combined None
        gp2 = rp.compute_global_portfolio(
            own_hashrate_hs=None, network_hashrate_hs=NET, rentals_pl_30d_sats=500.0
        )
        assert gp2["combined"] is None

    def test_own_detail_merged(self):
        gp = rp.compute_global_portfolio(
            own_hashrate_hs=OWN,
            network_hashrate_hs=NET,
            rentals_pl_30d_sats=0.0,
            own_detail={"source": "fleet", "fleet_n": 3, "worker_hs": 50e12},
        )
        assert gp["own"]["source"] == "fleet"
        assert gp["own"]["fleet_n"] == 3
        assert gp["own"]["worker_hs"] == 50e12


# ═════════════════════════════════════════════════════════════════════════
#  _own_hashrate_for_portfolio — dedup fleet vs worker
# ═════════════════════════════════════════════════════════════════════════


class TestOwnHashrateDedup:
    @pytest.fixture
    def appmod(self):
        import app as app_module

        return app_module

    def test_fleet_preferred_when_larger(self, appmod, monkeypatch):
        # tenant default → worker leg ativo (self-hosted) + frota maior
        monkeypatch.setattr(
            appmod,
            "latest_snapshot",
            {"worker": {"hashrate": 50e12}, "network": {"hashrate": NET}},
        )

        class _FakeRegistry:
            def list_devices(self, tenant_id="", with_telemetry=False):
                return [
                    {"id": "a", "hashrate_hs": 80e12},
                    {"id": "b", "hashrate_hs": 20e12},
                    {"id": "c", "hashrate_hs": 0},  # idle — ignorado
                ]

        import axe_fleet.routes as _axe_routes

        monkeypatch.setattr(_axe_routes, "_registry", _FakeRegistry())
        out = appmod._own_hashrate_for_portfolio("default")
        assert out["hashrate_hs"] == 100e12  # max(fleet 100T, worker 50T)
        assert out["source"] == "fleet"
        assert out["fleet_n"] == 2
        assert out["worker_hs"] == 50e12

    def test_worker_fallback_when_no_fleet(self, appmod, monkeypatch):
        monkeypatch.setattr(
            appmod,
            "latest_snapshot",
            {"worker": {"hashrate": 42e12}, "network": {"hashrate": NET}},
        )

        class _FakeRegistry:
            def list_devices(self, tenant_id="", with_telemetry=False):
                return []

        import axe_fleet.routes as _axe_routes

        monkeypatch.setattr(_axe_routes, "_registry", _FakeRegistry())
        out = appmod._own_hashrate_for_portfolio("default")
        assert out["hashrate_hs"] == 42e12
        assert out["source"] == "worker"

    def test_none_when_no_sources(self, appmod, monkeypatch):
        monkeypatch.setattr(appmod, "latest_snapshot", {"worker": {}, "network": {}})

        class _FakeRegistry:
            def list_devices(self, tenant_id="", with_telemetry=False):
                return []

        import axe_fleet.routes as _axe_routes

        monkeypatch.setattr(_axe_routes, "_registry", _FakeRegistry())
        out = appmod._own_hashrate_for_portfolio("default")
        assert out["hashrate_hs"] == 0
        assert out["source"] == "none"

    def test_non_default_tenant_ignores_global_worker(self, appmod, monkeypatch):
        """Multi-tenant isolation: o worker do latest_snapshot é GLOBAL — um
        tenant não-default NÃO herda o hashrate do operador (fix HIGH do
        review). A frota (tenant-scoped) continua sendo a única fonte."""
        monkeypatch.setattr(
            appmod,
            "latest_snapshot",
            {"worker": {"hashrate": 500e12}, "network": {"hashrate": NET}},
        )

        class _FakeRegistry:
            def list_devices(self, tenant_id="", with_telemetry=False):
                return [
                    {"id": "a", "hashrate_hs": 80e12},
                    {"id": "b", "hashrate_hs": 20e12},
                ]

        import axe_fleet.routes as _axe_routes

        monkeypatch.setattr(_axe_routes, "_registry", _FakeRegistry())
        out = appmod._own_hashrate_for_portfolio("tenant-b")
        # Worker global ignorado (worker_hs None) — own vem só da frota.
        assert out["hashrate_hs"] == 100e12
        assert out["source"] == "fleet"
        assert out["worker_hs"] is None

    def test_max_source_when_worker_beats_fleet(self, appmod, monkeypatch):
        """Tenant default: frota existe mas o worker reporta mais → max() com
        source='max' (nunca soma, honesto sobre qual número venceu)."""
        monkeypatch.setattr(
            appmod,
            "latest_snapshot",
            {"worker": {"hashrate": 500e12}, "network": {"hashrate": NET}},
        )

        class _FakeRegistry:
            def list_devices(self, tenant_id="", with_telemetry=False):
                return [{"id": "a", "hashrate_hs": 80e12}]

        import axe_fleet.routes as _axe_routes

        monkeypatch.setattr(_axe_routes, "_registry", _FakeRegistry())
        out = appmod._own_hashrate_for_portfolio("default")
        assert out["hashrate_hs"] == 500e12
        assert out["source"] == "max"
        assert out["fleet_total_hs"] == 80e12
        assert out["worker_hs"] == 500e12


# ═════════════════════════════════════════════════════════════════════════
#  /api/rentals — bloco global_portfolio
# ═════════════════════════════════════════════════════════════════════════


class TestRentalsRouteGlobalPortfolio:
    @pytest.fixture
    def rclient(self):
        import app as app_module

        app_module.app.config["TESTING"] = True
        app_module._RENTALS_CACHE.clear()
        with app_module.app.test_client() as c:
            yield c
            app_module._RENTALS_CACHE.clear()

    def test_route_carries_global_portfolio(self, rclient, monkeypatch):
        import app as app_module

        monkeypatch.setattr(
            app_module._rental_perf,
            "fetch_mrr_rentals",
            lambda rtype="renter", history=False, limit=50, tenant_id="": {
                "success": True,
                "needs_auth": False,
                "rentals": [],
                "total": 0,
            },
        )
        monkeypatch.setattr(
            app_module._rental_perf,
            "fetch_braiins_contracts",
            lambda tenant_id="": {
                "success": True,
                "needs_auth": False,
                "contracts": [],
            },
        )
        monkeypatch.setattr(
            app_module._rental_perf, "get_rig_blacklist", lambda tenant_id="": []
        )
        monkeypatch.setattr(
            app_module._rental_perf, "ingest_rentals", lambda *a, **k: True
        )
        # Registry sem frota → own vem do worker (determinístico, sem depender
        # de devices deixados por outros testes no DB de scratch).
        import axe_fleet.routes as _axe_routes

        class _EmptyRegistry:
            def list_devices(self, tenant_id="", with_telemetry=False):
                return []

        monkeypatch.setattr(_axe_routes, "_registry", _EmptyRegistry())
        # Série determinística: 4 semanas de +1000 sats de P/L → 30d = +4000.
        monkeypatch.setattr(
            app_module._rental_perf,
            "compute_portfolio_series",
            lambda tenant_id="", bucket="week": {
                "bucket": "week",
                "estimate": True,
                "points": [
                    {
                        "label": f"W{i}",
                        "pl_sats": 1000.0,
                        "rentals": 1,
                        "spent_sats": 5000.0,
                        "delivered_thh": 100.0,
                    }
                    for i in range(4)
                ],
                "totals": {"spent_sats": 20000, "pl_sats": 4000, "rentals": 4},
            },
        )
        # Own: worker 100 TH/s + rede 100 EH/s → EV 45000 sats/dia.
        monkeypatch.setattr(
            app_module,
            "latest_snapshot",
            {"worker": {"hashrate": OWN}, "network": {"hashrate": NET}},
        )

        resp = rclient.get("/api/rentals")
        assert resp.status_code == 200
        data = resp.get_json()
        gp = data.get("global_portfolio") or {}
        assert gp["own"]["hashrate_th"] == pytest.approx(100.0)
        assert gp["own"]["daily_revenue_sats"] == 45000
        assert gp["rentals"]["pl_30d_sats"] == 4000.0
        assert gp["rentals"]["count_30d"] == 4
        assert gp["combined"]["pl_30d_sats"] == 45000 * 30 + 4000
        assert gp["own"]["source"] == "worker"
