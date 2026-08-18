# 🐛 Incidente — NiceHash: priceFactor 1e18 ignorado → preço 1e6× inflado no HashMarket

**Auditoria de unidades dos fetchers · 18-Ago-2026**
**Status: ✅ RESOLVIDO — PRs #304 (`785acef`) e #306 (`076e453`) mergeados e deployados**

> **Evidência primária:** payload real da API v2 do NiceHash (`api2.nicehash.com/api/v2/hashpower/orderBook` — pública, sem auth) capturado em 18-Ago-2026 + git diff dos fixes (`a3c92fa`, `0b5b0f9`) + probes de produção (`/api/snapshot`, Playwright no painel).

---

## 1. Resumo executivo

O HashMarket mostrava o preço do NiceHash como **68.000.000 sats/TH/d** (e ROI **−99.1%**), quando o valor real de mercado é **~68 sats/TH/d**. Causa raiz: a API v2 do NiceHash **declara as unidades no próprio payload** — `priceFactor` e `marketFactor` = `1e18` (EH) — e o código as ignorava, tratando `price` como BTC/TH/day e `acceptedSpeed` como H/s. O resultado era um fator de **1e6×** no preço, quebrando ROI/EV/score de todas as superfícies que consomem a oferta do NiceHash.

**Sequência de dois fixes (mesmo audit):**
1. **#304** (`a3c92fa` → merge `785acef`): leitura de `priceFactor`/`marketFactor` + conversão correta → preço 68 sats/TH/d ✓, mas expôs um **segundo** problema: uma ordem fantasma/junk (com `acceptedSpeed` de rigs fantasmas ou `limit=0`) vencia o "cheapest" e o painel mostrava ROI **+5.462.274%** (custo ~0).
2. **#306** (`0b5b0f9` → merge `076e453`): filtro de ordens fantasma (`acceptedSpeed=0`) + **rejeição de outlier** (ordens < 20% da mediana do book) → painel mostra **52.8 sats/TH/d · ROI plausível**.

---

## 2. Findings Table

| Sev | Fase | Achado | Evidência | Impacto | Fix |
|---|---|---|---|---|---|
| **Sev-1** | P0 | **`priceFactor`/`marketFactor` = 1e18 (EH) declarados pela API, ignorados pelo código** — `price` (BTC/EH/dia) tratado como BTC/TH/dia; `acceptedSpeed` (EH) tratado como H/s | Payload real: `"priceFactor": "1000000000000000000.00000000"`, `"price": "0.68"`, `"acceptedSpeed": "0.00057"` vs código pré-fix | Preço **1e6× inflado** (68.000.000 vs 68 sats/TH/d) → ROI −99.1% · EV −0.099 BTC vs cost 0.1 BTC · score/quotes errados | ✅ **#304** (`a3c92fa`): `btc_per_th_day = price / priceFactor × 1e12`; `speed_ph = acceptedSpeed × marketFactor / 1e15`; `limit_hs = limit × marketFactor` + 4 testes com payload real |
| **Sev-1** | P0 | **Ordem fantasma/junk vence o cheapest** — após o fix de unidade, ordem com `acceptedSpeed` de rig fantasma (ou `limit=0`, ex. `price: 0.0001` BTC/EH/d vs book real 0.5876–0.6823) passa no filtro de `alive` e destrói o ROI | Probe pós-#304: NiceHash 68 sats/TH/d mas ROI **+5.462.274%** (custo ~0) | Painel com ROI absurdo; decisão de compra impossível | ✅ **#306** (`0b5b0f9`): filtro `acceptedSpeed>0` (fantasma) + **outlier < 20% da mediana** do book ativo → rejeitado antes do "cheapest" |

---

## 3. Causa raiz — a API declara a unidade; o código a ignorava

**Payload real (18-Ago, `api2.nicehash.com/api/v2/hashpower/orderBook?algorithm=SHA256`):**

```json
"stats": { "BTC": {
  "priceFactor": "1000000000000000000.00000000",
  "marketFactor": "1000000000000000000.00000000",
  "orders": [
    { "price": "0.68", "acceptedSpeed": "0.00057", "limit": "100000", "alive": true }
  ]
}}
```

