"""
CYPHER65 // SSE fan-out — contrato da extração (RFC #478 · PR B2 / Issue #499)
==============================================================================
Tripwire da extração `app.py` → `services/sse.py`.

O SSE não tinha UM teste sequer antes deste PR: o registry, o broadcast e a
rota viviam no meio do monólito e só eram exercitados por um navegador. Estes
testes são a régua do B2 — eles falam com a rota real (test client, stream
destravado) e com o fan-out real, não com uma réplica:

  1. `/api/stream` pertence ao blueprint `sse` — nenhuma rota SSE órfã
     registrada direto em `app`;
  2. mimetype e headers (`Cache-Control`, `Connection`, `X-Accel-Buffering`)
     continuam os do EventSource;
  3. `_broadcast_snapshot` re-exportado pelo `app.py` é o MESMO objeto de
     `services.sse` (o `poll_loop` chama o fan-out do módulo);
  4. o módulo não importa `app` (sem ciclo);
  5. o fan-out entrega o payload serializado a um cliente conectado, e
     `default=str` preserva o que o `json.dumps` puro recusaria;
  6. cliente com fila cheia é considerado morto e evictado (fila maxsize=5);
  7. sem dado novo o gerador emite `: keepalive` (o proxy não derruba a
     conexão) — a cadência de 3s é a do contrato, então este teste leva 3s.
"""

import inspect
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as _app_module  # noqa: E402
import services.sse as _sse  # noqa: E402


@pytest.fixture
def client():
    _app_module.app.config["TESTING"] = True
    with _app_module.app.test_client() as c:
        yield c


def _open_stream(client):
    """Abre `/api/stream` com o stream destravado (sem buffer).

    Atenção: o cliente entra no registry quando a resposta ABRE — o test client
    já inicia o gerador no ``client.get(...)``, então leia ``client_count()``
    ANTES desta chamada se quiser medir o delta.
    """
    resp = client.get("/api/stream", buffered=False)
    return resp


# ── 1. Propriedade do blueprint ────────────────────────────────────────────


def _stream_rules():
    return [r for r in _app_module.app.url_map.iter_rules() if r.rule == "/api/stream"]


def test_stream_route_belongs_to_the_sse_blueprint():
    rules = _stream_rules()
    assert len(rules) == 1, f"esperava exatamente uma rota /api/stream: {rules}"
    endpoint = rules[0].endpoint
    assert endpoint.startswith(
        "sse."
    ), f"/api/stream fora do blueprint sse (endpoint={endpoint})"
    assert endpoint == "sse.sse_stream"


def test_stream_route_methods_unchanged():
    rule = _stream_rules()[0]
    assert sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS")) == ["GET"]


# ── 2. Mimetype e headers do EventSource ───────────────────────────────────


def test_stream_mimetype_and_headers_unchanged(client):
    resp = _open_stream(client)
    try:
        assert resp.mimetype == "text/event-stream"
        # `/api/stream` põe `no-cache`; o `after_request` do app.py (Issue #125)
        # acrescenta `no-store, must-revalidate` — o prefixo é o do contrato.
        assert resp.headers["Cache-Control"].startswith("no-cache")
        assert resp.headers["X-Accel-Buffering"] == "no"
        assert resp.headers["Connection"] == "keep-alive"
    finally:
        resp.close()


def test_stream_starts_with_the_connected_comment(client):
    resp = _open_stream(client)
    try:
        assert next(resp.response) == b": connected\n\n"
    finally:
        resp.close()


# ── 3. O re-export é um objeto só ──────────────────────────────────────────


def test_broadcast_is_reexported_from_app_and_is_the_same_object():
    from app import _broadcast_snapshot as from_app

    assert from_app is _sse.broadcast_snapshot


def test_sse_module_does_not_import_app():
    source = inspect.getsource(_sse)
    assert "\nimport app" not in source
    assert "\nfrom app import" not in source


# ── 4. O fan-out entrega de verdade ────────────────────────────────────────


def test_broadcast_pushes_payload_to_a_connected_client(client):
    before = _sse.client_count()
    resp = _open_stream(client)
    iterator = resp.response
    try:
        assert _sse.client_count() == before + 1, "cliente não entrou no registry"
        assert next(iterator) == b": connected\n\n"

        _sse.broadcast_snapshot({"ts": 123, "btc_price": 60000.0})

        chunk = next(iterator)
        assert chunk.startswith(b"data: ")
        assert json.loads(chunk[len(b"data: ") :].strip()) == {
            "ts": 123,
            "btc_price": 60000.0,
        }
    finally:
        resp.close()


def test_broadcast_stringifies_values_json_would_reject(client):
    """`json.dumps(..., default=str)` continua valendo para datetime/Decimal."""
    import datetime as _dt

    resp = _open_stream(client)
    iterator = resp.response
    try:
        next(iterator)
        _sse.broadcast_snapshot({"when": _dt.datetime(2026, 9, 11, 12, 0, 0)})
        chunk = next(iterator)
        payload = json.loads(chunk[len(b"data: ") :].strip())
        assert payload["when"].startswith("2026-09-11 12:00:00")
    finally:
        resp.close()


def test_client_with_full_queue_is_evicted(client):
    """Fila maxsize=5: o 6º payload sem consumo marca o cliente como morto."""
    before = _sse.client_count()
    resp = _open_stream(client)
    iterator = resp.response
    try:
        next(iterator)
        assert _sse.client_count() == before + 1
        for i in range(6):
            _sse.broadcast_snapshot({"i": i})
        assert _sse.client_count() == before
    finally:
        resp.close()


def test_client_is_unregistered_when_the_response_closes(client):
    before = _sse.client_count()
    resp = _open_stream(client)
    next(resp.response)
    assert _sse.client_count() == before + 1
    resp.close()
    assert _sse.client_count() == before


# ── 5. Keepalive do gerador (cadência de 3s do contrato) ───────────────────


def test_idle_stream_emits_keepalive(client):
    resp = _open_stream(client)
    iterator = resp.response
    try:
        next(iterator)  # ": connected"
        # Sem broadcast: o gerador bloqueia em q.get(timeout=3) e cai no
        # except queue.Empty → comentário de keepalive.
        assert next(iterator) == b": keepalive\n\n"
    finally:
        resp.close()
