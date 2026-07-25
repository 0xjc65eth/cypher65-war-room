"""
Unit tests for the Opportunity Engine (/api/opportunities).

Tests ID stability (same price → same ID across calls),
ID changes (different price → different ID), and edge cases
(no data, one platform available, both available).

Strategy: monkeypatch agents.solo_mining_advisor.execute_tool
so the endpoint receives controlled Braiins/MRR prices without
making real HTTP calls. Uses app.test_client() for Flask requests.
"""

import json
import pytest


# ── Module-level import ─────────────────────────────────────────────
# Import the Flask app so we can use its test_client.
import app as _app  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """Return a Flask test client."""
    _app.app.testing = True
    return _app.app.test_client()


def _mock_execute_tool(price_braiins=None, price_mrr=None):
    """Return a function that replaces `execute_tool` with controlled data.

    Parameters
    ----------
    price_braiins : float or None
        The price_btc_per_ph_day value for Braiins (None → no price)
    price_mrr : float or None
        The price_btc_per_ph_day value for MRR (None → no price)
    """
    def _execute_tool(tool_name, params=None):  # noqa: ARG001
        if tool_name == "get_braiins_orderbook":
            if price_braiins is not None:
                return {"price_btc_per_ph_day": price_braiins}
            return {"error": "Braiins orderbook has no valid prices"}
        if tool_name == "get_mrr_listings":
            if price_mrr is not None:
                return {"price_btc_per_ph_day": price_mrr}
            return {"error": "MRR_API_KEY/MRR_API_SECRET not configured"}
        return {"error": "unknown tool"}
    return _execute_tool


def _ensure_snapshot_data():
    """Ensure the latest_snapshot has network difficulty + worker hashrate
    so the inner if-block (``if difficulty and worker_hr:``) succeeds."""
    from services.state import latest_snapshot
    if not latest_snapshot.get("network") or not latest_snapshot.get("network", {}).get("difficulty"):
        latest_snapshot["network"] = {"difficulty": 127170500429035.0, "hashrate": None, "height": None}
    worker = latest_snapshot.get("worker") or {}
    if not worker.get("hashrate"):
        worker["hashrate"] = 225e12  # 225 TH/s
    latest_snapshot["worker"] = worker


# ── Tests ─────────────────────────────────────────────────────────────

class TestOppEngineIDStability:
    """Verifica que o mesmo preço → mesmo ID em chamadas consecutivas."""

    def test_same_price_same_id_braiins(self, monkeypatch, client):
        """Mesmo preço Braiins em 3 chamadas → mesmo ID."""
        _ensure_snapshot_data()
        mock_tool = _mock_execute_tool(price_braiins=0.000123456)
        monkeypatch.setattr(
            "agents.solo_mining_advisor.execute_tool",
            mock_tool,
        )

        ids = []
        for _ in range(3):
            resp = client.get("/api/opportunities")
            data = json.loads(resp.data)
            opps = data.get("opportunities", [])
            ids.append(opps[0]["id"] if opps else None)

        assert ids[0] == ids[1] == ids[2], (
            f"Esperava IDs iguais, obtive {ids}"
        )
        assert isinstance(ids[0], str), f"ID deve ser string, obtive {type(ids[0])}"
        assert ids[0].startswith("braiins_"), (
            f"ID deve começar com 'braiins_', obtive {ids[0]}"
        )
        assert ids[0] == "braiins_0.0", (
            f"Esperava 'braiins_0.0', obtive {ids[0]}"
        )

    def test_same_price_same_id_mrr(self, monkeypatch, client):
        """Mesmo preço MRR em 3 chamadas → mesmo ID."""
        _ensure_snapshot_data()
        mock_tool = _mock_execute_tool(
            price_braiins=0.000200,
            price_mrr=0.000150,  # cheaper → MRR appears
        )
        monkeypatch.setattr(
            "agents.solo_mining_advisor.execute_tool",
            mock_tool,
        )

        ids = []
        for _ in range(3):
            resp = client.get("/api/opportunities")
            data = json.loads(resp.data)
            opps = data.get("opportunities", [])
            # MRR is the 2nd opportunity (index 1)
            mrr_id = opps[1]["id"] if len(opps) > 1 else None
            ids.append(mrr_id)

        assert ids[0] == ids[1] == ids[2], (
            f"Esperava MRR IDs iguais, obtive {ids}"
        )
        assert isinstance(ids[0], str), f"ID deve ser string, obtive {type(ids[0])}"
        assert ids[0].startswith("mrr_"), (
            f"ID deve começar com 'mrr_', obtive {ids[0]}"
        )
        assert ids[0] == "mrr_0.0", (
            f"Esperava 'mrr_0.0', obtive {ids[0]}"
        )


