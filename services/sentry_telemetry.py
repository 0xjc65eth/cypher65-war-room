"""Sentry error tracking (Issue #176) — env-gated, PII-safe, request_id-correlated.

Extracted from the inline block in app.py into a testable module. Everything
here is a SAFE NO-OP when Sentry is not configured (no DSN) or when the
sentry-sdk package is not installed — honest telemetry rule: a monitoring
dependency must never break the app boot or the request path.

Responsibilities:
- ``get_sentry_config()``: parse SENTRY_DSN / SENTRY_TRACES_SAMPLE_RATE /
  SENTRY_ENVIRONMENT / SENTRY_RELEASE ONCE (guarded — a misconfigured env
  var must never 500 the boot or the index route).
- ``compute_release()``: SENTRY_RELEASE env → git short SHA (best-effort,
  cached) → fallback ``cypher65-war-room@dev``.
- ``init_sentry()``: lazy ``import sentry_sdk``; registers ``before_send``
  + ``before_breadcrumb`` that inject the ACTIVE request_id (ContextVar from
  services.observability — Issue #124) into every event/breadcrumb, so an
  operator can trace an error end-to-end in Sentry (webhook → DB → poll).
- ``set_request_tag(rid)``: per-request/worker-pass tag, called from the
  Flask before_request hook and from _do_poll.
- ``sentry_active()``: whether init succeeded (drives the admin badge).

PII safety: ``send_default_pii=False`` + ``include_local_variables=False``
explicit — no emails, no local variables in events (buyer emails are already
masked at source — Issue #116). `before_send` only ADDS the correlation id;
it never strips anything else.
"""

import logging
import os
import subprocess
import threading

log = logging.getLogger("cypher65.sentry")

# Parsed once at import (guarded). Reused by the backend init AND by the
# index route (frontend SDK injection) — the env var is never re-parsed per
# request, so a broken value can never 500 the dashboard.
_DSN = os.environ.get("SENTRY_DSN", "").strip()
_TRACES_SAMPLE_RATE = 0.1
try:
    _TRACES_SAMPLE_RATE = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1"))
except (TypeError, ValueError):
    log.warning("[monitor] SENTRY_TRACES_SAMPLE_RATE inválido — usando 0.1")

_ENVIRONMENT = os.environ.get("SENTRY_ENVIRONMENT", "").strip()
if not _ENVIRONMENT:
    try:
        from config import is_cloud_deploy

        _ENVIRONMENT = "cloud" if is_cloud_deploy() else "self-hosted"
    except Exception:
        _ENVIRONMENT = "self-hosted"

# Release: SENTRY_RELEASE env → git short SHA → dev fallback. Cached once so
# the subprocess never runs per error (also never per boot-loop).
_release_lock = threading.Lock()
_release_cache: str | None = None
_DEV_RELEASE = "cypher65-war-room@dev"


def compute_release() -> str:
    """Best-effort release id for Sentry release tracking.

    Priority: SENTRY_RELEASE env (operator pins a deploy) → git short SHA
    (``cypher65-war-room@<sha>``) → ``cypher65-war-room@dev``. The subprocess
    argv is fully static (no shell=True) — nosec B603: nothing user-supplied
    is ever interpolated into the command.
    """
    global _release_cache
    with _release_lock:
        if _release_cache is not None:
            return _release_cache
        env_rel = os.environ.get("SENTRY_RELEASE", "").strip()
        if env_rel:
            _release_cache = env_rel
            return _release_cache
        try:
            out = subprocess.run(  # nosec B603 — static argv, no shell
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                timeout=2,
                check=False,
            )
            sha = out.stdout.decode("utf-8", "replace").strip()
            if sha and len(sha) <= 40:
                _release_cache = f"cypher65-war-room@{sha}"
                return _release_cache
        except Exception:
            pass
        _release_cache = _DEV_RELEASE
        return _release_cache


def get_sentry_config() -> dict:
    """Safe snapshot of the parsed Sentry config (no secrets beyond the DSN
    the operator already configured in the env — same value the index route
    injects into the frontend SDK)."""
    return {
        "dsn": _DSN,
        "traces_sample_rate": _TRACES_SAMPLE_RATE,
        "environment": _ENVIRONMENT,
        "release": compute_release(),
        "enabled": bool(_DSN),
    }


# Whether sentry_sdk.init succeeded (module-level, set by init_sentry).
_active = False
_active_lock = threading.Lock()


def sentry_active() -> bool:
    """True when Sentry init succeeded (DSN set + SDK importable)."""
    return _active


def _inject_request_id(event: dict, hint: dict) -> dict:
    """before_send: tag + extra the active request_id onto every event.

    The request_id comes from the same ContextVar the JSON logs use (Issue
    #124), so the Sentry event correlates 1:1 with the log line. Returns the
    event unchanged when no id is active (background/boot errors).
    """
    try:
        from services.observability import get_request_id

        rid = get_request_id()
        if rid:
            event.setdefault("tags", {})["request_id"] = rid
            event.setdefault("extra", {})["request_id"] = rid
    except Exception:
        pass
    return event


def _inject_breadcrumb_request_id(crumb: dict, hint: dict) -> dict:
    """before_breadcrumb: stamp the active request_id onto every breadcrumb."""
    try:
        from services.observability import get_request_id

        rid = get_request_id()
        if rid:
            crumb.setdefault("data", {})["request_id"] = rid
    except Exception:
        pass
    return crumb


def init_sentry() -> bool:
    """Initialize the Sentry SDK when SENTRY_DSN is set (lazy import).

    Never a hard dependency: without the DSN or without the package the app
    boots normally. Returns True when the SDK is live.
    """
    global _active
    if not _DSN:
        return False
    with _active_lock:
        if _active:
            return True
        try:
            import sentry_sdk  # noqa: WPS433 — lazy, optional dependency

            sentry_sdk.init(
                dsn=_DSN,
                traces_sample_rate=_TRACES_SAMPLE_RATE,
                release=compute_release(),
                environment=_ENVIRONMENT,
                send_default_pii=False,  # explicit PII guard (Issue #116)
                include_local_variables=False,  # never ship local vars
                before_send=_inject_request_id,
                before_breadcrumb=_inject_breadcrumb_request_id,
            )
            _active = True
            log.info(
                "[monitor] Sentry enabled (dsn=set, env=%s, release=%s)",
                _ENVIRONMENT,
                compute_release(),
            )
            return True
        except Exception as e:
            # ImportError (package absent) or SDK init failure — never fatal.
            log.warning("[monitor] Sentry init skipped: %s", e)
            return False


def set_request_tag(rid: str) -> None:
    """Tag the current Sentry scope with the request_id (safe no-op when
    inactive). Called from attach_request_id (Flask before_request) and from
    the poll pass — the tag follows the scope of that request/thread."""
    if not _active or not rid:
        return
    try:
        import sentry_sdk  # noqa: WPS433 — lazy, optional dependency

        sentry_sdk.set_tag("request_id", rid)
    except Exception:
        pass
