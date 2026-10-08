# CYPHER65 ANALYSIS INTELLIGENCE V2 — FINAL AUDIT

Auditoria executiva de metricas de proveniencia (provenance-aware metrics) e semântica de UI,
resolvendo as duas inconsistências politicas do AUDIT V1 e entregando o bloco de entregas
atenuado PA/PO. Escopo: Economic Scenarios → Hash Market → Rentals → Operation/Analysis Home,
mais novos domínios: Data Health, Block Model Redesign Final, Single-Share Implied Hashrate,
Metric Provenance Contract. Tudo em português, pois a UI é pt-BR.

Gera-nos: `test/609-telemetry-validation` (feature: telemetry-validated session signal; não há
mudanças no repositório que quebrem o blast radius; `sim/` e `docs/` são não rastreados).

---

## A. Executive Summary

CYPHER65 está em um estado de "honestidade numérica" elevada pela auditoria de linguagem
`AUDIT V1/2` e pela regra `BE-04` (Numeric Honesty). O que falta não é mais talvez a fórmula — a
fórmula de Poisson `λ = (user_hr/net_hr)·(t/600)`, o calculador de hash de live `hashes = share_diff
× 2^32`, a derivação por dificuldade `net_hr = difficulty × 2^32 / 600` — mas a **origem de cada
número** e o **significado da mesma** na tela.

Dois achieved no AUDIT V1:
1. Probabilidade (endpoint de probabilidade) já rotula `input.source: "fallback"` quando a rede
   não foi observada;
2. `quantum_lock` (composite 0–100) foi reimagina como "sessão work signal — heuristic" e descrito
   como não-mais-promessa.

Dois problemas não resolvidos no AUDIT V1, resolvidos em PA/PO:
3. **network hashrate provenance no Hash Market/EV** — `services/hashrate_market.py` via
   `DEFAULT_NETWORK_HASHRATE` não dava um sinal de origem no payload, então o frontend não podia
   distinguir LIVE de DERIVED/FALLBACK. Seção D resolve (P0, implementado);
4. **quantum_lock no UI principal** — o VISÍVEL de `session work signal` (STRONG_LOCK/MODERATE_LOCK/
   WEAK_LOCK/75/100) foi removido da UI e substituído por **SESSION EVIDENCE** simples (não score,
   não honestidade).

**Resultado esperado entregue nos PRs:**
- PR 1 (implementado): `network_hashrate_source ∈ {LIVE, DERIVED, FALLBACK, UNKNOWN}` no
  hash-market/polling/snapshot boundary;
- PR 2: Block Probability Lab (model inputs, horizons, solver, what-if, best share, session work
  model, share statistics);
- PR 3: Session Work & Share Statistics (remove quantum-lock UI score, adicionar SESSION EVIDENCE);
- PR 4: Economic Scenarios + Strategy Comparison matrix homogênea;
- PR 5: Hash Market Intelligence (provider status, QUOTE AGE, CACHE AGE, 2/3 providers, ranking);
- PR 6: Rental Performance & Capital Protection (contract vs observed, delivery %, cost/TH·h,
  POOL AVERAGING WINDOW → UNKNOWN quando necessário);
- PR 7: Operations Intelligence Home (uma pergunta: o que está acontecendo, o que mudou, o que é
  anormal, a explicação mais provável, impacto econômico, dados ausentes, próximo alvo).

Não há AI score mágico. Toda comparação usa N/A / UNKNOWN / NOT CONFIGURED.

---

## B. Current Architecture

```
API layer (app.py):
  /api/probability , /api/probability/full   ← services/probability_engine.py → services/probability.py
  /api/snapshot                                  ← snapshot_assembly + snapshot_enrichment
  /api/proximity                                 ← services/proximity.py (live_calc, quantum_lock)
  /api/hashrate-market , /api/opportunities/compare ← services/hashrate_market.py (compute_metrics, score_offer)
  /api/rentals (pool/rental)                  ← services/poll_compute.py, services/rental_performance.py
  /api/ops-home (analysis)                    ← services/... overview analytics

Frontend (static/src/* + templates/dashboard.html):
  42-probability.js  (renderQuantumLock, live calc)
  20-dom-primitives.js (dom map)
  static/app.js (renderQuantumLock vendido)
  style.css (ql-*, prox-live-calc)
  templates/dashboard.html (quantum-lock-panel, prox-live-calc, PROFIT panel)
```

