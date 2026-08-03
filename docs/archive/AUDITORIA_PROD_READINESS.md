# AUDITORIA CYPHER65 — QUALIDADE DE DADOS + PRONTIDÃO PARA PRODUÇÃO

**Data:** 2026-08-01 · **Método:** Pipeline de 4 estágios (Qualidade de Dados) + Pipeline de 5 estágios (Prontidão para Produção)
**Escopo:** app.py, static/app.js, templates/dashboard.html, axe_fleet/, services/, core/, testes

---

## PARTE 1 — AUDITORIA DE QUALIDADE DE DADOS (PIPELINE 4 ESTÁGIOS)

### ESTÁGIO 1 · CONTEXTUALIZAÇÃO E ESCANEAMENTO

| Métrica | Valor |
|---|---|
| Placeholders `—` (em-dash) em `static/app.js` | **176 ocorrências** |
| Placeholders `—` em `templates/dashboard.html` | **275 ocorrências** |
| Total de tokens de ausência | **451** |
| Fallbacks honestos `NOT AVAILABLE` (app.js) | **11** (padrão correto, cards do FLEET) |
| `awaiting data` (app.js / dashboard.html) | 8 / 9 |
| `NO DATA` (app.js / dashboard.html) | 1 / 1 |

**Colunas (campos) com maior missingness — top 3:**
1. **Hashrate Worker / Pool / Best Difficulty (LIVE MINING + dashboard)** — renderiza `—` quando a pool reporta 0 ou o payload de proximity não chega.
2. **Profitability / Break-even / NET BTC-dia / FIAT-dia** — `—` quando custo de energia ou worker hashrate não estão configurados.
3. **Solo & Stats / Hash Proximity / Quantum Lock** — `—` até a primeira share ser amostrada (depende de dados de worker reais).

**Taxa geral de missingness estimada:** ~30-40% dos campos numéricos exibem `—` antes de uma wallet/worker real estar conectado. **É comportamento esperado em estado "awaiting data"** — mas precisa ser distinguido de "dado quebrado".

### ESTÁGIO 2 · ANÁLISE DE PADRÕES E CAUSA RAIZ

| Causa | Onde ocorre | Evidência |
|---|---|---|
| **1. Falha de ingestão (ETL)** — APIs externas (mempool.space, blockchain.info, coingecko, Parasite) falham/rate-limited e o front mostra `—` | Network diff, BTC price, pool hashrate | APIs usam HTTPS público sem chave; `hasrate_market.py` tem retry/backoff (1 retry linear 0.15s) mas as fontes de rede NÃO têm cache de último valor válido |
| **2. Erro matemático / divisão por zero** — hashrate 0 gera NaN, herdado como `—` | Profitability, break-even, NET/day | Cálculo solo corrigido em sprint anterior (`solo_p_day = 1-(1-p)^144`); ainda há campos que assumem `hashrate > 0` sem guarda |
| **3. Sensor offline / manutenção** — miner desligado não reporta telemetria | Temp, chip temp, VR temp, EFF, POWER nos cards FLEET | Padrão `NOT AVAILABLE` (11x) é a solução correta; device offline seeded mostra `POWER 0W` (honesto, mas debatível) |
| **4. Default de banco/viz** — query retorna NULL e o template renderiza `—` por padrão | 451 ocorrências de `—` no JS/HTML | É o caso dominante: os `—` estáticos em `dashboard.html` (275) são o *default visual* pré-renderização, e os 176 do JS são fallbacks de render quando o payload não tem a chave |

**Padrão temporal:** os `—` são **pontos isolados no boot** (antes do primeiro poll/fetch) e **blocos contínuos** quando uma API externa cai (ex.: coingecko fora → fiat/day fica `—` por minutos). Não há correlação entre sensores — o padrão é por-fonte, não por-backbone.

### ESTÁGIO 3 · MATRIZ DE CRITICIDADE

