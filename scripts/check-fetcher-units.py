#!/usr/bin/env python3
"""check-fetcher-units.py — guard de regressão de unidade dos fetchers (CI).

Auditoria 18-Ago-2026: cada API de mercado declara a unidade dos preços no
próprio payload (NiceHash priceFactor/marketFactor=1e18, MRR price.type/
hashrate.advertised.type, Braiins hr_unit) e o código as ignorava — preços
1e6x/24.000x/1000x inflados. Os fixes (#304/#306, #312, #315/#316) leram os
fatores declarados.

Este guard roda os fetchers contra payloads REAIS capturados em 18-Ago
(tests/fixtures/fetchers/*.json) e falha se o preço normalizado sair da
faixa econômica plausível (10–200 sats/TH/d) — qualquer regressão de
unidade re-inflaria o preço por 1e3x+ e seria detectada aqui.

Uso:
    python scripts/check-fetcher-units.py

Faixa configurável via env (a hashprice decai com o tempo/halvings):
    FETCHER_UNITS_MIN=10 FETCHER_UNITS_MAX=200 python scripts/check-fetcher-units.py

Refresh das fixtures quando a API mudar de formato (contrato novo):
    curl -s 'https://api2.nicehash.com/main/api/v2/hashpower/orderBook?algorithm=SHA256' \
      > tests/fixtures/fetchers/nicehash_orderbook.json
    curl -s 'https://www.miningrigrentals.com/api/v2/rig?type=sha256&order=price' \
      > /tmp/mrr.json  # depois encurtar para 6 records
    curl -s 'https://hashpower.braiins.com/v1/spot/orderbook' \
      > tests/fixtures/fetchers/braiins_orderbook.json

Exit codes:
    0 — todos os fetchers na faixa
    1 — pelo menos um fetcher fora da faixa (regressão de unidade)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "fetchers"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Faixa econômica plausível para SHA-256 (18-Ago-2026): 10–200 sats/TH/d.
# Valores reais no momento da captura: NiceHash ~68, MRR ~66, Braiins ~49.
# Configurável via env para acompanhar a hashprice (que decai com o tempo).
MIN_SATS = float(os.environ.get("FETCHER_UNITS_MIN", 10))
MAX_SATS = float(os.environ.get("FETCHER_UNITS_MAX", 200))


def _load(name: str) -> dict:
    with open(FIXTURES / name) as fh:
        return json.load(fh)


def _sats_per_th_day(btc_per_th_day: float) -> float:
    return btc_per_th_day * 1e8


def _check(name: str, result: dict, expected_unit: str | None = None) -> bool:
    if "error" in result:
        print(f"  ❌ {name}: erro inesperado: {result['error']}")
        return False
    btc_per_th_day = result.get("price_btc_per_th_day")
    if not isinstance(btc_per_th_day, (int, float)) or btc_per_th_day <= 0:
        print(f"  ❌ {name}: price_btc_per_th_day ausente/zerado: {btc_per_th_day}")
        return False
    sats = _sats_per_th_day(btc_per_th_day)
    ok = MIN_SATS <= sats <= MAX_SATS
    unit = ""
    if expected_unit is not None:
        got_unit = result.get("price_raw_unit") or result.get("price_unit")
        unit_ok = got_unit == expected_unit
        if not unit_ok:
            print(
                f"  ❌ {name}: unidade {got_unit!r} != esperada {expected_unit!r}"
            )
        ok = ok and unit_ok
        unit = f" · unit={got_unit!r}"
    status = "✅" if ok else "❌"
    print(f"  {status} {name}: {sats:.1f} sats/TH/d{unit}")
    return ok


def main() -> int:
    os.environ.setdefault("SECRET_KEY", "test-secret-0123456789")
    from agents.solo_mining_advisor import tools

    mrr_payload = _load("mrr_orderbook.json")
    nicehash_payload = _load("nicehash_orderbook.json")
    braiins_payload = _load("braiins_orderbook.json")

    print("Fetcher units guard — payloads reais 18-Ago-2026")
    print(f"  faixa plausível: {MIN_SATS}–{MAX_SATS} sats/TH/d\n")

    fails = 0

    # ── NiceHash (priceFactor/marketFactor = 1e18, fix #304/#306) ─────────
    nh_resp = mock.MagicMock()
    nh_resp.ok = True
    nh_resp.json.return_value = nicehash_payload
    with mock.patch(
        "agents.solo_mining_advisor.tools.requests.get", return_value=nh_resp
    ):
        nh = tools.get_nicehash_orderbook()
    if not _check("nicehash (priceFactor 1e18)", nh):
        fails += 1

    # ── MRR (price.type/hashrate.advertised.type="ph", fix #312) ──────────
    mrr_resp = mock.MagicMock()
    mrr_resp.ok = True
    mrr_resp.json.return_value = mrr_payload
    with mock.patch(
        "agents.solo_mining_advisor.tools.requests.get", return_value=mrr_resp
    ):
        mrr = tools.get_mrr_listings(api_key="guard-key", api_secret="guard-secret")
    if not _check("mrr (price.type=ph)", mrr):
        fails += 1

    # ── Braiins orderbook público SEM chave (fallback EH/day, fix #315) ────
    st_401 = mock.MagicMock()
    st_401.ok = False
    st_401.status_code = 401
    ob_ok = mock.MagicMock()
    ob_ok.ok = True
    ob_ok.json.return_value = braiins_payload

    def _braiins_get(url, **kw):
        if "settings" in url:
            return st_401
        return ob_ok

    with mock.patch("agents.solo_mining_advisor.tools.requests.get", _braiins_get):
        braiins_public = tools.get_braiins_orderbook()
    if not _check(
        "braiins (orderbook público, sem chave → EH/day)", braiins_public, "EH/day"
    ):
        fails += 1

    # ── Braiins COM chave (hr_unit oficial EH/day, fix #269) ───────────────
    st_key = mock.MagicMock()
    st_key.ok = True
    st_key.json.return_value = {"hr_unit": "EH/day"}
    ob_key = mock.MagicMock()
    ob_key.ok = True
    ob_key.json.return_value = braiins_payload

    def _braiins_get_keyed(url, **kw):
        if "settings" in url:
            return st_key
        return ob_key

    with mock.patch(
        "agents.solo_mining_advisor.tools.requests.get", _braiins_get_keyed
    ), mock.patch(
        "agents.solo_mining_advisor.tools.braiins_credentials",
        return_value={"api_key": "guard-key", "api_secret": ""},
    ):
        braiins_keyed = tools.get_braiins_orderbook()
    if not _check("braiins (com chave, hr_unit=EH/day)", braiins_keyed, "EH/day"):
        fails += 1

    print()
    if fails:
        print(f"❌ fetcher-units guard FAILED — {fails} fetcher(s) fora da faixa")
        return 1
    print("✅ fetcher-units guard green — unidades corretas nos 4 caminhos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
