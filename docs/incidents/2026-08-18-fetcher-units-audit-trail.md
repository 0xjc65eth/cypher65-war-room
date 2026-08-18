# 🧭 Trilha de Auditoria — Unidades dos Fetchers do HashMarket (18-Ago-2026)

**Auditoria única e consolidada de fatores de unidade de todos os fetchers de preço**
**Status: 2/3 corrigidos · 1 pendente (Braiins Bug B — fallback sem chave)**

> **Motivação:** a auditoria de 18-Ago-2026 (varredura de fatores de unidade) revelou um
> padrão sistêmico: **cada API de mercado declara a unidade dos preços/hashrates no próprio
> payload** (`priceFactor`/`marketFactor` no NiceHash, `price.type`/`hashrate.advertised.type`
> no MRR, `hr_unit` no Braiins) — e o código assumia unidades fixas. Este documento é a
> **fonte única de verdade** do estado de cada correção, ligando incidentes, issues e PRs.

---

## 1. Matriz consolidada por fetcher

| Fetcher | Unidade declarada pela API | O que o código assumia | Fator de erro | Sev | Issue | PR (fix) | Status |
|---|---|---|---|---|---|---|---|
| **NiceHash** | `priceFactor`/`marketFactor` = `1e18` (EH) | BTC/TH/day + H/s | **1e6×** (68M vs 68 sats/TH/d) | **Sev-1** | #303 | #304 (`785acef`) | ✅ **RESOLVIDO** |
| **NiceHash (junk)** | `acceptedSpeed=0` (ordem fantasma) e `limit=0` (ordem lixo) | vence o "cheapest" | ROI +5.4M% | **Sev-1** | #305 | #306 (`076e453`) | ✅ **RESOLVIDO** |
| **MRR** | `price.type="ph"` · `hashrate.advertised.type="ph"` | BTC/hora + TH/s | **24.000×** (11.4M vs 66 sats/TH/d) | **Sev-1** | #311 | #312 (`88715b7`) | ✅ **RESOLVIDO** |
| **Braiins (bid, com chave)** | `hr_unit` (`EH/day`, `100PH/day`, `10PH/day`, `TH/day`) | `price_unit` (campo inexistente) | 10×–1000× no `price_sat` | **Sev-1** | #267 | #269 (`6a1f68a`) + #270 | ✅ **RESOLVIDO** (fail-closed + prova real EH/day) |
| **Braiins (orderbook, SEM chave)** | orderbook público cotiza em `sats/EH/day` | fallback `sats/PH/day` (fator 1.0) quando `/spot/settings` → 401 | **1000×** (49.050 vs ~49 sats/TH/d no prod) | **Sev-2** | — | — | ⚠️ **PENDENTE (Bug B)** |
| **Parasite** | — (retired, sempre `None`) | — | — | — | — | — | ✅ sem risco |

---

## 2. Detalhe por correção

### 2.1 NiceHash — priceFactor 1e18 (Sev-1, ✅ resolvido)
- **Sintoma no painel:** 68.000.000 sats/TH/d · ROI −99.1% (EV −0.099 BTC vs cost 0.1 BTC).
- **Causa raiz:** API v2 declara `priceFactor`/`marketFactor` = `1e18` (EH); o código tratava
  `price` como BTC/TH/day e `acceptedSpeed` como H/s.
