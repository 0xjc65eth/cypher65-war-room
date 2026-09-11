"""
CYPHER65 // DB bootstrap — contrato da extração (RFC #478 · PR B4 / #507)
========================================================================
Tripwire da extração `app.py` → `services/bootstrap.py`.

`init_db()` são 576 linhas de DDL: tabelas, ALTERs guardados para DBs legados,
índices, os pragmas da conexão e o carimbo da revisão do schema — além de
delegar o `ensure_table()` dos módulos de telemetria. Estes testes travam a
fronteira:

  1. os nomes movidos são o MESMO objeto nos dois módulos — `app.init_db()`,
     `appmod.purge_old()` e `app_module.SCHEMA_VERSION`, que a suíte usa,
     continuam válidos;
  2. `get_db` passou a ter UMA implementação (`services.db`); o `app.py` só
     re-exporta — a duplicata idêntica foi eliminada;
  3. `services/bootstrap.py` não importa `app` (sem ciclo), checado no AST;
  4. `init_db()` cria exatamente as tabelas e índices esperados, é
     **idempotente** e carimba a revisão do schema;
  5. o boot (`import app`) deixa o schema criado no `DB_PATH` do env — é o que
     o `tests/conftest.py` assume em ~20 módulos;
  6. `purge_old()` mantém a retenção de 30 dias.

Nota: o schema é um contrato. Adicionar uma tabela/índice novo exige atualizar
`EXPECTED_TABLES`/`EXPECTED_INDEXES` aqui — de propósito.
"""

import ast
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
import services.bootstrap as bootstrap  # noqa: E402
import services.db as db_module  # noqa: E402

# Tabelas criadas por `bootstrap.init_db()` SOZINHO (dump ao vivo do
# sqlite_master; ver a PR #508). `devices` e `axe_agent_commands` NÃO entram
# aqui: quem as cria são os registries no boot (DeviceRegistry /
# CoreDeviceRegistry) — ver BOOT_TABLES abaixo.
EXPECTED_TABLES = {
    "alert_history",
    "alert_rules",
    "alerts",
    "audit_logs",
    "automation_execution_log",
    "automation_rules",
    "axe_devices",
    "axe_telemetry",
    "best_diff_history",
    "beta_analytics",
    "conversion_events",
    "degradation_metrics",
    "doc_feedback",
    "donations",
    "error_metrics",
    "hashrate_market_history",
    "highest_diff_events",
    "maintenance_records",
    "pool_metrics",
    "proximity_history",
    "schema_version",
    "settings",
    "share_timeline",
    "snapshots",
    "tenant_settings",
    "tenants",
    "users",
    "wallet_address_history",
}

# Tabelas que existem só depois do BOOT completo (criadas pelos registries de
# dispositivo, não pelo init_db).
BOOT_ONLY_TABLES = {"devices", "axe_agent_commands"}

# Índices que o init_db precisa garantir (os criados pelos módulos de
# telemetria entram pelas chamadas ensure_table/ensure_degradation_table).
EXPECTED_INDEXES = {
    "idx_alerts_active",
    "idx_alerts_device",
    "idx_alerts_ts",
    "idx_degradation_metrics_hour",
    "idx_doc_feedback_section",
    "idx_error_metrics_hour",
    "idx_snapshots_ts",
    "idx_share_timeline_ts",
    "idx_tenant_settings_tenant",
    "idx_users_tenant",
    "idx_wallet_history_addr",
    "idx_wallet_history_ts",
    "uq_snapshots_ts",
}


def _objects(db_path: str, kind: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE 'sqlite_%'",
            (kind,),
        ).fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


def _master(db_path: str) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT type, name, COALESCE(sql,'') FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
    finally:
        conn.close()


# ── 1. Re-export: um objeto só ─────────────────────────────────────────────


def test_moved_callables_are_the_same_object_in_both_modules():
    assert app_module.init_db is bootstrap.init_db
    assert app_module.purge_old is bootstrap.purge_old
    assert app_module._record_schema_version is bootstrap._record_schema_version


def test_schema_version_constant_is_shared_with_the_app():
    assert app_module.SCHEMA_VERSION == bootstrap.SCHEMA_VERSION
    from services.schema import CURRENT_SCHEMA_VERSION

    assert bootstrap.SCHEMA_VERSION == CURRENT_SCHEMA_VERSION


# ── 2. get_db: uma implementação só ────────────────────────────────────────


def test_get_db_has_a_single_implementation():
    """A duplicata `app.get_db` (idêntica a `services.db.get_db`) morreu."""
    assert app_module.get_db is db_module.get_db
    assert app_module.get_db.__module__ == "services.db"


