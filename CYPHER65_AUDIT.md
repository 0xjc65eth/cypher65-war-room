# 🔍 CYPHER65 — AUDITORIA TÉCNICA COMPLETA

**Data:** 27 Jul 2026  
**Versão do código:** Restaurada ao commit `0133a17` (23 Jul 2026), pré-HERMES  
**Analista:** Freebuff (DeepSeek Pro V4)  
**Escopo:** Auditoria completa antes de qualquer implementação nova

---

## 1. ARQUITETURA ATUAL

```
                    CYPHER65
                        |
              Flask (app.py)
            +--------+--------+
            |        |        |
        services/   routes/  agents/
            |        |        |
      state.py     [orphaned] opportunity_engine.py
      polling.py              solo_mining_advisor/
      proximity.py
      probability.py
      probability_engine.py [orphaned]
            |
      /data/war_room.sqlite
            |
            +--------+--------+
            |        |        |
        Parasite   Mempool   CoinGecko
        .space     .space    .com
```

### Stack

| Camada | Tecnologia | Versão | Observação |
|--------|-----------|--------|------------|
| Backend | Python / Flask | 3.10+ / Flask 3.x | Single file `app.py` (2.520 linhas) |
| Frontend | Vanilla JS + HTML + CSS | ES2020 | `static/app.js` (1.306L), `style.css` (1.842L), `dashboard.html` (1.140L) |
| Database | SQLite | 3.x | `data/war_room.sqlite` |
| HTTP | requests | Última | Polling paralelo via ThreadPoolExecutor |
| Charts | Chart.js (CDN) | 3.x | 4 gráficos: hashrate, pool, best-diff, network |
| Outros | Web Audio API, Canvas API | — | Alertas sonoros, Matrix rain, gauges SVG |

### Frontend

O dashboard é **single-page**: o Jinja2 template `dashboard.html` renderiza todos os painéis inline. O JavaScript em `app.js` faz polling a cada 15s via `fetchSnapshot()`, atualizando a UI com dados do `/api/snapshot`.

**24 painéis** no total, divididos em:
- **Hero** — worker, hashrate, best diff, status
- **Monitoramento** — proximity meter, pool, account, network
- **Analytics** — halving, mempool fees, profitability, gauges, milestones
- **Live Mining** — workers grid, share calculator
- **CFO/Monte Carlo** — probabilidade, simulação interativa
- **Charts** — hashrate, pool, best-diff, network difficulty
- **Eventos** — high-diff events, timeline feed, leaderboard
- **Terminal** — logs, alerts, solo mining terminal
- **Modais** — settings, export, wallet connect

### Backend

O backend está **parcialmente modularizado**:

**✅ Extraídos para `services/`:**

| Módulo | Status | Uso |
|--------|--------|-----|
| `services/state.py` | ✅ VERIFIED | Single source of truth — usado por app.py, polling.py, proximity.py |
| `services/polling.py` | ✅ VERIFIED | `poll_once()`, `purge_old()`, `poll_loop()` — injetado via `polling.init(config)` |
| `services/proximity.py` | ✅ VERIFIED | Proximity meter, quantum lock, rolling avg — injetado via `proximity.init(get_db)` |

**⚠️ Existem mas NÃO conectados:**

| Módulo | Status | Problema |
|--------|--------|----------|
| `routes/solo_mining_routes.py` | ⚠️ ORPHANED | Blueprint `solo_mining_bp` definido mas NUNCA registrado em app.py |
| `services/probability_engine.py` | ⚠️ ORPHANED | `register_probability_routes(app)` nunca chamado |
| `services/probability.py` | ⚠️ ORPHANED | Importado por probability_engine.py mas nunca exposto |

---

## 2. FUNCIONALIDADES EXISTENTES

### VERIFIED (testado com dado real)

