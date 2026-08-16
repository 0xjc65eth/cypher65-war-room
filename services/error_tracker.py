"""Local error-rate telemetry (Issue #176) — the $0 half of observability.

Complements Sentry for ANY deployment (self-host included): every
ERROR/CRITICAL log record is bucketed per hour into SQLite (``error_metrics``)
carrying the active request_id, so the Admin panel renders an error-rate
trend + recent errors WITHOUT any third-party dependency. When SENTRY_DSN is
configured the SAME records also flow to Sentry via its own LoggingIntegration
— this module never calls the Sentry SDK directly.

Design (same discipline as services/pool_metrics):
- Pure-DB module (no app imports) — app.py wires the connection factory.
- ``ErrorMetricsHandler``: a logging.Handler attached to the root logger that
  records ERROR/CRITICAL records (level-gated; WARNING/INFO are NEVER
  recorded). A DB failure inside emit() must never break the logging path.
- ``record_error()``: upsert per (hour_bucket, module, func, message) —
  repeated identical errors within the same hour increment ``count`` instead
  of spamming rows.
- Retention: 7 days (same window as pool_metrics).
- Honest telemetry: only REAL logged errors; an empty table means zero errors.
"""

import logging
import time
from typing import Callable, List, Optional

log = logging.getLogger("cypher65.error_tracker")

# Retenção: 7 dias de buckets por hora ≈ 168 linhas por módulo — irrelevante
# em disco, cobre bem a janela de investigação de incidente.
ERROR_METRICS_RETENTION_DAYS = 7
# Mensagens truncadas no row (a coluna é TEXT; o cap evita rows gigantes de
# stack traces repetidos no mesmo bucket horário).
_MESSAGE_MAX = 200
_FIELD_MAX = 64

