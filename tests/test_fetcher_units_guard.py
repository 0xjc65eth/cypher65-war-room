"""test_fetcher_units_guard.py — self-test do guard de unidades dos fetchers.

O guard (scripts/check-fetcher-units.py) roda os fetchers contra payloads
REAIS capturados (tests/fixtures/fetchers/*.json) e falha se o preço
normalizado sair da faixa econômica plausível (10–200 sats/TH/d).

Roda de duas formas (padrão dos guards do repo):
    python tests/test_fetcher_units_guard.py   # standalone (exit code)
    pytest tests/test_fetcher_units_guard.py   # suíte completa

Testes:
1. Guard passa com as fixtures reais (4 caminhos na faixa).
2. Regressão de unidade é DETECTADA: NiceHash 1e6x, MRR 24.000x e Braiins
   1000x (os bugs da auditoria 18-Ago) ficam fora da faixa e o guard falha.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# O guard tem hífen no nome (padrão scripts/) — carrega via importlib.
_guard_path = ROOT / "scripts" / "check-fetcher-units.py"
_spec = importlib.util.spec_from_file_location("check_fetcher_units", _guard_path)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def test_guard_passes_with_real_fixtures():
    """Todos os 4 caminhos com payloads reais ficam na faixa (10–200 sats)."""
    assert guard.main() == 0


def test_nicehash_unit_regression_detected():
    """Bug #303 (priceFactor 1e18 ignorado) → 46 sats × 1e6 = 46M → falha."""
    fake_result = {"price_btc_per_th_day": 0.68}  # 0.68 BTC/TH/d = 68M sats
    assert guard._check("nicehash (regressão 1e6x)", fake_result) is False


def test_mrr_unit_regression_detected():
    """Bug #311 (price.type ignorado) → 66 sats × 24.000 = 11.4M → falha."""
    fake_result = {
        "price_btc_per_th_day": 0.1148,  # (0.00066×24)/0.138 → 11.478.261 sats
    }
    assert guard._check("mrr (regressão 24.000x)", fake_result) is False


def test_braiins_unit_regression_detected():
    """Bug #315 (fallback PH/day) → 49 sats × 1000 = 49.050 → falha."""
    fake_result = {
        "price_btc_per_th_day": 0.0004905,  # 49.050 sats/TH/d
    }
    assert guard._check("braiins (regressão 1000x)", fake_result) is False


def test_braiins_wrong_unit_label_detected():
    """Caminho sem chave deve reportar EH/day — unit errada = falha."""
    fake_result = {
        "price_btc_per_th_day": 4.9126e-7,  # ~49 sats (correto)
        "price_raw_unit": "sats/PH/day",  # unidade errada (bug pré-fix)
    }
    assert guard._check("braiins (unit errada)", fake_result, "EH/day") is False


def _run_all() -> int:
    """Standalone runner (exit code 0/1) — padrão dos self-tests dos guards."""
    tests = [
        ("guard verde nas fixtures reais", test_guard_passes_with_real_fixtures),
        ("detecta regressão nicehash 1e6x", test_nicehash_unit_regression_detected),
        ("detecta regressão mrr 24.000x", test_mrr_unit_regression_detected),
        ("detecta regressão braiins 1000x", test_braiins_unit_regression_detected),
        ("detecta unit label errada braiins", test_braiins_wrong_unit_label_detected),
    ]
    fails = 0
    print("fetcher-units guard self-test")
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
