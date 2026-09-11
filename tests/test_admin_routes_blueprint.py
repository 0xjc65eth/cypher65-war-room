"""
CYPHER65 // /api/admin/* — contrato do blueprint extraído (RFC #478 · PR B1)
===========================================================================
Tripwire da extração `app.py` → `routes/admin_routes.py` (Issue #495).

Um refactor puro não pode mudar UM único path, método ou decisão de gate.
Estes testes são a régua do B1 e a proteção dos PRs B2–B4, que vão mover
mais domínios para fora do monólito:

  1. toda rota `/api/admin/*` vive no blueprint `admin` — nenhuma órfã
     registrada direto em `app`;
  2. o gate `_admin_request_allowed` é UM objeto só: `app` re-exporta o do
     módulo, então `from app import _admin_request_allowed` (contrato usado
     por `tests/test_admin_gate_matrix.py`) segue válido;
  3. cada rota gateada responde 403 para origem remota sem key E para
     credencial declarada e errada (matriz da Issue #481) — prova de que o
     gate continua aplicado depois da mudança de arquivo;
  4. a lista de rotas **sem** gate é exatamente a lacuna conhecida
     (`/api/admin/sessions`, Issue #496) — rota nova sem gate quebra o CI,
     e corrigir #496 também quebra (obrigando a atualizar o contrato);
  5. o `SessionManager` do boot é injetado (sem import circular).

Nada aqui lê `app.py` para "confirmar a extração": os testes falam com o
`url_map` real e com o test client, como um cliente falaria.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as _app_module  # noqa: E402
import routes.admin_routes as _admin_module  # noqa: E402

LOCAL = "127.0.0.1"
REMOTE = "8.8.8.8"

# Rotas `/api/admin/*` que DEVEM passar pelo gate compartilhado.
# (method, path, kwargs do test client)
GATED_ROUTES = [
    ("GET", "/api/admin/docs-feedback", {}),
    ("GET", "/api/admin/pool-metrics", {}),
    ("GET", "/api/admin/error-rate", {}),
    ("GET", "/api/admin/degradation-rate", {}),
    ("POST", "/api/admin/licenses", {"json": {"plan": "pro", "months": 1}}),
    ("GET", "/api/admin/analytics", {}),
    ("GET", "/api/admin/postgres-readiness", {}),
    ("GET", "/api/admin/conversion", {}),
    ("GET", "/api/admin/rentals/accepted-recos", {}),
]

# Lacuna conhecida e ACEITA por enquanto: `/api/admin/sessions` é anterior ao
# gate. Corrigir é mudança de comportamento → Issue #496 (fora do B1). A lista
# é fechada de propósito: qualquer rota nova sem gate falha o CI.
KNOWN_UNGATED = {"/api/admin/sessions"}


@pytest.fixture
def rclient(tmp_path, monkeypatch):
    """Flask test client + scratch DB (as rotas leem o ledger)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "admin_bp.sqlite"))
    _app_module.app.config["TESTING"] = True
    with _app_module.app.test_client() as c:
        yield c


def _call(client, method, path, remote=LOCAL, key=None, **kwargs):
    headers = dict(kwargs.pop("headers", {}))
    if key is not None:
        headers["X-API-Key"] = key
    return client.open(
        path,
        method=method,
        environ_base={"REMOTE_ADDR": remote},
        headers=headers,
        **kwargs,
    )


# ── 1. Propriedade do blueprint ────────────────────────────────────────────


def _admin_rules():
    return {
        r.rule: r
        for r in _app_module.app.url_map.iter_rules()
        if r.rule.startswith("/api/admin")
    }


def test_every_admin_route_belongs_to_the_admin_blueprint():
    """Nenhuma rota /api/admin/* deve ser servida fora do blueprint."""
    rules = _admin_rules()
    assert rules, "blueprint admin não registrou nenhuma rota"
    orphans = {
        rule: r.endpoint
        for rule, r in rules.items()
        if not r.endpoint.startswith("admin.")
    }
    assert orphans == {}, f"rotas /api/admin/* fora do blueprint admin: {orphans}"


def test_admin_url_map_is_the_expected_set():
    """Paths e métodos exatos — o refactor não pode renomear nada."""
    expected = {
        "/api/admin/docs-feedback": "GET",
        "/api/admin/sessions": "GET",
        "/api/admin/pool-metrics": "GET",
        "/api/admin/error-rate": "GET",
        "/api/admin/degradation-rate": "GET",
        "/api/admin/licenses": "POST",
        "/api/admin/analytics": "GET",
        "/api/admin/postgres-readiness": "GET",
        "/api/admin/conversion": "GET",
        "/api/admin/rentals/accepted-recos": "GET",
    }
    actual = {
        rule: next(m for m in r.methods if m not in ("HEAD", "OPTIONS"))
        for rule, r in _admin_rules().items()
    }
    assert actual == expected


