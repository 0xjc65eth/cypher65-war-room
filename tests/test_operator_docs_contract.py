"""Contract tests for the operator-facing Flyovers documentation."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FLYOVER = ROOT / "docs" / "OPERATOR_FLYOVER.md"
QUICKSTART = ROOT / "docs" / "OPERATOR_QUICKSTART.md"
RUNTIME_MAP = ROOT / "docs" / "architecture" / "runtime-map.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _mermaid_blocks(markdown: str) -> list[str]:
    return re.findall(r"```mermaid\n(.*?)\n```", markdown, flags=re.DOTALL)


def test_flyover_has_exact_narrative_spine_and_stays_narratable():
    text = _read(FLYOVER)
    headings = [
        "## 0. One-sentence product",
        "## 1. Context — runtime architecture",
        "## 2. Problem — operator without a war room",
        "## 3. Change — what this PR adds",
        "## 4. How to use it (happy path, 15 minutes)",
        "## 5. Benefits that are allowed to be claimed",
        "## 6. Implementation care / safety contract",
        "## 7. Impact",
    ]

    positions = [text.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert len(text.splitlines()) <= 250
    assert "TL;DR em português" in text


def test_real_operator_modules_remain_named():
    corpus = "\n".join((_read(FLYOVER), _read(QUICKSTART), _read(RUNTIME_MAP)))
    modules = [
        "Live Mining",
        "Block Statistics",
        "Scenario Economics",
        "AXE Fleet Command",
        "Hash Market",
        "Rentals Hub",
        "Auto-Pilot",
        "Alerts & Automations",
        "AI Operator",
        "Mobile companion",
    ]

    for module in modules:
        assert module in corpus


def test_safety_contract_is_explicit_and_fail_closed():
    corpus = "\n".join((_read(FLYOVER), _read(QUICKSTART), _read(RUNTIME_MAP)))
    required = [
        "advisory_only",
        "executed: false",
        "navigate_to",
        "POST /api/auto-pilot/recommendations/<id>/respond",
        "stale/offline",
        "last real cached value",
        "dry-run",
        "dry_run:false",
        "one-time human confirmation",
        "checkout_unavailable",
        "BTCPAY_RECONCILIATION_VERIFIED=1",
        "MIT covers the source code",
    ]

    for statement in required:
        assert statement in corpus

    forbidden_claims = [
        "guaranteed profit",
        "you will find a block",
        "beats NiceHash",
        "one click restarts the farm from Auto-Pilot",
    ]
    allowed_claims_section = _read(FLYOVER).split("Do not claim:", 1)[0]
    for claim in forbidden_claims:
        assert claim.lower() not in allowed_claims_section.lower()


def test_quickstart_uses_real_first_run_contract():
    text = _read(QUICKSTART)
    for value in (
        "cp .env.example .env",
        "./run.sh",
        "BTC_ADDRESS=",
        "WORKER_NAME=",
        "PORT=8765",
        "http://localhost:8765/api/healthz",
    ):
        assert value in text

    assert "DEBUG_MOCK=1" in text
    assert "Do not set `DEBUG_MOCK=1`" in text


def test_mermaid_contract_has_one_runtime_flow_and_one_advisory_sequence():
    flyover_blocks = _mermaid_blocks(_read(FLYOVER))
    runtime_blocks = _mermaid_blocks(_read(RUNTIME_MAP))

    assert len(flyover_blocks) == 1
    assert flyover_blocks[0].startswith("flowchart LR")
    assert len(re.findall(r"\w+\[[^]]+\]", flyover_blocks[0])) <= 12
    assert all(
        len(label.split()) <= 3
        for label in re.findall(r"\w+\[([^]]+)\]", flyover_blocks[0])
    )
    for edge_label in (
        "snapshots",
        "live data",
        "guard actions",
        "approved commands",
        "audit state",
        "tenant state",
    ):
        assert f"|{edge_label}|" in flyover_blocks[0]

    assert len(runtime_blocks) == 1
    assert runtime_blocks[0].startswith("sequenceDiagram")
    for step in (
        "Accept advisory",
        "Record advisory_only",
        "navigate_to destination",
        "Require human confirmation",
        "Command, blacklist, or buy",
    ):
        assert step in runtime_blocks[0]
