"""Issue #636: device removal cannot interrupt other miners' telemetry."""

import pytest

import agent.agent as agent


@pytest.mark.parametrize("removed", [True, False])
def test_removed_device_does_not_crash_poll_loop_or_return_on_rescan(
    monkeypatch, removed
):
    devices = [
        {"ip": "192.168.1.50", "type": "bitaxe"},
        {"ip": "192.168.1.60", "type": "cgminer"},
    ]
    polls = []
    pulls = []
    registrations = []
    sleeps = []

    class StopLoop(Exception):
        pass

    def post(path, payload, **kwargs):
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
    monkeypatch.setattr(agent.time, "sleep", sleep)
    with pytest.raises(StopLoop):
        agent.main()

    expected = [devices[0]["ip"], devices[1]["ip"]]
    expected += [devices[1]["ip"]] if removed else expected[:]
    assert polls == expected
    assert len(pulls) == 2
    assert len(registrations) == (3 if removed else 1)
