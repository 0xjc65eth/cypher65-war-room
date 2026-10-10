"""Issue #777: transport reported MAC evidence with each telemetry sample."""

from types import SimpleNamespace

import pytest

import agent.agent as agent


@pytest.mark.parametrize("telemetry", [{}, {"hashrate_hs": 123_000_000_000}])
def test_retry_preserves_reported_mac_timestamp_and_event_id(monkeypatch, telemetry):
    sent = []
    reported_mac = "02:11:22:33:44:55"
    event = agent._build_telemetry_event("192.168.1.10", telemetry, mac=reported_mac)

    def post(path, payload, timeout):
        assert path == "/api/agent/telemetry"
        sent.append(dict(payload))
        return (503, {}) if len(sent) == 1 else (200, {"success": True})

    monkeypatch.setattr(agent, "_post", post)
    monkeypatch.setattr(agent, "time", SimpleNamespace(sleep=lambda _: None))
    assert agent._push_telemetry_event(event) == (200, {"success": True})
    assert len(sent) == 2
    assert sent[0] == sent[1] == event
    assert event["mac"] == reported_mac
    assert len(event["idempotency_key"]) == 32
    assert event["telemetry"]["ts"] > 0
    assert "ts" not in telemetry


def test_same_ip_new_reported_mac_does_not_reuse_previous_event_identity():
    first = agent._build_telemetry_event(
        "192.168.1.10", {"ts": 1234567890}, mac="02:11:22:33:44:55"
    )
    second = agent._build_telemetry_event(
        "192.168.1.10", {"ts": 1234567890}, mac="02:66:77:88:99:AA"
    )
    assert first["ip"] == second["ip"]
    assert first["mac"] != second["mac"]
    assert first["idempotency_key"] != second["idempotency_key"]


def test_legacy_caller_does_not_invent_physical_identity():
    event = agent._build_telemetry_event("192.168.1.10", {})
    assert event["mac"] == ""


@pytest.mark.parametrize(
    "reported_mac,sample,expected_mac",
    [
        ("02:11:22:33:44:55", {}, "02:11:22:33:44:55"),
        ("", {}, ""),
        ("02:11:22:33:44:55", {"mac": "02:66:77:88:99:AA"}, "02:66:77:88:99:AA"),
        ("02:11:22:33:44:55", {"mac": ""}, ""),
        ("02:11:22:33:44:55", {"mac": None}, None),
    ],
)
def test_poll_loop_transports_the_discovered_mac_without_inventing_one(
    monkeypatch, reported_mac, sample, expected_mac
):
    device = {
        "ip": "192.168.1.10",
        "type": "cgminer",
        "mac": reported_mac,
    }
    pushed = []

    class StopLoop(Exception):
        pass

    def post(path, payload, **kwargs):
        if path == "/api/agent/register":
            return 201, {"count": 1, "blocked": []}
        if path == "/api/agent/telemetry":
            pushed.append(payload)
        return 200, {"commands": []}

    def stop(_seconds):
        raise StopLoop

    monkeypatch.setattr(agent, "EXPLICIT_DEVICES", [])
    monkeypatch.setattr(agent, "RESCAN_EVERY", 100)
    monkeypatch.setattr(agent, "scan_lan", lambda: [device])
    monkeypatch.setattr(agent, "_poll_telemetry", lambda _: sample)
    monkeypatch.setattr(agent, "_post", post)
    monkeypatch.setattr(
        agent, "time", SimpleNamespace(time=agent.time.time, sleep=stop)
    )
    with pytest.raises(StopLoop):
        agent._run_main()
    assert len(pushed) == 1
    assert pushed[0]["ip"] == device["ip"]
    assert pushed[0]["mac"] == expected_mac
    assert pushed[0]["telemetry"]["ts"] > 0
