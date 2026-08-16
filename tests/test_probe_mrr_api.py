"""Issue #152 (item b) — probe MRR com credenciais próprias.

Cobre a precedência de credenciais (CLI > env > .env), a descrição da
origem sem expor valores, e o veredito do ``--check``
(``validate_credentials``) com ``call`` mockado — sem rede.
"""

import importlib.util
import os

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_spec = importlib.util.spec_from_file_location(
    "probe_mrr", os.path.join(_REPO, "scripts", "probe_mrr_api.py")
)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)


@pytest.fixture(autouse=True)
def _clean_creds(monkeypatch):
    """Isola os testes de .env/env reais do ambiente."""
    for k in ("MRR_API_KEY", "MRR_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(probe, "env", {"MRR_API_KEY": "", "MRR_API_SECRET": ""})
    yield


# ── resolve_credentials: CLI > env > .env ───────────────────────────────────


def test_resolve_cli_over_env_over_dotenv(monkeypatch):
    monkeypatch.setenv("MRR_API_KEY", "env_key")
    monkeypatch.setenv("MRR_API_SECRET", "env_sec")
    monkeypatch.setattr(
        probe,
        "env",
        {"MRR_API_KEY": "dotenv_key", "MRR_API_SECRET": "dotenv_sec"},
    )

    k, s = probe.resolve_credentials(cli_key="cli_key", cli_secret="cli_sec")
    assert (k, s) == ("cli_key", "cli_sec")

    k, s = probe.resolve_credentials()
    assert (k, s) == ("env_key", "env_sec")


def test_resolve_falls_back_to_dotenv():
    probe.env["MRR_API_KEY"] = "dotenv_key"
    probe.env["MRR_API_SECRET"] = "dotenv_sec"
    k, s = probe.resolve_credentials()
    assert (k, s) == ("dotenv_key", "dotenv_sec")


def test_resolve_per_field_independent(monkeypatch):
    # key vem do CLI, secret cai no .env — campos independentes.
    monkeypatch.setattr(
        probe, "env", {"MRR_API_KEY": "", "MRR_API_SECRET": "dotenv_sec"}
    )
    k, s = probe.resolve_credentials(cli_key="cli_key")
    assert (k, s) == ("cli_key", "dotenv_sec")


def test_resolve_strips_whitespace():
    # Valor com \n/espaço corrompe o HMAC → falso 401 (ver mrr_credentials).
    k, s = probe.resolve_credentials(cli_key="  k  ", cli_secret="\ns\n")
    assert (k, s) == ("k", "s")


# ── creds_source: origem sem expor valores ──────────────────────────────────


def test_creds_source_labels(monkeypatch):
    assert probe.creds_source(cli_key="x") == "key=cli · sec=none"

    monkeypatch.setenv("MRR_API_SECRET", "s")
    assert probe.creds_source(cli_key="x") == "key=cli · sec=env"

    monkeypatch.setattr(probe, "env", {"MRR_API_KEY": "k", "MRR_API_SECRET": "s"})
    monkeypatch.delenv("MRR_API_SECRET", raising=False)
    assert probe.creds_source() == "key=.env · sec=.env"


# ── validate_credentials (--check), sem rede ────────────────────────────────


def test_validate_credentials_authed(monkeypatch):
    monkeypatch.setattr(
        probe,
        "call",
        lambda ep: {"success": True, "data": {"authed": True, "auth_mesage": "ok"}},
    )
    v = probe.validate_credentials()
    assert v["authed"] is True


def test_validate_credentials_bad_nonce(monkeypatch):
    monkeypatch.setattr(
        probe,
        "call",
        lambda ep: {
            "success": True,
            "data": {"authed": False, "auth_mesage": "Invalid Key - Bad Nonce."},
        },
    )
    v = probe.validate_credentials()
    assert v["authed"] is False
    assert "Bad Nonce" in v["msg"]


def test_validate_credentials_http_error(monkeypatch):
    monkeypatch.setattr(probe, "call", lambda ep: {"HTTP": 500, "body": "boom"})
    v = probe.validate_credentials()
    assert v["authed"] is False
    assert "HTTP 500" in v["msg"]


def test_validate_credentials_transport_error(monkeypatch):
    monkeypatch.setattr(probe, "call", lambda ep: {"error": "connection timeout"})
    v = probe.validate_credentials()
    assert v["authed"] is False
    assert "timeout" in v["msg"]