ERROR_METRICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS error_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hour_ts INTEGER NOT NULL,
    module TEXT NOT NULL DEFAULT '',
    func TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    level TEXT NOT NULL DEFAULT 'ERROR',
    count INTEGER NOT NULL DEFAULT 1,
    last_ts INTEGER NOT NULL,
    last_request_id TEXT NOT NULL DEFAULT '',
    UNIQUE(hour_ts, module, func, message)
)
"""

ERROR_METRICS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_error_metrics_hour ON error_metrics(hour_ts)"
)

# Installed handler (module-level singleton — install() is idempotent).
_installed: Optional["ErrorMetricsHandler"] = None


def ensure_table(conn) -> None:
    """Create error_metrics (+ index) if missing. Idempotent, safe on boot."""
    c = conn.cursor()
    c.execute(ERROR_METRICS_SCHEMA)
    c.execute(ERROR_METRICS_INDEX)
    conn.commit()


def record_error(
    conn,
    module: str = "",
    func: str = "",
    message: str = "",
    level: str = "ERROR",
    request_id: str = "",
    ts: Optional[int] = None,
) -> int:
    """Bucket one error record into its hour and increment the count.

    Args:
        conn: sqlite3 connection (row_factory optional).
        module/func/message/level: log-record fields (truncated to sane caps).
        request_id: active correlation id (Issue #124) for the last event.
        ts: error timestamp (unix). Defaults to now.

    Returns:
        Number of rows touched (1 = inserted or incremented). Never raises —
        callers (the logging handler) treat any failure as non-fatal.
    """
    now = int(ts if ts is not None else time.time())
    hour_ts = now // 3600 * 3600
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO error_metrics "
            "(hour_ts, module, func, message, level, count, last_ts, last_request_id) "
            "VALUES (?, ?, ?, ?, ?, 1, ?, ?) "
            "ON CONFLICT(hour_ts, module, func, message) DO UPDATE SET "
            "count = count + 1, last_ts = excluded.last_ts, "
            "last_request_id = excluded.last_request_id",
            (
                hour_ts,
                (module or "")[:_FIELD_MAX],
                (func or "")[:_FIELD_MAX],
                (message or "")[:_MESSAGE_MAX],
                (level or "ERROR")[:8],
                now,
                (request_id or "")[:_FIELD_MAX],
            ),
        )
        # Retention purge (cheap, runs once per error — same cadence as the
        # pool_metrics sampler discipline).
        cutoff = now - ERROR_METRICS_RETENTION_DAYS * 86400
        c.execute("DELETE FROM error_metrics WHERE hour_ts < ?", (cutoff,))
        conn.commit()
        return c.rowcount or 1
    except Exception as e:
        log.warning("[error_tracker] record failed: %s", e)
        return 0


def fetch_error_rate(conn, hours: int = 24, limit: int = 60) -> dict:
    """Aggregate error metrics for the admin view.

    Args:
        conn: sqlite3 connection.
        hours: lookback window (default 24h).
        limit: cap for the ``recent`` error list (default 60).

    Returns:
        Dict with ``total`` (error events in window), ``peak_per_hour``,
        ``buckets`` (one entry per hour that HAS errors: ``ts`` + ``errors``
        + per-module breakdown), ``top_modules`` (across the window) and
        ``recent`` (last_error-id rows with request_id, newest first).
        Empty buckets is HONEST — zero errors means zero entries, never a
        fabricated 0 row.
    """
    hours = max(1, min(hours, 7 * 24))
    cutoff = int(time.time()) - hours * 3600
    c = conn.cursor()

    # Per-hour totals + module breakdown (one pass, grouped).
    rows = c.execute(
        "SELECT hour_ts, module, SUM(count) AS total "
        "FROM error_metrics WHERE hour_ts >= ? "
        "GROUP BY hour_ts, module ORDER BY hour_ts ASC",
        (cutoff,),
    ).fetchall()

    buckets: List[dict] = []
    top_mods: dict = {}
    peak = 0
    total = 0
    for r in rows:
        hour = r["hour_ts"]
        mod = r["module"] or "?"
        cnt = r["total"] or 0
        top_mods[mod] = top_mods.get(mod, 0) + cnt
        if not buckets or buckets[-1]["ts"] != hour:
            buckets.append({"ts": hour, "errors": 0, "modules": []})
        buckets[-1]["errors"] += cnt
        buckets[-1]["modules"].append({"module": mod, "count": cnt})
        total += cnt
        if buckets[-1]["errors"] > peak:
            peak = buckets[-1]["errors"]

    # Recent error rows (newest first) — the audit table with request_id.
    recent_rows = c.execute(
        "SELECT hour_ts, module, func, message, level, count, last_ts, "
        "last_request_id FROM error_metrics ORDER BY last_ts DESC LIMIT ?",
        (max(1, min(limit, 500)),),
    ).fetchall()
    recent = [dict(r) for r in recent_rows]

    top_modules = sorted(
        ({"module": m, "count": n} for m, n in top_mods.items()),
        key=lambda x: x["count"],
        reverse=True,
    )
    return {
        "hours": hours,
        "total": total,
        "peak_per_hour": peak,
        "buckets": buckets,
        "top_modules": top_modules[:10],
        "recent": recent,
    }


def purge_error_metrics(conn, days: int = ERROR_METRICS_RETENTION_DAYS) -> int:
    """Delete error-metric rows older than ``days``. Returns rows deleted."""
    cutoff = int(time.time()) - days * 86400
    c = conn.cursor()
    c.execute("DELETE FROM error_metrics WHERE hour_ts < ?", (cutoff,))
    conn.commit()
    return c.rowcount


class ErrorMetricsHandler(logging.Handler):
    """Root-logger handler that buckets ERROR/CRITICAL records into SQLite.

    Level-gated at construction (default ERROR): WARNING/INFO/debug records
    never touch the DB. ``emit`` never raises — a broken DB must not break
    the logging path (a second try/except catches even the recovery branch).
    """

    def __init__(self, conn_factory: Callable, level: int = logging.ERROR):
        super().__init__(level=level)
        self._conn_factory = conn_factory
        # Re-entrancy guard: a record_* failure self-logs a WARNING that
        # would otherwise re-enter this handler (and the degradation handler)
        # → unbounded recursion. Guarded emit swallows the recursion record.
        self._in_emit = False

    def emit(self, record: logging.LogRecord) -> None:
        if self._in_emit:
            return
        self._in_emit = True
        try:
            try:
                from services.observability import get_request_id

                rid = get_request_id()
            except Exception:
                rid = ""
            conn = self._conn_factory()
            try:
                record_error(
                    conn,
                    module=record.name,
                    func=record.funcName or "",
                    message=record.getMessage(),
                    level=record.levelname,
                    request_id=rid,
                )
            finally:
                conn.close()
        except Exception:
            # Honest telemetry: logging can never be broken by telemetry.
            pass
        finally:
            self._in_emit = False


def install(conn_factory: Callable, level: int = logging.ERROR) -> ErrorMetricsHandler:
    """Attach the ErrorMetricsHandler to the root logger (idempotent).

    app.py wires the real get_db factory here at boot. Returns the handler so
    callers can remove it (tests) — module-level singleton: calling install()
    twice returns the SAME handler without duplicating emission.
    """
    global _installed
    if _installed is not None:
        return _installed
    handler = ErrorMetricsHandler(conn_factory, level=level)
    logging.getLogger().addHandler(handler)
    _installed = handler
    return handler


def uninstall() -> None:
    """Remove the installed handler (test teardown). Safe no-op otherwise."""
    global _installed
    if _installed is not None:
        logging.getLogger().removeHandler(_installed)
        _installed = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  WARNING / degradation bucket (Issue #202)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# The error bucket is ERROR/CRITICAL-only BY DESIGN (honest error rate: an
# empty error_metrics means ZERO errors). Degradation lives in its OWN table
# so the two trends never mix — every WARNING record lands here. The hot-path
# `except: pass` sites converted in Issue #202 now emit WARNINGs instead of
# dying silent, so a provider hiccup that used to be invisible is now counted
# and the admin panel surfaces spike/sustained badges (the $0 rate alert).
# Same discipline as the error bucket: pure-DB, level-gated handler, and a DB
# failure inside emit() never breaks the logging path.

DEGRADATION_METRICS_RETENTION_DAYS = 7
# Spike badge: >= this many WARNINGs in a single hour = degradation spike.
DEGRADATION_SPIKE_PER_HOUR = 100

DEGRADATION_METRICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS degradation_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hour_ts INTEGER NOT NULL,
    module TEXT NOT NULL DEFAULT '',
    func TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    level TEXT NOT NULL DEFAULT 'WARNING',
    count INTEGER NOT NULL DEFAULT 1,
    last_ts INTEGER NOT NULL,
    last_request_id TEXT NOT NULL DEFAULT '',
    UNIQUE(hour_ts, module, func, message)
)
"""

DEGRADATION_METRICS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_degradation_metrics_hour "
    "ON degradation_metrics(hour_ts)"
)