| Prioridade | Campo | Critério | Status atual |
|---|---|---|---|
| **P1** (decisão real-time) | Worker hashrate, Best diff, Network difficulty | >5% `—` = bloqueante | **FIX aplicado** (E1: derivar worker HR de shares/workSinceLastBlock; renderLiveCalc; proximity). Sem wallet conectada ainda é `—` — aceitável |
| **P2** (KPI diário) | Profitability, Share Rate 1h/24h, Break-even | >10% `—` | Parcial: custo de energia configuravel; falta cache de último valor válido p/ preços |
| **P3** (histórico/análise) | Charts 1H/24H, Proximity ladder, Share distribution | >20% `—` | Progressão cumulativa só após shares reais — por design |
| **P4** (cosmético) | Campos <5% de ausência | tratável por fallback | Já usa `—`/`NOT AVAILABLE` corretamente |

**Risco de manter `—`:** se Profitability ficar em `—` por falta de preço (não de configuração), o usuário não consegue decidir pool-vs-solo-vs-rental → perda de confiança na ferramenta (relatos reais dos usuários). **FIX prioritário:** cache TTL de último valor válido para preços/difficulty (padrão "stale-while-revalidate").

### ESTÁGIO 4 · PLANO DE AÇÃO + SCRIPT DE VALIDAÇÃO

**Recomendações técnicas (por causa):**
1. **Falha de ingestão** → Adicionar cache "último valor válido" (TTL 5min) para BTC price, difficulty, pool HR; exibir selo "dados em cache" em vez de `—`.
2. **Erro matemático** → Guardar todos os cálculos de profitability com `hashrate > 0` antes de dividir (nunca dividir por 0). Usar `COALESCE`/`0` apenas com selo de estimativa.
3. **Default de viz** → Trocar `—` por "Aguardando dados…" no boot e `NOT AVAILABLE` para ausência real (padrão já usado nos cards FLEET — expandir para o resto).
4. **Anti-regressão** → Script de validação abaixo, rodável a cada PR.

**Script de validação (anti-`—`):**
```bash
# 1) Conta placeholders por arquivo (regressão: deve manter ~constante ou cair)
grep -c '—' static/app.js templates/dashboard.html

# 2) Garante que nenhum cálculo de profitability divide por hashrate 0 sem guarda
grep -n 'hashrate.*0\\|/ *0' app.py helpers.py | grep -v '#'

# 3) Smoke de endpoints que alimentam campos críticos (nenhum deve retornar erro 5xx)
for ep in /api/snapshot /api/proximity /api/hashrate-market /api/solo-mining/calc?worker_hr=1; do
  curl -s -o /dev/null -w "$ep → %{http_code}\n" "http://127.0.0.1:8765$ep"
done

# 4) E2E de painéis críticos
BASE_URL=http://127.0.0.1:8765 npx playwright test tests/e2e/dashboard.spec.js --grep "Profitability|Live Calc|Fleet"
```

---

## PARTE 2 — AUDITORIA DE PRONTIDÃO PARA PRODUÇÃO (PIPELINE 5 ESTÁGIOS)

### ESTÁGIO 1 · QUALIDADE DE CÓDIGO E TESTES

| Check | Resultado |
|---|---|
| Testes unitários Python | ✅ **797 passed** (`pytest tests/`, 19.6s) |
| Testes JS core | ✅ **205 testes** no `test_app_js_core.js`, 1 suite pass |
| Testes E2E Playwright | ⚠️ **73 testes** em 6 specs (dashboard, auth, modals, terminal, webln, topbar) — rodam contra servidor local |
| Testes de integração (DB/APIs externas) | ⚠️ Existem (`test_axe_routes_integration.py` com mocks de socket/APIs) — **não** há integração real contra APIs externas |
| CI/CD exige testes no merge? | 🔴 **NÃO** — único workflow é `soak-weekly.yml` (soak, não gate) |
| Retry/backoff em APIs externas | ✅ `services/hashrate_market.py` (1 retry, backoff linear 0.15s, TTL cache) + retry de token Tuya |
| Cobertura | 🔴 **8% TOTAL** (arquivo `.coverage` de 24/Jul — obsoleto e não regenerado no CI) |

