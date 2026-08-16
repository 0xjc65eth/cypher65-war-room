"""Tests for the env-gated frontend Sentry block in the dashboard.

Covers the contract:
  - WITHOUT SENTRY_DSN: the dashboard HTML must NOT contain the Sentry
    browser SDK (zero external requests, zero overhead, e2e intact).
  - WITH SENTRY_DSN: the HTML embeds the DSN and the init call so browser
    runtime errors are captured (complementing the backend JSON logs).

The gating lives in app.py (index route passes sentry_dsn only when the env
var is set) + templates/dashboard.html ({% if sentry_dsn %} block).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as _app_module  # noqa: E402


@pytest.fixture
def rclient():
    _app_module.app.config["TESTING"] = True
    _app_module.app.config["JWT_SECRET_KEY"] = "cypher65-test-secret-key-0123456789"
    with _app_module.app.test_client() as c:
        yield c


def _get_html(rclient):
    resp = rclient.get("/")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_sentry_gated_off_without_dsn(rclient, monkeypatch):
    """Sem SENTRY_DSN o SDK do browser NÃO aparece no HTML (env-gated)."""
    monkeypatch.setattr(_app_module, "_SENTRY_DSN", "")
    html = _get_html(rclient)
    assert "browser.sentry-cdn.com" not in html
    assert "Sentry.init" not in html
    assert "__SENTRY_DSN__" not in html
    # O template ainda renderiza o resto normalmente.
    assert "CYPHER65" in html


def test_sentry_active_with_dsn(rclient, monkeypatch):
    """Com SENTRY_DSN o HTML embute o DSN + init (captura de erros on)."""
    monkeypatch.setattr(
        _app_module, "_SENTRY_DSN", "https://abc123@o1.ingest.sentry.io/0000000")
    html = _get_html(rclient)
    assert "browser.sentry-cdn.com" in html
    assert "Sentry.init" in html
    assert "abc123@o1.ingest.sentry.io" in html
    # Environment + release sempre presentes para triagem.
    assert "cypher65-war-room" in html
    assert "environment" in html