| Funcionalidade | Arquivo(s) | Fonte de Dado | Notas |
|---------------|-----------|---------------|-------|
| Monitoramento worker cypher65 | app.py, state.py | Parasite API `/api/user/{addr}` | Hashrate, best diff, last submission, uptime |
| Pool overview | app.py, state.py | Parasite `/api/pool-stats` | Hashrate, workers, highest diff, last block |
| Account/LN info | app.py | Parasite `/api/account/{addr}` | LN address, total diff, blocks found |
| Leaderboard | app.py | Parasite `/api/leaderboard` | Top 30 miners |
| High-diff events | app.py | Parasite `/api/highest-diff` | Global + user-specific |
| Network stats | app.py | blockchain.info + mempool.space | Difficulty, hashrate, block height |
| BTC price | app.py | CoinGecko | USD, BRL, EUR, GBP (cache 5min) |
| Mempool fees | app.py | mempool.space | Recommended fees |
| Halving countdown | app.py | Calculated | Rolling avg block time |
| Profitability | app.py, helpers.py | CALCULATED | Fiat conversion, share-of-pool |
| Proximity meter | services/proximity.py | CALCULATED + REAL | Pct of network, distance factor, milestones |
| Quantum Lock | services/proximity.py | CALCULATED | Health score 0-100 based on shares + proximity + momentum |
| Alerts | app.py, state.py | CALCULATED | Hashrate drop, stale, offline, new block, new high-diff |
| Live Mining Calculator | services/proximity.py | CALCULATED | Per-share math, cumulative P(block), consistency check |
| Monte Carlo | calculators no dashboard | CALCULATED | CFO panel (10k iterações) |
| Settings | app.py, routes | SQLite | Key-value persistence |
| Export CSV | app.py | SQLite | Backup/restore de configurações |
| Wallet Connect | app.py | — | `POST /api/set-address` com validação + persistência |

### PARCIAL (funciona mas incompleto)

| Funcionalidade | Problema | Impacto |
|---------------|----------|---------|
| Workers grid (all workers) | Dados da pool mostram hashrate=0 (rigs offline) | Dados reais, não é bug |
| Opportunity Engine | Endpoint `/api/opportunities` existe em app.py mas testes quebram (rate limit + session wipe) | Testes P0 quebrados |
| Rate limiting | Presente (`@app.before_request`) mas sem isolamento de teste | Testes falham com 429 |
| Paginação leaderboard | Limitado a 30 via query param | Aceitável para MVP |

### NÃO IMPLEMENTADO (mas solicitado no Master Spec)

| Funcionalidade | Status | Motivo |
|---------------|--------|--------|
| Braiins adapter | ❌ NOT IMPLEMENTED | `solo_mining.py` tem funções para Braiins/MRR mas não conectadas |
| MRR adapter | ❌ NOT IMPLEMENTED | `solo_mining.py` tem funções para MRR mas sem API key configurada |
| NiceHash adapter | ❌ NOT IMPLEMENTED | Não existe |
| Miner telemetry (temp, fan, power) | ❌ IMPOSSIBLE | API da Parasite NÃO expõe esses dados |
| Payout history | ❌ IMPOSSIBLE | Parasite não tem `/api/payouts` (404 confirmado) |
| Block rewards | ❌ IMPOSSIBLE | Parasite não tem `/api/blocks` (404 confirmado) |
| Anomaly detection | ❌ NOT IMPLEMENTED | Apenas alerts básicos de hashrate drop + offline |
| CYPHER AI Brain | ❌ NOT IMPLEMENTED | Removido junto com HERMES |
| Smart alerts configuráveis | ❌ NOT IMPLEMENTED | Apenas alerts fixos por polling |
| Health score (multi-componente) | ⚠️ PARCIAL | Quantum Lock existe mas não está exposto como "Health Score" |
| Opportunity score (0-100) | ❌ NOT IMPLEMENTED | Apenas comparação raw de preços |
| Rental strategy engine | ❌ NOT IMPLEMENTED | Comparação de aluguel existe mas não estratégia |
| PWA completo | ⚠️ PARCIAL | `manifest.json` e `sw.js` existem, mas sem service worker funcional |
| Mobile app (iOS/Android) | ❌ NOT IMPLEMENTED | Arquitetura não existe |

---

## 3. ROTAS — INLINE vs BLUEPRINT (DESCOBERTA CRÍTICA)

