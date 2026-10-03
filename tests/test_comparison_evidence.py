import pytest
from helpers import build_decision_matrix


@pytest.mark.parametrize(
    "inputs",
    [
        {"solo_expected_time_days": 200, "solo_p_year_pct": 20},
        {"pool_net_usd_per_day": 5},
        {"lender_net_usd_per_day": 7},
        {"pool_net_usd_per_day": True, "lender_net_usd_per_day": 7},
        {"pool_net_usd_per_day": float("nan"), "lender_net_usd_per_day": 7},
    ],
)
def test_no_winner_without_two_comparable_alternatives(inputs):
    assert build_decision_matrix(**inputs)["best_option"] == "insufficient"


def test_solo_is_model_mean_not_deadline():
    dm = build_decision_matrix(solo_expected_time_days=200, solo_p_year_pct=20)
    assert dm["rows"]["solo"]["expected_time_days"] == 200
    assert "not a deadline" in dm["recommendation"]