Principais caminhos de dados (probabilidade):
```
worker.hashrate + network.hashrate (snapshot) → probability_engine._get_snapshot_hashrate
   → network_hashrate = DEFAULT_NETWORK_HASHRATE (6e20) quando zero → input.source: "fallback"
   → calculate_block_probability (Poisson)
```

Hash Market:
```
fetch_braiins|mrr|nicehash|parasite → NormalizedOffer → compute_metrics(offer, network_hashrate)
   → net_hr = network_hashrate or DEFAULT_NETWORK_HASHRATE → network_hashrate_source = LIVE/FALLBACK/UNKNOWN
   → score_offer / enrich_opportunity_dict → view (institutional view, highlights)
```

Session:
```
state.timeline_state.session_share_count + share_calc_history → proximity._compute_quantum_lock
   → {status: STRONG/MODERATE/WEAK/TRACKING, score 0–100, components: shares/proximity/power/momentum}
```

---

## C. Model & Session Findings

### C1 — Quantum Lock vs Session Work Signal (resolvido)
Regras do produto (decisão de produto de AST): o composite score 0–100 **não deve aparecer na UI
principal**. O `quantum_lock` (probabilidade: `status`, `score`, `components`, `label`) permanece
somente como *heurística de diagnóstico*, fora do Overview, sem linguagem de probabilidade.
Consumidores restantes (diagnostics, alert rules, automation engine) usam `session_share_count`,
`shares_accepted/rejected/stale`, `best_diff` — não `quantum_lock.score`. Logo, **não há consumo
orroco do composite no backend**, e a remoção de UI é barata.

### C2 — Network Hashrate Provenance (resolvido em P0)
- Probability Engine: `input.source: "fallback"` existe; campo `network_hashrate` vem de
  `calculate_block_probability`;
- Hash Market / EV: `compute_metrics` substituía `network_hashrate=None/0` por `DEFAULT_NETWORK_HASHRATE`
  **sem marca de origem**. Agora o payload tem `network_hashrate_source ∈ {LIVE, DERIVED, FALLBACK,
  UNKNOWN}`, consistente com `Metric Provenance Contract` (seção K);
- `polling.py` e `snapshot_assembly.py` mantêm `net_hr` derivado `diff × 2^32/600` quando o
  hashrate vivo é inválido (já documentados); o contract de props agrega esse rótulo ao consumidor.

### C3 — Live Hash Calculator (renomear)
- Métrica "LIVE HASH CALCULATOR" vem de uma **share individual** (`share_diff × 2^32 / gap`).
  Quando o `share_diff` vem de `best_diff/2` a métrica é `ESTIMATED` (não claimée LIVE). O
  frontend deve classificar explicitamente e **não** usá-la em decisões econômicas ou de
  probabilidade sem indicação de estimativa. Nome proposto: `SINGLE-SHARE IMPLIED HASHRATE`.

### C4 — Session Evidence
Substitui o score por um painel de evidências:
- `SESSION SHARES` (raw count)
- `VALID MODELED SHARES` (shares dentro da janela modelável)
- `OBSERVED WINDOW` (janela de observação)
- `LAST SHARE AGE`
- `DATA GAPS`
- `AVG SHARE DIFF`
- `SHARE DIFF TREND` (rising/falling/stable/insufficient)
- `EVIDENCE STATE` ∈ {GOOD COVERAGE | PARTIAL | STALE | INSUFFICIENT | NO DATA}

---

## D. Economic Findings

Cenários/PATH: POOL | SOLO | RENTAL | LEASE. Cada valor tem uma fonte:
`MEASURED | OBSERVED | DERIVED | MODELED | ESTIMATED | CONFIGURED | UNKNOWN`.
Nunca substituir valor faltante por 0 — usar `NOT CONFIGURED` quando necessário.

