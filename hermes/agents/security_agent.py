"""
SecurityAgent
=============
Specialized agent for security analysis, authentication status, and risk detection.
"""

import os
from typing import Dict, Any


class SecurityAgent:
    """Handles security-related analysis."""

    def __init__(self):
        self.name = "SecurityAgent"

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data_source = payload.get("_data_source", "NO_DATA")

        result = {
            "agent": self.name,
            "status": "success",
            "data_source": data_source,
            "analysis": {},
        }

        api_key_set = bool(os.environ.get("API_KEY"))
        debug_mock = os.environ.get("DEBUG_MOCK") == "1"

        # Rate limit config
        rate_limit = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "60"))

        result["analysis"] = {
            "api_key_protected": api_key_set,
            "api_key_status": "PROTECTED" if api_key_set else "UNPROTECTED — set API_KEY env var",
            "mock_mode_enabled": debug_mock,
            "mock_mode_status": "DISABLED (production safe)" if not debug_mock else "⚠ ENABLED — DEBUG ONLY",
            "rate_limit_per_minute": rate_limit,
            "hermes_auth_status": "AUTHENTICATED" if api_key_set else "OPEN — requires API_KEY",
            "endpoints_protected": [
                "/api/hermes/chat",
                "/api/hermes/agents",
                "/api/hermes/ask-agent",
            ] if api_key_set else [],
            "endpoints_public": ["/api/hermes/health", "/", "/healthz"],
            "recommendations": [],
        }

        if not api_key_set:
            result["analysis"]["recommendations"].append(
                "CRITICAL: Set API_KEY environment variable to protect Hermes endpoints."
            )
        if debug_mock:
            result["analysis"]["recommendations"].append(
                "WARNING: DEBUG_MOCK=1 is enabled. Never use in production."
            )

        return result