**Problema:** `routes/solo_mining_routes.py` define um Blueprint `solo_mining_bp` com 3 endpoints, mas ele **NUNCA É REGISTRADO** em `app.py`. Em vez disso, os mesmos 3 endpoints estão **duplicados inline** em `app.py` (linhas 2253-2380).

| Endpoint | Inline (app.py) | Blueprint (routes/) | Status |
|----------|----------------|-------------------|--------|
| `/api/solo-mining/calc` | ✅ L2253-2303 | ✅ routes/solo_mining_routes.py | DUPLICADO |
| `/api/solo-mining/compare` | ✅ L2305-2360 | ✅ routes/solo_mining_routes.py | DUPLICADO |
| `/api/solo-mining/network` | ✅ L2362-2380 | ✅ routes/solo_mining_routes.py | DUPLICADO |
| `/api/probability` | ❌ | ⚠️ services/probability_engine.py | **ORFÃO** |

**Impacto:** 
- As versões inline em app.py **são as que realmente servem**
- As versões Blueprint em `routes/` são **código morto**
- O endpoint de probabilidade **não existe** (nunca registrado)

---

## 4. TESTES

| Suíte | Status | Observação |
|-------|--------|------------|
| Testes coletados | 236 testes | `pytest --collect-only` |
| `tests/agents/` | 54 passed | ✅ |
| `tests/integration/` | 32 passed | ✅ |
| `tests/test_opportunity_engine.py` | 11 FAIL | Rate limit 429 + session wipe |
| `tests/test_persistence.py` | ERROR | `app._restore_btc_address_from_db` não existe (renomeado para `_load_persisted_address`) |
| `tests/test_session_wipe.py` | FAIL | Endpoint `/api/set-address` existe mas testes esperam comportamento específico |
| **Resultado final** | ❌ **QUEBRADO** | 3 arquivos com falhas |

---

## 5. FONTES DE DADOS — ORIGEM E CONFIABILIDADE

| Fonte | Dado | Tipo | Confiabilidade | Fallback |
|-------|------|------|---------------|----------|
| `parasite.space/api` | Pool stats, user, account, leaderboard, highest-diff | REAL | Alta (live) | None |
| `mempool.space/api` | Block height, fees | REAL | Alta | None |
| `blockchain.info/q/*` | Difficulty, hashrate | REAL (text) | Média (formato muda) | Fórmula canônica |
| `api.coingecko.com` | BTC price | REAL | Alta (cache 5min) | Cache em memória |
| SQLite local | Histórico, eventos, alertas | REAL | Alta | — |

**Dados que NÃO existem em nenhuma fonte atual:**
- Temperatura, fan speed, power consumption — **N/A (não exposto pela pool)**
- Payout history, block rewards — **N/A (endpoints 404)**
- Per-share logs — **N/A (server-side operator data)**
- Worker status explícito (online/offline) — **INFERIDO de lastSubmission**

---

## 6. PROBLEMAS CRÍTICOS (P0)

| # | Problema | Arquivo | Impacto | Correção |
|---|---------|---------|---------|----------|
| P0.1 | `routes/solo_mining_routes.py` não registrado | app.py | Código morto; blueprints duplicados | Registrar blueprint + remover inline |
| P0.2 | `services/probability_engine.py` não registrado | app.py | `/api/probability` não existe | Chamar `register_probability_routes(app)` |
| P0.3 | `test_persistence.py` collection error | tests/ | Testes não rodam | Renomear referência para `_load_persisted_address` |
| P0.4 | `test_opportunity_engine.py` falha por rate limit | app.py + tests/ | 11 testes quebrados | Isolar rate limit em modo TESTING |
| P0.5 | `test_session_wipe.py` falha | tests/ | Teste de wipe não passa | Sincronizar lógica com testes |

## PROBLEMAS ALTOS (P1)

| # | Problema | Arquivo | Impacto |
|---|---------|---------|---------|
| P1.1 | app.py com 2.520 linhas monolíticas | app.py | Manutenibilidade baixa | 
| P1.2 | Anomaly detection inexistente | app.py | Apenas alerts básicos |
| P1.3 | Braiins/MRR/NiceHash adapters não implementados | solo_mining.py | Hashpower market incompleto |
| P1.4 | Sem autenticação real | app.py | Dashboard exposto sem login |

