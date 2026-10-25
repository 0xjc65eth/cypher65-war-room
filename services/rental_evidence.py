"""Tenant-scoped destination-pool observations for operator-declared rentals.

These are sampled pool API readings, not seller reports or proof of continuous
delivery. The pool's hashrate averaging window is unknown. No financial action
is performed by this module. See docs/RENTAL_EVIDENCE.md for the trust boundary.
"""

import csv
import io
import json
import math
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from typing import Any

from services.db import get_db

SOURCE = "parasite_pool_worker"
SOURCE_BASE = "https://parasite.space/api/user/"
MAX_POINTS = 10000
RETENTION_S = 30 * 86400
MAX_SOURCES = 250
MAX_BINDINGS = 50
LIMITATIONS = [
    "Destination-pool API readings, not seller-reported hashrate.",
    "Rental contract and exclusive worker association are operator declarations.",
    "Pool averaging window and hashrate measurement timestamp are unknown.",
    "Collection intervals are not averaging windows or proof of continuous delivery.",
    "Collection requires an active wallet polling session; gaps invalidate alerts.",
    "Evidence retention: 30 days, at most 10000 points per rental across revisions.",
]


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the additive ledger schema, idempotently.

    Example: ``ensure_schema(conn); conn.commit()`` at application bootstrap.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS rental_evidence_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL, address TEXT NOT NULL,
            worker_key TEXT NOT NULL, worker_value TEXT NOT NULL,
            last_seen REAL NOT NULL,
            UNIQUE(tenant_id,address,worker_key,worker_value)
        );
        CREATE TABLE IF NOT EXISTS rental_evidence_bindings (
            tenant_id TEXT NOT NULL, provider TEXT NOT NULL, rental_id TEXT NOT NULL,
            source_id INTEGER NOT NULL, revision INTEGER NOT NULL,
            config TEXT NOT NULL, created_at REAL NOT NULL, enabled INTEGER NOT NULL,
            PRIMARY KEY(tenant_id,provider,rental_id)
        );
        CREATE TABLE IF NOT EXISTS rental_evidence_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL, provider TEXT NOT NULL, rental_id TEXT NOT NULL,
            revision INTEGER NOT NULL, observed_at REAL NOT NULL, point TEXT NOT NULL,
            UNIQUE(tenant_id,provider,rental_id,revision,observed_at)
        );
        CREATE INDEX IF NOT EXISTS idx_rental_evidence_points
            ON rental_evidence_points(tenant_id,provider,rental_id,revision,observed_at);
        CREATE TABLE IF NOT EXISTS rental_evidence_alerts (
            tenant_id TEXT NOT NULL, provider TEXT NOT NULL, rental_id TEXT NOT NULL,
            revision INTEGER NOT NULL, window_start REAL NOT NULL, alert TEXT NOT NULL,
            UNIQUE(tenant_id,provider,rental_id,revision,window_start)
        );
    """
    )


def validate_identity(provider: str, rental_id: str) -> None:
    """Reject unsupported providers and unbounded rental references.

    Example: ``validate_identity('mrr', '123456')``.
    """
    if provider not in {"mrr", "braiins"} or not re.fullmatch(
        r"[A-Za-z0-9_.:-]{1,128}", rental_id
    ):
        raise ValueError("Provedor ou referência de aluguel inválidos.")


def _number(value: Any, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Informe valores numéricos válidos.")
    result = float(value)
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError("Valor fora dos limites permitidos.")
    return result


def _sources(conn: sqlite3.Connection, tenant_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM rental_evidence_sources WHERE tenant_id=? "
        "ORDER BY last_seen DESC,id LIMIT ?",
        (tenant_id, MAX_SOURCES),
    ).fetchall()
    return [
        dict(
            id=r["id"],
            address=r["address"],
            worker_key=r["worker_key"],
            worker_value=r["worker_value"],
            last_seen=r["last_seen"],
            label=f'{r["address"]} · {r["worker_key"]}={r["worker_value"]}',
            source=SOURCE,
        )
        for r in rows
    ]


def configure(tenant_id: str, provider: str, rental_id: str, body: dict) -> dict:
    """Save a fully explicit rule and exclusive worker declaration.

    Example: ``configure('tenant-a', 'mrr', '1', {'source_id': 1,
    'contract_th': 100, 'threshold_pct': 90, 'duration_s': 300,
    'max_gap_s': 30, 'exclusive_worker': True})``. No defaults activate alerts.
    """
    validate_identity(provider, rental_id)
    if not isinstance(body, dict) or body.get("exclusive_worker") is not True:
        raise ValueError("Declare um worker exclusivo para este aluguel.")
    source_id = _number(body.get("source_id"), 1, 2**53 - 1)
    contract = _number(body.get("contract_th"), 1e-9, 1e9)
    threshold = _number(body.get("threshold_pct"), 1e-9, 100)
    duration = _number(body.get("duration_s"), 15, 86400)
    gap = _number(body.get("max_gap_s"), 15, min(3600, duration))
    if any(v != int(v) for v in (source_id, duration, gap)):
        raise ValueError("Fonte e intervalos devem ser inteiros.")
    now = time.time()
    with closing(get_db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        source = conn.execute(
            "SELECT * FROM rental_evidence_sources WHERE tenant_id=? AND id=?",
            (tenant_id, int(source_id)),
        ).fetchone()
        if source is None or now - source["last_seen"] > gap:
            raise ValueError("Fonte inexistente ou desatualizada; conecte a wallet.")
        current = conn.execute(
            "SELECT revision,enabled FROM rental_evidence_bindings "
            "WHERE tenant_id=? AND provider=? AND rental_id=?",
            (tenant_id, provider, rental_id),
        ).fetchone()
        active = conn.execute(
            "SELECT COUNT(*) FROM rental_evidence_bindings WHERE tenant_id=? AND enabled=1",
            (tenant_id,),
        ).fetchone()[0]
        retained = conn.execute(
            "SELECT COUNT(*) FROM rental_evidence_bindings WHERE tenant_id=?",
            (tenant_id,),
        ).fetchone()[0]
        if (active >= MAX_BINDINGS and not (current and current["enabled"])) or (
            retained >= MAX_BINDINGS and not current
        ):
            raise ValueError("Limite de 50 referências de aluguel atingido.")
        # A worker cannot simultaneously substantiate two different rentals.
        duplicate = conn.execute(
            "SELECT 1 FROM rental_evidence_bindings WHERE tenant_id=? AND source_id=? "
            "AND enabled=1 AND NOT(provider=? AND rental_id=?)",
            (tenant_id, source_id, provider, rental_id),
        ).fetchone()
        if duplicate:
            raise ValueError("Este worker já está vinculado a outro aluguel.")
        config = dict(
            provider=provider,
            rental_id=rental_id,
            source_id=int(source_id),
            address=source["address"],
            worker_key=source["worker_key"],
            worker_value=source["worker_value"],
            contract_th=contract,
            threshold_pct=threshold,
            duration_s=int(duration),
            max_gap_s=int(gap),
            exclusive_worker=True,
            declaration="operator",
            revision=current["revision"] + 1 if current else 1,
            created_at=now,
        )
        conn.execute(
            "INSERT INTO rental_evidence_bindings VALUES(?,?,?,?,?,?,?,1) "
            "ON CONFLICT(tenant_id,provider,rental_id) DO UPDATE SET "
            "source_id=excluded.source_id,revision=excluded.revision,config=excluded.config,"
            "created_at=excluded.created_at,enabled=1",
            (
                tenant_id,
                provider,
                rental_id,
                int(source_id),
                config["revision"],
                json.dumps(config),
                now,
            ),
        )
    return config


def disable(tenant_id: str, provider: str, rental_id: str) -> None:
    """Disable collection without erasing retained evidence.

    Example: ``disable('tenant-a', 'mrr', '1')``.
    """
    validate_identity(provider, rental_id)
    with closing(get_db()) as conn, conn:
        conn.execute(
            "UPDATE rental_evidence_bindings SET enabled=0 WHERE tenant_id=? "
            "AND provider=? AND rental_id=?",
            (tenant_id, provider, rental_id),
        )


def evaluate(config: dict | None, points: list[dict], now: float) -> dict:
    """Evaluate consecutive sampled readings; missing data never means zero.

    Example: ``evaluate(config, points, time.time())['status']``.
    """
    result = dict(
        status="unconfigured",
        last_observed_at=None,
        window_start=None,
        window_end=None,
        samples=0,
        observed_th=None,
        delivery_pct=None,
        alert=None,
    )
    if not config:
        return result
    result["status"] = "missing"
    if not points:
        return result
    latest = points[-1]
    result["last_observed_at"] = latest["observed_at"]
    if now - latest["observed_at"] > config["max_gap_s"]:
        result["status"] = "stale"
        return result
    if latest["quality"] != "observed":
        return result
    result.update(
        observed_th=latest["hashrate_th"],
        delivery_pct=latest["delivery_pct"],
        status="healthy",
    )
    if latest["delivery_pct"] >= config["threshold_pct"]:
        return result
    streak: list[dict] = []
    for point in reversed(points):
        if (
            point["quality"] != "observed"
            or point["delivery_pct"] >= config["threshold_pct"]
        ):
            break
        if (
            streak
            and streak[-1]["observed_at"] - point["observed_at"] > config["max_gap_s"]
        ):
            break
        streak.append(point)
    start = streak[-1]["observed_at"]
    result.update(
        window_start=start,
        window_end=latest["observed_at"],
        samples=len(streak),
        status="insufficient" if len(streak) < 2 else "watching",
    )
    if len(streak) >= 2 and latest["observed_at"] - start >= config["duration_s"]:
        result["status"] = "under_delivery"
        result["alert"] = {
            key: config[key] for key in ("threshold_pct", "duration_s", "max_gap_s")
        }
        result["alert"].update(observed_at=latest["observed_at"], window_start=start)
    return result


def alert_message(event: dict) -> str:
    """Format an explicit sampled-reading warning for the operator.

    Example: ``alert_message(event)`` preserves threshold, duration and gaps.
    """
    return (
        f"Aluguel {event['provider']}:{event['rental_id']}: leituras do worker "
        f"do pool abaixo de {event['threshold_pct']:g}% por pelo menos "
        f"{event['duration_s']} s, com lacunas de até {event['max_gap_s']} s. "
        "Contrato/vínculo declarados pelo operador; amostragem não comprova "
        "entrega contínua e a janela média do pool não é informada."
    )


def _points(
    conn: sqlite3.Connection,
    tenant_id: str,
    provider: str,
    rental_id: str,
    revision: int | None = None,
) -> list[dict]:
    rows = conn.execute(
        "SELECT point FROM rental_evidence_points WHERE tenant_id=? AND provider=? "
        "AND rental_id=? AND observed_at>=? AND (? IS NULL OR revision=?) "
        "ORDER BY observed_at DESC LIMIT ?",
        (
            tenant_id,
            provider,
            rental_id,
            time.time() - RETENTION_S,
            revision,
            revision,
            MAX_POINTS,
        ),
    ).fetchall()
    return [json.loads(r[0]) for r in reversed(rows)]


def collect(
    tenant_id: str,
    address: str,
    payload: Any,
    collection_started_at: float,
    collection_completed_at: float,
) -> list[dict]:
    """Persist one actual upstream retrieval, not browser reads/cache replays.

    Example: ``collect('tenant-a', address, raw_pool_payload, started, completed)``.
    Call only with original fetch metadata; matching is exact and case-sensitive.
    """
    if not tenant_id or not re.fullmatch(r"[A-Za-z0-9]{14,100}", address):
        return []
    now = time.time()
    if not all(
        math.isfinite(v) for v in (collection_started_at, collection_completed_at)
    ):
        return []
    if not 0 < collection_started_at <= collection_completed_at <= now + 1:
        return []
    workers = payload.get("workerData") if isinstance(payload, dict) else None
    valid_payload = isinstance(workers, list)
    oversized = (
        isinstance(payload, dict) and payload.get("_rental_quality") == "oversized"
    ) or (valid_payload and len(workers) > MAX_SOURCES)
    if oversized:
        valid_payload = False
    workers = (
        [w for w in (workers or []) if isinstance(w, dict)] if valid_payload else []
    )
    events: list[dict] = []
    with closing(get_db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "DELETE FROM rental_evidence_sources WHERE tenant_id=? AND last_seen<? "
            "AND id NOT IN (SELECT source_id FROM rental_evidence_bindings WHERE tenant_id=?)",
            (tenant_id, now - RETENTION_S, tenant_id),
        )
        sources = _sources(conn, tenant_id)
        known = {(s["address"], s["worker_key"], s["worker_value"]) for s in sources}
        for worker in workers[:MAX_SOURCES]:
            key = "id" if worker.get("id") not in (None, "") else "name"
            value = str(worker.get(key) or "")
            if not value or len(value) > 128 or any(ord(c) < 32 for c in value):
                continue
            identity = (address, key, value)
            if identity not in known and len(known) >= MAX_SOURCES:
                continue
            conn.execute(
                "INSERT INTO rental_evidence_sources(tenant_id,address,worker_key,worker_value,last_seen) "
                "VALUES(?,?,?,?,?) ON CONFLICT(tenant_id,address,worker_key,worker_value) "
                "DO UPDATE SET last_seen=MAX(last_seen,excluded.last_seen)",
                (tenant_id, address, key, value, collection_completed_at),
            )
            known.add(identity)
        bindings = conn.execute(
            "SELECT config FROM rental_evidence_bindings WHERE tenant_id=? AND enabled=1 "
            "AND source_id IN (SELECT id FROM rental_evidence_sources WHERE tenant_id=? AND address=?)",
            (tenant_id, tenant_id, address),
        ).fetchall()
        for row in bindings:
            config = json.loads(row[0])
            # Never backfill a new rule with a response retrieved before it existed.
            if collection_started_at < config["created_at"]:
                continue
            latest = conn.execute(
                "SELECT MAX(observed_at) FROM rental_evidence_points WHERE tenant_id=? "
                "AND provider=? AND rental_id=? AND revision=?",
                (
                    tenant_id,
                    config["provider"],
                    config["rental_id"],
                    config["revision"],
                ),
            ).fetchone()[0]
            if latest is not None and collection_completed_at <= latest:
                continue
            matches = [
                w
                for w in workers
                if str(w.get(config["worker_key"], "")) == config["worker_value"]
            ]
            quality = (
                "oversized"
                if oversized
                else (
                    "api_error"
                    if not valid_payload
                    else "unmapped" if not matches else "ambiguous"
                )
            )
            hr = None
            if len(matches) == 1:
                try:
                    hr = _number(matches[0].get("hashrate"), 0, 1e25)
                    quality = "observed"
                except ValueError:
                    quality = "missing"
            point = dict(
                observed_at=collection_completed_at,
                source=SOURCE,
                source_url=SOURCE_BASE + address,
                address=address,
                worker_key=config["worker_key"],
                worker_value=config["worker_value"],
                collection_started_at=collection_started_at,
                collection_completed_at=collection_completed_at,
                upstream_measured_at=None,
                averaging_window_s=None,
                hashrate_th=None if hr is None else hr / 1e12,
                quality=quality,
                delivery_pct=(
                    None if hr is None else hr / 1e12 / config["contract_th"] * 100
                ),
                provider=config["provider"],
                rental_id=config["rental_id"],
                revision=config["revision"],
                config=config,
            )
            cursor = conn.execute(
                "INSERT OR IGNORE INTO rental_evidence_points(tenant_id,provider,rental_id,revision,observed_at,point) "
                "VALUES(?,?,?,?,?,?)",
                (
                    tenant_id,
                    config["provider"],
                    config["rental_id"],
                    config["revision"],
                    collection_completed_at,
                    json.dumps(point),
                ),
            )
            if not cursor.rowcount:
                continue
            identity_params = (tenant_id, config["provider"], config["rental_id"])
            conn.execute(
                "DELETE FROM rental_evidence_points WHERE tenant_id=? AND provider=? AND rental_id=? "
                "AND (observed_at<? OR id NOT IN (SELECT id FROM rental_evidence_points "
                "WHERE tenant_id=? AND provider=? AND rental_id=? ORDER BY observed_at DESC LIMIT ?))",
                (*identity_params, now - RETENTION_S, *identity_params, MAX_POINTS),
            )
            points = _points(conn, *identity_params, config["revision"])
            verdict = evaluate(config, points, now)
            if verdict["alert"]:
                alert_insert = conn.execute(
                    "INSERT OR IGNORE INTO rental_evidence_alerts VALUES(?,?,?,?,?,?)",
                    (
                        *identity_params,
                        config["revision"],
                        verdict["window_start"],
                        json.dumps(verdict["alert"]),
                    ),
                )
                if alert_insert.rowcount:
                    event = dict(
                        provider=config["provider"],
                        rental_id=config["rental_id"],
                        revision=config["revision"],
                        **verdict["alert"],
                    )
                    # Point, dedup and durable feed/history commit together.
                    # An insert error rolls all of them back, permitting retry.
                    conn.execute(
                        "INSERT INTO alerts(ts,severity,category,message,device_id,alert_type,"
                        "is_acknowledged,active,meta,tenant_id) VALUES(?, 'WARN','rental_delivery',"
                        "?,'','rental_delivery',0,1,?,?)",
                        (
                            int(event["observed_at"]),
                            alert_message(event),
                            json.dumps(event),
                            tenant_id,
                        ),
                    )
                    conn.execute(
                        "INSERT INTO alert_history(ts,alert_type,device_id,severity,action_taken,tenant_id) "
                        "VALUES(?,'rental_delivery','','WARN',?,?)",
                        (int(event["observed_at"]), alert_message(event), tenant_id),
                    )
                    events.append(event)
        conn.execute(
            "DELETE FROM rental_evidence_alerts WHERE tenant_id=? AND window_start<?",
            (tenant_id, now - RETENTION_S),
        )
    return events


def summarize_coverage(points: list[dict]) -> dict:
    """Summarize sample quality without treating missing values as zero."""
    total = len(points or [])
    valid = sum(
        1
        for point in points or []
        if isinstance(point, dict)
        and point.get("quality") == "observed"
        and point.get("hashrate_th") is not None
        and point.get("delivery_pct") is not None
        and math.isfinite(_coverage_number(point.get("hashrate_th")))
        and math.isfinite(_coverage_number(point.get("delivery_pct")))
    )
    stamps = [
        point.get("observed_at")
        for point in points or []
        if isinstance(point, dict)
        and isinstance(point.get("observed_at"), (int, float))
        and math.isfinite(point["observed_at"])
    ]
    start_at = min(stamps) if stamps else None
    end_at = max(stamps) if stamps else None
    return {
        "status": "AVAILABLE" if total else "NO DATA",
        "observation_count": total,
        "observed_count": valid,
        "missing_count": total - valid,
        "observed_pct": (valid / total * 100.0) if total else None,
        "window_start": start_at,
        "window_end": end_at,
    }


def _coverage_number(value: Any) -> float:
    """Coerce already-validated JSON numeric values for coverage aggregation."""
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return float("nan")


def read(tenant_id: str, provider: str, rental_id: str) -> dict:
    """Return retained evidence and a fresh verdict for a single tenant.

    Example: ``read('tenant-a', 'mrr', '1')['evaluation']['status']``.
    """
    validate_identity(provider, rental_id)
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT config,enabled FROM rental_evidence_bindings WHERE tenant_id=? AND provider=? AND rental_id=?",
            (tenant_id, provider, rental_id),
        ).fetchone()
        binding = json.loads(row["config"]) if row and row["enabled"] else None
        points = (
            _points(conn, tenant_id, provider, rental_id, binding["revision"])
            if binding
            else []
        )
        return dict(
            success=True,
            binding=binding,
            sources=_sources(conn, tenant_id),
            evaluation=evaluate(binding, points, time.time()),
            coverage=summarize_coverage(points),
            points=points[-20:],
            limitations=LIMITATIONS,
            retention_days=30,
            max_points=MAX_POINTS,
        )


def export_csv(tenant_id: str, provider: str, rental_id: str) -> str:
    """Export all retained revisions with source, UTC timestamps and rule.

    Example: ``export_csv('tenant-a', 'mrr', '1')``. Empty readings stay empty.
    """
    validate_identity(provider, rental_id)
    columns = [
        "provider",
        "rental_id",
        "revision",
        "source",
        "source_url",
        "address",
        "worker_key",
        "worker_value",
        "observed_at_utc",
        "collection_started_at_utc",
        "collection_completed_at_utc",
        "upstream_measured_at",
        "averaging_window_s",
        "quality",
        "hashrate_th",
        "delivery_pct",
        "contract_th",
        "threshold_pct",
        "duration_s",
        "max_gap_s",
        "declaration",
        "exclusive_worker",
        "retention_days",
        "max_retained_points",
        "limitations",
    ]
    with closing(get_db()) as conn:
        points = _points(conn, tenant_id, provider, rental_id)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for point in points:
        row = {key: point.get(key) for key in columns}
        for key in ("observed_at", "collection_started_at", "collection_completed_at"):
            row[key + "_utc"] = datetime.fromtimestamp(
                point[key], timezone.utc
            ).isoformat()
        row.update(
            {
                key: point["config"].get(key)
                for key in (
                    "contract_th",
                    "threshold_pct",
                    "duration_s",
                    "max_gap_s",
                    "declaration",
                    "exclusive_worker",
                )
            }
        )
        row.update(
            retention_days=30,
            max_retained_points=MAX_POINTS,
            limitations=" | ".join(LIMITATIONS),
        )
        # Spreadsheet formulas must never execute operator/pool supplied identifiers.
        row = {
            key: (
                "'" + value
                if isinstance(value, str)
                and value.lstrip().startswith(("=", "+", "-", "@"))
                else value
            )
            for key, value in row.items()
        }
        writer.writerow(row)
    return output.getvalue()
