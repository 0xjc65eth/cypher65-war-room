"""Revogação de tokens de agente por tenant (Issue #582).

POR QUE ISTO EXISTE
-------------------
O fix do #578 fechou a **cunhagem** anônima de token de agente, mas não
invalida o que já foi cunhado: um token mintado na janela de exposição segue
válido por ``AGENT_TOKEN_TTL`` (365 dias). E o mecanismo de revogação existente
(``services.auth.revoke_token``) não resolve, por três razões medidas no código:

1. Ele exige a **string do token** — não há enumeração, então é impossível
   revogar "quem cunhou naquela janela".
2. A blacklist em memória é FIFO-podada (``_BLACKLIST_MAX=10000``,
   ``KEEP=5000``): depois de 5 000 revogações posteriores a entrada é
   **descartada silenciosamente** e o token volta a valer.
3. A persistência em SQLite (``REVOKED_TOKENS_DB=1``, opt-in, e **ausente do
   ``render.yaml``**) apaga linhas mais antigas que ``REFRESH_TTL + 1h`` =
   **7 dias + 1h**. Ou seja: a janela de revogação efetiva é MENOR que a
   validade do token — a revogação de um token de 1 ano se autodestrói em ~7
   dias sem avisar ninguém.

O MODELO: UM EPOCH POR TENANT
-----------------------------
Em vez de guardar cada token, guardamos **um inteiro por tenant**. O token de
agente carrega o epoch vigente no momento em que foi cunhado; ``_require_agent``
recusa qualquer token cujo claim seja anterior ao epoch atual. Revogar =
incrementar o contador — instantâneo, durável, sem rotacionar ``SECRET_KEY``
(que deslogaria todos os usuários e exigiria ação no dashboard do Render) e sem
depender de enumerar tokens.

Consequência desejada: tokens emitidos **antes** desta feature não têm o claim,
então contam como epoch 0 e morrem no primeiro incremento. Fail-closed.

POR QUE NÃO ``services.settings``
---------------------------------
``load_settings()`` cacheia por tenant **no processo e para sempre** (só é
invalidado por ``save_setting`` no MESMO processo). Num topology de dois
processos (``python -m services.workers`` + gunicorn — ver ``render.yaml``), um
worker ficaria com o epoch velho indefinidamente e a revogação **nunca** teria
efeito ali. Aqui a leitura vai direto ao SQLite, com memo curto de
``_MEMO_TTL`` segundos: barato por request e propagado em segundos.

FALHA DE LEITURA: BEST-EFFORT, COMO NO RESTO DO AUTH
---------------------------------------------------
Se o SQLite falhar, vale o **último valor conhecido**; sem nenhum, libera. É o
mesmo precedente que ``services/auth.py`` já estabelece para a blacklist
("persistência é estritamente best-effort; um erro de DB degrada para memória e
NUNCA quebra a autenticação"). A alternativa — fechar — derruba a frota inteira
num hiccup de SQLite, e o usuário veria apenas "agente offline" sem causa.
O que NUNCA é best-effort: se temos um valor, ele é aplicado.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Optional

log = logging.getLogger(__name__)

# Claim que carrega o epoch no JWT de agente.
EPOCH_CLAIM = "agent_epoch"

# TTL do memo do epoch. Curto de propósito: é o atraso máximo entre a revogação
# e o último worker do cluster passar a recusar o token.
_MEMO_TTL = 5.0

# tenant_id -> (lido_em, epoch)
_memo: dict = {}

# Guarda do DDL — uma vez por processo por path (mesmo padrão de
# services/auth.py::_revoked_table_ready), para não rodar CREATE TABLE IF NOT
# EXISTS a cada request de agente.
_table_ready: set = set()


def _db_path() -> str:
    """Path do SQLite, lido em tempo de chamada (testes redirecionam DB_PATH)."""
    import os

    path = os.environ.get("DB_PATH")
    if path:
        return path
    try:
        from config import DB_PATH as _cfg

        return _cfg
    except Exception:  # pragma: no cover — config sempre importável no runtime
        return "data/war_room.sqlite"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=3)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def _ensure_table(conn: sqlite3.Connection, path: str) -> None:
    if path in _table_ready:
        return
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tenant_token_epochs ("
        " tenant_id TEXT PRIMARY KEY,"
        " epoch INTEGER NOT NULL DEFAULT 0,"
        " updated_ts INTEGER NOT NULL DEFAULT 0)"
    )
    conn.commit()
    _table_ready.add(path)


def get_epoch(tenant_id: str) -> Optional[int]:
    """Epoch atual do tenant, ou ``None`` quando não deu para saber.

    ``None`` é deliberadamente diferente de ``0``: ``0`` significa "este tenant
    nunca revogou" e é um FATO; ``None`` é uma FALHA de leitura. Tratar falha
    como 0 passaria a recusar tokens legítimos; tratar como sucesso silencioso
    esconderia o problema. O chamador decide (ver :func:`is_revoked`).
    """
    tenant_id = tenant_id or "default"
    now = time.monotonic()
    cached = _memo.get(tenant_id)
    if cached and now - cached[0] < _MEMO_TTL:
        return cached[1]

    path = _db_path()
    conn = None
    try:
        conn = _connect()
        _ensure_table(conn, path)
        row = conn.execute(
            "SELECT epoch FROM tenant_token_epochs WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()
        epoch = int(row["epoch"]) if row is not None else 0
        _memo[tenant_id] = (now, epoch)
        return epoch
    except Exception as e:  # noqa: BLE001 — best-effort, igual a services/auth
        log.warning("[agent_tokens] epoch lookup failed (best-effort): %s", e)
        return cached[1] if cached else None
    finally:
        if conn is not None:
            conn.close()


def bump_epoch(tenant_id: str) -> int:
    """Incrementa o epoch do tenant — invalida TODO token de agente dele.

    Devolve o novo epoch. Levanta em falha: uma revogação que não persistiu
    NÃO pode ser reportada como sucesso (o usuário precisa saber que os tokens
    continuam valendo).
    """
    tenant_id = tenant_id or "default"
    path = _db_path()
    conn = None
    try:
        conn = _connect()
        _ensure_table(conn, path)
        conn.execute(
            "INSERT INTO tenant_token_epochs(tenant_id, epoch, updated_ts) "
            "VALUES(?, 1, ?) "
            "ON CONFLICT(tenant_id) DO UPDATE SET "
            " epoch = epoch + 1, updated_ts = excluded.updated_ts",
            (tenant_id, int(time.time())),
        )
        conn.commit()
        row = conn.execute(
            "SELECT epoch FROM tenant_token_epochs WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()
        epoch = int(row["epoch"])
    finally:
        if conn is not None:
            conn.close()
    # Memo atualizado (não só invalidado): os requests seguintes já recusam.
    _memo[tenant_id] = (time.monotonic(), epoch)
    return epoch


def epoch_of(payload: Optional[dict]) -> int:
    """Epoch declarado por um token. Ausente/inválido → ``0``.

    Token emitido antes desta feature não tem o claim e conta como 0, então
    morre no primeiro ``bump_epoch`` do tenant. Fail-closed por construção.
    """
    if not payload:
        return 0
    try:
        return int(payload.get(EPOCH_CLAIM) or 0)
    except (TypeError, ValueError):
        return 0


def is_revoked(payload: Optional[dict]) -> bool:
    """``True`` quando o token de agente foi superado pelo epoch do tenant.

    Sem valor conhecido do epoch (leitura falhou e não há memo), devolve
    ``False`` — best-effort, seguindo o precedente de ``services/auth.py``.
    """
    tenant_id = (payload or {}).get("sub") or "default"
    current = get_epoch(tenant_id)
    if current is None:
        return False
    return epoch_of(payload) < current


def invalidate_memo(tenant_id: Optional[str] = None) -> None:
    """Limpa o memo (testes / troca de DB_PATH em runtime)."""
    if tenant_id is None:
        _memo.clear()
    else:
        _memo.pop(tenant_id or "default", None)