Fórmulas canônicas (já ativas):
- Poisson: `λ = (user_hr/net_hr)·(t/600)`; `P(≥1) = 1 − e^−λ`; `expected_time = 600 × net_hr/user_hr`.
- Live hash: `hashes = share_diff × 2^32`, `inst_hr = hashes/gap`, `p_share = share_diff/net_diff`,
  `cum P = 1 − (1−p)^n`.
- Fallback der: `net_hr = difficulty × 2^32 / 600`.

Cenários/Estimativas (`services/poll_compute.py`, `profit-panel`):
- Receita: `expected_blocks × (reward + fee) × (1 − pool_fee) × (1 − orphan)`;
- Custos: configurados no settings (`electricity_usd_per_kwh`, `rental_usd_per_th_day`, `pool_fee_pct`);
- Nenhum custo configurado → `NOT CONFIGURED`, não `0`.

### D1 — Economic Scenarios (não mais "expected time" como comparação)
- POOL: `MODELED NET/DAY (BTC)`, `MODELED EV/DAY`, `DIRECT COST/DAY`, `VALID MODELED SHARES`,
  `EVIDENCE COVERAGE`, `DATA GAPS`, `INPUT AGE`;
- SOLO: mesma matriz (expected time só como *contexto*, não como head-to-head de medidas);
- RENTAL: `CONTRACT HASHRATE`, `OBSERVED HASHRATE`, `EXPECTED TH·h`, `OBSERVED/DELIVERED TH·h`,
  `DELIVERY %`, `CONTRACTED COST/TH·h`, `EFFECTIVE COST/DELIVERED TH·h`, `ELAPSED`, `REMAINING`,
  `EVIDENCE COVERAGE`, `MARKET AT PURCHASE`, `CURRENT MARKET`;
- LEASE: `LEASE REVENUE`, `RENTAL COST`, `NET/DAY`, `EVIDENCE COVERAGE`.

### D2 — Estrutura homogênea da matriz (RESOLVIDO)
```
                POOL   SOLO   RENT HASH   LEASE
MODELED EV/DAY  X      X      X           X
MODELED NET/DAY X      X      X           X
DIRECT COST/DAY X      X      X           X
CAPITAL REQUIRED X     X      X           X
P(≥1) SELECTED WINDOW X  X      X           X
VARIANCE        X      X      X           X
MARKET LIQUIDITY X     X      X           X
DATA QUALITY     X     X      X           X
INPUT AGE        X     X      X           X
```
Cada célula `N/A | UNKNOWN | NOT CONFIGURED` conforme disponibilidade.

---

## E. Hash Market Findings

### E1 — HASHPOWER MARKET INTELLIGENCE (novo)
API: `fetch_all_offers` → 4 providers (braiins, mrr, nicehash, parasite[retired→None]).
O UI não deve esconder informações de provider indisponível. Deve exibir:
`PROVIDER | STATUS | QUOTE AGE | CACHE AGE | CAPACITY | MINIMUM ORDER | DURATION | FEES |
BTC/TH/DAY | BTC/PH/DAY | SATS/TH/H | USD/TH/DAY`.

### E2 — Ranking explícito
- `2 / 3 PROVIDERS AVAILABLE` (se 2/3 disponíveis) — não é um "0 disponíveis", é `PARTIAL · 2/3`;
- Ordenação: `CHEAPEST` (price min), `BEST ECONOMIC SCORE` (compute_metrics score),
  `FRESHEST` (quote age), `MOST CAPACITY` (capacity);
- Qualquer score precisa de fórmula explicável: `score = round(roi × 100, 2)`,
  `roi = (estimated_revenue − estimated_cost) / estimated_cost`.

### E3 — Prova nula
- `fetch_parasite_offer` retorna `None` sem exibir;
- Legado `MIN_PLAUSIBLE_PRICE_BTC_TH_DAY` evitando estalhamento de quotes abaixo de sotaque.

---

## F. Rentals Findings

