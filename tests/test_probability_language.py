"""Comprehension-copy contracts for block probability and economics (Issue #378)."""

import math
from pathlib import Path

import pytest

from services.probability import calculate_block_probability
from solo_mining import calc_prob_best_diff_exceeds


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_probability_payload_exposes_source_window_units_and_assumptions():
    result = calculate_block_probability(100e12, 700e18, 86_400)

    context = result["model_context"]
    assert context["model"] == "Poisson"
    assert context["source"]
    assert context["window_seconds"] == 86_400
    assert context["units"]["probability"] == "decimal 0..1"
    assert context["units"]["mean_interval"] == "seconds"
    assert "independent hashes" in context["assumptions"]
    assert "Past work does not increase" in context["independence_notice"]
    assert "NOT A DEADLINE" in result["note"]


def test_dashboard_copy_does_not_present_mean_as_deadline_or_history_as_progress():
    html = _read("templates/dashboard.html")
    js = _read("static/app.js")
    active_copy = html + js + _read("solo_mining.py") + _read("services/ai_operator.py")

    forbidden = (
        "Next block ≈",
        "TIME TO BLOCK",
        ">EXPECTED TIME<",
        "CUMULATIVE P(BLOCK) PROGRESSION",
        "HASH PROXIMITY · QUANTUM-LOCK",
        "HOT STREAK na proximidade",
        "proximidade de bloco está acelerando",
        "closer to a block",
        "— keep going!",
        "Expected block time:",
        "E[time to block]",
    )
    for phrase in forbidden:
        assert phrase not in active_copy

    required = (
        "MODEL MEAN INTERVAL",
        "SESSION P(≥1) ESTIMATE",
        "past work does not change the next hash",
        "não aumenta a chance do próximo hash",
        "Cenários econômicos não prometem lucro",
    )
    for phrase in required:
        assert phrase in active_copy


def test_probability_and_economics_tooltips_state_measurement_context():
    html = _read("templates/dashboard.html")

    assert "Fonte: snapshot atual; unidade: tempo" in html
    assert "janela: dia-modelo; unidade: BTC/dia" in html
    assert "janela: 30 dias; unidade: moeda" in html
    assert "janela: dia-modelo; unidade: USD/TH·d" in html
    assert "Premissas: hashes independentes" in html


def test_mobile_and_commercial_copy_reject_countdown_and_profit_promises():
    mobile = _read("mobile/src/screens/Block/BlockHuntScreen.tsx")
    readme = _read("README.md")
    icps = _read("docs/ICPS.md")

    assert "Model mean interval" in mobile
    assert "not a countdown or guarantee" in mobile
    assert "Past work does not change the next-hash odds" in mobile
    assert "These are not countdowns, progress or predictions" in readme
    assert "no profit promise" in readme
    assert "sem prazo ou contagem regressiva" in icps


def test_legacy_identifiers_remain_for_api_compatibility():
    service = _read("services/probability.py")
    proximity = _read("services/proximity.py")

    assert '"expected_time_to_block_seconds"' in service
    assert '"expected_blocks"' in service
    assert '"quantum_lock": quantum_lock' in proximity
    assert '"hot_streak": hot_streak' in proximity


def test_best_share_threshold_probability_uses_hash_target_probability():
    # threshold difficulty 1 needs 2**32 hashes for lambda=1, so the exact
    # independent-hash result converges to 1-e^-1 (not e^-threshold/share).
    result = calc_prob_best_diff_exceeds(2**32, 1, 1)
    assert result["p_best_exceeds_threshold"] == pytest.approx(
        1 - math.exp(-1), rel=1e-8
    )
    assert "historical best shares do not affect" in result["note"]


def test_best_share_threshold_probability_handles_certain_single_hash_target():
    # A target at difficulty 1 / 2**32 is met by every hash. This also guards
    # the stable formula from evaluating log1p(-1).
    result = calc_prob_best_diff_exceeds(1, 1, 1 / 2**32)
    assert result["p_best_exceeds_threshold"] == 1.0
    assert result["p_best_exceeds_pct"] == 100.0
