"""Fail-closed production safety gates for side-effecting operations.

These gates are deliberately independent from licensing, tenant settings and
frontend state.  A capability is enabled only when its dedicated environment
variable contains an explicitly accepted true value.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any


ENABLE_PHYSICAL_COMMANDS = "ENABLE_PHYSICAL_COMMANDS"
ENABLE_AUTONOMOUS_COMMANDS = "ENABLE_AUTONOMOUS_COMMANDS"
ENABLE_REAL_HASHRATE_PURCHASES = "ENABLE_REAL_HASHRATE_PURCHASES"
ENABLE_REAL_PAYMENTS = "ENABLE_REAL_PAYMENTS"

_EXPLICIT_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _is_explicitly_enabled(name: str, env: Mapping[str, str] | None = None) -> bool:
    """Return true only for an explicit, allowlisted string value.

    Reading the environment at call time keeps policy changes observable to
    long-running processes without caching sensitive process configuration.
    Unexpected types and values fail closed.
    """

    source = os.environ if env is None else env
    raw_value = source.get(name)
    if not isinstance(raw_value, str):
        return False
    return raw_value.strip().lower() in _EXPLICIT_TRUE_VALUES


def can_execute_physical_command(env: Mapping[str, str] | None = None) -> bool:
    """Whether non-dry-run commands may reach physical devices."""

    return _is_explicitly_enabled(ENABLE_PHYSICAL_COMMANDS, env)


def can_execute_autonomous_command(env: Mapping[str, str] | None = None) -> bool:
    """Whether autonomous logic may execute commands without a human."""

    return _is_explicitly_enabled(ENABLE_AUTONOMOUS_COMMANDS, env)


def can_purchase_hashrate(env: Mapping[str, str] | None = None) -> bool:
    """Whether the application may submit a real hashrate purchase."""

    return _is_explicitly_enabled(ENABLE_REAL_HASHRATE_PURCHASES, env)


def can_process_real_payment(env: Mapping[str, str] | None = None) -> bool:
    """Whether the application may initiate or settle real payments."""

    return _is_explicitly_enabled(ENABLE_REAL_PAYMENTS, env)


def safety_policy_status(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return a sanitized operator-facing snapshot of the safety policy.

    Raw environment values are intentionally excluded so this object is safe
    for structured logs and authenticated diagnostics.
    """

    return {
        "default": "deny",
        "physical_commands": can_execute_physical_command(env),
        "autonomous_commands": can_execute_autonomous_command(env),
        "real_hashrate_purchases": can_purchase_hashrate(env),
        "real_payments": can_process_real_payment(env),
    }
