"""Issue #735: actual SQLite telemetry reads stay constant, not a latency SLO.

Synthetic rows are bulk fixtures, not ingestion or physical hardware evidence.
Both real Flask routes use the real registry; transport fails closed.
"""

import json
import re
import sqlite3
import time

from flask import Flask
import pytest

from axe_fleet import routes
from axe_fleet.registry import DeviceRegistry
from scripts.measure_fleet_scale import deny_network
from services.auth import create_token


@pytest.mark.parametrize("endpoint", ["summary", "health"])
@pytest.mark.parametrize("count", [0, 1, 100, 500])
@pytest.mark.parametrize("measured", [False, True], ids=["absent", "measured"])
def test_telemetry_query_count_is_constant(
    tmp_path, monkeypatch, endpoint, count, measured
):
    db_path = str(tmp_path / "query_contract.sqlite")
    statements = []

    def connect():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        connection.set_trace_callback(statements.append)
        return connection

    secret = "735-query-contract-secret-0123456789"
    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("SECRET_KEY", secret)
    monkeypatch.setenv("API_KEY", "735-query-contract-synthetic-key")
    monkeypatch.setenv("TENANT_API_KEYS", "")
    monkeypatch.setenv("REVOKED_TOKENS_DB", "0")
    registry = DeviceRegistry(connect)
    registry.ensure_tables()
    now = int(time.time())
    with connect() as connection:
        connection.executemany(
            "INSERT INTO axe_devices "
            "(id, name, tenant_id, agent_managed, status, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    f"synthetic-{index}",
                    f"Synthetic {index:04d}",
                    "query-contract",
                    1,
                    "ONLINE" if measured else "OFFLINE",
                    now,
                )
                for index in range(count)
            ],
        )
        if measured:
            connection.executemany(
                "INSERT INTO axe_telemetry (device_id, tenant_id, ts, payload) "
                "VALUES (?, ?, ?, ?)",
                [
                    (
                        f"synthetic-{index}",
                        "query-contract",
                        now,
                        json.dumps({"hashrate_hs": 100_000_000_000, "ts": now}),
                    )
                    for index in range(count)
                ],
            )
    flask_app = Flask("trusted_batch_query_contract")
    flask_app.config.update(TESTING=True, SECRET_KEY=secret, JWT_SECRET_KEY=secret)
    flask_app.register_blueprint(routes.axe_fleet_bp, url_prefix="/api/axe-fleet")
    monkeypatch.setattr(routes, "_registry", registry)
    with flask_app.app_context():
        token = create_token("query-contract", extra_claims={"role": "viewer"})

    statements.clear()
    with deny_network() as attempts:
        response = flask_app.test_client().get(
            f"/api/axe-fleet/{endpoint}",
            headers={"Authorization": f"Bearer {token}"},
            environ_overrides={"REMOTE_ADDR": "203.0.113.2"},
        )
    assert response.status_code == 200
    payload = response.get_json()
    stats = payload if endpoint == "summary" else payload["fleet_stats"]
    assert stats["total_devices"] == count
    assert stats["total_hashrate_hs"] == (count * 100_000_000_000 if measured else 0)
    assert attempts == []
    telemetry_reads = [
        statement
        for statement in statements
        if re.search(r"\bSELECT\b.*\bFROM\s+axe_telemetry\b", statement, re.I | re.S)
    ]
    assert len(telemetry_reads) == 1, telemetry_reads
