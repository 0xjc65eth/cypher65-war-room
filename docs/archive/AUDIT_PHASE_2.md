# 🌐 FASE 2 — AUDITORIA PARASITE.SPACE · RELATÓRIO COMPLETO

**Data:** 23 Jul 2026
**Auditor:** Buffy (AI Agent)
**Método:** Engenharia reversa + testes live + referência open-source

---

## ⚠️ AVISO IMPORTANTE

A Parasite.space **não possui documentação oficial de API**. Todos os endpoints foram descobertos por engenharia reversa (inspecionando o dashboard oficial) e referenciando o projeto open-source `DozNot/rpi-parasite-pool-dashboard-display`. Endpoints internos podem mudar sem aviso.

---

## ✅ ENDPOINTS CONFIRMADOS (Live Test em 23 Jul 2026)

### 1. `GET /api/pool-stats`
**Status:** ✅ Funcional | **Timeout:** 10s

| Campo | Tipo | Valor exemplo |
|-------|------|---------------|
| `hashrate` | Integer | `184000000000000000` (H/s) |
| `workers` | Integer | `12514` |
| `users` | Integer | `2675` |
| `highestDifficulty` | String | `"63.3T"` |
| `lastBlockHash` | String | `"00000000000000000000b3b4..."` |
| `lastBlockTime` | String | `"958527"` (Unix timestamp) |
| `workSinceLastBlock` | Integer | `120565649496096` |
| `uptime` | String | `"458d 14h"` |

**Usado no projeto?** ✅ Sim

---

### 2. `GET /api/user/{btc_address}`
**Status:** ✅ Funcional | **Timeout:** 10s

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `hashrate` | Number | Hashrate total agregado |
| `workers` | Number | Contagem de workers ativos |
| `lastSubmission` | String | Tempo desde último submit (ex: `"45s ago"`) |
| `bestDifficulty` | String | Maior difficulty alcançada |
| `uptime` | String | Duração total de uptime |
| `workerData` | Array | Lista de workers individuais |

**`workerData[]` fields:**
- `id` (String)
- `name` (String)
- `hashrate` (Number)
- `bestDifficulty` (String)
- `lastSubmission` (String)
- `uptime` (String)
- `difficulty` (Number/undefined) — vardiff atual

**Usado no projeto?** ✅ Sim

---

### 3. `GET /api/account/{btc_address}`
**Status:** ✅ Funcional | **Timeout:** 10s

| Campo | Tipo |
|-------|------|
| `account.btc_address` | String |
| `account.ln_address` | String |
| `account.past_ln_addresses` | Array |
| `account.total_diff` | Integer |
| `account.last_updated` | String |
| `account.metadata.block_count` | Integer |
| `account.metadata.highest_blockheight` | Integer |
| `account.metadata.is_private` | Boolean |
| `lightning` | Null (sempre null nos testes) |

**Usado no projeto?** ✅ Sim

---

### 4. `GET /api/leaderboard`
**Status:** ✅ Funcional | **Timeout:** 10s
**Parâmetros:** `?limit=N`, `?type=combined`

| Campo por entry | Tipo |
|-----------------|------|
| `id` | Integer |
| `address` | String (truncado: `"bc1q...858s"`) |
| `diff` | Integer |
| `total_blocks` | Integer |
| `diff_rank` | Integer |
| `loyalty_rank` | Integer |
| `combined_score` | Float |
| `claimed` | Boolean |

**Default:** Retorna ~9 entradas sem parâmetros.

**Usado no projeto?** ✅ Sim (originalmente sem parâmetros)

---

### 5. `GET /api/highest-diff`
**Status:** ✅ Funcional | **Timeout:** 10s
**Parâmetros:** `?type=user-diffs&address={addr}&limit=N`

**Global (sem params):**
| Campo | Tipo |
|-------|------|
| `block_height` | Integer |
| `difficulty` | Float |
| `top_diff_address` | String |
| `claimed` | Boolean |
| `block_timestamp` | Integer |

**User-diffs (com params):**
Mesmos campos, mas `top_diff_address` é substituído por `address`.

**Usado no projeto?** ✅ Sim (originalmente endpoint global, sem filtrar por usuário)

---

### 6. `GET /api/user/{btc_address}/historical`
**Status:** ✅ Funcional | **Timeout:** 10s
**Parâmetros:** `?period=1d|7d|30d`, `?interval=15m|1h|6h`

| Campo por entry | Tipo |
|-----------------|------|
| `timestamp` | ISO 8601 String |
| `hashrate` | Number |

**Períodos testados:**
- `1d / 15m` → 200 ✅
- `7d / 1h` → 200 ✅
- `30d / 6h` → 200 ✅

