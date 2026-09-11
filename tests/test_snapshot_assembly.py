"""
CYPHER65 // Snapshot assembly — contrato da extração (RFC #478 · PR B3 / #501)
==============================================================================
Tripwire da extração `services/user_polling.py` → `services/snapshot_assembly.py`.

`_build_snapshot` (240 linhas) monta o dict que o dashboard consome, e a camada
de fetch global que o alimenta saiu com ela. Estes testes travam a fronteira:

  1. os nomes movidos são o MESMO objeto nos dois módulos — `app.py` importa
     `_build_snapshot` de `services.user_polling` e isso não pode mudar;
  2. `services/snapshot_assembly.py` não importa `services.user_polling` nem
     `app` (sem ciclo) — checado no AST, não por substring;
  3. o fetch layer agora é resolvido nos globals do módulo NOVO: patchear
     `services.snapshot_assembly` intercepta, patchear `services.user_polling`
     não — o teste positivo E o negativo, porque este é o jeito de o refactor
     quebrar em silêncio (um patch que não intercepta não falha; ele apenas
     deixa o teste passar com dados reais ou vazios);
  4. `_build_snapshot` mantém o schema e os defaults (todas as chaves, `stale`
     False, `pool` normalizado para None quando o upstream está vazio);
  5. endereço vazio curto-circuita sem tocar a rede.
"""

import ast
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.snapshot_assembly as sa  # noqa: E402
import services.user_polling as up  # noqa: E402

ADDRESS = "bc1qtestaddress"

# Chaves do snapshot montado por _build_snapshot (schema consumido pelo front).
SNAPSHOT_KEYS = {
    "ts",
    "btc_address",
    "worker",
    "worker_index",
    "user_aggregate",
    "pool",
    "account",
    "account_meta",
    "lightning",
    "leaderboard_entry",
    "leaderboard_total",
    "highest_diffs",
    "network",
    "btc_price",
    "luck_estimate",
    "halving",
    "mempool_fees",
    "profitability",
    "milestones",
    "proximity",
    "network_share_gauge",
    "alerts_recent",
    "timeline_recent",
    "event_stats",
    "leaderboard_table_top_30",
    "all_workers",
}


def _patch_fetchers(monkeypatch, module, *, height, usd):
    """Mocka os 8 fetchers do `_build_snapshot` no módulo dado (sem rede)."""
    monkeypatch.setattr(module, "_fetch_user_data", lambda address: {"workerData": []})
    monkeypatch.setattr(module, "_fetch_account", lambda address: None)
    monkeypatch.setattr(
        module, "_fetch_global_pool", lambda: {"hashrate": 1e15, "workers": 3}
    )
    monkeypatch.setattr(module, "_fetch_global_leaderboard", lambda limit=100: [])
    monkeypatch.setattr(
        module, "_fetch_global_highest_diffs", lambda address, limit=20: []
    )
    monkeypatch.setattr(
        module, "_fetch_global_network", lambda: (height, 1.26e14, 6e20)
    )
    monkeypatch.setattr(
        module,
        "_fetch_global_btc_price",
        lambda: {"bitcoin": {"usd": usd, "brl": 350000.0}},
    )
    monkeypatch.setattr(
        module, "_fetch_global_mempool_fees", lambda: {"fastestFee": 12}
    )


# ── 1. Re-export: um objeto só nos dois módulos ────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "_build_snapshot",
        "_cached_user_fetch",
        "_fetch_account",
        "_fetch_global_btc_price",
        "_fetch_global_highest_diffs",
        "_fetch_global_leaderboard",
        "_fetch_global_mempool_fees",
        "_fetch_global_network",
        "_fetch_global_pool",
        "_fetch_json",
        "_fetch_text",
        "_fetch_user_data",
        "_get_global",
        "_update_global",
    ],
)
def test_moved_callables_are_the_same_object_in_both_modules(name):
    """`from services.user_polling import X` continua entregando o objeto real."""
    assert getattr(up, name) is getattr(sa, name)


def test_moved_mutable_state_is_shared_not_copied():
    """Cache e btc_price_cache são o MESMO dict — não uma cópia que divergiria."""
    assert up._global_cache is sa._global_cache
    assert up.btc_price_cache is sa.btc_price_cache


def test_moved_constants_keep_their_values():
    assert up.GLOBAL_CACHE_TTL == sa.GLOBAL_CACHE_TTL
    assert up.USER_FETCH_TTL == sa.USER_FETCH_TTL
    assert up.PARASITE_API == sa.PARASITE_API
    assert up.MEMPOOL_API == sa.MEMPOOL_API
    assert up.FETCH_MAX_RETRIES == sa.FETCH_MAX_RETRIES


