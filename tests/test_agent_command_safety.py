"""Security regressions for Issue #645 agent command delivery."""

import sqlite3
import time

import pytest

from app import app
from axe_fleet.registry import DeviceRegistry
from axe_fleet.routes import AGENT_COMMAND_TTL_S
from services.auth import create_token


@pytest.fixture
def client(monkeypatch):
    secret = "agent-command-test-secret-0123456789abcdef"
    saved = app.config.get("JWT_SECRET_KEY")
    app.config["TESTING"] = True
    app.config["JWT_SECRET_KEY"] = secret
    monkeypatch.setenv("SECRET_KEY", secret)
    with app.test_client() as flask_client:
        yield flask_client
    if saved is None:
        app.config.pop("JWT_SECRET_KEY", None)
    else:
        app.config["JWT_SECRET_KEY"] = saved


@pytest.fixture
def registry(tmp_path):
    db_path = str(tmp_path / "commands.sqlite")

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    instance = DeviceRegistry(get_db)
    instance.ensure_tables()
    return instance


@pytest.fixture
def agent_token():
    return create_token(
        subject="acme",
        ttl=86400,
        extra_claims={"agent": True, "role": "agent"},
    )


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _active_device(registry, ip="192.168.10.20", device_type="bitaxe"):
    device = registry.upsert_agent_device(
        ip, tenant_id="acme", info={"type": device_type, "firmware": "AxeOS"}
    )
    registry.save_agent_telemetry(
        device["id"], {"hashrate_hs": 1_000_000_000}, tenant_id="acme"
    )
    return registry.get_device(device["id"], tenant_id="acme")


def _pull(client, token, registry):
    from unittest.mock import patch

    with patch("axe_fleet.routes._registry", registry):
        return client.post("/api/agent/commands/pull", headers=_headers(token), json={})


def _command_row(registry, command_id):
    conn = registry._get_db()
    row = conn.execute(
        "SELECT status, result FROM axe_agent_commands WHERE id=?", (command_id,)
    ).fetchone()
    conn.close()
    return dict(row)


def test_pull_blocks_when_physical_policy_is_disabled(
    client, agent_token, registry, monkeypatch
):
    monkeypatch.delenv("ENABLE_PHYSICAL_COMMANDS", raising=False)
    device = _active_device(registry)
    queued = registry.enqueue_agent_command(device["id"], "restart", tenant_id="acme")

    response = _pull(client, agent_token, registry)

    assert response.get_json()["commands"] == []
    assert _command_row(registry, queued["id"]) == {
        "status": "blocked",
        "result": "deployment_policy_disabled",
    }


def test_pull_expires_old_command(client, agent_token, registry, monkeypatch):
    monkeypatch.setenv("ENABLE_PHYSICAL_COMMANDS", "true")
    device = _active_device(registry)
    queued = registry.enqueue_agent_command(device["id"], "restart", tenant_id="acme")
    conn = registry._get_db()
    conn.execute(
        "UPDATE axe_agent_commands SET created_at=? WHERE id=?",
        (int(time.time()) - AGENT_COMMAND_TTL_S - 1, queued["id"]),
    )
    conn.commit()
    conn.close()

    response = _pull(client, agent_token, registry)

    assert response.get_json()["commands"] == []
    assert _command_row(registry, queued["id"]) == {
        "status": "expired",
        "result": "command_expired",
    }


def test_pull_blocks_offline_device(client, agent_token, registry, monkeypatch):
    monkeypatch.setenv("ENABLE_PHYSICAL_COMMANDS", "true")
    device = registry.upsert_agent_device("192.168.10.21", tenant_id="acme")
    queued = registry.enqueue_agent_command(device["id"], "restart", tenant_id="acme")

    response = _pull(client, agent_token, registry)

    assert response.get_json()["commands"] == []
    assert _command_row(registry, queued["id"])["result"] == "device_not_ready"


def test_ack_requires_json_boolean(client, agent_token, registry, monkeypatch):
    from unittest.mock import patch

    monkeypatch.setenv("ENABLE_PHYSICAL_COMMANDS", "true")
    device = _active_device(registry)
    queued = registry.enqueue_agent_command(device["id"], "restart", tenant_id="acme")
    pull = _pull(client, agent_token, registry)
    assert pull.get_json()["commands"][0]["id"] == queued["id"]

    with patch("axe_fleet.routes._registry", registry):
        invalid = client.post(
            f"/api/agent/commands/{queued['id']}/ack",
            headers=_headers(agent_token),
            json={"success": "false"},
        )
        valid = client.post(
            f"/api/agent/commands/{queued['id']}/ack",
            headers=_headers(agent_token),
            json={"success": False, "result": "device refused"},
        )

    assert invalid.status_code == 400
    assert valid.status_code == 200
    assert _command_row(registry, queued["id"])["status"] == "failed"
