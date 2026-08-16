"""
CYPHER65 // pool metrics persistence — Issue #17
================================================
Histórico PERSISTENTE das métricas de operação do pool (sessions, polls/seg,
fila, workers, total polls/errors) em SQLite, amostrado periodicamente (60s
por padrão). O Admin CFO passa a ver TENDÊNCIAS (últimas 24h) em vez de só o
valor em memória do momento — que zerava a cada restart.

Módulo puro de DB (sem imports do app) — o app.py faz o wiring: a thread
sampler chama ``_POLL_POOL.stats()`` + ``queue_depth()`` +
``auto_exclude_alert_counters()`` e grava via ``record_snapshot``. Os testes
exercitam as funções diretamente com um conn de scratch.
"""

import logging
import time
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("cypher65.pool_metrics")

# Retenção: a linha de tendência precisa de ~24-48h; 7 dias dá margem folgada
# sem crescer o arquivo (60s * 1440/dia * 7 ≈ 10k linhas).
POOL_METRICS_RETENTION_DAYS = 7
# Cadência padrão do sampler (segundos) — critério de aceite pede ~60s.
POOL_METRICS_INTERVAL = 60

POOL_METRICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS pool_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL UNIQUE,
    sessions_active INTEGER,
    scheduled INTEGER,
    queue_pending INTEGER,
    workers_alive INTEGER,
    pool_size INTEGER,
    total_polls INTEGER,
    total_errors INTEGER,
    polls_per_sec REAL,
    uptime_secs REAL,
    last_poll_ts REAL,
    stalled INTEGER,
    webhook_queue INTEGER,
    auto_exclude_total INTEGER
)
"""

POOL_METRICS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_pool_metrics_ts ON pool_metrics(ts)"
)

# Columnas que vêm direto do stats() do PollWorkerPool.
_STATS_KEYS = (
    "sessions_active",
    "scheduled",
    "queue_pending",
    "workers_alive",
    "pool_size",
    "total_polls",
    "total_errors",
    "polls_per_sec",
    "uptime_secs",
    "last_poll_ts",
    "stalled",
)


def record_snapshot(conn, stats: Dict[str, Any], ts: Optional[int] = None) -> int:
    """Persist one pool-health snapshot row.

    Args:
        conn: sqlite3 connection (row_factory optional).
        stats: dict from PollWorkerPool.stats() plus the extras the app wires
            in — ``webhook_queue`` (int) and ``auto_exclude_total`` (int).
        ts: sample timestamp (unix). Defaults to now.

    Returns:
        Number of rows written (0 when the same second was already recorded —
        UNIQUE(ts) + INSERT OR IGNORE dedupes a double-fired sampler tick).
    """
    sample_ts = int(ts if ts is not None else time.time())
    row = {
        "ts": sample_ts,
        "stalled": 1 if stats.get("stalled") else 0,
        "webhook_queue": int(stats.get("webhook_queue") or 0),
        "auto_exclude_total": int(stats.get("auto_exclude_total") or 0),
    }
    for key in _STATS_KEYS:
        row[key] = stats.get(key)

    cols = ", ".join(row.keys())
    placeholders = ", ".join("?" for _ in row)
    c = conn.cursor()
    c.execute(
        f"INSERT OR IGNORE INTO pool_metrics ({cols}) VALUES ({placeholders})",
        tuple(row.values()),
    )
    conn.commit()
    return c.rowcount


def fetch_history(conn, hours: int = 24, limit: Optional[int] = None) -> List[dict]:
    """Fetch the most recent pool-metrics rows (oldest → newest).

    Args:
        conn: sqlite3 connection.
        hours: lookback window in hours (default 24).
        limit: optional cap on the number of rows returned (most recent).

    Returns:
        List of dict rows (ts + every metric column) sorted by ts ascending.
    """
    cutoff = int(time.time()) - hours * 3600
    sql = "SELECT * FROM pool_metrics WHERE ts >= ? " "ORDER BY ts ASC"
    params: list = [cutoff]
    if limit:
        # Most recent `limit` rows, then re-sort ascending for the chart.
        sql = "SELECT * FROM pool_metrics WHERE ts >= ? " "ORDER BY ts DESC LIMIT ?"
        params.append(int(limit))
    c = conn.cursor()
    rows = [dict(r) for r in c.execute(sql, params)]
    if limit:
        rows.reverse()
    return rows


def purge_pool_metrics(conn, days: int = POOL_METRICS_RETENTION_DAYS) -> int:
    """Delete pool-metrics rows older than ``days`` (retention window).

    Returns:
        Number of deleted rows.
    """
    cutoff = int(time.time()) - days * 86400
    c = conn.cursor()
    c.execute("DELETE FROM pool_metrics WHERE ts < ?", (cutoff,))
    conn.commit()
    return c.rowcount


def sampler_loop(
    stats_fn: Callable[[], Dict[str, Any]],
    conn_fn: Callable[[], Any],
    interval: float = POOL_METRICS_INTERVAL,
    jitter: float = 5.0,
    stop_event: Optional[Any] = None,
) -> None:
    """Daemon loop: snapshot pool health every ``interval`` seconds.

    A short boot jitter (default 5s) avoids a fleet of instances stampeding
    the DB at the same instant. A failing ``stats_fn``/DB write logs a warning
    and skips the tick — the loop never dies (same pattern as
    _rate_limit_persist_loop).
    """
    time.sleep(jitter)
    while True:
        try:
            stats = stats_fn()
            conn = conn_fn()
            try:
                record_snapshot(conn, stats)
            finally:
                conn.close()
        except Exception as e:
            log.warning("[pool_metrics] sampler tick error: %s", e)
        if stop_event is not None:
            if stop_event.wait(interval):
                return
        else:
            time.sleep(interval)
