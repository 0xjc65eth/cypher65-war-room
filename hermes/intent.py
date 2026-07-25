"""
HERMES Intent Engine
====================
Detects user intent from natural language messages.
"""

import re
from typing import Dict, Any
from enum import Enum


class IntentType(str, Enum):
    MINING_STATUS = "MINING_STATUS"
    PROBABILITY = "PROBABILITY"
    HASHRATE_ANALYSIS = "HASHRATE_ANALYSIS"
    RENTAL_COMPARISON = "RENTAL_COMPARISON"
    FINANCIAL = "FINANCIAL"
    ALERTS = "ALERTS"
    WORKER_HEALTH = "WORKER_HEALTH"
    GENERAL = "GENERAL"
    UNKNOWN = "UNKNOWN"


class IntentEngine:
    """Detects intent and extracts entities from user messages."""

    def __init__(self):
        self.patterns = {
            IntentType.MINING_STATUS: [
                r"(como est[aá]|status|como vai|minera[cç][aã]o|operação)",
                r"(meu miner|meus workers|hashrate)",
            ],
            IntentType.PROBABILITY: [
                r"(probabilidade|chance|chance de|probab|encontrar bloco|block)",
                r"(quanto.*chance|qual.*probabilidade)",
            ],
            IntentType.HASHRATE_ANALYSIS: [
                r"(hashrate|queda|subiu|caiu|an[aá]lise|tend[eê]ncia)",
            ],
            IntentType.RENTAL_COMPARISON: [
                r"(alugar|aluguel|rental|onde alugar|melhor alugar)",
            ],
            IntentType.FINANCIAL: [
                r"(custo|roi|lucro|preju|gasto|receita|payout)",
            ],
            IntentType.WORKER_HEALTH: [
                r"(sa[uú]de|health|temperatura|problema|offline|anormal)",
            ],
            IntentType.ALERTS: [
                r"(alerta|notifica|problema|erro|aviso)",
            ],
        }

    def detect(self, message: str) -> Dict[str, Any]:
        """Detect intent and return structured result."""
        message_lower = message.lower().strip()

        for intent, patterns in self.patterns.items():
            for pattern in patterns:
                if re.search(pattern, message_lower):
                    return {
                        "intent": intent.value,
                        "confidence": 0.85,
                        "raw_message": message,
                    }

        return {
            "intent": IntentType.UNKNOWN.value,
            "confidence": 0.4,
            "raw_message": message,
        }