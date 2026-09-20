"""Issue #636: exercise the installer's real serializers, without installing.

launchd/systemd artifacts are parsed; the fallback and env backup run against
an inert Python stub. No HOME override, supervisor, network or real agent.
"""

import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "agent" / "install.sh"
KEYS = (
    "CYPHER65_SERVER_URL",
    "CYPHER65_AGENT_TOKEN",
    "CYPHER65_POLL_INTERVAL",
    "CYPHER65_SCAN_CIDR",
    "CYPHER65_DEVICES",
)


@pytest.fixture(params=[False, True], ids=["auto-network", "explicit-network"])
def artifacts(tmp_path, request):
    # Deliberately awkward values catch XML, shell, systemd and cron escaping.
    install_dir = tmp_path / "agent's space & %n $TEST"
    install_dir.mkdir()
    config = dict(
        zip(
            KEYS,
            [
                "https://dashboard.example/?a=1&b='two'",
                "fixture'\"$(printf BAD);%n\\token\nsecond line",
                "31",
                "192.168.20.0/24" if request.param else "",
                "192.168.20.50,192.168.20.60" if request.param else "",
            ],
        )
    )
    source = INSTALLER.read_text()
    # Run real preflight/defaults/exports and serializers, stopping before
    # download/install. The explicit install directory keeps HOME untouched.
    preflight = source[: source.index("# ── 4 · Download")]
    harness = tmp_path / "generate.sh"
    harness.write_text(preflight + '\nPY="$1"\nwrite_config "$2" "$3"\n')
    environment = {
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
        **config,
        "CYPHER65_AGENT_DIR": str(install_dir),
    }
    if not request.param:
        environment.pop("CYPHER65_SCAN_CIDR")
        environment.pop("CYPHER65_DEVICES")
    generated = {}
    for kind in ("env", "launchd", "systemd", "fallback", "cron"):
        destination = install_dir / ("run.sh" if kind == "fallback" else kind)
        if request.param:
            # Reinstall over an older permissive artifact, not only new files.
            destination.write_text("old fixture")
            destination.chmod(0o755)
        subprocess.run(
            [
                "bash",
                str(harness),
                sys.executable,
                kind,
                str(destination),
            ],
            env=environment,
            check=True,
            capture_output=True,
            timeout=10,
        )
        generated[kind] = destination
    return install_dir, config, generated


def test_launchd_receives_network_overrides_and_escaped_values(artifacts):
    install_dir, config, generated = artifacts
    with generated["launchd"].open("rb") as source:
        plist = plistlib.load(source)
    assert plist["EnvironmentVariables"] == config
    assert plist["ProgramArguments"] == [sys.executable, str(install_dir / "agent.py")]
    assert plist["StandardErrorPath"] == str(install_dir / "agent.log")
    assert plist["KeepAlive"] is True


def test_systemd_preserves_network_configuration_as_single_directives(artifacts):
    install_dir, config, generated = artifacts
    lines = generated["systemd"].read_text().splitlines()
    # These serializers use the JSON-compatible subset of systemd C escapes.
    env_lines = [
        line.removeprefix("Environment=")
        for line in lines
        if line.startswith("Environment=")
    ]
    decoded = dict(
        json.loads(line).replace("%%", "%").split("=", 1) for line in env_lines
    )
    assert decoded == config
    exec_line = next(
        line.removeprefix("ExecStart=")
        for line in lines
        if line.startswith("ExecStart=")
    )
    decoder = json.JSONDecoder()
    python, end = decoder.raw_decode(exec_line)
    agent = json.loads(exec_line[end:].strip())
    assert python.replace("%%", "%").replace("$$", "$") == sys.executable
    assert agent.replace("%%", "%").replace("$$", "$") == str(install_dir / "agent.py")
    assert lines.count("Restart=always") == 1


def test_env_backup_roundtrips_in_shell_without_evaluating_values(artifacts):
    _, config, generated = artifacts
    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -a; . "$1"; "$2" -c \'import json,os; print(json.dumps({k:v for k,v in os.environ.items() if k.startswith("CYPHER65_")}))\'',
            "test",
            str(generated["env"]),
            sys.executable,
        ],
        env={"PATH": os.defpath},
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert json.loads(result.stdout) == config


def test_fallback_executes_inert_agent_with_network_overrides(artifacts, tmp_path):
    install_dir, config, generated = artifacts
    (install_dir / "agent.py").write_text(
        'import json,os\nprint(json.dumps({k:v for k,v in os.environ.items() if k.startswith("CYPHER65_")}))\n'
    )
    # Stop after the first poll. This is a shell function, not a real daemon.
    result = subprocess.run(
        [
            "bash",
            "-c",
            'sleep() { exit 0; }; . "$1"',
            "test",
            str(generated["fallback"]),
        ],
        env={"PATH": os.defpath},
        cwd=tmp_path,
        check=True,
        capture_output=True,
        timeout=10,
    )
    assert result.stdout == b""
    assert json.loads((install_dir / "agent.log").read_text()) == config


def test_generated_credentials_are_private_from_creation(artifacts):
    _, _, generated = artifacts
    for path in generated.values():
        assert path.stat().st_mode & 0o077 == 0


def test_cron_escapes_percent_and_points_to_fallback(artifacts):
    install_dir, _, generated = artifacts
    line = generated["cron"].read_text()
    assert line.startswith("@reboot ")
    assert "\\%n" in line
    assert "run.sh" in line
    assert "agent.log" in line
    assert line.count("\n") == 1
