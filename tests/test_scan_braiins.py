"""
Direct unit tests for _scan_braiins().

Tests all code paths: execute_tool exception, missing/zero price,
missing difficulty, zero hashrate, and the happy path.

Imports the function directly from agents.opportunity_engine — no Flask,
no HTTP, no monkeypatching needed. execute_tool and snapshot are plain
callables/dicts passed as arguments.
"""

from unittest.mock import patch

import pytest

from agents.opportunity_engine import _scan_braiins, generate_opportunity_id, scan


# ── Snapshot fixtures ────────────────────────────────────────────────


def _snapshot(difficulty=127170500429035.0, worker_hr=225e12):
    """Return a minimal snapshot dict with the given values."""
    return {
        "network": {"difficulty": difficulty},
        "worker": {"hashrate": worker_hr},
    }


# ── execute_tool fixtures ───────────────────────────────────────────


def _tool_ok(price=0.000123):
    """Return an execute_tool that returns a valid Braiins price."""
    def _fn(tool_name, params=None):
        if tool_name == "get_braiins_orderbook":
            return {"price_btc_per_ph_day": price}
        return {"error": "unknown tool"}
    return _fn


def _tool_no_price():
    """Return an execute_tool that returns a response without a price key."""
    def _fn(tool_name, params=None):
        return {"error": "orderbook empty"}
    return _fn


def _tool_zero_price():
    """Return an execute_tool that returns price = 0."""
    def _fn(tool_name, params=None):
        return {"price_btc_per_ph_day": 0.0}
    return _fn


def _tool_negative_price():
    """Return an execute_tool that returns a negative price."""
    def _fn(tool_name, params=None):
        return {"price_btc_per_ph_day": -0.001}
    return _fn


def _tool_raises():
    """Return an execute_tool that raises an exception."""
    def _fn(tool_name, params=None):
        raise ConnectionError("Braiins API unreachable")
    return _fn


# ══════════════════════════════════════════════════════════════════════
# Tests: execute_tool exceptions
# ══════════════════════════════════════════════════════════════════════


class TestExecuteToolException:
    """execute_tool levanta exceção → _scan_braiins retorna [].

    O try/except interno de _scan_braiins deve capturar qualquer exceção
    e retornar lista vazia (nunca propagar).
    """

    def test_connection_error_returns_empty(self):
        """ConnectionError ao chamar a API → retorna []."""
        result = _scan_braiins(_tool_raises(), _snapshot())
        assert result == []

    def test_timeout_returns_empty(self):
        """TimeoutError → retorna []."""
        def _timeout(tool_name, params=None):
            raise TimeoutError("Braiins API timed out")
        result = _scan_braiins(_timeout, _snapshot())
        assert result == []

    def test_value_error_returns_empty(self):
        """ValueError dentro de execute_tool → retorna []."""
        def _bad(tool_name, params=None):
            raise ValueError("invalid response format")
        result = _scan_braiins(_bad, _snapshot())
        assert result == []


# ══════════════════════════════════════════════════════════════════════
# Tests: price validation
# ══════════════════════════════════════════════════════════════════════


class TestPriceValidation:
    """Preço ausente, zero ou negativo → _scan_braiins retorna []."""

    def test_no_price_key_returns_empty(self):
        """Resposta sem 'price_btc_per_ph_day' → retorna []."""
        result = _scan_braiins(_tool_no_price(), _snapshot())
        assert result == []

    def test_zero_price_returns_empty(self):
        """Preço = 0.0 → retorna []."""
        result = _scan_braiins(_tool_zero_price(), _snapshot())
        assert result == []

    def test_negative_price_returns_empty(self):
        """Preço negativo → retorna []."""
        result = _scan_braiins(_tool_negative_price(), _snapshot())
        assert result == []

    def test_price_none_returns_empty(self):
        """price key com valor None → retorna []."""
        def _none_price(tool_name, params=None):
            return {"price_btc_per_ph_day": None}
        result = _scan_braiins(_none_price, _snapshot())
        assert result == []


# ══════════════════════════════════════════════════════════════════════
# Tests: snapshot data validation
# ══════════════════════════════════════════════════════════════════════