class TestOppEngineIDChanges:
    """Verifica que preço diferente → ID diferente."""

    def test_different_price_different_id(self, monkeypatch, client):
        """Preços significativamente diferentes → IDs diferentes."""
        _ensure_snapshot_data()

        # First call: price = 0.000123
        mock1 = _mock_execute_tool(price_braiins=0.000123)
        monkeypatch.setattr(
            "agents.solo_mining_advisor.execute_tool",
            mock1,
        )
        resp1 = client.get("/api/opportunities")
        data1 = json.loads(resp1.data)
        id1 = data1["opportunities"][0]["id"]

        # Second call: price = 0.000789 (different rounding)
        mock2 = _mock_execute_tool(price_braiins=0.000789)
        monkeypatch.setattr(
            "agents.solo_mining_advisor.execute_tool",
            mock2,
        )
        resp2 = client.get("/api/opportunities")
        data2 = json.loads(resp2.data)
        id2 = data2["opportunities"][0]["id"]

        assert id1 != id2, (
            f"Esperava IDs diferentes, obtive id1={id1} id2={id2}"
        )
        assert id1.startswith("braiins_")
        assert id2.startswith("braiins_")
        assert id1 == "braiins_0.0"
        assert id2 == "braiins_0.001"

    def test_small_change_within_rounding(self, monkeypatch, client):
        """Pequena mudança que não afeta o rounding de 3 casas → mesmo ID."""
        _ensure_snapshot_data()

        # 0.0001234 e 0.0001235 ambos arredondam para 0.000
        ids = []
        for price in [0.0001234, 0.0001235, 0.0001239]:
            mock = _mock_execute_tool(price_braiins=price)
            monkeypatch.setattr(
                "agents.solo_mining_advisor.execute_tool",
                mock,
            )
            resp = client.get("/api/opportunities")
            data = json.loads(resp.data)
            opps = data.get("opportunities", [])
            ids.append(opps[0]["id"] if opps else None)

        assert ids[0] == ids[1] == ids[2], (
            f"Esperava mesmo ID para flutuações pequenas, obtive {ids}"
        )
        assert ids[0].startswith("braiins_"), "ID deve ter prefixo braiins_"
        assert isinstance(ids[0], str), "ID deve ser string"


class TestOppEngineEdgeCases:
    """Casos extremos: dados faltando, plataforma única, etc."""

    def test_both_platforms_available(self, monkeypatch, client):
        """Ambas as plataformas retornam preços → 2 oportunidades."""
        _ensure_snapshot_data()
        mock_tool = _mock_execute_tool(
            price_braiins=0.000200,
            price_mrr=0.000150,  # cheaper → appears
        )
        monkeypatch.setattr(
            "agents.solo_mining_advisor.execute_tool",
            mock_tool,
        )

        resp = client.get("/api/opportunities")
        data = json.loads(resp.data)
        opps = data.get("opportunities", [])

        assert len(opps) == 2, f"Esperava 2 oportunidades, obtive {len(opps)}"
        assert opps[0]["platform"] == "braiins"
        assert opps[1]["platform"] == "mrr"

    def test_only_braiins_available(self, monkeypatch, client):
        """Apenas Braiins disponível → 1 oportunidade."""
        _ensure_snapshot_data()
        mock_tool = _mock_execute_tool(
            price_braiins=0.000200,  # MRR returns error
        )
        monkeypatch.setattr(
            "agents.solo_mining_advisor.execute_tool",
            mock_tool,
        )

        resp = client.get("/api/opportunities")
        data = json.loads(resp.data)
        opps = data.get("opportunities", [])

        assert len(opps) == 1, f"Esperava 1 oportunidade, obtive {len(opps)}"
        assert opps[0]["platform"] == "braiins"

    def test_only_mrr_available(self, monkeypatch, client):
        """Apenas MRR disponível e mais barato que Braiins → 1 oportunidade."""
        _ensure_snapshot_data()
        mock_tool = _mock_execute_tool(
            price_mrr=0.000100,  # cheap enough to appear even without Braiins
        )
        monkeypatch.setattr(
            "agents.solo_mining_advisor.execute_tool",
            mock_tool,
        )

        resp = client.get("/api/opportunities")
        data = json.loads(resp.data)
        opps = data.get("opportunities", [])

        assert len(opps) == 1, f"Esperava 1 oportunidade, obtive {len(opps)}"
        assert opps[0]["platform"] == "mrr"

    def test_neither_platform_available(self, monkeypatch, client):
        """Nenhuma plataforma disponível → 0 oportunidades (sem OBSOLETE)."""
        _ensure_snapshot_data()
        # Garante que não há preços em cache para evitar OBSOLETE fallback
        from services.state import last_known_prices as _lkp
        _lkp["braiins"] = None
        _lkp["mrr"] = None

        mock_tool = _mock_execute_tool()
        monkeypatch.setattr(
            "agents.solo_mining_advisor.execute_tool",
            mock_tool,
        )

        resp = client.get("/api/opportunities")
        data = json.loads(resp.data)
        opps = data.get("opportunities", [])

        assert len(opps) == 0, (
            f"Esperava 0 oportunidades (APIs offline, sem cache), obtive {len(opps)}"
        )

    def test_mrr_not_shown_when_not_cheaper(self, monkeypatch, client):
        """MRR existe mas não é 10% mais barato que Braiins → não aparece."""
        _ensure_snapshot_data()
        mock_tool = _mock_execute_tool(
            price_braiins=0.000200,
            price_mrr=0.000190,  # apenas 5% mais barato, não 10%
        )
        monkeypatch.setattr(
            "agents.solo_mining_advisor.execute_tool",
            mock_tool,
        )

        resp = client.get("/api/opportunities")
        data = json.loads(resp.data)
        opps = data.get("opportunities", [])
        mrr_opps = [o for o in opps if o.get("platform") == "mrr"]

        assert len(mrr_opps) == 0, (
            f"MRR não deveria aparecer (preço muito próximo), "
            f"mas apareceu: {mrr_opps}"
        )
        # Braiins should still appear
        braiins_opps = [o for o in opps if o.get("platform") == "braiins"]
        assert len(braiins_opps) == 1

    def test_empty_response_when_no_worker_data(self, monkeypatch, client):
        """Sem dados de worker/difficulty → oportunidades não são geradas (sem OBSOLETE)."""
        # Garante que snapshot está vazio
        from services.state import latest_snapshot, last_known_prices as _lkp
        latest_snapshot["network"] = {}
        latest_snapshot["worker"] = {}
        # Garante que não há preços em cache para evitar OBSOLETE fallback
        _lkp["braiins"] = None
        _lkp["mrr"] = None

        mock_tool = _mock_execute_tool(price_braiins=0.000200)
        monkeypatch.setattr(
            "agents.solo_mining_advisor.execute_tool",
            mock_tool,
        )

        resp = client.get("/api/opportunities")
        data = json.loads(resp.data)
        opps = data.get("opportunities", [])

        assert len(opps) == 0, (
            f"Esperava 0 oportunidades (sem dados de worker, sem cache), "
            f"obtive {len(opps)}"
        )