_degradation_handler: Optional["DegradationMetricsHandler"] = None
# Honest since-boot counter (GIL-protected int): how many WARNINGs fired since
# the process started — retention-independent, unlike the table's 7d window.
_degradation_total = 0


def ensure_degradation_table(conn) -> None:
    """Create degradation_metrics (+ index) if missing. Idempotent."""
    c = conn.cursor()
    c.execute(DEGRADATION_METRICS_SCHEMA)
    c.execute(DEGRADATION_METRICS_INDEX)
    conn.commit()


def record_degradation(
    conn,
    module: str = "",
    func: str = "",
    message: str = "",
    level: str = "WARNING",
    request_id: str = "",
    ts: Optional[int] = None,
) -> int:
    """Bucket one WARNING/degradation record into its hour (Issue #202).

    Same upsert + retention discipline as record_error, plus the module-level
    since-boot counter. Never raises — telemetry can't break the app.
    """
    global _degradation_total
    now = int(ts if ts is not None else time.time())
    hour_ts = now // 3600 * 3600
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO degradation_metrics "
            "(hour_ts, module, func, message, level, count, last_ts, last_request_id) "
            "VALUES (?, ?, ?, ?, ?, 1, ?, ?) "
            "ON CONFLICT(hour_ts, module, func, message) DO UPDATE SET "
            "count = count + 1, last_ts = excluded.last_ts, "
            "last_request_id = excluded.last_request_id",
            (
                hour_ts,
                (module or "")[:_FIELD_MAX],
                (func or "")[:_FIELD_MAX],
                (message or "")[:_MESSAGE_MAX],
                (level or "WARNING")[:8],
                now,
                (request_id or "")[:_FIELD_MAX],
            ),
        )
        cutoff = now - DEGRADATION_METRICS_RETENTION_DAYS * 86400
        c.execute("DELETE FROM degradation_metrics WHERE hour_ts < ?", (cutoff,))
        conn.commit()
        _degradation_total += 1
        return c.rowcount or 1
    except Exception as e:
        log.warning("[error_tracker] record_degradation failed: %s", e)
        return 0


