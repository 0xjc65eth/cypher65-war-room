"""Issue #669: agent presence never rejuvenates scan or miner evidence."""

from types import SimpleNamespace

import axe_fleet.routes as routes


def test_presence_only_preserves_scan_receipt_and_tenant_isolation(monkeypatch):
    clock = [1000]
    monkeypatch.setattr(routes, "time", SimpleNamespace(time=lambda: clock[0]))
    monkeypatch.setattr(routes, "_agent_heartbeats", {})
    routes._store_agent_heartbeat("a", {"result": "no_devices", "found": 0})
    routes._store_agent_heartbeat("b", {"result": "ok", "found": 2})
    original = routes.agent_presence("a")["scan"]
    assert original["received_at"] == 1000
    for tick in (1030, 1060, 1090, 1120, 1150):
        clock[0] = tick
        routes._store_agent_heartbeat("a", {})
        assert routes.agent_presence("a") == {
            "alive": True,
            "last_seen": tick,
            "scan": original,
        }
    assert routes.agent_presence("b")["alive"] is False
    assert routes.agent_presence("b")["scan"]["found"] == 2
    clock[0] = 1250
    assert routes.agent_presence("a")["alive"] is False
    routes._store_agent_heartbeat("a", {"result": "ok", "found": 1})
    assert routes.agent_presence("a")["scan"]["received_at"] == 1250


def test_presence_before_first_completed_scan_is_not_a_zero_scan(monkeypatch):
    monkeypatch.setattr(routes, "_agent_heartbeats", {})
    routes._store_agent_heartbeat("new-agent", {})
    info = routes.agent_presence("new-agent")
    assert info["alive"] is True
    assert info["scan"] is None