class TestSnapshotValidation:
    """Difficulty ou hashrate ausentes → _scan_braiins retorna []."""

    def test_difficulty_missing_returns_empty(self):
        """Snapshot sem network.difficulty → retorna []."""
        snap = {"network": {}, "worker": {"hashrate": 225e12}}
        result = _scan_braiins(_tool_ok(), snap)
        assert result == []

    def test_difficulty_none_returns_empty(self):
        """network.difficulty = None → retorna []."""
        snap = {"network": {"difficulty": None}, "worker": {"hashrate": 225e12}}
        result = _scan_braiins(_tool_ok(), snap)
        assert result == []

    def test_difficulty_zero_returns_empty(self):
        """network.difficulty = 0 → retorna [] (falsy)."""
        snap = {"network": {"difficulty": 0}, "worker": {"hashrate": 225e12}}
        result = _scan_braiins(_tool_ok(), snap)
        assert result == []

    def test_network_missing_returns_empty(self):
        """Snapshot sem 'network' key → retorna []."""
        snap = {"worker": {"hashrate": 225e12}}
        result = _scan_braiins(_tool_ok(), snap)
        assert result == []

    def test_hashrate_zero_returns_empty(self):
        """worker.hashrate = 0 → retorna [] (falsy)."""
        snap = {"network": {"difficulty": 127e12}, "worker": {"hashrate": 0}}
        result = _scan_braiins(_tool_ok(), snap)
        assert result == []

    def test_hashrate_missing_returns_empty(self):
        """Snapshot sem worker.hashrate → default 0 → retorna []."""
        snap = {"network": {"difficulty": 127e12}, "worker": {}}
        result = _scan_braiins(_tool_ok(), snap)
        assert result == []

    def test_worker_missing_returns_empty(self):
        """Snapshot sem 'worker' key → .get('worker',{}) → hashrate=0 → retorna []."""
        snap = {"network": {"difficulty": 127e12}}
        result = _scan_braiins(_tool_ok(), snap)
        assert result == []


# ══════════════════════════════════════════════════════════════════════
# Tests: happy path — all data valid
# ══════════════════════════════════════════════════════════════════════


class TestHappyPath:
    """Dados completos e válidos → _scan_braiins retorna [oportunidade]."""

    def test_returns_list_with_one_item(self):
        """Dados válidos → retorna lista com 1 item."""
        result = _scan_braiins(_tool_ok(), _snapshot())
        assert isinstance(result, list)
        assert len(result) == 1

    def test_opportunity_has_braiins_platform(self):
        """Oportunidade gerada tem platform='braiins'."""
        result = _scan_braiins(_tool_ok(), _snapshot())
        assert result[0]["platform"] == "braiins"

    def test_opportunity_has_correct_price(self):
        """Preço da oportunidade corresponde ao preço retornado pela tool."""
        price = 0.000123
        result = _scan_braiins(_tool_ok(price=price), _snapshot())
        assert result[0]["price"] == price

    def test_opportunity_has_correct_id(self):
        """ID gerado corresponde a generate_opportunity_id('braiins', price)."""
        price = 0.000123
        expected_id = generate_opportunity_id("braiins", price)
        result = _scan_braiins(_tool_ok(price=price), _snapshot())
        assert result[0]["id"] == expected_id

    def test_title_contains_price_in_sats(self):
        """Título inclui o preço formatado em sats/PH/day."""
        price = 0.000123
        result = _scan_braiins(_tool_ok(price=price), _snapshot())
        expected_sats = price * 1e6
        assert f"{expected_sats:.1f}" in result[0]["title"]

    def test_status_is_REAL(self):
        """Status é 'REAL' porque Braiins retorna preço real."""
        result = _scan_braiins(_tool_ok(), _snapshot())
        assert result[0]["status"] == "REAL"

    def test_severity_is_INFO(self):
        """severity é 'INFO'."""
        result = _scan_braiins(_tool_ok(), _snapshot())
        assert result[0]["severity"] == "INFO"

    def test_description_contains_worker_ths(self):
        """Descrição inclui o hashrate do worker em TH/s."""
        result = _scan_braiins(_tool_ok(), _snapshot(worker_hr=100e12))
        assert "100.0 TH/s" in result[0]["description"]