# ── 2. Sem ciclo ───────────────────────────────────────────────────────────


def _imported_modules(path):
    tree = ast.parse(open(path).read())
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods.append(node.module or "")
    return mods


def test_snapshot_assembly_does_not_import_user_polling_or_app():
    """O wiring é unidirecional: user_polling → snapshot_assembly."""
    mods = _imported_modules(sa.__file__)
    forbidden = [
        m for m in mods if m in ("app", "services.user_polling", "user_polling")
    ]
    assert forbidden == [], f"import circular: {forbidden}"


def test_app_import_surface_still_resolves_to_the_module():
    """`app.py` importa `_build_snapshot` de services.user_polling (contrato)."""
    from services.user_polling import _build_snapshot as via_user_polling

    assert via_user_polling is sa._build_snapshot


# ── 3. O fetch layer é resolvido no módulo novo ────────────────────────────


def test_patching_snapshot_assembly_intercepts_the_fetch_layer(monkeypatch):
    _patch_fetchers(monkeypatch, sa, height=857200, usd=61234)
    snap = sa._build_snapshot(ADDRESS, "miner")
    assert snap["network"]["height"] == 857200
    assert snap["btc_price"]["usd"] == 61234
    assert snap["mempool_fees"] == {"fastestFee": 12}


def test_patching_user_polling_does_not_intercept_the_fetch_layer(monkeypatch):
    """O trap documentado no cabeçalho do módulo novo.

    `_build_snapshot` resolve os nomes nos globals de `services.snapshot_assembly`
    — um `setattr(services.user_polling, "_fetch_global_network", …)` é inerte.
    Os dois lados estão mockados aqui (sem rede) com valores distintos, então o
    que o snapshot mostra é a prova de qual módulo manda.
    """
    _patch_fetchers(monkeypatch, sa, height=111, usd=1)
    _patch_fetchers(monkeypatch, up, height=999, usd=999)

    snap = sa._build_snapshot(ADDRESS, "miner")

    assert snap["network"]["height"] == 111
    assert snap["btc_price"]["usd"] == 1


# ── 4. Schema e defaults preservados ───────────────────────────────────────


def test_build_snapshot_keeps_the_full_schema(monkeypatch):
    _patch_fetchers(monkeypatch, sa, height=857200, usd=61234)
    snap = sa._build_snapshot(ADDRESS, "miner")
    assert set(snap) == SNAPSHOT_KEYS
    assert snap["btc_address"] == ADDRESS
    assert isinstance(snap["ts"], int)
    assert snap["network"]["stale"] is False
    assert snap["btc_price"]["stale"] is False
    assert snap["btc_price"]["brl"] == 350000.0


def test_build_snapshot_normalizes_empty_pool_to_none(monkeypatch):
    _patch_fetchers(monkeypatch, sa, height=857200, usd=61234)
    monkeypatch.setattr(sa, "_fetch_global_pool", lambda: {})
    snap = sa._build_snapshot(ADDRESS, "miner")
    assert snap["pool"] is None


def test_build_snapshot_computes_the_halving_countdown(monkeypatch):
    _patch_fetchers(monkeypatch, sa, height=857200, usd=61234)
    snap = sa._build_snapshot(ADDRESS, "miner")
    halving = snap["halving"]
    # 857200 // 210000 = 4 → a próxima era fecha em 5 * 210000.
    next_height = ((857200 // 210000) + 1) * 210000
    assert next_height == 1050000
    assert halving["next_height"] == next_height
    assert halving["blocks_remaining"] == next_height - 857200
    assert halving["estimated_days_remaining"] == (next_height - 857200) * 600 / 86400.0
    assert halving["epoch_label"] == "#5/33"


# ── 5. Short-circuit sem rede ──────────────────────────────────────────────


def test_empty_address_short_circuits_without_fetching(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("endereço vazio não pode tocar a rede")

    for name in (
        "_fetch_user_data",
        "_fetch_account",
        "_fetch_global_pool",
        "_fetch_global_leaderboard",
        "_fetch_global_highest_diffs",
        "_fetch_global_network",
        "_fetch_global_btc_price",
        "_fetch_global_mempool_fees",
    ):
        monkeypatch.setattr(sa, name, _boom)

    snap = sa._build_snapshot("", "miner")
    assert set(snap) == SNAPSHOT_KEYS
    assert snap["btc_address"] == ""
    assert snap["network"]["height"] is None