**Semântica oficial (NiceHash v2 Hashpower):**
- `price` é **BTC por (priceFactor) H/s por dia** — com `priceFactor=1e18` (EH), `price` = **BTC/EH/dia**.
- `acceptedSpeed`/`limit` estão na unidade de `marketFactor` (EH para 1e18).

**O que o código pré-fix fazia** (`get_nicehash_orderbook` em `agents/solo_mining_advisor/tools.py`):

```python
# ANTES (bug):
price_btc_per_ph_day = float(best["price"])   # 0.68 — tratado como BTC/TH/dia
# 0.68 BTC/TH/d = 68.000.000 sats/TH/d — 1e6× sobre o real (0.68 BTC/EH/d = 6.8e-7 BTC/TH/d)
```

**Correção** (padrão atual, `tools.py` L537-596):

```python
price_factor   = float(btc_stats.get("priceFactor", 1e18))    # 1e18 → EH
market_factor  = float(btc_stats.get("marketFactor", 1e18))
btc_per_th_day = price_raw / price_factor * 1e12              # 0.68/1e18*1e12 = 6.8e-7 = 68 sats
speed_ph       = speed_factor_units * market_factor / 1e15    # EH → PH/s
limit_hs       = float(best.get("limit", 0)) * market_factor  # EH → H/s
```

---

## 4. Prova real (produção)

| Métrica | Antes do fix | Depois do deploy (#304+#306) | Real de mercado |
|---|---|---|---|
| **NiceHash sats/TH/d** | 0.01 (junk) / **68.000.000** (unidade errada) | **52.76–62.9** (flutua com o mercado) | ~50–120 (fair value ~75) |
| **NiceHash ROI** | −99.1% → +5.462.274% | **−21.6% a −2.9%** (plausível) | ±30% em torno de 0 |
| **Est. cost (BTC)** | ~0 (junk) | **0.00001511** (Playwright) | ~0.0000150 |

**Evidência (18-Ago, probes em `cypher65-war-room.onrender.com`):**
- **Probe `/api/snapshot`** pós-deploy: `nicehash | 52.76 sats/TH/d` — filtro de outlier ativo, ordem junk rejeitada.
- **Playwright no painel** (aba HashMarket): NiceHash **52.8 sat/TH/d**, est. cost `0.00001511 BTC`, ROI plausível.
- **Testes com payload real** (`tests/test_hashrate_market_parsers.py` L237-288): mock agora inclui `priceFactor`/`marketFactor` = 1e18 e `price: "0.68"` → assert de **6.8e-7 BTC/TH/d (= 68 sats)**.

---

## 5. Impacto e lições

**Impacto:** quando o fix de unidade ainda não existia, o NiceHash ficava **fora do mercado** (parecia 1e6× caro) — nenhuma ordem seria recomendada; após o fix parcial (#304), parecia **gratuito** (ROI +5M%) — risco de decisão de compra errada. Ambos os estados quebravam a confiança no HashMarket.

**Lições (padrão sistêmico — varredura dos fetchers em 18-Ago):**
1. **Nunca assumir unidade de preço/hashrate** — ler os fatores declarados pela API no próprio payload.
2. O mesmo padrão apareceu em **outros fetchers** (mesmo audit): **MRR** declara `price.type: "ph"` e `hashrate.advertised.type: "ph"` (24.000× errado — Sev-1, correção em andamento) e **Braiins** depende do `hr_unit` do `/spot/settings` (fallback sem chave assume unidade errada — Sev-2, 1000× no prod).
3. **Filtros defensivos de book** (fantasma + outlier) são obrigatórios em qualquer agregador de ordem: ordem com preço fora de 20% da mediana é quase sempre lixo de API.

---

## 6. Artefatos

| Artefato | Referência |
|---|---|
| Fix unidade (priceFactor/marketFactor) | PR **#304** · commit `a3c92fa` → merge `785acef` (Closes **#303**) |
| Fix outlier/ordem fantasma | PR **#306** · commit `0b5b0f9` → merge `076e453` (Closes **#305**) |
| Código atual (fonte da verdade) | `agents/solo_mining_advisor/tools.py` L493-610 (`get_nicehash_orderbook`) |
| Testes com payload real | `tests/test_hashrate_market_parsers.py` L237-330 |
| Auditoria-fonte da varredura | 18-Ago-2026 — varredura de fatores de unidade de todos os fetchers (Braiins/MRR/NiceHash/Parasite) |