- **Fix (#304, `a3c92fa` → merge `785acef`):** `btc_per_th_day = price / priceFactor × 1e12`;
  `speed_ph = acceptedSpeed × marketFactor / 1e15`; `limit_hs = limit × marketFactor`;
  filtro de ordem fantasma (`acceptedSpeed=0`).
- **Fix complementar (#306, `0b5b0f9` → merge `076e453`):** rejeição de outlier — ordens
  abaixo de **20% da mediana** do book ativo são descartadas (ordem junk `limit=0` com
  `price=0.0001` vs book real 0.5876–0.6823 mostrava ROI +5.4M%).
- **Prova real (prod, 18-Ago):** probe `/api/snapshot` → **52.76 sats/TH/d**; Playwright →
  52.8 sats/TH/d · ROI plausível (−21.6% a −2.9%) · est. cost 0.00001511 BTC.
- **Registro:** [`docs/incidents/2026-08-18-nicehash-pricefactor-unit.md`](./2026-08-18-nicehash-pricefactor-unit.md) (issue #309 · PR #310).
- **Testes:** `tests/test_hashrate_market_parsers.py` L237-330 (payload real com
  `priceFactor`/`marketFactor`).

### 2.2 MRR — price.type / hashrate.advertised.type (Sev-1, ✅ resolvido)
- **Sintoma potencial:** com chave válida, MRR apareceria com preço 11.478.261 sats/TH/d
  (ROI ~−100%) — mesmo padrão do NiceHash. Não aparecia porque o provider estava sem chave.
- **Causa raiz:** payload real declara `price.type="ph"` (price = BTC/PH/**dia**) e
  `hashrate.advertised.type="ph"` (hash = **PH/s**); o código tratava price como BTC/**hora**
  e hash como TH/s → `(0.00066×24)/0.138 = 0.1148`.
- **Prova aritmética da semântica real:** `price/24 × hash_ph == hour` (exato) no payload
  real capturado (`/rig?type=sha256` público, 18-Ago): `0.00066/24 × 0.138 = 0.000003795` ✓.
- **Fix (#312, commit `6761956` → merge `88715b7`):** helper `_mrr_hashrate_th(rig)` honra
  `type="ph"` (×1000 → TH/s) e `price.type="ph"` → `price/1000`; registros **legacy sem type**
  mantêm o contrato antigo (BTC/hora + TH) por retrocompatibilidade; mesmo tratamento no
  `best_rig_hash_th` do retorno.
- **Prova real:** repro com payload real capturado → **66.00 sats/TH/d · best_rig_hash_th
  138.0** (0.138 PH × 1000) · 100 listings.
- **Testes:** `tests/test_hashrate_market_parsers.py` — `test_success_with_ph_units_real_payload`
  (6.6e-7 BTC/TH/d = 66 sats, hash 138) + `test_ph_units_without_type_field_legacy`.

### 2.3 Braiins — bid com chave (Sev-1, ✅ resolvido) — ver relatório completo
- **Causa raiz (#267):** código lia `price_unit` (0 ocorrências no OpenAPI oficial); o campo
  real é `hr_unit` (`EH/day`, `100PH/day`, `10PH/day`, `TH/day`) — conversão de preço morta.
- **Fix (#269 + #270):** `helpers.braiins_hr_unit_factor()` (fonte única) + leitura de
  `hr_unit` + **fail-closed** (400, nenhum POST) em unidade desconhecida; bandas dinâmicas
  do `/spot/settings` (F3), identity obrigatória (F4), audit imutável (F5), rate-limit (F6).
- **Prova real:** `hr_unit` real da conta = **EH/day** colhido via chip unit no modal de
  produção (PR #286); risco residual #267 fechado (PR #288).
- **Registro:** [`docs/incidents/2026-08-17-braiins-buy-hash-verification.md`](./2026-08-17-braiins-buy-hash-verification.md) (Go/No-Go completo).

### 2.4 Braiins — orderbook sem chave (Sev-2, ⚠️ PENDENTE — Bug B)
- **Sintoma no prod (18-Ago):** Braiins 2044 SATS/TH·h (= **49.050 sats/TH/d**) vs ~49 reais.
- **Causa raiz:** sem chave válida, `/spot/settings` responde **401** (`{"message":"No API key
  found in request"}` — probe real) → o código cai no default `price_unit = "sats/PH/day"`
  (fator 1.0) — mas o **orderbook público cotiza em `sats/EH/day`** → 1000×.
- **Local:** `agents/solo_mining_advisor/tools.py` L181-188 (`get_braiins_orderbook`).
- **Status:** ⚠️ **sem issue aberta** — correção pendente (o usuário optou por corrigir
  NiceHash → MRR primeiro; este ficou de fora).
- **Fix sugerido:** quando `/spot/settings` não responde OK, assumir `sats/EH/day` (fator
  `braiins_hr_unit_factor("EH/day") = 1000`) em vez de `sats/PH/day`, e registrar warning.

---

## 3. Linha do tempo da varredura (18-Ago-2026)

| Horário (UTC) | Evento |
|---|---|
| 04:41 | Fix NiceHash priceFactor (#304, merge `785acef`) |
| 10:47 | Fix NiceHash outlier/junk (#306, merge `076e453`) |
| 11:42 | Fix network hashrate 24× (#308, merge `9a1adfe`) — achado durante a verificação do deploy |
| 12:09 | Incidente NiceHash registrado (#310, merge `e203092`) |
| 12:49 | Fix MRR price.type/hashrate.type (#312, merge `88715b7`) |
| 14:14 | **Este documento** — trilha consolidada |

---

## 4. Lições (regras permanentes para fetchers de preço)

1. **Nunca assumir unidade de preço/hashrate** — ler os fatores declarados pela API no
   próprio payload (`priceFactor`/`marketFactor`, `price.type`, `hashrate.advertised.type`,
   `hr_unit`) antes de qualquer conversão.
2. **Toda conversão exige teste com payload real** (não mock sintético sem os campos de
   unidade — foi exatamente isso que cimentou os bugs do NiceHash e do MRR).
3. **Filtros defensivos de book são obrigatórios** em agregadores de ordem: ordem fantasma
   (`acceptedSpeed=0`) e outlier (< 20% da mediana) são lixo de API que envenena o cheapest.
4. **Caminho sem credenciais também precisa de unidade correta** — o fallback sem chave do
   Braiins (Bug B) mostrou que o default pode estar 1000× errado mesmo em modo read-only.

---

## 5. Pendências

| Item | Sev | Ação necessária |
|---|---|---|
| **Braiins Bug B** — fallback sem chave assume `sats/PH/day` (orderbook cotiza em `sats/EH/day`) | Sev-2 | Abrir issue + fix no `get_braiins_orderbook` (L181-188): default `sats/EH/day` quando `/spot/settings` falha |

---

## 6. Artefatos

| Artefato | Local |
|---|---|
| Incidente NiceHash (1e6×) | [`docs/incidents/2026-08-18-nicehash-pricefactor-unit.md`](./2026-08-18-nicehash-pricefactor-unit.md) |
| Verificação enterprise Buy Hash Braiins (Go/No-Go) | [`docs/incidents/2026-08-17-braiins-buy-hash-verification.md`](./2026-08-17-braiins-buy-hash-verification.md) |
| OpenAPI oficial Braiins (fonte do contrato) | [`docs/reference/braiins-hashpower-api-openapi.yml`](../reference/braiins-hashpower-api-openapi.yml) |
| Código (fonte da verdade) | `agents/solo_mining_advisor/tools.py` · `services/hashrate_market.py` · `helpers.py` |
| Testes com payload real | `tests/test_hashrate_market_parsers.py` · `tests/test_agent_tools.py` |