def test_get_db_reads_db_path_from_the_environment_at_call_time(monkeypatch, tmp_path):
    target = str(tmp_path / "env_at_call.sqlite")
    monkeypatch.setenv("DB_PATH", target)
    conn = db_module.get_db()
    conn.close()
    assert tmp_path.joinpath("env_at_call.sqlite").exists()


# ── 3. Sem ciclo ───────────────────────────────────────────────────────────


def test_bootstrap_does_not_import_app():
    tree = ast.parse(open(bootstrap.__file__).read())
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods.append(node.module or "")
    forbidden = [m for m in mods if m == "app"]
    assert forbidden == [], f"import circular: {forbidden}"


# ── 4. init_db: schema, idempotência, carimbo ─────────────────────────────


def test_init_db_creates_exactly_the_expected_tables(monkeypatch, tmp_path):
    db_path = str(tmp_path / "boot.sqlite")
    monkeypatch.setenv("DB_PATH", db_path)
    bootstrap.init_db()
    assert _objects(db_path, "table") == EXPECTED_TABLES


def test_init_db_creates_the_expected_indexes(monkeypatch, tmp_path):
    db_path = str(tmp_path / "boot.sqlite")
    monkeypatch.setenv("DB_PATH", db_path)
    bootstrap.init_db()
    assert EXPECTED_INDEXES <= _objects(db_path, "index")


def test_init_db_is_idempotent(monkeypatch, tmp_path):
    """Rodar de novo não altera um único objeto de schema."""
    db_path = str(tmp_path / "boot.sqlite")
    monkeypatch.setenv("DB_PATH", db_path)
    bootstrap.init_db()
    first = _master(db_path)
    bootstrap.init_db()
    bootstrap.init_db()
    assert _master(db_path) == first


def test_init_db_stamps_the_schema_version(monkeypatch, tmp_path):
    db_path = str(tmp_path / "boot.sqlite")
    monkeypatch.setenv("DB_PATH", db_path)
    bootstrap.init_db()
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT version FROM schema_version").fetchall()
    finally:
        conn.close()
    assert [r[0] for r in rows] == [bootstrap.SCHEMA_VERSION]


def test_init_db_creates_the_telemetry_tables_it_delegates(monkeypatch, tmp_path):
    """init_db não é só DDL local — ele garante o schema dos serviços."""
    db_path = str(tmp_path / "boot.sqlite")
    monkeypatch.setenv("DB_PATH", db_path)
    bootstrap.init_db()
    tables = _objects(db_path, "table")
    assert {
        "doc_feedback",  # services.doc_feedback
        "error_metrics",  # services.error_tracker
        "degradation_metrics",  # services.error_tracker (Issue #202)
        "conversion_events",  # services.conversion
        "beta_analytics",  # services.beta_analytics
    } <= tables


# ── 5. O boot cria o schema no DB_PATH do env (contrato do conftest) ───────


def test_importing_app_bootstraps_the_schema_at_the_env_db_path():
    """`import app` roda init_db() no escopo do módulo — conftest depende disso."""
    db_path = os.environ.get("DB_PATH")
    assert db_path, "conftest deve apontar DB_PATH para um scratch"
    tables = _objects(db_path, "table")
    assert EXPECTED_TABLES <= tables


def test_boot_also_creates_the_registry_owned_tables():
    """`devices`/`axe_agent_commands` vêm dos registries, não do init_db()."""
    db_path = os.environ.get("DB_PATH")
    assert BOOT_ONLY_TABLES <= _objects(db_path, "table")


# ── 6. purge_old: retenção de 30 dias ──────────────────────────────────────


def test_purge_old_deletes_only_rows_older_than_thirty_days(monkeypatch, tmp_path):
    import time

    db_path = str(tmp_path / "purge.sqlite")
    monkeypatch.setenv("DB_PATH", db_path)
    bootstrap.init_db()

    now = int(time.time())
    old_ts = now - 31 * 86400
    new_ts = now - 1 * 86400
    conn = sqlite3.connect(db_path)
    try:
        for ts in (old_ts, new_ts):
            conn.execute("INSERT INTO snapshots (ts) VALUES (?)", (ts,))
        conn.commit()
    finally:
        conn.close()

    bootstrap.purge_old()

    conn = sqlite3.connect(db_path)
    try:
        kept = [r[0] for r in conn.execute("SELECT ts FROM snapshots").fetchall()]
    finally:
        conn.close()
    assert kept == [new_ts], "purge_old deve manter só o que está dentro dos 30 dias"