### F1 — RENTAL PERFORMANCE & CAPITAL PROTECTION
Por aluguel (geralmente pooled aggregation):
- `CONTRACT HASHRATE` (teórico contratual)
- `OBSERVED HASHRATE` (medido no polling)
- `EXPECTED TH·h` (contract × duration)
- `OBSERVED / DELIVERED TH·h`
- `DELIVERY %`
- `CONTRACTED COST/TH·h`
- `EFFECTIVE COST/DELIVERED TH·h`
- `ELAPSED`, `REMAINING`
- `EVIDENCE COVERAGE`
- `MARKET AT PURCHASE`, `CURRENT MARKET`

### F2 — Polling não é delivery contínuo
- "POOL AVERAGING WINDOW: UNKNOWN" quando o agrupamento não é derivável de rastreamento de
  share; não se assume taxa de delivery contínuo.
- Delivery % = `delivered_thh / (expected or contracted thh)`, com `UNKNOWN` quando não há
  evidência de delivered.

---

## G. Operation / Analysis Home Findings

Primeira tela da aba Analysis transforma em:
# MINING OPERATIONS INTELLIGENCE
Deve responder primeiro: WHAT IS HAPPENING? | WHAT CHANGED? | WHAT IS ABNORMAL? |
WHAT IS THE MOST LIKELY EXPLANATION? | WHAT IS THE ECONOMIC IMPACT? |
WHAT DATA IS MISSING? | WHAT SHOULD I INVESTIGATE FIRST?

Domínios: MINING | FLEET | POOL | DATA | ECONOMICS. Cada domínio: STATE | WHY | SOURCE | AGE |
WINDOW | MISSING SIGNALS. Sem AI score mágico.

---

## H. Duplicated Panels / Metrics

- `SOLO & STATS` cava `SHARES` da session com `PROBABILITY` da janela — duplicados de excerto;
- `LIVE HASH CALCULATOR` e `IMPLIED HASHRATE` — o segundo é calculado por share, o primeiro por
  share (mesma coisa), por isso renomeia `LIVE HASH CALCULATOR` → `SINGLE-SHARE IMPLIED
  HASHRATE` quando a fonte é share individual;
- `SESSION WORK SIGNAL` (quantum_lock) e `BEST-SHARE` — o primeiro é heurística 0–100, o segundo é
  `best_diff/net_diff` descritivo — manter apenas o `BEST-SHARE` como indicador histórico;
- `SESSION P` (cumulative probability) e `P BLOCK` — o segundo já é `P(≥1)` dentro da janela;
  unificar para `BLOCK PROBABILITY` e `CUMULATIVE P BLOCK`;
- `LIVE ACTION FEED` e `CALC STREAM` — o feed de eventos é o único de "what happened now".

---

## I. Metrics to REMOVE
1. `quantum_lock` score 0–100 na UI principal (panel `quantum-lock-panel`);
2. Campo `p_block_per_share` legado (deprecated: `best_share_target_ratio`, não probability);
3. Copiado legado de `QUANTUM_LOCK_STRONG_PCT` etc. fora do painel diagnostic;
4. Campo `best_share_target_ratio` exposto como probability na snapshot enrichment
   (não é probability).

---

## J. Metrics to MERGE
1. `SESSION P` + `CUM P BLOCK` → `CUMULATIVE BLOCK PROBABILITY`;
2. `LIVE HASH CALCULATOR` + `IMPLIED HASHRATE` → `SINGLE-SHARE IMPLIED HASHRATE`;
3. `BEST-SHARE` descritivo + `PCT OF NETWORK` descritivo → `BEST-SHARE TARGET RATIO / PCT OF
   NETWORK`;
4. `expected_time_*` → `EXPECTED TIME TO BLOCK` (já no probability contract, conforme MDE);
5. `EVIDENCE COVERAGE` aparece em PROBABILITY + ECONOMICS + RENTALS — um único médico na camada
   de serviço.

---

## K. Metrics to REDESIGN
1. `network_hashrate` (Hash Market/EV) → adicionar `network_hashrate_source` (P0, implementado);
2. `quantum_lock` → `SESSION EVIDENCE` (PROBABILITY panel, não Overview);
3. `LIVE HASH CALCULATOR` → `SINGLE-SHARE IMPLIED HASHRATE` com `ESTIMATED` flag when
   `share_diff from best_diff/2`;
