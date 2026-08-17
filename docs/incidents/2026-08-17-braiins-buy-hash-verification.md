# 🔍 Verificação Enterprise — Braiins "Buy Hash" (Place Bid)

**Staff-Level Review · Research → Implementation → Validation · 17-Ago-2026**
**Status: ✅ GO — todos os achados Sev-1/Sev-2 corrigidos (PRs #269 e #270 mergeados)**

> **Evidência primária:** OpenAPI oficial do Braiins (3083 linhas, baixado de
> `hashpower.braiins.com/api` em 17-Ago-2026) persistido em
> [`docs/reference/braiins-hashpower-api-openapi.yml`](../reference/braiins-hashpower-api-openapi.yml)
> + código (`services/rental_performance.py`, `app.py`,
> `agents/solo_mining_advisor/tools.py`, frontend).

---

## 1. Executive Verdict — **GO (condições atendidas)**

> **Veredito inicial (17-Ago, antes dos fixes):** CONDITIONAL GO — bloqueado
> por um P0 de contrato: o código lia `price_unit` de `/spot/settings`, campo
> **inexistente** no OpenAPI oficial (0 ocorrências) — o campo real é
> `hr_unit` (`EH/day`, `100PH/day`, `10PH/day`, `TH/day`). A conversão de
> unidade era código morto e o `price_sat` enviado podia estar **10×–1000×
> errado** dependendo da unidade da conta.
>
> **Estado atual (pós-fix #269 + #270):** ✅ **GO**. O P0 foi corrigido
> (leitura de `hr_unit` + conversão + fail-closed em unidade desconhecida) e
> os 4 achados Sev-2 da auditoria foram implementados: validação contra o
> `/spot/settings` **ao vivo**, `identity` obrigatória no `dest_upstream`,
> **audit imutável** de toda tentativa e **rate-limit** dedicado por tenant.
> O caminho do dinheiro agora tem 4 camadas de proteção independentes
> (clamps estáticos → unidade fail-closed → bounds dinâmicos do mercado →
> rate-limit) + trilho de auditoria append-only.

---

## 2. Findings Table (ordenado por severidade)

| Sev | Fase | Achado | Evidência | Impacto | Fix |
|---|---|---|---|---|---|
| **Sev-1** | P0 | **`price_unit` inexistente → unidade errada**: código lia `price_unit` (0 ocorrências no OpenAPI); o oficial é `hr_unit` (`EH/day`, `100PH/day`, `10PH/day`, `TH/day`) | OpenAPI L16-18, L1462-1473 vs código pré-fix | Bid com `price_sat` 10×–1000× errado; sanity band não cobre todos os casos | ✅ **#269** (`6a1f68a`): `helpers.braiins_hr_unit_factor()` (fonte única) + leitura de `hr_unit` + **fail-closed** (400, nenhum POST) em unidade desconhecida |
| **Sev-2** | P1 | **Sem `/spot/settings` antes do bid**: contrato exige "read this resource before placing a bid"; clamps eram hard-coded, sem tick/min/max dinâmicos | OpenAPI L41-45, L1426-1496 vs código pré-fix | Ordem podia ser rejeitada com erro não antecipado; clamps divergentes do mercado | ✅ **#270** (`46a9ac9`) F3: `braiins_market_limits()` pre-valida tick/price/amount/speed contra os **mesmos números** do servidor |
| **Sev-2** | P2 | **`identity` (worker) opcional, mas contrato exige**: `UpstreamSpecification.required: [url, identity]` | OpenAPI L2463-2476 vs código pré-fix | Bid podia ser rejeitado upstream (worker ausente) | ✅ **#270** F4: `upstream_identity` **obrigatória** (400 antes do wire) + campo `required` no modal + hint |
| **Sev-2** | P4 | **Sem audit imutável de cada tentativa**: só telemetria de sucesso; tentativas rejeitadas/falhas não registradas | Código pré-fix (só `track_event("braiins_bid")` no sucesso) | Sem trilha financeira completa p/ auditoria | ✅ **#270** F5: `_audit_braiins_bid()` grava `placed/rejected/rate_limited` no `audit_logs` (append-only, **sem PII**) + rota de leitura tenant-scoped |
| **Sev-2** | P3 | **Sem rate-limit dedicado**: budget global 300/min/tenant é largo demais para endpoint de dinheiro | `config.py` RATE_LIMIT_PER_MINUTE vs natureza do endpoint | Abuso/stuck client podia gerar múltiplas ordens em rajada | ✅ **#270** F6: `BRAIINS_BID_PER_MINUTE=6`/tenant → **429 antes de qualquer chamada ao provider** |

**Nenhum achado Sev-3/Sev-4 aberto.** Itens positivos já presentes desde o início (mantidos):
sanity clamps `1e4..1e9` (rede de segurança), confirmação dupla no frontend
(checkbox + digitar COMPRAR), idempotência por `cl_order_id`, envelope
tolerance `{bid_id|id|order_id}` e conversão TH→PH na rota.

---

## 3. API Contract Compliance Matrix (Expected vs Actual)

Contrato de referência: `SpotPlaceBidRequest` (OpenAPI L2477-2501) + `UpstreamSpecification` (L2463-2476) + `MarketSettings` (L1426-1496).

| Campo (contrato oficial) | Contrato | Antes do fix | Depois do fix |
|---|---|---|---|
| `dest_upstream.url` | requerido | ✅ `stratum+tcp/ssl` validado | ✅ igual |
| `dest_upstream.identity` | **requerido** (L2465-2467) | ⚠️ opcional (`if identity`) | ✅ **obrigatório** (400) + sempre no body |
| `amount_sat` | requerido | ✅ presente | ✅ + banda dinâmica `min/max_limited_bid_amount_sat` |
| `price_sat` | requerido, na unidade do `hr_unit` | ❌ **sempre em sats/PH/day** (conversão morta) | ✅ convertido pelo fator oficial + banda `min/max_bid_price_sat` + múltiplo de `tick_size_sat` |
| `speed_limit_ph` | opcional, em PH/s | ✅ presente (TH/1000 na rota) | ✅ + banda `min/max_bid_speed_limit_ph` |
| `cl_order_id` | opcional (idempotência) | ✅ presente | ✅ igual |
| `memo` | opcional | ✅ presente | ✅ igual |
| `/spot/settings` antes do bid | **exigido** ("the server validates orders against these values" L44) | ❌ não consultado | ✅ `braiins_market_limits()` por bid (1 chamada = unidade + bounds) |
| Unidade de preço | `hr_unit` (L16-18, L1463-1469) | ❌ `price_unit` (inexistente) | ✅ `hr_unit` (fallback `price_unit` legado) |
| Resposta do bid | `{id, cl_order_id}` (L2502-2506) | ✅ envelope tolerance `{bid_id|id|order_id}` | ✅ igual |

---

## 4. Security & Abuse Assessment

| Vetor | Status | Evidência |
|---|---|---|
| Token Braiins exposto ao frontend | ✅ Seguro | `apikey` só em header server-side (`_braiins_key(tenant_id)`); nunca no payload de API |
| Injeção via pool URL / worker identity | ✅ Mitigado | URL restrita a prefixos `stratum://`; identity/memo truncados (`[:120]`/`[:200]`); valores sempre como strings no JSON |
| Isolamento multi-tenant | ✅ Seguro | `_braiins_key(tenant_id)` resolve chave por tenant; rate-limit por `t:<tenant>` |
| Erros sensíveis vazando ao cliente | ✅ Mitigado | `needs_auth` distingue 401/403; mensagens truncadas (`[:160]`); HTTP 400/429/502 mapeados sem vazar corpo da Braiins |
| Abuso/rajada de ordens | ✅ Mitigado | 429 antes de qualquer chamada ao provider + GC bounded |
| Confirmação antes de dinheiro real | ✅ Presente | checkbox + digitar `COMPRAR` (frontend) + gate no backend |
| Auditoria de cada tentativa | ✅ Presente | audit_logs append-only, sem PII (URL/worker nunca gravados) |
| Risco residual (unidade real da conta) | ⚠️ Baixo | Mitigado por fail-closed: se `hr_unit` da conta não for reconhecido, **nenhum POST** é feito (400 acionável). Prova real pendente: `curl -H "apikey: <key>" https://hashpower.braiins.com/v1/spot/settings \| jq '.hr_unit'` |

---

## 5. Test Evidence

| Camada | Cenário | Resultado |
|---|---|---|
| Unit (backend) | Conversão `hr_unit` EH/day/100PH/day/10PH/day/TH/day + unknown **fail-closed** (#269) | ✅ `test_rental_performance.py` |
| Unit (backend) | `upstream_identity` obrigatória — nenhum POST sem identity | ✅ novo teste |
| Unit (backend) | Bounds dinâmicos: tick não-múltiplo, price abaixo/above, amount acima, speed acima → **rejeitados localmente** | ✅ novo teste |
| Unit (backend) | Bounds dinâmicos in-band → POST com identity anexada | ✅ novo teste |
| Unit (backend) | `/spot/settings` indisponível (`{}`) → clamps estáticos seguem como rede final | ✅ novo teste |
| Route | Budget 6/min: 7º POST → **429**, serviço nunca chamado | ✅ novo teste |
| Route | Leitura do trilho `/api/rentals/braiins/bid/audit` → 200 + shape | ✅ novo teste |
| E2E | Modal: identity preenchida → submit habilita | ✅ `rentals.spec.js` |
| Regressão | `tests/` completo · JS core · pipeline frontend (axe 100) | ✅ **2604 passed, 1 skipped** · **1359** · green |

---

## 6. Required Fixes — Prioritized Backlog

| Fix | Critério de aceite | Status |
|---|---|---|
| **F1 (P0)** — unidade oficial `hr_unit` + conversão + fail-closed | `price_sat` no wire convertido pelo fator do `hr_unit`; unidade desconhecida → 400 sem POST; conversões EH/100PH/10PH/TH provadas por teste | ✅ #269 (`6a1f68a`) |
| **F2 (P0)** — aplicar o mesmo fix no `get_braiins_orderbook` (quote) | Orderbook normaliza via mesmo helper; warn+assume PH/day em read-only | ✅ #269 |
| **F3** — validação contra `/spot/settings` dinâmico | tick/price/amount/speed validados contra os mesmos valores do servidor; fallback estático documentado | ✅ #270 |
| **F4** — `identity` obrigatória | 400 antes do wire; frontend exige campo; e2e cobre | ✅ #270 |
| **F5** — audit imutável de toda tentativa | placed/rejected/rate_limited registrados; sem PII; rota de leitura tenant-scoped | ✅ #270 |
| **F6** — rate-limit no endpoint | 429 por tenant antes de chamada ao provider; GC bounded; testes | ✅ #270 |

**Follow-ups recomendados (não bloqueantes):**
- **F7 (P2)**: validar `max_bids_per_subaccount` do `MarketSettings` antes do POST (mais 1 bound dinâmico).
- **F8 (P2)**: reconciliação pós-criação — consultar `GET /spot/bid/current` e correlacionar com o `cl_order_id` auditado.
- **Prova real (operação)**: rodar o curl de `/spot/settings` com a chave do operador e documentar o `hr_unit` real.

---

## 7. Go / No-Go Decision Record

| Critério | Estado |
|---|---|
| Causa raiz isolada com evidência (não só hipótese) | ✅ OpenAPI oficial + código + testes |
| Owner claro para cada ação | ✅ Backend/Integrações (`rental_performance.py`, `app.py`) |
| Mecanismo para detectar cedo no futuro | ✅ testes permanentes (conversões, fail-closed, bounds, 429, audit) + gate de CI |
| Zero "achismos" | ✅ todo achado com referência (OpenAPI L#, arquivo:linha) |
| **Decisão final** | ✅ **GO — feature segura para uso com a conta real** |

**Responsável:** revisão senior (Research → Implementation → Validation). Condição
única remanescente (não bloqueante): prova real do `hr_unit` da conta do
operador — o sistema **falha fechado** se ela divergir do esperado.

---

## Histórico de artefatos

| Artefato | Onde |
|---|---|
| OpenAPI oficial (3083 linhas, 17-Ago-2026) | `docs/reference/braiins-hashpower-api-openapi.yml` |
| Fix Sev-1 unidade (PR #269, `6a1f68a`) | `helpers.py`, `services/rental_performance.py`, `agents/solo_mining_advisor/tools.py`, testes |
| Fix Sev-2 F3-F6 (PR #270, `46a9ac9`) | `services/rental_performance.py`, `app.py`, `static/app.js`, `templates/dashboard.html`, testes, e2e |
