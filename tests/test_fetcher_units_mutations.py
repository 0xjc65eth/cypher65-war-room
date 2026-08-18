"""test_fetcher_units_mutations.py — self-test do mutation test do guard.

O mutation test (scripts/check-fetcher-units-mutations.py) extrai o
`tools.py` PRÉ-FIX autêntico de cada bug da auditoria 18-Ago via
`git show <merge>^` e roda o fetcher mutado contra as fixtures reais —
o guard (#320) deve BLOQUEAR as 3 regressões históricas (NiceHash 1e6x,
MRR 24.000x, Braiins 1000x + unit errada).

Roda de duas formas (padrão dos guards do repo):
    python tests/test_fetcher_units_mutations.py   # standalone (exit code)
    pytest tests/test_fetcher_units_mutations.py   # suíte completa

Testes:
1. As 3 mutações (código pré-fix real) são todas DETECTADAS (guard falharia).
2. A faixa configurável funciona (apertar MIN → mutações ainda detectadas).
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# O script tem hífen no nome (padrão scripts/) — carrega via importlib.
_mut_path = ROOT / "scripts" / "check-fetcher-units-mutations.py"
_spec = importlib.util.spec_from_file_location("check_fetcher_units_mutations", _mut_path)
mut = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mut)


def test_all_historical_regressions_detected():
    """3/3 mutações com código PRÉ-FIX real devem ser bloqueadas."""
    assert mut.main() == 0


def test_detection_works_with_tighter_band():
    """Banda apertada (MIN=100) mantém a detecção das mutações.

    O MIN/MAX são lidos no import do módulo (constantes do guard), então o
    teste ajusta os ATRIBUTOS do módulo diretamente — env no meio do teste
    não teria efeito (achado do code review).
    """
    import unittest.mock as umock

    with (
        umock.patch.object(mut, "MIN_SATS", 100.0),
        umock.patch.object(mut, "MAX_SATS", 200.0),
    ):
        assert mut.main() == 0


def _run_all() -> int:
    """Standalone runner (exit code 0/1) — padrão dos self-tests dos guards."""
    tests = [
        ("3/3 mutações pré-fix detectadas", test_all_historical_regressions_detected),
        ("banda apertada mantém detecção", test_detection_works_with_tighter_band),
    ]
    fails = 0
    print("fetcher-units mutation test self-test")
    for name, fn in tests:
        try:
            fn()
            print(f"  ✅ {name}")
        except AssertionError as exc:
            print(f"  ❌ {name}: {exc}")
            fails += 1
    print()
    if fails:
        print(f"❌ self-test FAILED — {fails} teste(s) vermelho(s)")
        return 1
    print("✅ self-test green")
    return 0


if __name__ == "__main__":
    sys.exit(_run_all())
