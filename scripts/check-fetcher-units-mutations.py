#!/usr/bin/env python3
"""check-fetcher-units-mutations.py — mutation test do guard de unidades.

Prova que o guard de regressão de unidades (check-fetcher-units.py, #320)
BLOQUEARIA as 3 regressões históricas da auditoria 18-Ago-2026. Estratégia
de mutação real (não sintética): extrai o `tools.py` PRÉ-FIX autêntico de
cada bug via `git show <merge_sha>^:agents/solo_mining_advisor/tools.py`
e roda o fetcher mutado contra os MESMOS payloads reais das fixtures
(tests/fixtures/fetchers/*.json). Se o preço normalizado sair da faixa
econômica (10–200 sats/TH/d) ou a unidade vier errada, o guard falharia
no CI — a mutação foi DETECTADA.

Mutantes (os bugs da auditoria 18-Ago):
  1. NiceHash — priceFactor 1e18 ignorado → 46 sats × 1e6 = 46M (#303/#304)
  2. MRR      — price.type/hashrate.type "ph" ignorados → 66 sats × 24.000 (#311/#312)
  3. Braiins  — fallback sem chave sats/PH/day → 49 sats × 1000 (#315/#316)

Uso:
    python scripts/check-fetcher-units-mutations.py

Exit codes:
    0 — todas as mutações DETECTADAS (guard bloquearia cada regressão)
    1 — alguma mutação NÃO detectada (guard deixaria passar — falso seguro)
    2 — pré-requisitos ausentes (git repo / fixtures)

O teste exige acesso ao histórico git (git show) — roda no CI com clone
completo e localmente no fluxo Issue → PR.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "fetchers"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Faixa econômica — espelha o guard real (env-configurável).
MIN_SATS = float(os.environ.get("FETCHER_UNITS_MIN", 10))
MAX_SATS = float(os.environ.get("FETCHER_UNITS_MAX", 200))

# (nome, merge_sha do fix, fixture, expected_unit) — merge^ = estado pré-fix.
MUTATIONS = [
    (
        "nicehash priceFactor 1e18 ignorado",
        "785acef",  # merge do fix #304 (commit a3c92fa)
        "nicehash_orderbook.json",
        None,
    ),
    (
        "mrr price.type/hashrate.type ignorados",
        "88715b7",  # merge do fix #312 (commit 6761956)
        "mrr_orderbook.json",
        None,
    ),
    (
        "braiins fallback sats/PH/day (sem chave)",
        "ced0721",  # merge do fix #316 (commit 47af8a7)
        "braiins_orderbook.json",
        "EH/day",  # pós-fix reporta EH/day; pré-fix reportava sats/PH/day
    ),
]


def _extract_pre_fix(merge_sha: str, dst: Path) -> Path:
    """Extrai tools.py do commit PAI do merge (estado pré-fix) para dst."""
    out = subprocess.run(
        ["git", "show", f"{merge_sha}^:agents/solo_mining_advisor/tools.py"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if out.returncode != 0:
        raise RuntimeError(
            f"git show {merge_sha}^ falhou: {out.stderr.strip()[:200]}"
        )
    dst.write_text(out.stdout)
    return dst


def _load_module(path: Path, module_name: str):
    """Importa um tools.py avulso (pré-fix) como módulo isolado."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def json_load(path: Path) -> dict:
    with open(path) as fh:
        return json.load(fh)


def _run_mutation(name: str, merge_sha: str, fixture: str, expected_unit):
    """Roda o fetcher PRÉ-FIX contra a fixture real; retorna dict do guard."""
    with tempfile.TemporaryDirectory() as tmp:
        src = _extract_pre_fix(merge_sha, Path(tmp) / "tools_pre_fix.py")
        mod = _load_module(src, f"tools_pre_{merge_sha}")

        payload = json_load(FIXTURES / fixture)

        if "nicehash" in name:
            resp = mock.MagicMock()
            resp.ok = True
            resp.json.return_value = payload
            with mock.patch.object(mod.requests, "get", return_value=resp):
                result = mod.get_nicehash_orderbook()
        elif "mrr" in name:
            resp = mock.MagicMock()
            resp.ok = True
            resp.json.return_value = payload
            with mock.patch.object(mod.requests, "get", return_value=resp):
                result = mod.get_mrr_listings(
                    api_key="guard-key", api_secret="guard-secret"
                )
        else:  # braiins — sem chave → /spot/settings 401
            st_401 = mock.MagicMock()
            st_401.ok = False
            st_401.status_code = 401
            ob_ok = mock.MagicMock()
            ob_ok.ok = True
            ob_ok.json.return_value = payload

            def _braiins_get(url, **kw):
                if "settings" in url:
                    return st_401
                return ob_ok

            with mock.patch.object(mod.requests, "get", _braiins_get):
                result = mod.get_braiins_orderbook()

    return _evaluate(name, result, expected_unit)


