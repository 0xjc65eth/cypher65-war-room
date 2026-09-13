"""Fail-closed boot guards for cloud / public deploys (Issue #535).

Local self-host stays convenient: an ephemeral SECRET_KEY and CORS ``*``
are allowed when no PaaS flags are set. A Render/CLOUD_MODE process must
not boot with a rotating session secret, a wildcard CORS policy, or Flask
debug — those combinations make a public URL unsafe.

Cloud imports validate from ``app.py`` so ``gunicorn app:app`` and the direct
entry point enforce the same policy. CORS is also enforced per-request so a
wildcard that slips past boot still emits no ``Access-Control-Allow-Origin``.
"""

from __future__ import annotations

import os
from typing import Mapping, Optional

from config import is_cloud_deploy

_TRUTHY = ("1", "true", "yes", "on")


def secret_key_from_env(env: Mapping[str, str]) -> str:
    return (env.get("SECRET_KEY") or env.get("JWT_SECRET_KEY") or "").strip()


def auth_keys_configured(env: Mapping[str, str]) -> bool:
    return bool(
        (env.get("API_KEY") or "").strip() or (env.get("TENANT_API_KEYS") or "").strip()
    )


def cors_origins_raw(env: Mapping[str, str]) -> str:
    return (env.get("CORS_ORIGINS") or "").strip()


def flask_debug_requested(env: Mapping[str, str]) -> bool:
    debug = (env.get("FLASK_DEBUG") or "").strip().lower()
    if debug in _TRUTHY:
        return True
    flask_env = (env.get("FLASK_ENV") or "").strip().lower()
    return flask_env == "development"


def validate_boot_policy(
    env: Optional[Mapping[str, str]] = None, *, cloud: Optional[bool] = None
) -> None:
    """Abort process start when a public/cloud boot would be unsafe.

    Raises ``SystemExit`` with a FATAL message. Safe to call from tests.
    """
    source = env if env is not None else os.environ
    if cloud is None:
        cloud = is_cloud_deploy(source)
    secret = secret_key_from_env(source)
    if not secret and (cloud or auth_keys_configured(source)):
        raise SystemExit(
            "FATAL: SECRET_KEY is required on cloud deploys and whenever "
            "API_KEY/TENANT_API_KEYS is set. Set a stable SECRET_KEY in "
            "the environment."
        )
    if cloud and cors_origins_raw(source) == "*":
        raise SystemExit(
            "FATAL: CORS_ORIGINS=* is not allowed on cloud deploys. "
            "Set an explicit allow-list or leave CORS_ORIGINS unset."
        )
    if cloud and flask_debug_requested(source):
        raise SystemExit(
            "FATAL: Flask debug is not allowed on cloud deploys. "
            "Unset FLASK_DEBUG and FLASK_ENV."
        )


def persistence_flags(env: Optional[Mapping[str, str]] = None) -> dict:
    """Booleans only — never the secret values (Issue #539)."""
    source = env if env is not None else os.environ
    token = (source.get("GITHUB_TOKEN") or "").strip()
    key = (source.get("REMOTE_BACKUP_ENCRYPTION_KEY") or "").strip()
    dsn = (source.get("SENTRY_DSN") or "").strip()
    return {"remote_backup": bool(token and key), "sentry": bool(dsn)}


def cloud_ops_warnings(
    env: Optional[Mapping[str, str]] = None, *, cloud: Optional[bool] = None
) -> list:
    """Non-fatal operator warnings for a cloud boot without backup/Sentry."""
    source = env if env is not None else os.environ
    if cloud is None:
        cloud = is_cloud_deploy(source)
    if not cloud:
        return []
    flags = persistence_flags(source)
    warnings = []
    if not flags["remote_backup"]:
        warnings.append(
            "WARN: remote SQLite backup is not configured "
            "(GITHUB_TOKEN + REMOTE_BACKUP_ENCRYPTION_KEY). "
            "Ephemeral disks have no remote recovery copy."
        )
    if not flags["sentry"]:
        warnings.append("WARN: SENTRY_DSN is unset — errors will not reach Sentry.")
    return warnings


def cors_allow_origin(
    origins_env: str, request_origin: str, *, cloud: bool
) -> Optional[str]:
    """Return the Access-Control-Allow-Origin value, or None to omit it.

    Cloud deploys never reflect ``*``. Unset CORS_ORIGINS emits nothing
    (same-origin dashboard). Allow-list is exact-match, comma-separated.
    """
    origins = (origins_env or "").strip()
    if not origins:
        return None
    if origins == "*":
        return None if cloud else "*"
    allowed = [item.strip() for item in origins.split(",") if item.strip()]
    origin = (request_origin or "").strip()
    if origin and origin in allowed:
        return origin
    return None