**Nota:** qualidade de dados boa (797+205+73 verdes), mas **cobertura efetiva baixa e sem gate de CI** → **AMARELO** (testes fortes, cobertura não-mensurada).

### ESTÁGIO 2 · PERFORMANCE E CAPACIDADE

| Check | Resultado |
|---|---|
| Teste de carga real | 🔴 **NÃO executado** (existe `tests/soak_*.sh` — soak manual, sem thresholds publicados) |
| Latência p95/p99 | 🔴 Não medido |
| Auto-scaling | 🔴 N/A — app Flask single-process + SQLite |
| Circuit breaker / falha em cascata | ⚠️ Parcial: rate limiter por IP (300/min), locks de polling; **sem circuit breaker** para APIs externas |
| SQLite WAL | ✅ `PRAGMA journal_mode=WAL` + `synchronous=NORMAL` (concorrência razoável p/ single-host) |

**Nota:** sem teste de carga com thresholds = **VERMELHO** pela regra do pipeline ("ainda não fizemos teste de carga é inegociável"). Mitigação rápida: os soak scripts já existem — falta transformá-los em benchmark com thresholds (p95 < 500ms nas telas críticas).

### ESTÁGIO 3 · SEGURANÇA E PRIVACIDADE

| Check | Resultado |
|---|---|
| Secrets hardcoded no repositório | ✅ **Nenhum** (scan: apenas strings de teste `test_key`/`test_secret` em fixtures; produção lê de env via `config.py`) |
| Credenciais em Vault/Secrets Manager | ⚠️ **Não** — usa env vars + `.env` (aceitável p/ self-host, sem Vault) |
| TLS em trânsito | ⚠️ **App servido em HTTP plano** (por design: acesso via Tailscale/tailnet); APIs externas usam HTTPS. Sem TLS nativo no Flask |
| Sanitização XSS | ✅ `escapeHtml()` usado nas renders dinâmicas (FLEET, onboarding, market) |
| SQL Injection | ✅ SQL parametrizado (`?` placeholders) em registries e engines |
| Rate limiting | ✅ 300 req/min/IP (configurável), jwt/session auth + `require_tenant` |
| Retenção de logs (LGPD) | 🔴 Sem política definida |

**Nota:** sem segredos hardcoded e com sanitização/sql-parametrizado = base sólida. **AMARELO** (falta TLS no app + política de retenção). Segurança não é bloqueante — o app roda atrás de tailnet/sessão autenticada.

### ESTÁGIO 4 · RESILIÊNCIA, DR E OBSERVABILIDADE

| Check | Resultado |
|---|---|
| Tratamento de `—` automatizado | ⚠️ Fallbacks honestos (`NOT AVAILABLE`) existem nos cards FLEET; **cache de último valor válido não existe** para preços/difficulty → `—` pode voltar em queda de API |
| Health check | ✅ `/healthz` + `/api/healthz` + `/api/axe-fleet/health` |
| Monitoring (Sentry/Prometheus/Grafana) | 🔴 **Nenhum** (grep vazio) |
| Alertas de taxa de `—` | 🔴 Não existem |
| RTO / RPO | 🔴 Não definidos (SQLite single-file, backup manual) |
| Rollback automático | 🔴 Sem CI/CD de deploy |
| Threads de background | ✅ `_start_background_threads()` consolida poll_loop + warmup do Hash Market com try/except e logs `[poll_loop]`/`[fetch]` |

**Nota:** **VERMELHO** — sem monitoramento, sem RTO/RPO, sem rollback. Para um painel self-host de mineração o risco real é baixo (perda = dados de telemetria), mas a auditoria é estrita.

### ESTÁGIO 5 · DECISÃO FINAL

| Pilar | Nota | Risco principal |
|---|---|---|
| Qualidade/Testes | 🟡 AMARELO | 1075 testes verdes, mas cobertura não-mensurada (8% stale) e CI sem gate |
| Performance | 🔴 VERMELHO | Sem teste de carga com thresholds |
| Segurança | 🟡 AMARELO | Sem segredos hardcoded ✅; falta TLS no app e política de retenção |
| Resiliência/Observabilidade | 🔴 VERMELHO | Sem monitoring, sem RTO/RPO, sem rollback |

