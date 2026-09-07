"""Regression guards for the Playwright runner (Issue #430)."""

import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def _load_playwright_ci_policy(ci_value: str) -> dict:
    script = (
        "import('./tests/e2e/support/ci-policy.js').then(({isCiEnabled}) => "
        "console.log(JSON.stringify({enabled: isCiEnabled()})))"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        env={**os.environ, "CI": ci_value},
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_ci_false_is_not_treated_as_enabled():
    assert _load_playwright_ci_policy("false") == {
        "enabled": False,
    }


def test_ci_true_enables_ci_policy():
    assert _load_playwright_ci_policy("true") == {
        "enabled": True,
    }


def test_playwright_config_wires_explicit_ci_policy():
    config = (ROOT / "playwright.config.js").read_text(encoding="utf-8")
    assert "const isCI = isCiEnabled();" in config
    assert "forbidOnly: isCI" in config
    assert "retries: isCI ? 1 : 0" in config


def test_runner_default_rate_limit_matches_ci_capacity():
    runner = (ROOT / "run-e2e.sh").read_text(encoding="utf-8")
    assert 'RATE_LIMIT_PER_MINUTE="${RATE_LIMIT_PER_MINUTE:-10000}"' in runner


def test_boot_specs_report_http_status_before_waiting_for_app_shell():
    for relative_path in (
        "tests/e2e/dashboard.spec.js",
        "tests/e2e/modals.spec.js",
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "returned HTTP ${response.status()}" in source