# ── 2. O gate é um objeto só (re-export) ───────────────────────────────────


def test_gate_is_reexported_from_app_and_is_the_same_object():
    """`from app import _admin_request_allowed` continua funcionando."""
    from app import _admin_request_allowed as from_app
    from routes.admin_routes import _admin_request_allowed as from_module

    assert from_app is from_module


def test_admin_module_does_not_import_app():
    """O módulo não pode importar `app` (ciclo) — a dependência é o url_map."""
    import inspect

    source = inspect.getsource(_admin_module)
    assert "\nimport app" not in source
    assert "\nfrom app import" not in source


# ── 3. O gate continua aplicado em cada rota ───────────────────────────────


@pytest.mark.parametrize("method,path,kwargs", GATED_ROUTES)
def test_gated_routes_deny_remote_without_key(
    rclient, monkeypatch, method, path, kwargs
):
    monkeypatch.setenv("API_KEY", "op-secret-123")
    resp = _call(rclient, method, path, remote=REMOTE, **kwargs)
    assert resp.status_code == 403, f"{method} {path} não está gateada"


@pytest.mark.parametrize("method,path,kwargs", GATED_ROUTES)
def test_gated_routes_fail_closed_on_declared_wrong_key(
    rclient, monkeypatch, method, path, kwargs
):
    """Matriz da Issue #481 preservada após a extração, rota por rota."""
    monkeypatch.setenv("API_KEY", "op-secret-123")
    resp = _call(rclient, method, path, remote=LOCAL, key="wrong-key", **kwargs)
    assert resp.status_code == 403
    assert resp.get_json() == {"error": "admin access required"}


# Nota: a tabela-verdade completa do gate (local sem header = liberado,
# remoto com key válida = liberado, proxy header = remoto) é do
# tests/test_admin_gate_matrix.py — lá ela roda contra um probe route só, com
# DB controlado. Aqui a régua é outra: que cada rota movida CONTINUE passando
# pelo gate. Rotas que leem tabelas de telemetria não podem ser afirmadas como
# 200 num DB de rascunho (elas quebram por I/O, não por autorização), então a
# prova positiva é feita por rota que não depende de tabela populada.


def test_gated_route_accepts_valid_key_from_remote(rclient, monkeypatch):
    monkeypatch.setenv("API_KEY", "op-secret-123")
    resp = _call(
        rclient, "GET", "/api/admin/conversion", remote=REMOTE, key="op-secret-123"
    )
    assert resp.status_code == 200


def test_gated_route_allows_localhost_without_key(rclient, monkeypatch):
    """Localhost real = dev / Render Shell (Issue #254) — segue liberado."""
    monkeypatch.setenv("API_KEY", "op-secret-123")
    resp = _call(rclient, "GET", "/api/admin/conversion", remote=LOCAL)
    assert resp.status_code == 200


# ── 4. Lacuna conhecida, fechada a propósito ───────────────────────────────


def test_ungated_admin_routes_are_exactly_the_known_gap():
    """Rota nova sem gate → CI vermelho. Corrigir #496 → CI pede atualizar."""
    gated = {path for _, path, _ in GATED_ROUTES}
    ungated = set(_admin_rules()) - gated
    assert ungated == KNOWN_UNGATED, (
        f"conjunto de rotas sem gate mudou: {ungated}. "
        "Se você ADICIONOU uma rota, adicione o gate e mova para GATED_ROUTES. "
        "Se você GATEOU /api/admin/sessions, mova-a para GATED_ROUTES e "
        "atualize KNOWN_UNGATED (Issue #496)."
    )


# ── 5. Injeção do SessionManager ───────────────────────────────────────────


def test_session_manager_is_injected_from_app():
    """`/api/admin/sessions` lê o store do boot — sem import circular."""
    assert _admin_module._session_manager is _app_module._session_manager
    assert _admin_module._session_manager is not None


def test_admin_sessions_route_serves_the_boot_store(rclient):
    """A rota movida continua respondendo o payload de sessões."""
    resp = _call(rclient, "GET", "/api/admin/sessions")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body) == {"count", "sessions", "pool"}
    assert "auto_exclude_alerts" in body["pool"]
