"""Deployment contract for the production Bitcoin channel (Issue #330).

The blueprint may provision variable names, never provider credentials. These
tests also pin the operator runbook so a future cleanup cannot silently expose
a half-configured payment channel.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
RENDER_YAML = ROOT / "render.yaml"
OPS_DOC = ROOT / "docs" / "DEPLOYMENT_OPS.md"

BTCPAY_ENV_KEYS = (
    "BTCPAY_URL",
    "BTCPAY_API_KEY",
    "BTCPAY_STORE_ID",
    "BTCPAY_WEBHOOK_SECRET",
    "BTCPAY_RECONCILIATION_VERIFIED",
    "PAYMENT_BTC_ADDRESS",
    "LN_INVOICE_ENDPOINT",
)


def _env_by_key():
    blueprint = yaml.safe_load(RENDER_YAML.read_text())
    web = next(service for service in blueprint["services"] if service["type"] == "web")
    return {entry["key"]: entry for entry in web.get("envVars", [])}


@pytest.mark.parametrize("key", BTCPAY_ENV_KEYS)
def test_btcpay_env_is_provisioned_without_committed_value(key):
    entry = _env_by_key().get(key)
    assert entry is not None, f"{key} must be provisioned by the Render blueprint"
    if key == "BTCPAY_RECONCILIATION_VERIFIED":
        assert entry.get("value") == "0"
    else:
        assert entry.get("sync") is False
        assert "value" not in entry, f"{key} value must never be committed"


def test_runbook_pins_safe_activation_and_rollback():
    text = OPS_DOC.read_text()
    for required in (
        "InvoiceSettled",
        "/api/payments/btcpay/webhook",
        '"btcpay": true',
        "processed_invoices",
        "rollback",
        "BTCPAY_WEBHOOK_SECRET",
    ):
        assert required in text