# ══════════════════════════════════════════════════════════════════════
# Tests: type and edge safety
# ══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Casos de borda: tipos inesperados, valores extremos."""

    def test_empty_snapshot_returns_empty(self):
        """Snapshot vazio {} → network/worker vazios → retorna []."""
        result = _scan_braiins(_tool_ok(), {})
        assert result == []

    def test_none_snapshot_raises_type_error(self):
        """Snapshot=None → AttributeError ao chamar .get() → NÃO propagado?
        Nota: _scan_braiins acessa snapshot.get(), que funciona em None.
        """
        with pytest.raises(AttributeError):
            _scan_braiins(_tool_ok(), None)

    def test_none_execute_tool_returns_empty(self):
        """execute_tool=None → TypeError ao chamar → capturado pelo try/except interno → retorna [].

        TypeError é subclasse de Exception, então o except Exception em
        _scan_braiins captura e retorna lista vazia."""
        result = _scan_braiins(None, _snapshot())
        assert result == []

    def test_price_is_very_small_positive(self):
        """Preço muito pequeno mas positivo (ex: 1e-8) → considerável válido."""
        result = _scan_braiins(_tool_ok(price=1e-8), _snapshot())
        assert len(result) == 1
        assert result[0]["price"] == 1e-8

    def test_difficulty_is_string(self):
        """Difficulty como string numérica → ainda truthy."""
        snap = {"network": {"difficulty": "127170500429035"}, "worker": {"hashrate": 225e12}}
        result = _scan_braiins(_tool_ok(), snap)
        assert len(result) == 1

    def test_worker_hr_as_string(self):
        """worker.hashrate como string → float() no worker_th funciona."""
        snap = {"network": {"difficulty": 127e12}, "worker": {"hashrate": "225000000000000"}}
        result = _scan_braiins(_tool_ok(), snap)
        assert len(result) == 1


# ══════════════════════════════════════════════════════════════════════
#  Tests: scan() orchestration — ensures both platforms are called
#  correctly and that error isolation in scan() works.
# ══════════════════════════════════════════════════════════════════════


