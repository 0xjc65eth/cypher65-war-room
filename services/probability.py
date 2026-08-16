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

    if user_hashrate <= 0 or network_hashrate <= 0 or duration_seconds <= 0:
        return {
            "error": "Invalid input parameters",
            "probability_at_least_one": 0.0,
            "probability_zero": 1.0,
            "expected_blocks": 0.0,
        }

    # Taxa de blocos por segundo para o usuário
    block_rate_per_second = user_hashrate / network_hashrate / 600.0

    # λ (lambda) = taxa esperada de eventos no período
    lambda_rate = block_rate_per_second * duration_seconds

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

    return {
        "probability_at_least_one": round(prob_at_least_one, 6),
        "probability_zero": round(prob_zero, 6),
        "expected_blocks": round(expected_blocks, 4),
        "expected_time_to_block_seconds": round(expected_time_to_block, 1),
        "expected_time_to_block_human": _seconds_to_human(expected_time_to_block),
        "lambda": round(lambda_rate, 6),
        "duration_seconds": duration_seconds,
        "note": "EXPECTED VALUE — NOT A GUARANTEE. Mining is probabilistic.",
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
        "disclaimer": "All values are EXPECTED. Actual results follow probability distribution.",
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
