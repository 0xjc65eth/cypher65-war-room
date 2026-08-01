"""
CYPHER65 // Data Layer
======================
Single entry point for writing/querying telemetry metrics.

Design (production-grade but self-contained):
  * **SQLite is the source of truth** — the app already persists everything
    in SQLite (data/war_room.sqlite), so this module never *requires* an
    external service. Zero extra dependencies.
  * **InfluxDB is an optional mirror** (high-frequency short-term metrics).
    It is only used when INFLUXDB_URL/TOKEN/ORG/BUCKET are set AND the
    `influxdb_client` package is importable. If InfluxDB fails, writes fall
    back to SQLite and the failure is recorded — the app never breaks.
  * **Circuit breaker**: after 3 consecutive InfluxDB failures within a
    60s window the mirror is disabled for 5 minutes (then retried).
  * **Warm cache**: recent queries are memoized with a 5-minute TTL.

Honest-telemetry rule (project premise): a write only reports success when
it landed in SQLite (the durable store). The InfluxDB mirror is best-effort.
"""

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("cypher65.data_layer")

DATA_DIR = os.environ.get("CYPHER65_DATA_DIR", "data")
DB_PATH = os.path.join(DATA_DIR, "war_room.sqlite")

INFLUX_ENABLED = bool(os.environ.get("INFLUXDB_URL"))
INFLUX_URL = os.environ.get("INFLUXDB_URL", "http://localhost:8086")
INFLUX_TOKEN = os.environ.get("INFLUXDB_TOKEN", "")
INFLUX_ORG = os.environ.get("INFLUXDB_ORG", "cypher65")
INFLUX_BUCKET = os.environ.get("INFLUXDB_BUCKET", "fleet_metrics")

_INFLUX_CIRCUIT_MAX_FAILS = 3
_INFLUX_CIRCUIT_WINDOW = 60      # seconds
_INFLUX_CIRCUIT_COOLDOWN = 300   # seconds (5 min)
_CACHE_TTL = 300                 # seconds (5 min warm cache)


class CircuitBreaker:
    """Trips after N failures inside a window; reopens after a cooldown."""

    def __init__(self, max_fails: int = _INFLUX_CIRCUIT_MAX_FAILS,
                 window: float = _INFLUX_CIRCUIT_WINDOW,
                 cooldown: float = _INFLUX_CIRCUIT_COOLDOWN):
        self.max_fails = max_fails
        self.window = window
        self.cooldown = cooldown
        self._fail_ts: List[float] = []
        self._open_until = 0.0
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            if time.time() < self._open_until:
                return False
            return True

    def success(self) -> None:
        with self._lock:
            self._fail_ts = []

    def failure(self) -> None:
        with self._lock:
            now = time.time()
            self._fail_ts = [t for t in self._fail_ts if now - t < self.window]
            self._fail_ts.append(now)
            if len(self._fail_ts) >= self.max_fails:
                self._open_until = now + self.cooldown
                log.warning("[data_layer] InfluxDB circuit OPEN for %.0fs "
                            "(%d failures in %.0fs) — mirror disabled",
                            self.cooldown, len(self._fail_ts), self.window)
                self._fail_ts = []


