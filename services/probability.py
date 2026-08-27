"""
CYPHER65 — Block Probability Engine
====================================
Calcula probabilidades reais de encontrar blocos usando modelo Poisson.

Bitcoin block finding é um processo de Poisson com taxa:
    λ = (user_hashrate / network_hashrate) * (time_seconds / 600)

Onde 600 segundos = tempo médio entre blocos.

Nunca apresentar como "garantia". Sempre Expected Value.
"""

import math
from typing import Dict, Any, Optional


def _invalid_input_result() -> Dict[str, Any]:
    """Return the stable, JSON-safe response for invalid numeric inputs."""
    return {
        "error": "Invalid input parameters",
        "probability_at_least_one": 0.0,
        "probability_zero": 1.0,
        "expected_blocks": 0.0,
    }


def calculate_block_probability(
    user_hashrate: float,  # H/s do usuário/worker
    network_hashrate: float,  # H/s da rede
    duration_seconds: int,  # Período em segundos
    network_difficulty: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Calcula probabilidades de encontrar blocos usando distribuição Poisson.

    Retorna:
    - probability_at_least_one: Probabilidade de achar ≥1 bloco
    - probability_zero: Probabilidade de achar 0 blocos
    - expected_blocks: Número esperado de blocos
    - expected_time_to_block: Tempo esperado até o próximo bloco (segundos)
    """

    response_duration_seconds = duration_seconds
    try:
        user_hashrate = float(user_hashrate)
        network_hashrate = float(network_hashrate)
        duration_seconds = float(duration_seconds)
    except (TypeError, ValueError):
        return _invalid_input_result()

    if (
        not all(
            math.isfinite(value)
            for value in (user_hashrate, network_hashrate, duration_seconds)
        )
        or user_hashrate <= 0
        or network_hashrate <= 0
        or duration_seconds <= 0
    ):
        return _invalid_input_result()

    # Taxa de blocos por segundo para o usuário
    block_rate_per_second = user_hashrate / network_hashrate / 600.0

    # λ (lambda) = taxa esperada de eventos no período
    lambda_rate = block_rate_per_second * duration_seconds

    # Reject arithmetic overflow rather than returning Infinity in a JSON
    # probability response. A probability engine must fail closed: Infinity
    # could otherwise be read as a block or profit promise by the UI.
    if not math.isfinite(lambda_rate):
        return _invalid_input_result()

    # Probabilidade de 0 blocos (Poisson)
    prob_zero = math.exp(-lambda_rate)

    # Probabilidade de pelo menos 1 bloco
    prob_at_least_one = 1.0 - prob_zero

    # Expected blocks
    expected_blocks = lambda_rate

    # Expected time até o próximo bloco (segundos)
    expected_time_to_block = (
        600.0 * (network_hashrate / user_hashrate)
        if user_hashrate > 0
        else float("inf")
    )

    if not math.isfinite(expected_time_to_block):
        return _invalid_input_result()

    return {
        "probability_at_least_one": round(prob_at_least_one, 6),
        "probability_zero": round(prob_zero, 6),
        "expected_blocks": round(expected_blocks, 4),
        "expected_time_to_block_seconds": round(expected_time_to_block, 1),
        "expected_time_to_block_human": _seconds_to_human(expected_time_to_block),
        "lambda": round(lambda_rate, 6),
        "duration_seconds": response_duration_seconds,
        "note": "EXPECTED VALUE / STATISTICAL MODEL — NOT A DEADLINE OR FORECAST; NOT A GUARANTEE.",
        "model_context": {
            "model": "Poisson",
            "source": "current worker hashrate and network hashrate snapshot",
            "window_seconds": response_duration_seconds,
            "units": {"probability": "decimal 0..1", "mean_interval": "seconds"},
            "assumptions": [
                "constant hashrate during the selected window",
                "constant network hashrate during the selected window",
                "independent hashes",
                "600-second network block interval",
            ],
            "independence_notice": "Past work does not increase the probability of the next hash.",
        },
    }


def calculate_multiple_periods(
    user_hashrate: float,
    network_hashrate: float,
    network_difficulty: Optional[float] = None,
) -> Dict[str, Any]:
    """Calcula probabilidades para vários períodos padrão."""

    periods = {
        "1h": 3600,
        "6h": 21600,
        "12h": 43200,
        "24h": 86400,
        "7d": 604800,
        "30d": 2592000,
    }

    results = {}
    for label, seconds in periods.items():
        results[label] = calculate_block_probability(
            user_hashrate, network_hashrate, seconds, network_difficulty
        )

    return {
        "user_hashrate": user_hashrate,
        "network_hashrate": network_hashrate,
        "periods": results,
        "disclaimer": "Statistical estimates, not deadlines, forecasts, progress, or guarantees. Past work does not change the next-hash odds.",
    }


def _seconds_to_human(seconds: float) -> str:
    if seconds == float("inf"):
        return "N/A"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds/60:.1f}m"
    if seconds < 86400:
        return f"{seconds/3600:.1f}h"
    return f"{seconds/86400:.1f}d"
