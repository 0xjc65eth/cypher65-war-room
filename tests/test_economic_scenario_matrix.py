import pytest

from helpers import build_economic_scenario_matrix


def test_matrix_has_homogeneous_scenarios_and_units():
    matrix = build_economic_scenario_matrix(
        pool_ev_btc_per_day=0.1,
        pool_net_usd_per_day=10,
        pool_cost_usd_per_day=2,
        solo_ev_btc_per_day=0.12,
        solo_net_usd_per_day=12,
        solo_cost_usd_per_day=2,
        rental_ev_btc_per_day=0.08,
        rental_net_usd_per_day=8,
        rental_cost_usd_per_day=4,
        lease_ev_btc_per_day=0.09,
        lease_net_usd_per_day=9,
        lease_cost_usd_per_day=1,
        solo_p_day_pct=3.0,
        cost_modes={"POOL": True, "SOLO": True, "RENTAL": True, "LEASE": True},
    )

    assert matrix["horizon"] == "24h"
    assert set(matrix["scenarios"]) == {"POOL", "SOLO", "RENTAL", "LEASE"}
    metric_keys = set(matrix["scenarios"]["POOL"])
    assert all(set(row) == metric_keys for row in matrix["scenarios"].values())
    assert matrix["unit_contract"] == {
        "modeled_ev_btc_per_day": "BTC/day",
        "modeled_net_usd_per_day": "USD/day",
        "direct_cost_usd_per_day": "USD/day",
    }
    assert matrix["best_option"] == "POOL"
    assert matrix["scenarios"]["SOLO"]["modeled_net_usd_per_day"] == {
        "value": 12.0,
        "status": "AVAILABLE",
    }
    assert matrix["scenarios"]["SOLO"]["p_block_selected_window_pct"]["value"] == 3.0
    assert matrix["scenarios"]["SOLO"]["p_block_selected_window_pct"]["unit"] == "percent over 24h"


def test_unconfigured_cost_and_net_are_not_reported_as_zero():
    matrix = build_economic_scenario_matrix(
        pool_ev_btc_per_day=0.01,
        pool_net_usd_per_day=5,
        pool_cost_usd_per_day=0,
        cost_modes={"POOL": False},
    )
    pool = matrix["scenarios"]["POOL"]
    assert pool["modeled_ev_btc_per_day"] == {"value": 0.01, "status": "AVAILABLE"}
    assert pool["modeled_net_usd_per_day"] == {
        "value": None,
        "status": "NOT CONFIGURED",
    }
    assert pool["direct_cost_usd_per_day"] == {
        "value": None,
        "status": "NOT CONFIGURED",
    }
    assert matrix["best_option"] == "insufficient"


def test_missing_and_invalid_metrics_are_unknown_not_zero():
    matrix = build_economic_scenario_matrix(
        pool_ev_btc_per_day=float("nan"),
        pool_net_usd_per_day=None,
        pool_cost_usd_per_day=float("inf"),
        cost_modes={"POOL": True},
    )
    pool = matrix["scenarios"]["POOL"]
    assert pool["modeled_ev_btc_per_day"] == {"value": None, "status": "UNKNOWN"}
    assert pool["modeled_net_usd_per_day"] == {"value": None, "status": "UNKNOWN"}
    assert pool["direct_cost_usd_per_day"] == {"value": None, "status": "UNKNOWN"}


def test_solo_probability_is_only_applicable_to_solo():
    matrix = build_economic_scenario_matrix(solo_p_day_pct=4.2)
    assert matrix["scenarios"]["SOLO"]["p_block_selected_window_pct"] == {
        "value": 4.2,
        "status": "AVAILABLE",
        "unit": "percent over 24h",
    }
    assert matrix["scenarios"]["POOL"]["p_block_selected_window_pct"] == {
        "value": None,
        "status": "N/A",
        "unit": "percent over 24h",
    }


@pytest.mark.parametrize("bad", [True, "bad", float("nan"), float("inf")])
def test_bad_values_are_not_comparable(bad):
    matrix = build_economic_scenario_matrix(
        pool_net_usd_per_day=bad,
        cost_modes={"POOL": True},
    )
    assert matrix["best_option"] == "insufficient"
