"""
RentalAgent
===========
Specialized agent for hashrate rental comparison.
Currently: DATA SOURCE NOT CONNECTED — requires real market API integration.
"""

import os
from typing import Dict, Any


class RentalAgent:
    """Handles rental market analysis with adapter architecture ready."""

    # ── Provider adapter registry (prepared for future integration) ──
    PROVIDERS = {
        "braiins": {
            "name": "Braiins Hashpower",
            "status": "NOT CONNECTED",
            "description": "Marketplace order book for SHA-256 hashrate",
        },
        "mrr": {
            "name": "MiningRigRentals",
            "status": "NOT CONNECTED",
            "description": "Rig rental marketplace (SHA-256 + AsicBoost)",
        },
        "nicehash": {
            "name": "NiceHash",
            "status": "NOT CONNECTED",
            "description": "Hash-power marketplace (SHA-256 + other algos)",
        },
    }

    def __init__(self):
        self.name = "RentalAgent"

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        intent = payload.get("intent", "")
        btc_usd = payload.get("btc_usd", 0)
        data_source = payload.get("_data_source", "NO_DATA")

        result = {
            "agent": self.name,
            "status": "DATA SOURCE NOT CONNECTED",
            "analysis": {},
        }

        # Check if MRR API credentials are configured
        mrr_key = os.environ.get("MRR_API_KEY")
        mrr_secret = os.environ.get("MRR_API_SECRET")

        provider_status = {}
        for slug, info in self.PROVIDERS.items():
            connected = False
            if slug == "mrr" and mrr_key and mrr_secret:
                connected = True
            provider_status[slug] = {
                **info,
                "connected": connected,
            }

        any_connected = any(p["connected"] for p in provider_status.values())

        result["analysis"] = {
            "status": "CONNECTED" if any_connected else "DATA SOURCE NOT CONNECTED",
            "providers": provider_status,
            "available_comparisons": "NONE" if not any_connected else "LIMITED",
            "message": (
                "Rental comparison requires real market data integration. "
                "Set MRR_API_KEY and MRR_API_SECRET environment variables "
                "to enable MiningRigRentals data. Braiins Hashpower and "
                "NiceHash integration planned for future releases."
            ) if not any_connected else (
                "MiningRigRentals connected. Braiins and NiceHash not yet integrated."
            ),
            "note": (
                "RENTAL INTELLIGENCE — STATUS: DATA SOURCE NOT CONNECTED. "
                "No rental recommendations can be made without real market data. "
                "Never use mock/placeholder prices for financial decisions."
            ),
            "adapter_architecture": "Each provider implements: PRICE, HASHRATE, DURATION, FEES, AVAILABILITY, SOURCE, TIMESTAMP",
        }

        return result
