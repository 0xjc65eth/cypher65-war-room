"""
CYPHER65 — Database access layer
=================================
Ponto de entrada histórico para a conexão SQLite (Issue #508).

A implementação canônica de ``get_db()`` vive em ``services/bootstrap.py`` — o
dono do bootstrap/schema do SQLite, então a conexão (com os pragmas
WAL/synchronous/busy_timeout) mora junto do schema que ela serve.

Este módulo existe para o caminho de import histórico continuar funcionando:

    from services.db import get_db   # devolve o MESMO objeto do bootstrap

Não há segunda implementação: antes havia duas idênticas (``app.get_db`` e
``services.db.get_db``), e o ``app.py`` perdeu a cópia no PR B4 (#509). O alias
``DB_PATH`` que este módulo tinha (`config.DB_PATH`) também saiu — ninguém o
importava, e `config.DB_PATH` é o dono do valor (o `app.py` já o importa de lá).
"""

from services.bootstrap import get_db  # noqa: F401 — re-export (Issue #508)

__all__ = ["get_db"]