def _evaluate(name: str, result: dict, expected_unit) -> bool:
    """Verifica se a mutação SAIRIA da faixa (guard falharia)."""
    if "error" in result:
        print(f"  ❌ mutante {name}: erro inesperado: {result['error']}")
        return False
    btc_per_th_day = result.get("price_btc_per_th_day")
    if not isinstance(btc_per_th_day, (int, float)) or btc_per_th_day <= 0:
        print(
            f"  ❌ mutante {name}: price_btc_per_th_day ausente/zerado: "
            f"{btc_per_th_day}"
        )
        return False
    sats = btc_per_th_day * 1e8
    ok = MIN_SATS <= sats <= MAX_SATS
    unit_note = ""
    if expected_unit is not None:
        got_unit = result.get("price_raw_unit") or result.get("price_unit")
        unit_ok = got_unit == expected_unit
        ok = ok and unit_ok
        unit_note = f" · unit={got_unit!r} (esperado {expected_unit!r})"
    detected = not ok  # mutação detectada = preço/unidade FORA do aceitável
    flag = "DETECTADA" if detected else "PASSOU (falso seguro!)"
    icon = "✅" if detected else "🚨"
    print(
        f"  {icon} mutação [{name}]: {sats:,.1f} sats/TH/d{unit_note} "
        f"→ {flag}"
    )
    return detected


def _check_git_refs() -> bool:
    """Confirma que os refs pré-fix existem no histórico local.

    O teste extrai o tools.py pré-fix via `git show <merge>^` — se o checkout
    do CI for raso (fetch-depth: 1), os merges antigos não existem localmente
    e o `git show` falha. Em vez de contar como "mutação não detectada"
    (falso seguro), detectamos a causa e retornamos exit 2 com instrução.
    """
    for _, merge_sha, _, _ in MUTATIONS:
        probe = subprocess.run(
            ["git", "cat-file", "-e", f"{merge_sha}^{{commit}}"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        if probe.returncode != 0:
            print(
                f"❌ histórico git raso/incompleto: ref {merge_sha} não existe "
                "localmente (checkout com fetch-depth: 1?)"
            )
            print(
                "   Configure `fetch-depth: 0` no job de CI ou rode "
                "`git fetch --unshallow` localmente."
            )
            return False
    return True


def main() -> int:
    # Pré-requisitos
    if not FIXTURES.exists():
        print(f"❌ fixtures ausentes: {FIXTURES}")
        return 2
    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if probe.returncode != 0:
        print("❌ não estamos num repo git — mutation test exige histórico")
        return 2
    if not _check_git_refs():
        return 2

    print("Fetcher-units MUTATION test — código pré-fix real (git show ^)")
    print(f"  faixa plausível: {MIN_SATS}–{MAX_SATS} sats/TH/d\n")

    detected = 0
    for name, merge_sha, fixture, expected_unit in MUTATIONS:
        try:
            if _run_mutation(name, merge_sha, fixture, expected_unit):
                detected += 1
        except Exception as exc:  # noqa: BLE001 — falha do harness = não detectada
            print(f"  ❌ mutação [{name}]: harness falhou: {str(exc)[:120]}")
    print()
    total = len(MUTATIONS)
    if detected == total:
        print(
            f"✅ mutation test green — {detected}/{total} mutações detectadas; "
            "o guard #320 bloquearia as 3 regressões históricas"
        )
        return 0
    print(
        f"🚨 mutation test FAILED — {detected}/{total} detectadas; "
        "o guard deixaria passar regressão de unidade"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