class TestOppEngineIsolation:
    """Verifica isolamento entre plataformas: uma falha não mata a outra."""

    def test_braiins_survives_mrr_exception(self, monkeypatch, client):
        """_scan_mrr lança exceção → Braiins sobrevive + scan_stats corretos.

        O monkeypatch em ``_scan_mrr`` (não em ``execute_tool``) é
        intencional: o try/except interno de ``_scan_mrr`` já captura
        erros de ``execute_tool``. Para testar o isolamento em ``scan()``
        precisamos que a exceção PROPAGUE de ``_scan_mrr`` — o que
        acontece com erros inesperados fora do ``execute_tool`` call.
        """
        _ensure_snapshot_data()

        # Mock execute_tool para Braiins funcionar
        def _mock_tool(tool_name, params=None):
            if tool_name == "get_braiins_orderbook":
                return {"price_btc_per_ph_day": 0.000200}
            return {"error": "unknown"}
        monkeypatch.setattr(
            "agents.solo_mining_advisor.execute_tool", _mock_tool,
        )

        # Mock _scan_mrr para LANÇAR exceção (bypassa o try/except interno)
        def _raise_mrr(*args, **kwargs):
            raise RuntimeError("MRR crash — simula falha inesperada")
        monkeypatch.setattr(
            "agents.opportunity_engine._scan_mrr", _raise_mrr,
        )

        resp = client.get("/api/opportunities")
        data = json.loads(resp.data)
        opps = data.get("opportunities", [])
        stats = data.get("scan_stats", {})

        # Braiins deve ter sobrevivido
        assert len(opps) == 1, (
            f"Esperava 1 oportunidade (Braiins), obtive {len(opps)}"
        )
        assert opps[0]["platform"] == "braiins", (
            f"Oportunidade deve ser Braiins, obtive {opps[0]['platform']}"
        )

        # scan_stats deve refletir o isolamento: Braiins OK, MRR com erro
        assert stats.get("braiins_ok") == 1, (
            f"braiins_ok deve ser 1, obtive {stats.get('braiins_ok')}"
        )
        assert stats.get("braiins_errors") == 0, (
            f"braiins_errors deve ser 0, obtive {stats.get('braiins_errors')}"
        )
        assert stats.get("mrr_errors") == 1, (
            f"mrr_errors deve ser 1, obtive {stats.get('mrr_errors')}"
        )
        assert stats.get("mrr_ok") == 0, (
            f"mrr_ok deve ser 0, obtive {stats.get('mrr_ok')}"
        )
