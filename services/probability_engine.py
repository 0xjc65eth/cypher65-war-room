"""
HERMES P0.3 — Probability Engine Integration
===========================================
Endpoint e funções para expor o Block Probability Engine via API.
"""

from flask import jsonify, request
from services.probability import (
    calculate_block_probability,
    calculate_multiple_periods,
)


def register_probability_routes(app):
    """Registra as rotas de probabilidade no Flask app."""

    @app.route("/api/probability")
    def api_probability():
        """
        Calcula probabilidades de encontrar blocos.

        Query params:
            hashrate: hashrate do usuário em H/s (obrigatório)
            network_hashrate: hashrate da rede em H/s (opcional, usa mempool se não fornecido)
            duration: duração em segundos (opcional, default 86400 = 24h)
        """
        try:
            user_hr = float(request.args.get("hashrate", 0))
            network_hr = float(request.args.get("network_hashrate", 0))
            duration = int(request.args.get("duration", 86400))

            if user_hr <= 0:
                return jsonify({"error": "hashrate parameter is required and must be > 0"}), 400

            # Se não tiver network_hashrate, usa um valor padrão razoável (~600 EH/s em 2026)
            if network_hr <= 0:
                network_hr = 6e20  # ~600 EH/s

            result = calculate_block_probability(user_hr, network_hr, duration)
            result["input"] = {
                "user_hashrate": user_hr,
                "network_hashrate": network_hr,
                "duration_seconds": duration,
            }

            return jsonify(result)

        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/probability/full")
    def api_probability_full():
        """Retorna probabilidades para múltiplos períodos padrão."""
        try:
            user_hr = float(request.args.get("hashrate", 0))
            network_hr = float(request.args.get("network_hashrate", 6e20))

            if user_hr <= 0:
                return jsonify({"error": "hashrate parameter is required"}), 400

            result = calculate_multiple_periods(user_hr, network_hr)
            return jsonify(result)

        except Exception as e:
            return jsonify({"error": str(e)}), 400

    return app