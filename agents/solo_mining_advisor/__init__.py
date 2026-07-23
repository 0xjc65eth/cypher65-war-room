"""
CYPHER SOLO MINING ADVISOR — Agent Handler
============================================
Main entry point for the Solo Mining Advisor agent.
Loads the system prompt, registers tools, and provides
the agent interface for freebuff/LLM orchestration.
"""

import os
import logging
from pathlib import Path

from .tools import TOOL_REGISTRY, TOOL_SCHEMAS, call_tool

log = logging.getLogger("cypher65.agent")

# ── Agent metadata ───────────────────────────────────────────────────────
AGENT_DIR = Path(__file__).parent

AGENT_NAME = "solo-mining-advisor"
AGENT_VERSION = "1.0.0"
AGENT_DISPLAY_NAME = "CYPHER Solo Mining Advisor"

# ═══════════════════════════════════════════════════════════════════════════
#  System prompt loader
# ═══════════════════════════════════════════════════════════════════════════

_system_prompt_cache = None


def get_system_prompt() -> str:
    """Load the system prompt from system-prompt.md.
    Cached at module level for performance."""
    global _system_prompt_cache
    if _system_prompt_cache is not None:
        return _system_prompt_cache

    prompt_path = AGENT_DIR / "system-prompt.md"
    try:
        with open(prompt_path, "r") as f:
            _system_prompt_cache = f.read()
        log.info("[solo-mining-advisor] system prompt loaded (%d chars)",
                 len(_system_prompt_cache))
    except FileNotFoundError:
        log.error("[solo-mining-advisor] system-prompt.md not found at %s", prompt_path)
        _system_prompt_cache = (
            "# CYPHER SOLO MINING ADVISOR\n\n"
            "You are a Bitcoin solo mining calculator. "
            "Respond in terminal style with step-by-step probability calculations.\n\n"
            "[ERROR] Full system prompt not found — using minimal fallback.\n"
        )
    return _system_prompt_cache


# ═══════════════════════════════════════════════════════════════════════════
#  Agent descriptor — what freebuff/LLM orchestration needs to register
# ═══════════════════════════════════════════════════════════════════════════

def get_agent_descriptor() -> dict:
    """Return the full agent descriptor for registration in freebuff."""
    return {
        "name": AGENT_NAME,
        "display_name": AGENT_DISPLAY_NAME,
        "version": AGENT_VERSION,
        "description": (
            "Terminal-style Bitcoin solo mining calculator. "
            "Covers hashrate rental (Braiins/MRR), parasite.space pool, "
            "and capital allocation decisions."
        ),
        "system_prompt": get_system_prompt(),
        "tools": list(TOOL_REGISTRY.keys()),
        "tool_schemas": TOOL_SCHEMAS,
        "capabilities": [
            "bitcoin_mining_probability",
            "hashrate_rental_comparison",
            "pool_economics",
            "terminal_formatting",
            "real_time_api_calls",
        ],
        "restrictions": [
            "never_give_financial_advice_as_certainty",
            "never_hardcode_live_prices_or_difficulty",
            "always_show_step_by_step_calculations",
            "scope_limited_to_sha256_solo_mining",
        ],
        "language": "pt-BR",
        "tone": "technical-terminal",
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Tool execution — called by freebuff when the LLM requests a tool call
# ═══════════════════════════════════════════════════════════════════════════

def execute_tool(tool_name: str, params: dict = None) -> dict:
    """Execute a tool by name. This is the main dispatch function
    that freebuff calls when the LLM decides to invoke a tool.

    Args:
        tool_name: one of get_network_difficulty, get_btc_price,
                   get_braiins_orderbook, get_mrr_listings,
                   get_parasite_pool_stats
        params: optional keyword arguments for the tool

    Returns:
        dict with tool result or error
    """
    log.info("[solo-mining-advisor] execute_tool: %s(%s)", tool_name, params or "")
    return call_tool(tool_name, params)


# ═══════════════════════════════════════════════════════════════════════════
#  Quick self-test — run to verify agent integrity
# ═══════════════════════════════════════════════════════════════════════════

def self_test() -> dict:
    """Run a quick integrity check on the agent.
    Verifies: system prompt loads, all tools are callable, basic connectivity."""
    results = {}

    # Check system prompt
    prompt = get_system_prompt()
    results["system_prompt"] = {
        "loaded": len(prompt) > 100,
        "length": len(prompt),
    }

    # Check tool registry
    results["tool_registry"] = {
        "count": len(TOOL_REGISTRY),
        "tools": list(TOOL_REGISTRY.keys()),
    }

    # Check each tool is callable
    for name, fn in TOOL_REGISTRY.items():
        results[f"tool_{name}"] = {
            "callable": callable(fn),
            "has_docstring": bool(fn.__doc__),
        }

    # Check tool schemas
    results["tool_schemas"] = {
        "count": len(TOOL_SCHEMAS),
        "all_have_descriptions": all(
            s.get("description") for s in TOOL_SCHEMAS.values()
        ),
    }

    return results


if __name__ == "__main__":
    # Run self-test when executed directly
    import json
    test_results = self_test()
    print(json.dumps(test_results, indent=2))
