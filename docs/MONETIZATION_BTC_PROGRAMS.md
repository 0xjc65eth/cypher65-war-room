# 💎 CYPHER65 WAR ROOM — ENTERPRISE PLAN + BTC MONETIZATION PROGRAMS

**Owner:** Staff Engineering Team (Pesquisa · Implementação · Validação)
**Status:** Plano executável · **Baseline:** Aug 2026 · **Paywall validado** (PRO_KEYS_DB=1, 11/11 checks) em 17-Aug-2026 — aguarda ativação em produção (#256)
**Pagamento (regra inegociável):** exclusivamente em Bitcoin para
`35gjAoadgQxrNc1Kx6QiSLx7wCCXRnRFkM` (P2SH — **validado** com
`helpers.validate_btc_address()` → `{'valid': True}`)

> North star: transformar o War Room de *monitoring dashboard* em *autonomous
> mining operation system* — a única mudança que aumenta pricing power — e
> monetizar via Bitcoin nativo (WebLN/Lightning + on-chain), alinhado ao ethos
> self-custody do público-alvo (Bitaxe/Parasite miners).

---

## 1. Resumo Executivo

**Diagnóstico:** a base técnica já é enterprise-grade (design system v2 com
5 cores/2px, gate axe-core real no CI com score 100/100, guards de tokens/a11y/
DOM/XSS, icon sweep Lucide, funil de conversão `paywall_view → modal_open →
checkout_start → paid → key_activated` com LTV/CAC, licensing PRO/PREMIUM
off-by-default). Os 3 buracos restantes são: **(a)** monetização ativa ainda
inexistente — o gate está em *open mode* e o único provider é Lemon Squeezy
(cartão/PayPal, 5%+$0.50), que **não** aceita BTC; **(b)** backlog de
dados/observabilidade **fechado** (#204/#206 entregues — restam #205/#239/#185,
P1/P2, na tabela §2); **(c)** a infra BTC **já existe e está subutilizada** —
`donations` (WebLN + on-chain via mempool.space + hashpower) provada por
`test_donation_dedup.py`.

**Estado atualizado (17-Aug-2026):** o paywall foi **validado end-to-end
localmente** — `PRO_KEYS_DB=1` → 402 em rota PRO + `paywall_view` countado +
`funnel_report` não-vazio (**11/11 checks**, §10). Falta apenas o flip da env
var em produção (Issue **#256**) para o funil coletar dados reais.

**Oportunidade de receita:** três programas premium pagos **só em BTC**
(PRO/PREMIUM/ENTERPRISE) reutilizando 100% da infra pronta (licensing,
conversion, upgrade modal) e adicionando **um adaptador de pagamento BTC**
(~2 semanas de dev) + **paywall BTC nativa no modal existente**. Público-alvo
(Parasite.space: 2.675+ usuários, 12.514+ workers) já é Bitcoin-native — a
barreira de pagamento cai de "cartão + KYC" para "QR + 1 confirmação".

**Números-guia (unit economics existentes, BUSINESS_PLAN.md):** margem 98%,
LTV:CAC 21.6:1, PRO $9/mo, PREMIUM $29/mo. Em BTC: PRO ≈ 0.00012 BTC/mês,
PREMIUM ≈ 0.00040 BTC/mês (a preço de referência $75k/BTC — conversão
dinâmica via `merge_btc_quotes`, já no código).

---

## 2. Achados por Severidade

| Sev | Problema | Evidência | Impacto | Owner | Fase |
|---|---|---|---|---|---|
| Sev-2 | Paywall exige cartão/PayPal via Lemon Squeezy — **zero aceitação BTC** | `services/payments.py` (LS-only) · `config.py:15` | Público-alvo Bitcoin-native não converte; perda de receita | Implementação | **P4** |
| Sev-2 | Gate de licensing em *open mode* permanente (tudo free, sem data de ativação) | `services/licensing.py` (`_ACTIVATION_ENV` vazia) · **validação 17-Aug: `PRO_KEYS_DB=1` → 402 + funil ativo (11/11, §10)** | Monetização validada localmente; falta flip da env var em prod (**#256**) | Implementação | P4 |
| Sev-2 | Dados de alerta/rentals marcados stale sem `updated_at` + amostras ts=0 dropadas | Issue **#204** (P2, **fechada** — PRs #252/#253) | Séries históricas incompletas = decisão errada | Backend | P2 |
| Sev-3 | Sem SLIs/SLOs de completude de dados (expected-vs-received) | Issue **#206** (P3, **fechada** — PRs #252/#253) | Degradação invisível até o cliente reclamar | DevOps/SRE | P2 |
| Sev-3 | Buckets de auditoria dropam ts≤0 sem bucket "desconhecido" + meta JSON corrompido silencioso | Issue **#205** (P3, aberta) | Auditoria não auditável | Frontend | P1 |
| Sev-3 | Mobile usa paleta RN antiga (149 hex fora do tema) | Issue **#239** (P3, aberta) | Inconsistência visual cross-platform | Frontend | P1 |
| Sev-3 | Módulos pesados sem lazy loading (chart sob demanda + cap de render) | Issue **#185** (P3, aberta) | Percepção de lentidão em mobile | Frontend | P2 |
| Sev-4 | `BTC_ADDRESS` env mistura papel de *wallet do operador* com *endereço de pagamento* | `config.py:15` · `services/polling.py:179` | Risco de confusão operacional ao ativar pagamento BTC | Backend | P4 |
| Sev-4 | Upgrade modal mostra preço em USD fixo (`$9/mo`) sem conversão sats | `templates/dashboard.html:2773` | Paywall BTC precisa exibir sats/BTC | Frontend | P4 |

---

## 3. Roadmap por Hierarquia (P0 → P4)

### P0 — Stop the Bleeding · *critério: zero Sev-1 aberto*
**Status: ✅ já atingido** (Sev-1 skeleton #214, indicador de instância #198,
sentinelas #203, paginação MRR #200, buckets de warning #202 foram entregues).
Nenhuma ação nova — **gate de regressão**: manter CI verde (build-image,
pytest+JS core 1359, frontend audit, e2e, axe 100/100).

### P1 — Foundations · *critério: consistência ≥ 95%*
| Ação | Owner | KPI |
|---|---|---|
| Mobile tokens: theme.ts com paleta RN (149 hex → 0) + guard vira GATE (#239) | Frontend | tokens-hex mobile = 0 · guard no CI |
| Auditoria buckets ts≤0 + meta JSON robusto (#205) | Frontend | zero bucket "desconhecido" ausente |
| Padronizar estados vazios/erro/carregando (audit enterprise #185 parent) | Frontend | cobertura de estados = 100% dos painéis |

### P2 — Enterprise Patterns · *critério: KPIs de UX atingidos*
| Ação | Owner | KPI |
|---|---|---|
| SLIs/SLOs de completude: expected-vs-received por fetch (#206) | DevOps | SLO 99% no painel de observabilidade |
| Fix de `updated_at`/stale em rentals + alertas (#204) | Backend | 0 payloads stale sem timestamp |
| Lazy loading de módulos pesados + cap de render (#185) | Frontend | LCP mobile < 2.5s · CLS = 0 |

### P3 — Craft & Differentiation · *critério: AI-Smell Score ≥ 4.6*
| Ação | Owner | KPI |
|---|---|---|
| Revisão de copy: remover textos robóticos/generic (auditoria design) | Frontend/Design | AI-Smell Score ≥ 4.6 (rúbrica 1-5) |
| Micro-interações nos CTAs de upgrade (hover/entrada/saída, prefers-reduced-motion) | Frontend | motion audit green · a11y 100/100 |

### P4 — Monetization Layer · *critério: programas prontos para venda*
| Ação | Owner | KPI |
|---|---|---|
| **Adapter BTC** (BTCPay Server OU WebLN+on-chain nativo) → `issue_license` | Backend | checkout BTC criado em < 1s |
| **Paywall BTC no modal** (QR BIP-21 + copiar endereço + sats + status poll) | Frontend | conversão paywall→paid ≥ 2% |
| **Ativação automática pós-pagamento** (webhook → license → `key_activated`) | Backend | ativação < 60s após confirmação |
| **Loja de planos** (PRO/PREMIUM/ENTERPRISE/LIFETIME) em BTC | Frontend/Backend | 4 programas publicados |

---

## 4. Divisão de Trabalho por Time

### 🔬 Time de Pesquisa (Discovery & Diagnosis) — entregue neste documento
- Mapeou o fluxo de monetização end-to-end: 402 → modal → LS checkout → webhook
  → `issue_license` → `key_activated` (evidência: `licensing.py`, `payments.py`,
  `conversion.py`, `app.py:5179`).
- **Achado-chave:** infra de BTC **já existe** (`donations` WebLN/on-chain/
  hashpower com dedup por txid/preimage — `app.py:1098`, `test_donation_dedup.py`)
  → o adapter BTC de PRO/PREMIUM reusa o mesmo watcher.
- **Benchmark (web):** BTCPay Server self-hosted (0% fee, self-custody,
  webhooks assinados, QR BIP-21 + Lightning, ativação: Lightning instantânea /
  on-chain 1 confirmação) vs custodiais (Coinbase Commerce/OpenNode ~1% + KYC).
  **Recomendação:** BTCPay Server (self-custody, zero fee, sem KYC — alinhado
  ao público) com **fallback WebLN nativo** para ativação instantânea (o
  projeto já tem código WebLN no Support modal).
- Lista priorizada: tabela §2 (2 Sev-2 · 4 Sev-3 · 2 Sev-4).

### 🛠️ Time de Implementação (Execution)
| Entregável | Spec resumida |
|---|---|
| `services/btcpay.py` (novo) | Adapter BTCPay Greenfield API: criar invoice (amount em sats, `orderId` = plano+funnel_id), verificar webhook HMAC, mapear `Settled` → `licensing.issue_license`. Fallback: WebLN `sendPayment` (BOLT-11) + watcher on-chain existente |
| `POST /api/upgrade/checkout` (alterar) | `plan` + `method: "btc"|"lightning"` → invoice BTC (sats dinâmicos via `merge_btc_quotes`) ou LS (legado) |
| `POST /api/payments/btcpay/webhook` (novo) | Verificação de assinatura → `issue_license(plan, source="btcpay")` → `track_event("paid", meta={method:"btc"})` → `key_activated` no próximo request |
| Upgrade modal (dashboard.html + app.js) | Aba **Bitcoin**: QR BIP-21 (endereço fixo + amount), botão copiar endereço, badge de sats, countdown, poll de status (`/api/upgrade/status/:invoiceId`), CTA WebLN quando disponível; manter aba "cartão" (LS) como fallback |
| `config.py` | Renomear papel do endereço: `PAYMENT_BTC_ADDRESS` (novo, = `35gj...`) separado de `BTC_ADDRESS` (wallet de dados do operador) |
| Loja de planos (novo painel "Upgrade") | Tabela PRO/PREMIUM/ENTERPRISE/LIFETIME com preços em BTC + USD-referência, comparação free vs pago, FAQ "como pagar em BTC" |

### 🧪 Time de Validação (Quality & Success)
| Entregável | Como medir |
|---|---|
| Testes do adapter (unidade + integração) | `tests/test_btcpay_adapter.py` espelhando o padrão `test_license_keys.py` (24 casos): invoice criado, webhook assinatura forjada rejeitada, Settled→license, dedup de replay, fallback WebLN |
| Testes do modal/paywall (JS core + e2e) | JS core espelhado (padrão `test_app_js_core.js`) + `tests/e2e/upgrade-btc.spec.js` (Playwright): abrir modal, trocar para aba BTC, copiar endereço, mock de status pago → badge liberado |
| Gate de a11y + tokens no novo modal | `check-axe.cjs` (score ≥ 90, button-name 0) + `check-tokens-hex.sh` no PR |
| Funil BTC no dashboard CFO | `funnel_report()` com `method: "btc"` — conversão por etapa, drop-off |
| Validação do paywall PRO_KEYS_DB | **Feito (17-Aug): 11/11 checks** — 402 em rota PRO · upgrade payload · `paywall_view` countado · `funnel_report` não-vazio · chave emitida passa no gate (script local, DB scratch) |
| Release Readiness | Checklist: CI verde · 0 console errors no audit_ui · smoke 2 viewports · code review · PR com Closes #issue |

---

## 5. Programas de Vendas Detalhados

**Pagamento:** exclusivamente Bitcoin — endereço fixo **`35gjAoadgQxrNc1Kx6QiSLx7wCCXRnRFkM`**
(P2SH, validado) · canais: on-chain (BIP-21 QR) e Lightning (WebLN/BOLT-11).
Preços em **sats** convertidos na hora do checkout (fonte: `merge_btc_quotes`,
cache 5min), com valor de referência em USD exibido ("≈ $9/mo" para orientação,
nunca como cobrança em fiat).

| # | Programa | Incluído | Público | Preço sugerido | Ativação |
|---|---|---|---|---|---|
| 1 | **PRO (mensal)** | Monte Carlo, proximity meter, 30d history, webhooks, alerts avançados | Miner ativo Parasite/Bitaxe | **0.00012 BTC/mo** (~$9) | Webhook Settled → key automática; Lightning = imediata, on-chain = 1 confirmação |
| 2 | **PREMIUM (mensal)** | Tudo do PRO + **AI Operator real (LLM)** + multi-wallet + CSV export + backup | Operador multi-frota / decisor | **0.00040 BTC/mo** (~$29) | idem; upsell natural de PRO |
| 3 | **ENTERPRISE (mensal)** | White-label, API keys, integrações custom, SLA, suporte dedicado | Pool/marketplace/empresa | **0.00135 BTC/mo** (~$99) | Contrato manual + key dedicada (`/api/admin/licenses`) |
| 4 | **LIFETIME PRO** | PRO vitalício (license sem expiração — `issue_license(months=None)`) | Hobbyist que quer 1 pagamento | **0.0024 BTC** one-shot (~$180) | on-chain 1 confirmação |
| 5 | **Doar (não-tiers)** | Apoio ao projeto (já existe!) | Comunidade | livre, WebLN/on-chain | `donations` (já implementado) |

**Fluxo de compra e ativação na interface (elegante, enterprise, zero agressividade):**
1. Operador acessa recurso gated → **402** → modal de upgrade (já existe) com
   **aba "Bitcoin" como padrão** e aba "Cartão" como fallback discreto.
2. Aba Bitcoin mostra: resumo do plano, **endereço fixo + QR BIP-21** com
   amount em sats, botão **copiar**, countdown de 15min, e **"Pagar com
   Lightning"** (WebLN) quando o navegador suporta.
3. Status em tempo real: *aguardando pagamento* → *visto na rede* → *confirmado*
   (poll `/api/upgrade/status/:id` a cada 5s). Em confirmado, o modal exibe
   **"PRO ativado ✓"** com a key já aplicada (X-License-Key) — sem fricção.
4. `track_event("paid", meta={method:"btc", plan})` alimenta o funil; o CFO
   dashboard mostra conversão por canal.
5. Emails/página de recibo: TXID + endereço + plano + validade — auditável.

**Clareza free vs premium:** painel "Upgrade" com matriz de features
(✔ grátis / 🔒 PRO / 💎 PREMIUM), cada gated feature com badge no próprio
painel (mecanismo já existe via `license_status()`).

---

## 6. KPIs de UX e de Negócio

| KPI | Definição | Target | Ferramenta |
|---|---|---|---|
| **Conversion Rate (paywall→paid)** | paid / paywall_view (30d) | ≥ 2% (baseline funil existe) | `funnel_report()` |
| **Conversion por canal** | paid por `method: btc\|lightning\|card` | BTC ≥ 60% do total | conversion_events.meta |
| **Activation Rate** | key_activated / paid | ≥ 90% | funnel |
| **Time-to-Activation** | webhook Settled → key ativa | < 60s (Lightning < 5s) | logs/timing |
| **Retention (M1/M3)** | % com renovação | ≥ 52% (M1) | subscriptions (LS) / novas invoices BTC |
| **LTV:CAC** | unit economics | ≥ 21:1 (mantido) | `ltv_cac_report()` |
| **Task Success Rate (paywall)** | usuário completa compra sem suporte | ≥ 95% | e2e + UX test |
| **Error Rate (paywall)** | 402/erros no fluxo de pagamento | < 1% | error_tracker |
| **AI-Smell Score** | rúbrica 1-5 (copy/estados) | ≥ 4.6 | revisão design |
| **Visual Consistency** | tokens 100% (0 hex fora do CSS) | 100% | check-tokens-hex |
| **A11y (axe)** | score proxy + button-name | 100/100 · 0 | check-axe |
| **LCP mobile** | carga do dashboard | < 2.5s | audit_ui |

---

## 7. Critérios de Go / No-Go por Fase

| Fase | GO se... | NO-GO se... |
|---|---|---|
| **P1 Foundations** | guards mobile/tokens verdes no CI · buckets/estados auditados · consistência ≥ 95% | guards quebram · estados divergentes entre painéis |
| **P2 Enterprise** | SLO 99% visível · 0 payloads stale · LCP < 2.5s mobile | degradação de dados invisível · regressão de perf |
| **P3 Craft** | AI-Smell ≥ 4.6 · motion green · a11y 100/100 | copy genérica em áreas de conversão |
| **P4 Monetization** | Adapter BTC com testes 24+ · webhook verificado · e2e paywall verde · **pagamento teste recebido no endereço real (1 sat de prova)** · funil medindo canal BTC | Pagamento de teste não detectado · assinatura de webhook forjada aceita · ativação > 60s · modal sem a11y |

**Regra de ouro (staff):** a fase P4 **só faz GO** depois do teste de prova
real — um pagamento de 1 sat na testnet/mainnet com o endereço
`35gjAoadgQxrNc1Kx6QiSLx7wCCXRnRFkM` confirmando a ativação automática de uma
license de teste. Evidência > opinião.

---

## 8. Lacunas de Ownership

| Lacuna | Decisão proposta |
|---|---|
| `BTC_ADDRESS` (dados) vs endereço de pagamento (receita) no mesmo env | Novo `PAYMENT_BTC_ADDRESS` — dono: Backend |
| Quem opera o BTCPay Server (self-host) vs fallback WebLN | Operador/founder; o adapter suporta ambos — dono: Backend |
| Renovação automática em BTC (não existe push nativo) | Modelo **invoice-per-cycle** com reminder (padrão BTCPay) — dono: Product + Backend |
| Conversão de preço USD→sats em tempo de invoice | `merge_btc_quotes` (já no repo) com cache 5min — dono: Backend |

---

## 9. Próximos Passos Concretos (executáveis hoje)

1. **Issue P4-1:** `services/btcpay.py` + rota webhook + testes (`test_btcpay_adapter.py`) — Closes: novo issue
2. **Issue P4-2:** Modal upgrade com aba Bitcoin (QR + sats + status poll + WebLN) + e2e
3. **Issue P4-3:** `PAYMENT_BTC_ADDRESS` no config + migração de copy do modal
4. ✅ **#204 e #206 fechadas** (PRs #252/#253) — pré-requisito de confiança concluído
5. **Ativação do paywall (#256):** `PRO_KEYS_DB=1` no Render — runbook em §10.2
6. **Validação real:** 1-sat test no endereço real → GO da fase P4

---

## 10. Validação do Paywall (PRO_KEYS_DB) + Runbook de Ativação em Produção

**Data:** 17-Aug-2026 · **Evidência:** validação local end-to-end em DB scratch
(`PRO_KEYS_DB=1`) · **Issue:** #256 (aberta — ação do operador pendente)

### 10.1 Resultado da validação (11/11 checks ✅)

| # | Check | Resultado |
|---|---|---|
| 1 | Open mode (sem env): `/api/proximity` | 200 — gate no-op (deploy atual intacto) |
| 2 | `PRO_KEYS_DB=1` sem chave: `/api/proximity` | **402** |
| 3 | Body do 402 | `code=LICENSE_REQUIRED` |
| 4 | Body do 402 | payload `upgrade` com plano PRO ($9/mo) |
| 5 | `/api/admin/conversion?days=30` | 200 (admin gate proxy-aware #254 ok) |
| 6 | Telemetria de funil | `paywall_view` countado a cada 402 |
| 7 | `funnel_report()` | **não-vazio** — stages preenchidos |
| 8 | `visitors` | ≥ 1 (tenant anônimo — correto) |
| 9 | Emissão de chave via `/api/admin/licenses` | `C65-XXXX-...` emitida |
| 10 | Rota PRO com `X-License-Key` válida | **200** |
| 11 | Rota PRO sem chave (pós-emissão) | ainda **402** |

**Leitura:** o funil `paywall_view → key_activated` **funciona e coleta dados**
assim que o paywall ativa. O design off-by-default foi confirmado: zero env =
tudo grátis; `PRO_KEYS_DB=1` = gate ativo + funil alimentado. A validação de
produção anterior (14-Aug) mostrou funil vazio **por construção** (open mode),
não por bug de tracking.

### 10.2 Runbook de ativação em produção (operator action — #256)

> **Atualização (17-Aug):** a ativação virou **infra-as-code** — `PRO_KEYS_DB=1`
> agora vive no `render.yaml` (blueprint) e o job `diagnose-render` do
> `execution-pipeline.yml` **verifica o 402 após cada deploy** (falha com
> mensagem acionável se o gate voltar a open mode). O passo 1 manual abaixo
> só é necessário como fallback se o sync do blueprint não aplicar a var.

Pré-requisito: **PR #255 mergeado** (gate admin proxy-aware — sem ele,
`/api/admin/licenses` fica público no Render; com ele, exige `X-API-Key` real).

1. **Aplicar a env var:** o merge do PR de infra (`render.yaml` com
   `PRO_KEYS_DB=1`) dispara o sync do blueprint no push a master. Se o sync
   não aplicar sozinho: Render Dashboard → `cypher65-war-room` → **Blueprint**
   → **Sync now** (ou `render login` local + `render env set PRO_KEYS_DB 1`).
2. **Validar o gate ativo:**
   ```bash
   curl -s https://cypher65-war-room.onrender.com/api/proximity
   # → 402 {"error":"PRO feature requires a license key","code":"LICENSE_REQUIRED",...}
   ```
3. **Emitir a primeira chave** (admin — exige a `API_KEY` real de produção):
   ```bash
   curl -s -X POST https://cypher65-war-room.onrender.com/api/admin/licenses \
     -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
     -d '{"tier":"pro","days":30,"note":"ativação inicial"}'
   # → {"license_key":"C65-XXXX-...","ok":true}
   ```
4. **Confirmar que o funil começou a coletar** (após tráfego/402s):
   ```bash
   curl -s "https://cypher65-war-room.onrender.com/api/admin/conversion?days=30&weeks=8"
   # → funnel.stages.paywall_view > 0
   ```
5. **Opcional — completar a economia:** setar `MARKETING_SPEND_USD` para
   LTV:CAC/payback saírem do `null` em `ltv_cac_report()`.

**Rollback:** remover `PRO_KEYS_DB` → open mode imediato (gate volta a ser
no-op; nenhuma feature quebra).

### 10.3 Critério de GO da fase P4 (atualizado)

A validação local cobre os checks funcionais; **o GO final continua exigindo o
teste de prova real**: 1 sat no endereço `35gjAoadgQxrNc1Kx6QiSLx7wCCXRnRFkM`
com ativação automática detectada (webhook → license) — evidência > opinião.