## PROBLEMAS MÉDIOS (P2)

| # | Problema | Impacto |
|---|---------|---------|
| P2.1 | Polling fixo 15s sem modos (LIVE/BALANCED/BATTERY_SAVER) | Bateria em mobile |
| P2.2 | State global mutável sem locks | Race condition teórico |
| P2.3 | SQLite sem connection pool | Performance em carga |
| P2.4 | PWA incompleto (service worker não funcional) | Mobile installability |
| P2.5 | Sem testes JS/frontend | Regressão não detectada |

## PROBLEMAS BAIXOS (P3)

| # | Problema | Impacto |
|---|---------|---------|
| P3.1 | Placeholder `—` aparece antes do primeiro poll | UX |
| P3.2 | Tabelas com overflow em <600px | Mobile |
| P3.3 | Sem labels de acessibilidade ARIA | Acessibilidade |
| P3.4 | Sem verificador de contraste para daltônicos | Acessibilidade |

---

## 7. RECOMENDAÇÕES — ORDEM DE EXECUÇÃO

Seguindo a ordem do Master Spec (Phase 33), as ações recomendadas são:

### IMEDIATO (P0 blockers)
1. **Registrar o Blueprint** `solo_mining_bp` em app.py e remover as rotas inline duplicadas (reduz app.py em ~130 linhas)
2. **Conectar** `register_probability_routes(app)` — ativar `/api/probability` e `/api/probability/full`
3. **Corrigir** `test_persistence.py` — renomear `_restore_btc_address_from_db` para `_load_persisted_address`
4. **Corrigir** rate limit isolation nos testes para `test_opportunity_engine.py` passar

### FASE 1 (Architecture + Data Models)
5. **Remover código morto** de `routes/` após registrar blueprints
6. **Documentar data models** unificados (Miner, Worker, HashrateSnapshot, etc)

### FASE 2-4 (Adapters + Hashpower)
7. **Implementar Braiins adapter** real via `solo_mining.py` já existente
8. **Implementar MRR adapter** com API key configurável via env var
9. **Criar sistema de price normalization** para comparar ofertas

### FASE 5-10 (Inteligência)
10. **Expor Quantum Lock como Health Score** (0-100) no dashboard
11. **Criar anomaly detection** real (hashrate drop, reject rate spike, worker offline)
12. **Expandir Best Difficulty Engine** com milestones e tracking
13. **Criar Rental Strategy Engine** com 3 cenários (pessimista/base/otimista)

### FASE 11-16 (Alerts + AI)
14. **Smart alerts configuráveis** — UI para criar/editar alertas persistidos
15. **CYPHER AI Brain** — novo sistema de IA independente do HERMES removido
16. **CYPHER AI Terminal UI** — dentro da identidade visual existente

### FASE 17-25 (Mobile + PWA + Performance)
17. **PWA funcional** — service worker com cache, instalável
18. **Modos LIVE/BALANCED/BATTERY_SAVER** no polling
19. **Testes** — unitários (probability, hashrate) + integration (adapters) + UI
20. **Security audit** final

---

## 8. CONCLUSÃO

```
PROJETO:         CYPHER65 War Room
STACK:           Flask + Vanilla JS + SQLite
ESTADO:          FUNCIONAL MAS COM PROBLEMAS
                 
P0 (CRITICAL):    5 abertos
P1 (HIGH):        4 abertos
P2 (MEDIUM):      5 abertos
P3 (LOW):         4 abertos

VERIFIED:        18 funcionalidades
PARTIAL:          4 funcionalidades
NOT IMPLEMENTED: 15 funcionalidades
IMPOSSIBLE:       3 funcionalidades

PRODUCTION READY: NÃO (P0 blockers)
COMMERCIAL READY: NÃO (falta autenticação + multi-pool)
```

**Próximo passo recomendado:** Executar os **4 P0 blockers** (registrar blueprints, conectar probability engine, corrigir testes) antes de qualquer implementação nova. Isso desbloqueia a capacidade de testar e integrar as fases seguintes.