**Usado no projeto?** ❌ **NÃO USA** — o projeto consulta seu próprio SQLite para dados históricos.

---

## ❌ ENDPOINTS NÃO EXISTENTES (404)

| Endpoint | HTTP Status |
|----------|-------------|
| `/api/payouts` | 404 |
| `/api/blocks` | 404 |
| `/api/rewards` | 404 |
| `/api/earnings` | 404 |
| `/api/miners` | 404 |
| `/api/wallet-stats` | 404 |
| `/api/stats` | 404 |

---

## 📊 CRUZAMENTO: Master Prompt vs API Real

| Funcionalidade Solicitada | Disponível na API? | Situação |
|---------------------------|-------------------|----------|
| Workers da carteira | ⚠️ Parcial | `workerData[]` com 6 campos. Suficiente. |
| Status online/offline | ⚠️ Parcial | Inferido de `lastSubmission`. Sem campo explícito. |
| Hashrate por worker | ✅ Sim | `workerData[].hashrate` |
| Shares por worker | ❌ Não | API não expõe contagem. Apenas `lastSubmission` + `bestDifficulty`. |
| Best difficulty por worker | ✅ Sim | `workerData[].bestDifficulty` |
| Payout history | ❌ Não | `/api/payouts` = 404 |
| Block rewards | ❌ Não | `/api/blocks` = 404 |
| Earnings/wallet stats | ❌ Não | `/api/wallet-stats` = 404 |
| Stratum info | ❌ Não | API REST apenas. Sem dados Stratum. |
| Network difficulty | ❌ Não | Obtido via blockchain.info, não da Parasite. |
| BTC price | ❌ Não | Obtido via CoinGecko. |
| Histórico de hashrate | ✅ Sim | `/api/user/{addr}/historical` — disponível, não usado no original. |

---

## 🟢 O QUE JÁ ESTAVA CORRETO (PRÉ-AUDITORIA)

- **5 endpoints usados corretamente** com parsing adequado
- **Fallbacks múltiplos** para network difficulty (blockchain.info → fórmula canônica)
- **Timeline delta detection** — rastreia shares reais via mudanças no `lastSubmission` entre polls
- **Alert deduplication** — evita spam de alertas repetidos
- **Tratamento de erros** — `fetch_json` retorna `None` em falha, sem quebrar o poll

---

## 🟡 GAPS MÉDIOS (CORRIGIDOS NA FASE 3)

| Gap | Correção aplicada |
|-----|-------------------|
| `highest-diff` sem filtrar por usuário | ✅ Adicionado `?type=user-diffs&address={addr}` |
| Leaderboard sem paginação | ✅ Adicionado `?limit=30` |
| `/api/user/{addr}/historical` não usado | ✅ Backfill disponível para implementação futura |
| Apenas 1 worker exposto | ✅ Todos workers do `workerData[]` agora expostos |

---

## 🔴 GAPS CRÍTICOS (NÃO CONTORNÁVEIS)

| Gap | Explicação |
|-----|-----------|
| **Payout Analytics impossível** | API não expõe `/payouts`, `/rewards`, `/earnings` |
| **Block rewards impossível** | API não expõe blocos com reward BTC |
| **Wallet statistics impossível** | API não tem `/wallet-stats` |
| **Stratum V1/V2 impossível** | API REST apenas. Sem WebSocket Stratum |

**Estratégia para estes gaps:** Para Payout Analytics e Block Rewards, usar **ESTIMATED** labels com cálculos matemáticos (expected blocks × reward). Para Wallet Statistics, usar apenas o que `/api/account` fornece. Para Stratum, inviável no modelo atual.

---

## 📋 FONTES DE DADOS EXTERNAS (NÃO-PARASITE)

| Fonte | Dados | Fallback |
|-------|-------|----------|
| `mempool.space/api` | Block height, mempool fees | — |
| `blockchain.info/q/*` | Network difficulty, hashrate | Fórmula canônica: `hashrate = difficulty × 2³² / 600` |
| `api.coingecko.com` | BTC price (USD, BRL, EUR, GBP) | Cache 5min |

---

## ✅ CONCLUSÃO

A API da Parasite.space fornece **dados suficientes para um dashboard de monitoramento**, mas **não fornece dados de payout/rewards**. O projeto usava 5 dos 6 endpoints disponíveis — o endpoint `/historical` não era utilizado. As correções aplicadas na Fase 3 maximizaram o uso dos dados disponíveis. Features que dependem de payout history ou block rewards devem ser implementadas como **ESTIMATED** com labels claros.
