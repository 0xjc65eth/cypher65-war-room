"""
CYPHER65 // SSE fan-out — RFC #478 · PR B2 (Issue #499)
=======================================================
Extração mecânica do fan-out Server-Sent Events que vivia no meio do
`app.py`: mesmos corpos, mesmos headers, mesma fila, mesma decisão de
descarte de cliente. Nada aqui é comportamento novo.

Peças movidas:

  * o registry em memória dos clientes conectados (``_sse_clients`` + lock);
  * a rota ``GET /api/stream`` (blueprint ``sse_bp``, sem ``url_prefix``
    porque o path é fixo e é exatamente o que o ``EventSource`` do dashboard
    pede);
  * ``broadcast_snapshot()``, chamado pelo ``poll_loop`` do ``app.py`` depois
    de cada poll — o ``app.py`` re-exporta o MESMO objeto como
    ``_broadcast_snapshot``.

Fluxo: o ``poll_loop`` monta o snapshot → ``broadcast_snapshot(snapshot)``
extrai e serializa UMA vez o evento ``type=live`` de cinco campos, depois o
distribui para todas as filas. O gerador de cada cliente faz ``get(timeout=3)``;
sem dado novo ele emite ``: keepalive`` para o proxy não derrubar a conexão.
Cliente com fila cheia (``queue.Full``) é considerado morto e removido no
mesmo passo.

Nota de topologia (a mesma de ``services/workers.py``): o fan-out é
**in-process**. Num deploy multi-processo o push só alcança os clientes do
processo que os atende, e o poll de 15s do dashboard cobre a diferença;
pub/sub compartilhado (Redis) não está implementado — fora do escopo desta
extração.

Design rule: este módulo **nunca** importa ``app`` (o wiring é o inverso), então
`import services.sse` de um teste tem zero efeito colateral.
"""

import json
import logging
import queue
import threading
from math import isfinite
from typing import List

from flask import Blueprint, Response

log = logging.getLogger("cypher65.sse")

sse_bp = Blueprint("sse", __name__)

# Clientes conectados: uma `queue.Queue(maxsize=5)` por conexão EventSource.
_sse_clients: List["queue.Queue"] = []
_sse_clients_lock = threading.Lock()


def client_count() -> int:
    """Nº de clientes SSE conectados (observabilidade / contrato de teste).

    Substitui o antigo ``_sse_client_count = len(_sse_clients)`` do ``app.py``,
    que era uma atribuição local morta — o valor nunca era lido. Aqui ele vira
    leitura de verdade, e por isso é thread-safe (mesmo lock do registry).
    """
    with _sse_clients_lock:
        return len(_sse_clients)


@sse_bp.route("/api/stream")
def sse_stream():
    """SSE endpoint: yields latest snapshot data when it changes.
    Frontend connects via EventSource and receives push updates at ~3s intervals.
    Falls back gracefully to polling if SSE disconnects."""

    def event_stream():
        q = queue.Queue(maxsize=5)
        with _sse_clients_lock:
            _sse_clients.append(q)
        try:
            # Yield initial keepalive
            yield ": connected\n\n"
            while True:
                try:
                    data = q.get(timeout=3)
                    yield f"data: {data}\n\n"
                except queue.Empty:
                    # Send keepalive comment to prevent proxy timeouts
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            with _sse_clients_lock:
                try:
                    _sse_clients.remove(q)
                except ValueError:
                    pass

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def live_metrics_from_snapshot(snapshot: dict) -> dict:
    """Slim live-card payload (Issue #539).

    Hashrate and temperature change every poll; the rest of the dashboard
    stays on the 15s HTTP snapshot so the browser does not rebuild every
    panel. ``type=live`` is the discriminator the EventSource handler uses.
    """
    data = snapshot if isinstance(snapshot, dict) else {}
    worker = data.get("worker") if isinstance(data.get("worker"), dict) else {}
    pool = data.get("pool") if isinstance(data.get("pool"), dict) else {}
    fleet = data.get("axe_fleet") if isinstance(data.get("axe_fleet"), list) else []
    temps = []
    for device in fleet:
        if not isinstance(device, dict):
            continue
        tel = device.get("telemetry")
        if not isinstance(tel, dict):
            tel = device.get("_telemetry")
        if not isinstance(tel, dict):
            tel = {}
        raw = tel.get("temperature")
        if raw is None:
            raw = device.get("temperature")
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if isfinite(val):
            temps.append(val)
    avg_temp = round(sum(temps) / len(temps), 1) if temps else None
    return {
        "type": "live",
        "ts": _finite_number(data.get("ts")),
        "worker_hashrate": _finite_number(worker.get("hashrate")),
        "pool_hashrate": _finite_number(pool.get("hashrate")),
        "fleet_avg_temp": avg_temp,
    }


def _finite_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _sse_json(snapshot) -> str:
    """Serialize a live-metrics event for full snapshots; pass other dicts through."""
    if not isinstance(snapshot, dict):
        return json.dumps(snapshot, default=str)
    if snapshot.get("type") == "live":
        live = {
            "type": "live",
            "ts": _finite_number(snapshot.get("ts")),
            "worker_hashrate": _finite_number(snapshot.get("worker_hashrate")),
            "pool_hashrate": _finite_number(snapshot.get("pool_hashrate")),
            "fleet_avg_temp": _finite_number(snapshot.get("fleet_avg_temp")),
        }
        return json.dumps(live, default=str)
    if any(key in snapshot for key in ("worker", "pool", "axe_fleet")):
        return json.dumps(live_metrics_from_snapshot(snapshot), default=str)
    return json.dumps(snapshot, default=str)


def broadcast_snapshot(snapshot: dict):
    """Send live metrics (or a raw dict) to all connected SSE clients.
    Called by poll_loop after fetching and processing data."""
    try:
        payload = _sse_json(snapshot)
        dead_clients = []
        with _sse_clients_lock:
            for q in _sse_clients:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dead_clients.append(q)
            for q in dead_clients:
                _sse_clients.remove(q)
    except Exception as e:
        log.warning("[sse broadcast] error: %s", e)