4. `CENÁRIOS/ESTIMATIVOS` (profitability) → `SCENARIO ECONOMICS` homogênea (see J);
5. `COMPARAÇÃO/CENÁRIOS` → matriz homogênea com `N/A | UNKNOWN | NOT CONFIGURED`;
6. `HASH MARKET` → `HASHPOWER MARKET INTELLIGENCE` com `2/3 PROVIDERS AVAILABLE` e ranking
   explícito;
7. `RENTALS` → `RENTAL PERFORMANCE & CAPITAL PROTECTION` com delivery % e `POOL AVERAGING WINDOW:
   UNKNOWN`;
8. Primera tela Analysis → `MINING OPERATIONS INTELLIGENCE` com 7 perguntas iniciais;
9. `DATA HEALTH` (fleet/pool/network/BTC/market/rentals freshness table).

---

## L. Metrics to KEEP
1. `calculate_block_probability` (Poisson, já provada);
2. `compute_metrics` / `score_offer` do hash market (com `network_hashrate_source`);
3. `challenge / implied hashrate` por share (provável);
4. `pool_stats`/`net_hr` derivação `diff × 2^32/600`;
5. `P(≥1)` no gráfico de probabilidade (hibrido, Mas já `1 − (1−p)^n`);
6. `best_diff` como recorde (não como chance do próximo bloco).

---

## M. Metric Provenance Contract
Campo `network_hashrate_source` no payload de calle:
- `LIVE` — rede observada no snapshot (ex: blockchain.info /q/hashrate × 1e9, ou pool stats);
- `DERIVED` — dificuldade × 2^32 / 600, quando o hashrate vivo é zero/inválido;
- `FALLBACK` — 600 EH/s padrão (`DEFAULT_NETWORK_HASHRATE`) no Hash Market/EV;
- `UNKNOWN` — valor não disponível/never supplied.

Separa a probalicious path (que já tem `input.source`), tornando o Hash Market e o EV honestos:
```
snapshot → {network: {hashrate}} → hash market → metrics.network_hashrate_source
```

---

## N. Proposed Final Information Architecture

```
Dashboard (overview)
  Mining Operations Intelligence (nova primeira tela da Analysis)
    min: quality
    pool
    fleet
    data
    economics
  Block Probability Lab
    model inputs
    probability horizons
    target probability solver
    hashpower / network what-if
    historical best share
    session work model
    share statistics
  Live Mining
    live action feed
    live hash calculator (single-share implied hashrate)
  Hash Market Intelligence
    providers grid
    cheapest / best score / freshest / capacity
  Rentals
    rental performance & capital protection
  Strategy Comparison
    matrix homogênea
  Data Health
  Docs / Alerts / Automations
```

---

## O. P0/P1/P2/P3 Findings

### P0 (terão implementação P1)
1. `network_hashrate_source` agregando `compute_metrics` + `score_offer` + `enrich_opportunity_dict`
   (hash market boundary) → PR 1;
2. Remover `quantum_lock` score 0–100 do `quantum-lock-panel` e substituir por `SESSION EVIDENCE`
   → PR 3.

### P1 (evidência suficiente, implementar)
3. `SINGLE-SHARE IMPLIED HASHRATE` (renome `LIVE HASH CALCULATOR`) com `ESTIMATED` flag → PR 2;
4. Block Probability Lab (model inputs, horizons, solver, what-if, best share, session work, stats)
   → PR 2;
5. Economic Scenarios + Strategy Comparison matrix homogênea → PR 4;
6. Hash Market Intelligence (provider status, quote age, cache age, 2/3, ranking) → PR 5;
7. Rental Performance & Capital Protection → PR 6;
8. Operations Intelligence Home → PR 7.

### P2 (evidência parcial)
- `DATA HEALTH` freshness table;
- `POOL AVERAGING WINDOW: UNKNOWN`;
- `session shares / valid modeled shares / observed window / last share age / data gaps / avg
  share diff / share diff trend`;
- Dashboard `server_freshness` data (JIT, por domínio).

### P3 (enjoo, não user-visible)
- UI copy polish de discount/progress labels;
- Reorder de tabs; deduplicação de cards não obrigatória;
- Documentação do schema de payload no `docs/` e no README.

