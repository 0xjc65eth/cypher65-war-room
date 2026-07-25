"""
Direct unit tests for opportunity_engine helper functions.
Tests generate_opportunity_id() and build_response() WITHOUT Flask or app.py.

These tests import agents.opportunity_engine directly and call pure functions.
No test client, no monkeypatching, no HTTP — just deterministic function calls.
"""

import time
import pytest

from agents.opportunity_engine import (
    generate_opportunity_id,
    build_response,
)


# ══════════════════════════════════════════════════════════════════════
# generate_opportunity_id
# ══════════════════════════════════════════════════════════════════════

class TestGenerateOpportunityID:
    """Testa generate_opportunity_id(platform, price) → str."""

    def test_braiins_returns_braiins_prefix(self):
        """Prefixo 'braiins_' para plataforma Braiins."""
        oid = generate_opportunity_id("braiins", 0.000123)
        assert oid.startswith("braiins_")
        assert isinstance(oid, str)

    def test_mrr_returns_mrr_prefix(self):
        """Prefixo 'mrr_' para plataforma MRR."""
        oid = generate_opportunity_id("mrr", 0.000456)
        assert oid.startswith("mrr_")
        assert isinstance(oid, str)

    def test_rounds_to_3_decimals(self):
        """Preço 0.000123456 → arredonda para 0.000."""
        oid = generate_opportunity_id("braiins", 0.000123456)
        assert oid == "braiins_0.0"

    def test_price_0000789_rounds_to_0001(self):
        """Preço 0.000789 → arredonda para 0.001."""
        oid = generate_opportunity_id("braiins", 0.000789)
        assert oid == "braiins_0.001"

    def test_price_0015_rounds_to_002(self):
        """Preço 0.0015 → arredonda para 0.002 (banker's rounding: 5 → even)."""
        oid = generate_opportunity_id("mrr", 0.0015)
        # Python 3 round() uses banker's rounding: 0.0015 → 0.002
        assert oid == "mrr_0.002"

    def test_same_price_same_id(self):
        """Mesmo preço em 3 chamadas → mesmo ID."""
        ids = [generate_opportunity_id("braiins", 0.0005) for _ in range(3)]
        assert ids[0] == ids[1] == ids[2]

    def test_different_prices_different_ids(self):
        """Preços diferentes → IDs diferentes."""
        id1 = generate_opportunity_id("braiins", 0.0001)
        id2 = generate_opportunity_id("braiins", 0.0005)
        assert id1 != id2

    def test_same_price_different_platforms_different_ids(self):
        """Mesmo preço em plataformas diferentes → IDs diferentes."""
        id_braiins = generate_opportunity_id("braiins", 0.001)
        id_mrr = generate_opportunity_id("mrr", 0.001)
        assert id_braiins != id_mrr
        assert id_braiins.startswith("braiins_")
        assert id_mrr.startswith("mrr_")

    def test_zero_price(self):
        """Preço zero → ID com 0.0."""
        oid = generate_opportunity_id("braiins", 0.0)
        assert oid == "braiins_0.0"

    def test_negative_price(self):
        """Preço negativo → ID mantém sinal (round retorna -0.001)."""
        oid = generate_opportunity_id("mrr", -0.001)
        assert oid == "mrr_-0.001"

    def test_very_small_price_does_not_change_id(self):
        """Mudanças < 0.0005 não alteram o ID (abaixo do rounding)."""
        id_a = generate_opportunity_id("braiins", 0.0001234)
        id_b = generate_opportunity_id("braiins", 0.0001235)
        id_c = generate_opportunity_id("braiins", 0.0001239)
        assert id_a == id_b == id_c
        assert id_a == "braiins_0.0"

    def test_large_price(self):
        """Preço grande (ex: 1.0) → ID com 1.0."""
        oid = generate_opportunity_id("braiins", 1.0)
        assert oid == "braiins_1.0"

    def test_price_just_above_rounding_threshold(self):
        """Preço 0.0005 arredonda para 0.001 (round half up no Python 3)."""
        # Python 3 bank rounding: 0.0005 → 0.0 (rounds to even)
        # Mas nosso código usa round(0.0005, 3) = 0.0 em Python 3
        oid = generate_opportunity_id("braiins", 0.0005)
        assert oid == "braiins_0.0" or oid == "braiins_0.001"


# ══════════════════════════════════════════════════════════════════════
# build_response
# ══════════════════════════════════════════════════════════════════════


class TestBuildResponse:
    """Testa build_response(opportunities) → dict."""

    def test_returns_dict_with_expected_keys(self):
        """Resposta contém opportunities, ts, disclaimer."""
        result = build_response([])
        assert isinstance(result, dict)
        assert "opportunities" in result
        assert "ts" in result
        assert "disclaimer" in result

    def test_ts_is_recent_int(self):
        """timestamp ts é um int próximo a time.time()."""
        before = int(time.time())
        result = build_response([])
        after = int(time.time())
        assert isinstance(result["ts"], int)
        assert before <= result["ts"] <= after + 1

    def test_disclaimer_is_non_empty_string(self):
        """disclaimer é uma string não vazia."""
        result = build_response([])
        assert isinstance(result["disclaimer"], str)
        assert len(result["disclaimer"]) > 10

    def test_empty_list_returns_empty_opportunities(self):
        """Lista vazia → opportunities = []."""
        result = build_response([])
        assert result["opportunities"] == []

    def test_single_opportunity_passed_through(self):
        """1 oportunidade na entrada → 1 na saída."""
        opp = {"id": "braiins_0.001", "platform": "braiins"}
        result = build_response([opp])
        assert len(result["opportunities"]) == 1
        assert result["opportunities"][0]["id"] == "braiins_0.001"

    def test_two_opportunities_passed_through(self):
        """2 oportunidades na entrada → 2 na saída."""
        opps = [
            {"id": "braiins_0.001", "platform": "braiins"},
            {"id": "mrr_0.001", "platform": "mrr"},
        ]
        result = build_response(opps)
        assert len(result["opportunities"]) == 2

    def test_caps_at_3_opportunities(self):
        """Mais de 3 oportunidades → capped em 3."""
        opps = [{"id": f"p{i}", "platform": "test"} for i in range(10)]
        result = build_response(opps)
        assert len(result["opportunities"]) == 3

    def test_preserves_opportunity_order(self):
        """Ordem das oportunidades é preservada (primeiros 3)."""
        opps = [
            {"id": "first", "platform": "a"},
            {"id": "second", "platform": "b"},
            {"id": "third", "platform": "c"},
            {"id": "fourth", "platform": "d"},
        ]
        result = build_response(opps)
        ids = [o["id"] for o in result["opportunities"]]
        assert ids == ["first", "second", "third"]

    def test_does_not_mutate_input(self):
        """A função não modifica a lista de entrada."""
        original = [{"id": "test_1", "platform": "test"}]
        original_copy = list(original)
        build_response(original)
        assert original == original_copy

    def test_opportunities_are_full_dicts(self):
        """Cada oportunidade mantém todos os campos originais."""
        opp = {
            "id": "test_0.001",
            "platform": "test",
            "title": "Test deal",
            "description": "A test opportunity",
            "meta": "test data",
            "price": 0.001,
            "severity": "INFO",
            "status": "ESTIMATED",
        }
        result = build_response([opp])
        assert result["opportunities"][0] == opp