def fetch_degradation_rate(conn, hours: int = 24, limit: int = 60) -> dict:
    """Aggregate WARNING/degradation metrics for the admin view (Issue #202).

    Mirrors fetch_error_rate (buckets/modules/recent with request_id) and adds
    the rate-alert flags:
      - ``spike``: peak_per_hour >= DEGRADATION_SPIKE_PER_HOUR (100/h)
      - ``sustained``: spike AND warnings in >= 2 DISTINCT hours
      - ``total_since_boot``: the module counter (retention-independent)
    Empty buckets is HONEST — zero warnings means zero entries.
    """
    hours = max(1, min(hours, 7 * 24))
    cutoff = int(time.time()) - hours * 3600
    c = conn.cursor()

    rows = c.execute(
        "SELECT hour_ts, module, SUM(count) AS total "
        "FROM degradation_metrics WHERE hour_ts >= ? "
        "GROUP BY hour_ts, module ORDER BY hour_ts ASC",
        (cutoff,),
    ).fetchall()

    buckets: List[dict] = []
    top_mods: dict = {}
    peak = 0
    total = 0
    for r in rows:
        hour = r["hour_ts"]
        mod = r["module"] or "?"
        cnt = r["total"] or 0
        top_mods[mod] = top_mods.get(mod, 0) + cnt
        if not buckets or buckets[-1]["ts"] != hour:
            buckets.append({"ts": hour, "errors": 0, "modules": []})
        buckets[-1]["errors"] += cnt
        buckets[-1]["modules"].append({"module": mod, "count": cnt})
        total += cnt
        if buckets[-1]["errors"] > peak:
            peak = buckets[-1]["errors"]

    recent_rows = c.execute(
        "SELECT hour_ts, module, func, message, level, count, last_ts, "
        "last_request_id FROM degradation_metrics ORDER BY last_ts DESC LIMIT ?",
        (max(1, min(limit, 500)),),
    ).fetchall()
    recent = [dict(r) for r in recent_rows]

    top_modules = sorted(
        ({"module": m, "count": n} for m, n in top_mods.items()),
        key=lambda x: x["count"],
        reverse=True,
    )
    spike = peak >= DEGRADATION_SPIKE_PER_HOUR
    return {
        "hours": hours,
        "total": total,
        "peak_per_hour": peak,
        "buckets": buckets,
        "top_modules": top_modules[:10],
        "recent": recent,
        "spike": spike,
        "sustained": spike and len(buckets) >= 2,
        "total_since_boot": _degradation_total,
    }


def purge_degradation_metrics(
    conn, days: int = DEGRADATION_METRICS_RETENTION_DAYS
) -> int:
    """Delete degradation rows older than ``days``. Returns rows deleted."""
    cutoff = int(time.time()) - days * 86400
    c = conn.cursor()
    c.execute("DELETE FROM degradation_metrics WHERE hour_ts < ?", (cutoff,))
    conn.commit()
    return c.rowcount


class DegradationMetricsHandler(logging.Handler):
    """Root-logger handler that buckets WARNING records (Issue #202).

    Level-gated at WARNING construction, PLUS an explicit levelno check: the
    handler level only filters BELOW its threshold, so ERROR/CRITICAL records
    would otherwise also reach emit() and pollute the degradation table (the
    error table owns ERROR+; INFO is noise). ``emit`` never raises — same
    double-try/except discipline as ErrorMetricsHandler.
    """

    def __init__(self, conn_factory: Callable, level: int = logging.WARNING):
        super().__init__(level=level)
        self._conn_factory = conn_factory
        # Re-entrancy guard: record_degradation() failure self-logs a WARNING
        # that would re-enter THIS handler (WARNING passes its own gate — the
        # error handler is protected only by its ERROR level) → unbounded
        # recursion on a broken DB. Guarded emit swallows the recursion record.
        self._in_emit = False

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno != logging.WARNING:
            return  # ERROR/CRITICAL belong to error_metrics, INFO is noise
        if self._in_emit:
            return  # recursion guard (self-log of a failed write)
        self._in_emit = True
        try:
            try:
                from services.observability import get_request_id

                rid = get_request_id()
            except Exception:
                rid = ""
            conn = self._conn_factory()
            try:
                record_degradation(
                    conn,
                    module=record.name,
                    func=record.funcName or "",
                    message=record.getMessage(),
                    level=record.levelname,
                    request_id=rid,
                )
            finally:
                conn.close()
        except Exception:
            # Honest telemetry: logging can never be broken by telemetry.
            pass
        finally:
            self._in_emit = False


def install_degradation(
    conn_factory: Callable, level: int = logging.WARNING
) -> "DegradationMetricsHandler":
    """Attach the DegradationMetricsHandler to the root logger (idempotent).

    app.py wires get_db here at boot alongside install(). Module-level
    singleton: a second call returns the SAME handler without duplicating.
    """
    global _degradation_handler
    if _degradation_handler is not None:
        return _degradation_handler
    handler = DegradationMetricsHandler(conn_factory, level=level)
    logging.getLogger().addHandler(handler)
    _degradation_handler = handler
    return handler


def uninstall_degradation() -> None:
    """Remove the degradation handler (test teardown). Safe no-op otherwise."""
    global _degradation_handler
    if _degradation_handler is not None:
        logging.getLogger().removeHandler(_degradation_handler)
        _degradation_handler = None
