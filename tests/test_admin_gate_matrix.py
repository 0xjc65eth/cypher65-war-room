"""
CYPHER65 // admin gate — decision matrix (Issue #481)
=====================================================
Pins the fail-closed contract of `_admin_request_allowed()`:

  | origem         | header X-API-Key | resultado                            |
  |----------------|------------------|--------------------------------------|
  | localhost real | ausente          | 200 (dev / Render Shell — #254)      |
  | localhost real | válida           | 200                                  |
  | localhost real | DECLARADA e errada | 403 (fail-closed — Issue #481)     |
  | remote         | ausente          | 403                                  |
  | remote         | válida           | 200                                  |
  | remote         | errada           | 403                                  |
  | local + proxy header | qualquer   | 403 (proxy ⇒ remoto — Sev-2 #254)    |
  | localhost, sem API_KEY no env | ausente | 200 (trust original mantido) |

The discriminating case (fix of the audit finding): before #481, a WRONG
key from localhost returned 200 — a declared-but-invalid credential was
silently short-circuited by the `local OR key` disjunction. Now a declared
credential must MATCH, from any origin, or the request fails closed.

Runs against the real Flask test client and every /api/admin/* shape via
one representative route (the gate is shared by all of them).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as _app_module  # noqa: E402

PROBE_ROUTE = "/api/admin/rentals/accepted-recos"
LOCAL = "127.0.0.1"
REMOTE = "8.8.8.8"


@pytest.fixture
def rclient():
    """Flask test client (mirrors tests/test_admin_accepted_recos.py)."""
    _app_module.app.config["TESTING"] = True
    with _app_module.app.test_client() as c:
        yield c


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Per-test scratch DB — the probe route reads the rentals ledger."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "gate.sqlite"))


def _get(client, remote=LOCAL, key=None, proxy=False):
    """GET the probe route with a controlled origin/credential."""
    headers = {}
    if key is not None:
        headers["X-API-Key"] = key
    if proxy:
        headers["X-Forwarded-For"] = "203.0.113.9"
    return client.get(PROBE_ROUTE, environ_base={"REMOTE_ADDR": remote},
                      headers=headers)


# ── Localhost ──────────────────────────────────────────────────────────────

def test_local_no_header_allowed(rclient, db, monkeypatch):
    """Localhost sem header = dev/Render Shell (Issue #254) — continua OK."""
    monkeypatch.setenv("API_KEY", "op-secret-123")
    assert _get(rclient).status_code == 200


def test_local_valid_key_allowed(rclient, db, monkeypatch):
    monkeypatch.setenv("API_KEY", "op-secret-123")
    assert _get(rclient, key="op-secret-123").status_code == 200


def test_local_declared_wrong_key_denied(rclient, db, monkeypatch):
    """THE Issue #481 fix: localhost + credencial DECLARADA e errada → 403.

    Antes do fix este caso retornava 200 (a disjunção `local or key`
    curto-circuitava a credencial inválida em silêncio).
    """
    monkeypatch.setenv("API_KEY", "op-secret-123")
    resp = _get(rclient, key="wrong-key")
    assert resp.status_code == 403
    assert resp.get_json() == {"error": "admin access required"}


def test_local_wrong_key_denied_even_without_api_key_env(rclient, db, monkeypatch):
    """API_KEY não configurada + header errado declarado → 403.

    Declaram uma credencial; não há o que a valide; sem a env, não existe
    chave correta — qualquer header declarado é inválido por definição.
    O trust de localhost cobre a AUSÊNCIA de header, não uma errada.
    """
    monkeypatch.delenv("API_KEY", raising=False)
    assert _get(rclient, key="anything").status_code == 403


def test_local_no_header_without_api_key_env_still_allowed(rclient, db, monkeypatch):
    """Backward-compat: sem API_KEY no env e sem header, localhost continua
    liberado (o trust original da Issue #254 não pode quebrar deploys que
    nunca configuraram API_KEY)."""
    monkeypatch.delenv("API_KEY", raising=False)
    assert _get(rclient).status_code == 200


def test_local_empty_header_treated_as_absent(rclient, db, monkeypatch):
    """Header vazio (`X-API-Key: `) = ausente, não declaração inválida."""
    monkeypatch.setenv("API_KEY", "op-secret-123")
    assert _get(rclient, key="").status_code == 200


# ── Remote (com e sem proxy) ───────────────────────────────────────────────

def test_remote_no_header_denied(rclient, db, monkeypatch):
    monkeypatch.setenv("API_KEY", "op-secret-123")
    assert _get(rclient, remote=REMOTE).status_code == 403


def test_remote_valid_key_allowed(rclient, db, monkeypatch):
    monkeypatch.setenv("API_KEY", "op-secret-123")
    assert _get(rclient, remote=REMOTE, key="op-secret-123").status_code == 200


def test_remote_wrong_key_denied(rclient, db, monkeypatch):
    monkeypatch.setenv("API_KEY", "op-secret-123")
    assert _get(rclient, remote=REMOTE, key="wrong-key").status_code == 403


def test_local_via_proxy_header_denied(rclient, db, monkeypatch):
    """Sev-2 fix da Issue #254 segue intacto: header de proxy marca o request
    como REMOTO mesmo com remote_addr loopback (Render/proxy reverso)."""
    monkeypatch.setenv("API_KEY", "op-secret-123")
    assert _get(rclient, proxy=True).status_code == 403
    assert _get(rclient, proxy=True, key="op-secret-123").status_code == 200


# ── O gate é compartilhado por todas as rotas /api/admin/* ─────────────────

def test_gate_is_shared_across_admin_routes(rclient, db, monkeypatch):
    """A decisão fail-closed vale para TODA rota que usa o gate — a
    credencial declarada e errada é rejeitada no /licenses também."""
    monkeypatch.setenv("API_KEY", "op-secret-123")
    resp = rclient.post("/api/admin/licenses",
                        json={"plan": "pro", "months": 1},
                        environ_base={"REMOTE_ADDR": LOCAL},
                        headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 403


# ── Unidade: a função de gate diretamente ──────────────────────────────────

def test_gate_function_contract(rclient, db, monkeypatch):
    """`_admin_request_allowed()` direto: tabela-verdade sem I/O de rota."""
    from app import _admin_request_allowed

    monkeypatch.setenv("API_KEY", "op-secret-123")

    with _app_module.app.test_request_context(
            "/", environ_base={"REMOTE_ADDR": LOCAL}):
        assert _admin_request_allowed() is True          # local, sem header

    with _app_module.app.test_request_context(
            "/", environ_base={"REMOTE_ADDR": LOCAL},
            headers={"X-API-Key": "wrong-key"}):
        assert _admin_request_allowed() is False         # local + errada (#481)

    with _app_module.app.test_request_context(
            "/", environ_base={"REMOTE_ADDR": LOCAL},
            headers={"X-API-Key": "op-secret-123"}):
        assert _admin_request_allowed() is True          # local + válida

    with _app_module.app.test_request_context(
            "/", environ_base={"REMOTE_ADDR": REMOTE}):
        assert _admin_request_allowed() is False         # remoto, sem header

    with _app_module.app.test_request_context(
            "/", environ_base={"REMOTE_ADDR": REMOTE},
            headers={"X-API-Key": "op-secret-123"}):
        assert _admin_request_allowed() is True          # remoto + válida