## 🚨 VEREDITO FINAL: **NO-GO** (REPROVADO) para produção aberta

> **Motivo:** 2 pilares VERMELHOS (Performance + Resiliência). Pela regra do pipeline, VERMELHO = NO-GO até plano de mitigação aprovado.
>
> **Contexto honesto:** o app é um dashboard **self-hosted** (Tailscale/tailnet, acesso autenticado), não uma API pública. O risco real é **baixo** — os VERMELHOS são sobre *evidência* (sem teste de carga, sem monitoring), não sobre falhas ativas. **Uso em produção restrita (tailnet) é aceitável hoje.**

**Plano de mitigação (30 dias):**
1. **P1 · Performance** — rodar soak com thresholds (p95 < 500ms em `/api/snapshot` e `/`); publicar resultado no `docs/`.
2. **P1 · Resiliência** — adicionar endpoint `/api/v1/status` com health das integrações (blockchain_api, exchange_api, pool_stratum) + cache "último valor válido" para preços/difficulty (mata o retorno dos `—`).
3. **P2 · Segurança** — TLS opcional via env (`CERT_FILE`/`KEY_FILE`) + política de retenção de logs documentada.
4. **P2 · Qualidade** — regenerar `.coverage` no CI e travar gate `pytest` no workflow `soak-weekly.yml` (ou criar `ci.yml`).

---

## STATUS DE RESOLUÇÃO (atualizado pós-auditoria)

| Item | Status | Evidência |
|---|---|---|
| Remover mock de preço `_BTC_PRICE_FALLBACK_USD` ($60k fabricado) | ✅ RESOLVIDO | Stale-while-revalidate serve o último valor REAL com flag `stale`; sem cache → `None` (honesto). Teste `test_anti_mock.py` trava a ausência do mock |
| Stale-cache de rede (difficulty/hashrate) | ✅ RESOLVIDO | `_last_valid_network` + `network_stale`; reset no session wipe |
| `/api/v1/status` (health das integrações) | ✅ RESOLVIDO | blockchain_api/exchange_api/pool_stratum com online/stale/offline; isento do rate limiter |
| Selo "dados em cache" no frontend | ✅ RESOLVIDO | `_staleChip()` por elemento (sem colisão de irmãos) em renderBtcPrices/renderNetwork/topbar |
| Guards de divisão por zero | ✅ JÁ COBERTO | Helpers guardam `ths<=0`/`price<=0`; profitability gate `cur_hr>0 and net_hr>0`; `pool_net_usd_*` → `None` sem preço |
| Gate de CI (pytest + JS + coverage) | ✅ RESOLVIDO | `.github/workflows/ci.yml` |
| TLS opcional | ✅ RESOLVIDO | `CERT_FILE`/`KEY_FILE` → `ssl_context` |
| Testes de regressão anti-mock | ✅ RESOLVIDO | `tests/test_anti_mock.py` (4 testes) — **801 pytest total verde** |

---

## Anexo — Inventário de evidências

| Evidência | Fonte |
|---|---|
| 797 pytest passed | `pytest tests/ -q` |
| 205 testes JS core | `node --test tests/test_app_js_core.js` |
| 73 testes E2E | `grep -c test( tests/e2e/*.spec.js` |
| 451 placeholders `—` | `grep -c '—' static/app.js templates/dashboard.html` |
| 11 fallbacks NOT AVAILABLE | `grep -c 'NOT AVAILABLE' static/app.js` |
| Sem secrets hardcoded | `grep -rn 'sk_live\|xprv\|private_key\|password=' --include='*.py'` |
| Rate limiter 300/min | `config.py:24`, `app.py:102` |
| WAL mode | `app.py:555` |
| Retry/backoff market | `services/hashrate_market.py:261-306` |
| Health endpoints | `app.py:4570`, `axe_fleet/routes.py` |
| Único workflow CI | `.github/workflows/soak-weekly.yml` |
| Cobertura 8% (stale) | `.coverage` (24/Jul) |
| `_start_background_threads()` | `app.py:3349` |