class DataManager:
    """SQLite-first telemetry store with an optional InfluxDB mirror.

    Self-contained: importable with zero external deps. The Influx client is
    created lazily (and only if the package is installed) so the default
    deployment never pulls influxdb_client.
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._influx = None
        self._influx_write_api = None
        self._influx_attempted = False
        self.breaker = CircuitBreaker()
        # Storage init must never crash the caller: an unwritable/absent
        # directory (or a broken DB) degrades to honest False writes below.
        try:
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            self._init_schema()
        except Exception as e:
            log.error("[data_layer] storage init failed for %s: %s — "
                      "writes will report False (honest failure)",
                      self.db_path, e)
        if INFLUX_ENABLED:
            self._ensure_influx()

    # ── SQLite (durable source of truth) ───────────────────────────────
    def _init_schema(self) -> None:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS metric_samples (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        device_id TEXT NOT NULL,
                        metric TEXT NOT NULL,
                        value REAL,
                        ts INTEGER NOT NULL
                    )"""
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_metric_samples "
                    "ON metric_samples(device_id, metric, ts)"
                )
                conn.commit()
            finally:
                conn.close()

    def write_metric(self, device_id: str, metric: str, value: Any,
                     ts: Optional[int] = None) -> bool:
        """Persist one sample. Returns True when SQLite accepted it.

        The InfluxDB mirror is best-effort and never blocks the caller.
        """
        try:
            fv = float(value)
        except (TypeError, ValueError):
            fv = None
        ts = ts or int(time.time())

        # 1) Durable write: SQLite. A storage failure must NEVER take down the
        #    caller (poll loop / scraper) — log and return False (honest).
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path, timeout=10)
                try:
                    conn.execute(
                        "INSERT INTO metric_samples (device_id, metric, value, ts) "
                        "VALUES (?, ?, ?, ?)", (device_id, metric, fv, ts)
                    )
                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:
            log.error("[data_layer] SQLite write failed: %s", e)
            return False

        # 2) Best-effort mirror.
        if self.breaker.allow() and INFLUX_ENABLED:
            try:
                self._ensure_influx()
                if self._influx is not None:
                    self._write_influx(device_id, metric, fv, ts)
                    self.breaker.success()
            except Exception as e:  # mirror failure must never break the app
                self.breaker.failure()
                log.warning("[data_layer] InfluxDB mirror write failed: %s", e)
        return True

    # ── Queries (with warm 5-min cache) ─────────────────────────────────
    _query_cache: Dict[str, Any] = {}
    _query_cache_ts: Dict[str, float] = {}

    def query_recent(self, device_id: str, metric: str,
                     minutes: int = 15) -> List[Dict[str, Any]]:
        """Return samples for a device+metric over the last N minutes,
        oldest first. Cached for 5 minutes (warm cache)."""
        cache_key = f"{device_id}:{metric}:{minutes}"
        now = time.time()
        cached = self._query_cache.get(cache_key)
        if cached is not None and now - self._query_cache_ts.get(cache_key, 0) < _CACHE_TTL:
            return cached

        since = int(now) - minutes * 60
        rows: List[Dict[str, Any]] = []
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(
                    "SELECT ts, value FROM metric_samples "
                    "WHERE device_id=? AND metric=? AND ts>=? "
                    "ORDER BY ts ASC", (device_id, metric, since)
                )
                rows = [{"time": r["ts"], "value": r["value"]} for r in cur.fetchall()]
            finally:
                conn.close()

        self._query_cache[cache_key] = rows
        self._query_cache_ts[cache_key] = time.time()
        return rows

    def query_historical(self, device_id: str, metric: str,
                         hours: int = 24) -> List[Dict[str, Any]]:
        """Long-history query — delegates to the same SQLite table."""
        return self.query_recent(device_id, metric, minutes=hours * 60)

    # ── InfluxDB mirror (optional, lazy) ────────────────────────────────
    def _ensure_influx(self) -> None:
        if self._influx is not None or self._influx_attempted:
            return
        self._influx_attempted = True
        try:
            from influxdb_client import InfluxDBClient
            from influxdb_client.client.write_api import SYNCHRONOUS

            self._influx = InfluxDBClient(
                url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG
            )
            self._influx_write_api = self._influx.write_api(
                write_options=SYNCHRONOUS
            )
            self._influx_sync = SYNCHRONOUS
            log.info("[data_layer] InfluxDB mirror enabled at %s", INFLUX_URL)
        except ImportError:
            log.warning("[data_layer] influxdb_client not installed — "
                        "InfluxDB mirror disabled (SQLite remains active)")
            self._influx = None

    def _write_influx(self, device_id: str, metric: str, value: Any,
                      ts: int) -> None:
        from influxdb_client import Point

        point = Point("miner_stats") \
            .tag("device_id", device_id) \
            .field(metric, float(value)) \
            .time(ts, write_precision="s")
        self._influx_write_api.write(bucket=INFLUX_BUCKET, record=point)


# ── Module-level singleton (matches the app's shared-state pattern) ─────
# Created LAZILY so importing the module (tests, tooling) never touches the
# filesystem or the runtime DB.
_manager: Optional[DataManager] = None


def get_manager() -> DataManager:
    global _manager
    if _manager is None:
        _manager = DataManager()
    return _manager


def write_metric(device_id: str, metric: str, value: Any) -> bool:
    return get_manager().write_metric(device_id, metric, value)


def query_recent(device_id: str, metric: str, minutes: int = 15) -> List[Dict[str, Any]]:
    return get_manager().query_recent(device_id, metric, minutes)


def query_historical(device_id: str, metric: str, hours: int = 24) -> List[Dict[str, Any]]:
    return get_manager().query_historical(device_id, metric, hours)
