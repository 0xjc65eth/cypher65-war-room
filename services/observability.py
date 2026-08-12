"""Observability helpers (Issue #30) — cost-$0 observability layer.

- ``setup_logging()``: switches the root logger to a JSON structured
  formatter when ``LOG_JSON=1`` (no extra dependency — pure stdlib).
- ``boot_health()``: emits a structured boot health line (modules,
  schema version, worker name) once the app is ready.
- ``build_logger()``: returns a named logger with the shared format.

Design decisions (matriz de vendors em docs/DEPLOYMENT_OPS.md):
- Sentry: env-gated (``SENTRY_DSN``) — já integrado em app.py.
- Datadog/NewRelic: paid tiers → não adotados (regra de ouro CFO/CRO $0).
- OpenTelemetry: SDK é grátis, mas precisa de collector/backend — documentado
  como caminho futuro (exporter OTLP pode apontar pro Sentry).
- Logs JSON estruturados: $0, funciona com qualquer aggregator futuro
  (Sentry, Loki, CloudWatch, Datadog agent, etc).

IMPORTANTE (honest telemetry): logar em JSON NUNCA pode quebrar o app ou
os testes. Default é texto; JSON só quando LOG_JSON=1. O formatter é 100%
stdlib (json + traceback), zero dependência nova.
"""

import json
import logging
import os
import time
import traceback

log = logging.getLogger("cypher65")

# Extra fields set once per process (worker name, service) — avoids
# recomputing them on every record.
_EXTRA = {
    "service": "cypher65-war-room",
    "worker": os.environ.get("WORKER_NAME", "") or "",
}


class JsonFormatter(logging.Formatter):
    """Minimal JSON formatter — one line per record, greppable with jq.

    Keeps the legacy ``[module.funcName] message`` prefix inside ``message``
    so existing [fetch]/[persist]/[poll_loop] diagnostics stay searchable,
    and adds structured ``level``/``ts``/``module`` fields for aggregators.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "module": record.name,
            "func": record.funcName or "",
            "line": record.lineno,
            "message": record.getMessage(),
        }
        payload.update(_EXTRA)
        # Real LogRecords carry exc_info as a (type, value, tb) tuple; a bare
        # ``True`` (or anything non-iterable) must never crash the formatter.
        exc = getattr(record, "exc_info", None)
        if exc and isinstance(exc, tuple) and len(exc) == 3:
            try:
                payload["exc"] = "".join(traceback.format_exception(*exc))
            except (TypeError, ValueError):
                pass
        # Optional structured context via `extra={"ctx": {...}}`.
        ctx = getattr(record, "ctx", None)
        if isinstance(ctx, dict) and ctx:
            payload["ctx"] = ctx
        try:
            return json.dumps(payload, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            # Never break logging on unserializable payloads.
            return json.dumps({
                "ts": payload["ts"], "level": "ERROR",
                "module": record.name, "message": "log serialization failed",
            })


def setup_logging() -> bool:
    """Configure root logging. Returns True when JSON mode is active.

    Deterministic: replaces ALL existing handlers with one fresh
    StreamHandler so the format is never ambiguous regardless of what
    pytest / the runtime installed earlier.
    """
    json_mode = os.environ.get("LOG_JSON", "").strip() == "1"
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler()
    root.addHandler(handler)
    if json_mode:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)sZ %(levelname)s [%(module)s.%(funcName)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        ))
    root.setLevel(logging.INFO)
    return json_mode


def build_logger(name: str = "cypher65") -> logging.Logger:
    """Named logger sharing the configured root format."""
    return logging.getLogger(name)


def boot_health(extra: dict | None = None) -> None:
    """Emit one structured boot-health line after init completes.

    Honest telemetry: only real, measured values — never invented ones.
    """
    ctx = dict(extra or {})
    ctx.setdefault("event", "boot")
    ctx.setdefault("ts", int(time.time()))
    log.info("[boot] ready", extra={"ctx": ctx})
