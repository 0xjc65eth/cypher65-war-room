"""Issue #636: device removal cannot interrupt other miners' telemetry."""

from types import SimpleNamespace

import pytest

import agent.agent as agent


@pytest.mark.parametrize("failure", [None, 503, TimeoutError])
def test_presence_worker_is_independent_of_rescan_and_poll(monkeypatch, failure):
    """A fake clock covers 150s without any device or scan completion."""
    clock = [1000.0]
    calls = []

    class StopEvent:
        def is_set(self):
            return False

        def wait(self, seconds):
            assert seconds == 30
            clock[0] += seconds
            return clock[0] >= 1180

    def post(path, payload, timeout):
        calls.append((clock[0], path, payload, timeout))
        if failure is TimeoutError:
            raise TimeoutError("fixture")
        return failure or 200, {}

    monkeypatch.setattr(agent, "_post", post)
    monkeypatch.setattr(agent, "POLL_INTERVAL", 300)
    monkeypatch.setattr(agent, "RESCAN_EVERY", 100)
    agent._heartbeat_loop(StopEvent())
    assert [call[0] for call in calls] == [1000, 1030, 1060, 1090, 1120, 1150]
    assert all(call[1:] == ("/api/agent/heartbeat", {}, 3.0) for call in calls)


def test_heartbeat_worker_starts_before_scan_and_stops_on_failure(monkeypatch):
    events = []

    class StopEvent:
        def set(self):
            events.append("stop")

    class Worker:
        def __init__(self, *, target, args, name, daemon):
            assert target is agent._heartbeat_loop
            assert isinstance(args[0], StopEvent)
            assert name == "agent-heartbeat" and daemon

        def start(self):
            events.append("start")

        def join(self, timeout):
            assert timeout == 4
            events.append("join")

    def scan():
        events.append("scan")
        raise RuntimeError("fixture scan interruption")

    monkeypatch.setattr(agent, "AGENT_TOKEN", "fixture-token")
    monkeypatch.setattr(
        agent, "threading", SimpleNamespace(Event=StopEvent, Thread=Worker)
    )
    monkeypatch.setattr(agent, "scan_lan", scan)
    with pytest.raises(RuntimeError, match="fixture scan interruption"):
        agent.main()
    assert events == ["start", "scan", "stop", "join"]


@pytest.mark.parametrize("removed", [True, False])
def test_removed_device_does_not_crash_poll_loop_or_return_on_rescan(
    monkeypatch, removed
):
    devices = [
        {"ip": "192.168.1.50", "type": "bitaxe", "mac": "02:00:00:00:01:50"},
        {"ip": "192.168.1.60", "type": "cgminer"},
    ]
    polls = []
    pulls = []
    registrations = []
    sleeps = []

    class StopLoop(Exception):
        pass

    def post(path, payload, **kwargs):
        if path == "/api/agent/heartbeat":
            return 200, {"success": True}
        if path == "/api/agent/register":
            registrations.append(payload["devices"])
            blocked = (
                [{"ip": devices[0]["ip"]}] if removed and len(registrations) > 1 else []
            )
            return 200, {
                "count": len(payload["devices"]) - len(blocked),
                "blocked": blocked,
            }
        if path == "/api/agent/telemetry":
            if payload["ip"] == devices[0]["ip"]:
                return 410, {"removed": removed}
            return 200, {}
        assert path == "/api/agent/commands/pull"
        pulls.append(path)
        return 200, {"commands": []}

    def poll(device):
        polls.append(device["ip"])
        return {"hashrate_hs": 1}

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise StopLoop

    monkeypatch.setattr(agent, "AGENT_TOKEN", "fixture-token")
    monkeypatch.setattr(agent, "EXPLICIT_DEVICES", [])
    monkeypatch.setattr(agent, "RESCAN_EVERY", 1)
    monkeypatch.setattr(agent, "scan_lan", lambda: devices)
    monkeypatch.setattr(agent, "_poll_telemetry", poll)
    monkeypatch.setattr(agent, "_post", post)
    monkeypatch.setattr(
        agent, "time", SimpleNamespace(time=agent.time.time, sleep=sleep)
    )
    with pytest.raises(StopLoop):
        agent.main()

    expected = [devices[0]["ip"], devices[1]["ip"]]
    expected += [devices[1]["ip"]] if removed else expected[:]
    assert polls == expected
    assert len(pulls) == 2
    # Tombstoned IPs stay in blocked_ips and are not re-registered (Issue #638).
    assert len(registrations) == 1


def test_main_loop_skips_macless_bitaxe_while_polling_verified_peer(monkeypatch):
    devices = [
        {"ip": "192.168.1.50", "type": "bitaxe"},
        {"ip": "192.168.1.60", "type": "cgminer"},
    ]
    polled = []
    pushed = []

    class StopLoop(Exception):
        pass

    def post(path, payload, **kwargs):
        if path == "/api/agent/register":
            return 200, {"count": 2, "blocked": []}
        if path == "/api/agent/telemetry":
            pushed.append(payload["ip"])
        return 200, {"commands": []}

    def stop(_seconds):
        raise StopLoop

    monkeypatch.setattr(agent, "AGENT_TOKEN", "fixture-token")
    monkeypatch.setattr(agent, "EXPLICIT_DEVICES", [])
    monkeypatch.setattr(agent, "RESCAN_EVERY", 100)
    monkeypatch.setattr(agent, "scan_lan", lambda: devices)
    monkeypatch.setattr(
        agent, "_poll_telemetry", lambda dev: polled.append(dev["ip"]) or {}
    )
    monkeypatch.setattr(agent, "_post", post)
    monkeypatch.setattr(
        agent, "time", SimpleNamespace(time=agent.time.time, sleep=stop)
    )
    with pytest.raises(StopLoop):
        agent.main()
    assert polled == ["192.168.1.60"]
    assert pushed == ["192.168.1.60"]