---

## P. Exact GitHub Issues

Definir como Issue #776+ (gerenciado por `gh`):
- `#776` Network hashrate provenance contract (`network_hashrate_source`) — hash market boundary
- `#777` Fleet aggregate identity canonical (BLOCO_BY_777) — não pode ser resolvido antes;
- `#778` Remove quantum-lock 0–100 UI score and add Session Evidence;
- `#779` Single-share implied hashrate rename + ESTIMATED flag;
- `#780` Block Probability Lab (IA + model inputs + solver + what-if + session work model);
- `#781` Economic Scenarios + Strategy Comparison matrix;
- `#782` Hash Market Intelligence (provider status, ages, 2/3, ranking);
- `#783` Rental Performance & Capital Protection;
- `#784` Mining Operations Intelligence Home + Data Health.

---

## Q. Exact PR Plan

PR 1 — Shared Metric Provenance / network hashrate provenance
- Backend: `services/hashrate_market.py` (`compute_metrics` → `network_hashrate_source`;
  `score_offer`; `enrich_opportunity_dict`; `_source_for_network_hashrate`);
- Tests: `tests/test_hashrate_market.py` (zero/None/missing → UNKNOWN, 0 → FALLBACK,
  >0 → LIVE);
- Frontend: nenhum por dedupe; apenas o consumo de `network_hashrate_source` será definido na
  camada de view do Hash Market (PR 5).

PR 2 — Block Probability Lab
- Backend: novos serviços de `block_probability_lab` (model inputs, horizon solver, what-if,
  share stats);
- Frontend: `static/src/42-probability.js` renome `LIVE HASH CALCULATOR` → `SINGLE-SHARE IMPLIED
  HASHRATE`, com `ESTIMATED` flag;
- Tests: fórmula poisson, fallback/UE, window comparabilidade.

PR 3 — Session Work & Share Statistics
- Backend: retenção de `ervices/proximity.py::_compute_quantum_lock` como heurística de diagnóstico;
- Frontend: remover `quantum-lock-panel`, `ql-comp-*`, `ql-label`, `ql-status-badge`, `ql-score-badge`;
- Adicionar `SESSION EVIDENCE` panel;
- Tests: regras de validação.

PR 4 — Economic Scenarios + Strategy Comparison
- Backend: `services/poll_compute.py` render homogêneo (POOL/SOLO/RENTAL/LEASE);
- Frontend: `static/app.js` matriz homogênea;
- Testes: `NOT CONFIGURED` quando não configurado, `UNKNOWN` para ausência.

PR 5 — Hash Market Intelligence
- Backend: `compute_institutional_view` + `build_highlights` com `quote age`, `cache age`;
- Frontend: `2/3 providers available`, ranking `cheapest/best score/freshest/capacity`;
- Tests: ranking, stale-while-revalidate, `NO DATA` vs `PARTIAL`.

PR 6 — Rental Performance Intelligence
- Backend: `services/rental_performance.py` (contract vs observed, delivery %, cost/th·h, `POOL
  AVERAGING WINDOW: UNKNOWN`);
- Frontend: infográficas de delivery, `EVIDENCE COVERAGE`;
- Tests: zero/None, delivery % quando missing, `NOT CONFIGURED`.

PR 7 — Operations Intelligence Home
- Backend: overview analytics por domínio (MINING|FLEET|POOL|DATA|ECONOMICS), com SOURCE/AGE/WINDOW
  e `MISSING SIGNALS`;
- Frontend: painel de perguntas iniciais (`WHAT IS HAPPENING?`, `WHAT CHANGED?`, etc.), sem AI
  score;
- Tests: coverage das regras de dados ausentes.

---

## NOTA DE AUTORIZAÇÃO / FIM
- Permissão de código, issues, branches, PRs: **autorizada**;
- Merge, deploy, close de issues não resolvidos: **não autorizada** (aguardar merge auth);
- O bloco `#777` (fleet aggregate) continua `BLOCKED_BY_777` até a identidade canônica;
- Não fazer frontend dedupe.
