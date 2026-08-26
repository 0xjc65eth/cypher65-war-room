"""Unit tests for one-time physical-command confirmations."""

from services.command_confirmation import consume_confirmation, issue_confirmation


def test_confirmation_is_bound_to_exact_command_and_single_use(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "confirmations.sqlite"))
    issued = issue_confirmation(
        "tenant-a", "device-1", "restart", {"delay": 5}, now=100
    )

    assert consume_confirmation(
        issued["confirmation_token"],
        "tenant-a",
        "device-1",
        "restart",
        {"delay": 5},
        now=101,
    )
    assert not consume_confirmation(
        issued["confirmation_token"],
        "tenant-a",
        "device-1",
        "restart",
        {"delay": 5},
        now=102,
    )


def test_confirmation_rejects_changed_target_or_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "confirmations.sqlite"))
    issued = issue_confirmation(
        "tenant-a", "device-1", "pause", {"mode": "safe"}, now=100
    )

    assert not consume_confirmation(
        issued["confirmation_token"],
        "tenant-a",
        "device-2",
        "pause",
        {"mode": "safe"},
        now=101,
    )
    assert not consume_confirmation(
        issued["confirmation_token"],
        "tenant-a",
        "device-1",
        "pause",
        {"mode": "fast"},
        now=101,
    )


def test_confirmation_expires_fail_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "confirmations.sqlite"))
    issued = issue_confirmation("tenant-a", "device-1", "restart", now=100)

    assert not consume_confirmation(
        issued["confirmation_token"],
        "tenant-a",
        "device-1",
        "restart",
        now=issued["expires_at"] + 1,
    )