class TestScanOrchestration:
    """Testa scan() — orquestração entre Braiins e MRR.

    Diferente dos testes de _scan_braiins isolado, aqui testamos
    a função scan() que chama ambas as plataformas, extrai o preço
    do Braiins para passar ao MRR, e retorna scan_stats.
    """

    # ── Helper: multi-tool mock ────────────────────────────────────

    @staticmethod
    def _both_tools(braiins_price=0.000200, mrr_price=None):
        """Return execute_tool that handles both platforms.

        Parameters
        ----------
        braiins_price : float or None
            Braiins price to return (None → no price key).
        mrr_price : float or None
            MRR price to return (None → no price key).
            If ``mrr_price == "RAISE"``, the mock raises RuntimeError.
        """
        def _fn(tool_name, params=None):  # noqa: ARG001
            if tool_name == "get_braiins_orderbook":
                if braiins_price is not None:
                    return {"price_btc_per_ph_day": braiins_price}
                return {"error": "no braiins price"}
            if tool_name == "get_mrr_listings":
                if mrr_price == "RAISE":
                    raise RuntimeError("MRR crash")
                if mrr_price is not None:
                    return {"price_btc_per_ph_day": mrr_price}
                return {"error": "no mrr price"}
            return {"error": "unknown tool"}
        return _fn

    # ── Both platforms available ────────────────────────────────────

    def test_both_platforms_return_opportunities(self):
        """Ambas as plataformas com preço → 2 oportunidades."""
        tool = self._both_tools(braiins_price=0.000200, mrr_price=0.000100)
        snap = {"network": {"difficulty": 127e12}, "worker": {"hashrate": 225e12}}
        opps, stats = scan(tool, snap)

        assert len(opps) == 2, f"Esperava 2 oportunidades, obtive {len(opps)}"
        assert opps[0]["platform"] == "braiins"
        assert opps[1]["platform"] == "mrr"
        assert stats["braiins_ok"] == 1
        assert stats["mrr_ok"] == 1
        assert stats["braiins_errors"] == 0
        assert stats["mrr_errors"] == 0

    def test_braiins_price_is_passed_to_mrr_scan(self):
        """Preço do Braiins é passado ao _scan_mrr via braiins_price.

        Verificamos indiretamente: se MRR não for 10%+ mais barato que
        Braiins, MRR não aparece nas oportunidades (mrr_ok=1 porque
        o scan foi concluído sem exceção — simplesmente não gerou opp)."""
        # Braiins = 0.000200, MRR = 0.000190 (só 5% mais barato → não aparece)
        tool = self._both_tools(braiins_price=0.000200, mrr_price=0.000190)
        snap = {"network": {"difficulty": 127e12}, "worker": {"hashrate": 225e12}}
        opps, stats = scan(tool, snap)

        assert len(opps) == 1, f"Esperava 1 (Braiins only), obtive {len(opps)}"
        assert opps[0]["platform"] == "braiins"
        # MRR foi scaneado (sem exceção) mas não gerou oportunidade
        assert stats["braiins_ok"] == 1
        assert stats["mrr_ok"] == 1
        assert stats["mrr_errors"] == 0

    # ── Only Braiins ────────────────────────────────────────────────

    def test_only_braiins_returns_one_opportunity(self):
        """Apenas Braiins com preço → 1 oportunidade, scan_stats ok."""
        tool = self._both_tools(braiins_price=0.000200)
        snap = {"network": {"difficulty": 127e12}, "worker": {"hashrate": 225e12}}
        opps, stats = scan(tool, snap)

        assert len(opps) == 1, f"Esperava 1, obtive {len(opps)}"
        assert opps[0]["platform"] == "braiins"
        assert stats["braiins_ok"] == 1
        assert stats["braiins_errors"] == 0
        assert stats["mrr_errors"] == 0

    # ── Only MRR ────────────────────────────────────────────────────

    def test_only_mrr_returns_one_opportunity(self):
        """Apenas MRR com preço (Braiins sem preço) → 1 oportunidade (MRR).

        Braiins foi scaneado (braiins_ok=1) mas não gerou oportunidade
        porque execute_tool retornou dict sem price_btc_per_ph_day."""
        tool = self._both_tools(braiins_price=None, mrr_price=0.000100)
        snap = {"network": {"difficulty": 127e12}, "worker": {"hashrate": 225e12}}
        opps, stats = scan(tool, snap)

        assert len(opps) == 1, f"Esperava 1 (MRR only), obtive {len(opps)}"
        assert opps[0]["platform"] == "mrr"
        # Braiins foi scaneado sem exceção — só não gerou oportunidade
        assert stats["braiins_ok"] == 1
        assert stats["mrr_ok"] == 1

    # ── Neither platform ────────────────────────────────────────────

    def test_neither_platform_returns_empty(self):
        """Nenhuma plataforma com preço → 0 oportunidades (ambos scan_ok=1).

        Ambas foram scaneadas sem exceção — apenas não geraram
        oportunidades porque nenhum preço estava disponível."""
        tool = self._both_tools(braiins_price=None, mrr_price=None)
        snap = {"network": {"difficulty": 127e12}, "worker": {"hashrate": 225e12}}
        opps, stats = scan(tool, snap)

        assert opps == [], f"Esperava lista vazia, obtive {opps}"
        assert stats["braiins_ok"] == 1  # scan executou, só não gerou opp
        assert stats["mrr_ok"] == 1
        assert stats["braiins_errors"] == 0
        assert stats["mrr_errors"] == 0

    # ── MRR error isolation ─────────────────────────────────────────

    def test_mrr_exception_braiins_survives(self):
        """MRR levanta exceção → Braiins ainda aparece.

        NOTA: _scan_mrr captura exceções de execute_tool internamente
        (try/except Exception), então mrr_errors permanece 0 e mrr_ok=1
        porque o try em scan() não é acionado — a exceção não propaga.

        O cenário que aciona scan()'s except é quando _scan_mrr retorna
        algo inesperado (ex: não iterável) que quebra o .extend()."""
        tool = self._both_tools(braiins_price=0.000200, mrr_price="RAISE")
        snap = {"network": {"difficulty": 127e12}, "worker": {"hashrate": 225e12}}
        opps, stats = scan(tool, snap)

        assert len(opps) == 1, (
            f"Esperava 1 oportunidade (Braiins), obtive {len(opps)}"
        )
        assert opps[0]["platform"] == "braiins"
        assert stats["braiins_ok"] == 1
        assert stats["braiins_errors"] == 0
        # Exceção capturada por _scan_mrr, não por scan()
        assert stats["mrr_errors"] == 0
        assert stats["mrr_ok"] == 1

    # ── Both fail ───────────────────────────────────────────────────

    def test_both_exceptions_return_empty(self):
        """Ambas levantam exceção → 0 oportunidades (mas scan_ok=1).

        As exceções são capturadas internamente por _scan_braiins e
        _scan_mrr (try/except Exception dentro de cada scanner).
        scan() nunca vê as exceções — elas não propagam."""
        def _both_raise(tool_name, params=None):
            raise ConnectionError("all APIs down")
        snap = {"network": {"difficulty": 127e12}, "worker": {"hashrate": 225e12}}
        opps, stats = scan(_both_raise, snap)

        assert opps == []
        # Exceções capturadas internamente, nunca chegam em scan()
        assert stats["braiins_errors"] == 0
        assert stats["mrr_errors"] == 0
        assert stats["braiins_ok"] == 1
        assert stats["mrr_ok"] == 1

    # ── Missing worker data → no opportunities ──────────────────────

    def test_no_worker_data_braiins_skips_mrr_generates(self):
        """Worker hashrate = 0 → _scan_braiins retorna [], mas MRR gera.

        Braiins pula (dados insuficientes), mas MRR tem preço 50%
        mais barato que Braiins e gera oportunidade normalmente."""
        tool = self._both_tools(braiins_price=0.000200, mrr_price=0.000100)
        snap = {"network": {"difficulty": 127e12}, "worker": {"hashrate": 0}}
        opps, stats = scan(tool, snap)

        # Braiins não gerou (worker_hr=0), mas MRR gerou (preço OK)
        assert len(opps) == 1, f"Esperava 1 (MRR), obtive {len(opps)}"
        assert opps[0]["platform"] == "mrr", "MRR deve aparecer"
        assert stats["braiins_ok"] == 1
        assert stats["mrr_ok"] == 1

    # ── scan() outer try/except (non-iterable return) ──────────────

    def test_mrr_returns_none_via_patch_triggers_scan_except(self):
        """_scan_mrr é patchado para retornar None → scan() captura em
        opportunities.extend(), mrr_errors=1, braiins sobrevive."""
        tool = self._both_tools(braiins_price=0.000200, mrr_price=0.000100)
        snap = {"network": {"difficulty": 127e12}, "worker": {"hashrate": 225e12}}
        with patch("agents.opportunity_engine._scan_mrr", return_value=None):
            opps, stats = scan(tool, snap)

        assert len(opps) == 1, f"Braiins deve sobreviver; obtive {len(opps)}"
        assert opps[0]["platform"] == "braiins"
        assert stats["braiins_ok"] == 1
        assert stats["braiins_errors"] == 0
        assert stats["mrr_ok"] == 0
        assert stats["mrr_errors"] == 1

    def test_braiins_returns_none_via_patch_triggers_scan_except(self):
        """_scan_braiins é patchado para retornar None → scan() captura,
        braiins_errors=1, MRR continua sem preço."""
        snap = {"network": {"difficulty": 127e12}, "worker": {"hashrate": 225e12}}
        with patch("agents.opportunity_engine._scan_braiins", return_value=None):
            opps, stats = scan(self._both_tools(braiins_price=0.000200), snap)

        assert opps == []
        assert stats["braiins_ok"] == 0
        assert stats["braiins_errors"] == 1
        assert stats["mrr_ok"] == 1
        assert stats["mrr_errors"] == 0

    # ── scan_stats contract ─────────────────────────────────────────

    def test_scan_stats_has_all_four_keys(self):
        """scan_stats sempre contém as 4 chaves, mesmo com resultados variados."""
        tool = self._both_tools(braiins_price=0.000200, mrr_price=0.000100)
        snap = {"network": {"difficulty": 127e12}, "worker": {"hashrate": 225e12}}
        _, stats = scan(tool, snap)

        assert set(stats.keys()) == {
            "braiins_ok", "braiins_errors", "mrr_ok", "mrr_errors",
        }
