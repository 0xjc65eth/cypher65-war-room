# 🔥 PROJETO FÊNIX — Pipeline de Diagnóstico & Correção (v2 · Evidence-Based)

> **Autor:** Engenharia Chefe · Equipe Research & Implementação (60 membros)
> **Mandato:** Nenhum diagnóstico sem evidência. Nenhum fix sem backtest.
> **Estado do documento:** Baseline forense coletada em 2026-08-01 (benchmarks reais, arquivo:linha citados).

---

## 0. Executivo — O que foi provado (não o que foi suposto)

| # | Sintoma relatado no dashboard | Causa-raiz confirmada (arquivo:linha) | Benchmark real |
|---|---|---|---|
| E1 | Worker HR `0 H/s`, SYSTEM `OFFLINE` | O app **confia cegamente** no campo `hashrate` da API da pool. A Parasite retorna `"hashrate":"0"` (**string**) para workers com `lastSubmission` recente. `app.py:2001` copia o valor cru; `app.py:2018` converte → `0`. | `GET parasite.space/api/user/bc1qc…` → `200`, `hashrate:0`, `workerData[].hashrate="0"` |
| E2 | HashMarket mostra "3 offers" todas `ESTIMATED`/`DERIVED`, `HR:1.00 kH/s` | **(a) NiceHash quebrado**: `NICEHASH_PUBLIC_API=.../orderBook` sem `?algorithm=SHA256&market=0` → `400` (só fallback derived aparece). Braiins **já funciona** (`/v1/spot/orderbook` → 200); MRR exige `type`+auth. **(b) Bug de unidade**: backend envia hashrate em **TH/s** (`DEFAULT_RENTAL_HASHRATE_TH=1000` = 1 PH), frontend formata como **H/s** → `fmt.hashrate(1000)` = `"1.00 kH/s"`. | NiceHash `+params` → `200` com asks reais; Braiins orderbook `200` com bids reais |
| E3 | `WORK_DELTA` duplicado (2x mesmo ts) | `static/app.js:1152-1154` gera **id aleatório** (`Math.random()`) para eventos em formato array → o dedup `timelineIdsRendered` **nunca** funciona → cada render re-adiciona eventos iguais. | Log real mostra `WORK_DELTA` duplicado em `23:50:16` e `00:00:09` |
| E4 | Painel ALERTS cheio de alertas mock ("Test-History-Rec", "Maint-Device"…) | Testes escrevem no **DB real** `data/war_room.sqlite`: `tests/core/conftest.py:9` importa `app` (→ `init_db()` real); alertas com nomes de devices de teste persistidos com `active=1`. | `SELECT … FROM alerts` em `war_room.sqlite` → 24 alertas CRIT de teste |
| E5 | POOL LUCK `0.0%` | `app.py:2483` retorna `0.0` quando `wslb=0` (rodada nova/sem trabalho) e quando `cur_hr=0` o bloco nem executa → UI mostra 0% (parece azar). Sem dados deveria ser neutro (`—` ou `100%`). | Código `if wslb else 0.0` |
| E6 | Profitability `cost: $0` / Break-even `—` | `cost_mode` default = `"none"` (`services/settings.py:14`) e o cálculo só roda com `cur_hr>0 and net_hr>0` (`app.py:2550`). Com hashrate 0, tudo é `—`/`$0`. | `DEFAULT_SETTINGS["cost_mode"]="none"` |
| E7 | "No devices" / Seed Test falha | `axe_fleet/routes.py:433-434` retorna **403** sem `DEBUG_MOCK=1`; não há discovery de rede nem agente local → impossível adicionar miner remoto. | Gate `DEBUG_MOCK` no endpoint `seed-test` |
| E8 | Hashrate real existe mas não aparece | SHARE_FOUND a cada ~60s (log real) + `workSinceLastBlock` acumulando → dá para **derivar HR por shares** (`H = shares·diff·2³²/Δt`), mas o app só lê `worker.hashrate` da pool. | Log: `+18.23 G work since last poll` |
| E9 | Best Diff all-time "perdido" | **Não é bug**: `app.py:1282 _restore_all_time_best_diff()` + `:1303 _persist_all_time_best_diff()` já persistem em `settings`/`best_diff_history`. Endereço exibido vem de `_wallet_address` persistido (sobrescreve `.env` — comportamento esperado, não bug). | `grep` confirma restauração/persistência; log `(first)` = primeiro bump do processo |

**Resumo do Chefe:** Não há "bug único". Há **4 bugs de engenharia** (dedup do timeline, unidade TH/s no market, params/auth de providers — NiceHash/MRR, isolamento de DB de testes) e **2 lacunas de arquitetura** (sem derivação de hashrate por shares; sem agente local de descoberta). O restante dos `—` é **cascata** do E1 (hashrate=0 trava profitability, luck, break-even).

---

## 1. Metodologia (como os achados foram provados)

1. **Forense de código** — cada sintoma mapeado para `arquivo:linha` real.
2. **Benchmark ao vivo** — `curl` nas APIs reais (Parasite, Braiins, NiceHash, MRR, mempool) no dia da análise.
3. **Inspeção do DB** — queries diretas em `data/war_room.sqlite`.
4. **Rastreio front→back** — do elemento DOM (`#kpi-hashrate`, `.mkt-card__detail`) até a fonte de dados no backend.
5. **Nada de hipótese sem prova** — todo item da seção 0 tem coluna "Benchmark real".

---

## 2. Quadro de Evidências Detalhado (arquivo:linha)

### E1 — Hashrate 0 / SYSTEM OFFLINE
- `app.py:2001` — `"hashrate": w.get("hashrate")` (copiado cru, pode ser string `"0"`).
- `app.py:2018` — `hr = float(entry.get("hashrate") or 0)` → `0.0`.
- `app.py:1422` — `worker_hps = float(worker.get("hashrate") or 0)` → 0 em todo o pipeline.
- `static/app.js:3477` — `worker ? this.formatHashrate(worker.hashrate) : '0 H/s'` → exibe `0 H/s`.
- **Benchmark:** `curl https://parasite.space/api/user/bc1qpc3832…` → `{"hashrate":0,"workers":0,…,"workerData":[{…,"hashrate":"0","lastSubmission":"1785441520",…}]}` (string `"0"` com envio recente).

**Fix proposto (P1):** adicionar **derivação de hashrate por shares** quando `worker.hashrate <= 0` e houver `workSinceLastBlock`/`SHARE_FOUND` recentes: `H = Σ shares · share_diff · 2³² / Δt`. O `LIVE HASH CALCULATOR` (`app.py:2178`) já faz esse cálculo por share — só falta **propagá-lo** para `worker_hashrate` do snapshot.

### E2 — HashMarket: 3 offers falsas + unidade errada
- `agents/solo_mining_advisor/tools.py:29-32` — URLs: `BRAIINS_API=https://hashpower.braiins.com/v1`, `NICEHASH_PUBLIC_API=…/hashpower/orderBook`, `MRR_BASE=…/api/v2`.
- `services/hashrate_market.py:173-175` — KissMyHash cai em fallback `NiceHash+10%`; `:199` Parasite é `ESTIMATED`.
- `services/hashrate_market.py:25` — `DEFAULT_RENTAL_HASHRATE_TH = 1000.0` (TH/s).
- `static/app.js:1498` — `fmt.hashrate(o.hashrate)` espera **H/s** mas recebe **TH/s**.
- **Benchmarks ao vivo (2026-08-01):**
  - Braiins **orderbook OK** — `GET https://hashpower.braiins.com/v1/spot/orderbook` → `200` com bids reais (`price_sat`, `hr_matched_ph`). O código atual **já funciona**; a falha real é só `/spot/settings` → `401` (soft-fail tolerado, usa default `sats/PH/day`).
  - NiceHash **quebrado por falta de query params** — `…/hashpower/orderBook` (sem params) → `400`; adicionando `?algorithm=SHA256&market=0` → `200` com asks reais (`0.8305`, `0.6801` BTC/PH…).
  - MRR → `GET /api/v2/rig` → `200` mas exige campo `type` + `api_key`/`api_secret` (assinatura já existe em `tools.py:203`).

**Fix proposto (P1):**
- Braiins: **nenhuma mudança de URL** (endpoint correto); apenas garantir que `401` do `/spot/settings` não degrade o fetch (já é soft-fail).
- NiceHash: adicionar `?algorithm=SHA256&market=0` à URL em `tools.py:31` (parâmetro `market` = 0 EU / 1 US).
- MRR: carregar `api_key`/`api_secret` do settings/env (hoje vazios) e enviar `type` no payload.
- Normalizar: backend deve enviar **H/s** (ou o frontend multiplicar `hashrate_th * 1e12` antes de `fmt.hashrate`). Adicionar teste unitário de formatação (`fmt.hashrate(1e12) === '1.00 TH/s'`).

### E3 — Timeline duplicado (WORK_DELTA 2x)
- `static/app.js:1152-1154` — `_normalizeTimelineEvent` para arrays: `id: e[0] + '_' + String(Math.random()).slice(2, 8)` → **id não-determinístico**.
- `static/app.js:1166` — `newOnes = ordered.filter(e => !timelineIdsRendered.has(e.id))` → nunca deduplica.
- Duplicação só é visível para eventos com mesmo `ts` (WORK_DELTA aparece 2x com mesmo timestamp).

**Fix proposto (P1):** id estável por hash de `(ts, event_type, message)` — ex.: `e[0]+'|'+e[1]+'|'+e[3]`. Manter o caminho de objetos (que já tem `id` do backend) intacto.

### E4 — Alerta de teste no DB de produção
- `tests/core/conftest.py:9` — `from app import app, _core_registry` → roda `init_db()` real.
- `core/alerts/alert_engine.py` — `AlertEngine(db_path=…)` grava `alert_rules`/`alerts` no path default.
- DB real `data/war_room.sqlite`: 24 alertas CRIT (`Maint-Device status=0 == 0`, `Diag-Device`, `Test-History-Rec`, `Health-Listed`…).

**Fix proposto (P1):** isolamento de DB nos testes — `monkeypatch` de `DB_PATH`/`get_db` para `tmp_path`, e/ou fixture `autouse` que troca `app.config` + `sqlite3.connect` para um arquivo temporário. Depois: **purge** dos alertas/rules de teste do DB real (script de limpeza idempotente).

### E5 — Pool Luck 0%
- `app.py:2483` — `pool_luck_pct = (expected_wslb / wslb * 100.0) if wslb else 0.0`; com `cur_hr=0` o `if` interno nem roda → `luck` sem `pool_luck_pct` → UI `0.0%`.

**Fix proposto (P2):** sem dados → `None` (UI mostra `—`); neutro com rodada sem blocos. Quando `expected_wslb`/`wslb` inválidos, não emitir `0`.

### E6 — Profitability $0 / Break-even —
- `services/settings.py:14` — `cost_mode: "none"` default.
- `app.py:2550` — `if cur_hr > 0 and net_hr > 0:` (tudo dentro).

**Fix proposto (P2):** (1) depender de E1 para ter `cur_hr`; (2) quando `cost_mode="none"`, mostrar `$0` com tooltip "configure energy cost" (já existe link) e **nunca** `—` sem explicação; (3) adicionar default inteligente: se devices reais reportam watts, auto-set `cost_mode="power"`.

### E7 — Add Device / Seed Test
- `axe_fleet/routes.py:433` — `if os.environ.get("DEBUG_MOCK") != "1": return 403`.
- Sem agente local: `POST /api/axe-fleet/devices` precisa de IP alcançável via AxeOS.

**Fix proposto (P2/P3):** UI deve esconder/desabilitar "Seed Test" quando `DEBUG_MOCK` off (expor flag no `/api/axe-fleet/status`); arquitetura de agente local (Fase 3) para discovery ARP/`/24`.

### E9 — Best Diff all-time
- ✅ **Já resolvido no código atual**: `app.py:1282 _restore_all_time_best_diff()` + `:1303 _persist_all_time_best_diff()` (tabela `settings`/`best_diff_history`). O log `BEST_DIFF_BUMP (first)` foi o primeiro bump do processo — a persistência existe. **Nada a fazer** além de teste de restart.

### E10 — Wallet exibida ≠ `.env` (não é bug)
- A dashboard exibe `bc1qar0srr…wf5mdq` enquanto `.env` tem `bc1qpc3832…`. A causa é `_load_persisted_address()` (`app.py:1120`) restaurando `_wallet_address` do settings — **comportamento esperado** (a wallet conectada via UI vence). Não gastar squad investigando isso.

---

## 3. Priorização (Impacto × Esforço)

| Prioridade | Item | Impacto | Esforço |
|---|---|---|---|
| **P0** | E4 — Isolar DB de testes + purge de alertas mock | Alto (confiança) | M (fixture + script) |
| **P0** | E3 — Dedup estável do timeline | Alto (UX) | S (10 linhas) |
| **P1** | E1 — Derivação de hashrate por shares | **Crítico** (destrava tudo) | M |
| **P1** | E2a — Params/auth de providers (NiceHash `?algorithm&market`, MRR creds; Braiins OK) | Alto (market real) | M |
| **P1** | E2b — Unidade TH/s→H/s no market | Alto (dado errado) | S |
| **P2** | E5 — Pool luck neutro sem dados | Médio | S |
| **P2** | E6 — Cost model default + tooltips | Médio | S |
| **P2** | E7 — UI aware de DEBUG_MOCK | Médio | S |
| **P3** | Agente local de descoberta (Fase 3) | Alto | L |

---

## 4. Pipeline de Execução (Fases)

### Fase 0 — Baseline (✅ concluída neste documento)
- Forense + benchmarks registrados na seção 2.

### Fase 0.5 — Higiene crítica (P0) · Squad Alpha+Security
- [ ] 0.5.1 Isolar DB nos testes (`tests/core/conftest.py`, `tests/conftest.py`).
- [ ] 0.5.2 Script de purge idempotente: `DELETE FROM alerts WHERE device_id IN (SELECT … test devices)` + remoção de `alert_rules` com nome `Test-*`.
- [ ] 0.5.2b Mitigação rápida: honrar `show_test_alerts` (`app.py:1113`, default `"0"`) no filtro de `/api/alerts` — esconde alertas sintéticos enquanto o purge roda.
- [ ] 0.5.3 `static/app.js:1154` — id estável do timeline (hash de `ts|type|message`).
- **Critério de aceite:** `pytest` com DB temporário (sem tocar `war_room.sqlite`); dashboard sem alertas de teste após purge; timeline sem duplicados em 60s de SSE.

### Fase 1 — Revivendo os dados reais (P1) · Squad Beta+Gamma
- [ ] 1.1 Derivar hashrate por shares (`workSinceLastBlock`, SHARE_FOUND) quando pool reporta 0. Propagar para `worker_hashrate` do snapshot e KPI.
- [ ] 1.2 Corrigir NiceHash (`?algorithm=SHA256&market=0` em `tools.py:31`) + credenciais MRR do settings; **Braiins já OK** (backtest 2026-08-01). Fallback **explícito** (badge "FALLBACK" em vez de ESTIMATED silencioso).
- [ ] 1.3 Corrigir unidade no market (TH/s → H/s).
- **Critério de aceite:** com shares recentes, `kpi-hashrate` > 0; market mostra ≥2 offers reais com badge correto; `fmt.hashrate(1e12) === '1.00 TH/s'` (teste JS novo).

### Fase 2 — Lógica correta (P2) · Squad Gamma+Delta
- [ ] 2.1 Pool luck neutro (`None` → `—`).
- [ ] 2.2 Cost model: auto-default e tooltips claros.
- [ ] 2.3 UI aware de `DEBUG_MOCK` (esconder Seed Test).
- **Critério de aceite:** E2E + JS tests verdes; nenhum `—` sem tooltip de explicação.

### Fase 3 — Arquitetura (P3) · Squad Beta+Gamma+Ops
- [ ] 3.1 **Agente local** (Docker/Exe) com ARP scan `/24`, poll via API AxeOS, batch compactado via WebSocket a cada 30s → resolve "não consigo adicionar aparelhos" atrás de CGNAT/VPN.
- [ ] 3.2 Telemetria interna: health-check `/api/v1/status` por integração externa (blockchain_api, exchange_api, pool_stratum) + selo "Dados em Cache" quando fallback.
- **Critério de aceite:** adicionar miner por descoberta automática; status endpoint retorna online/offline por integração.

### Fase 4 — Pesquisa top-tier (Contínuo) · Squad Epsilon
- [ ] Benchmarking de features (GitHub/BitcoinTalk/Reddit): ASIC boost (Braiins OS+/VNish), eficiência J/TH por device, latency/ping por pool (stale share ratio), hardware errors >1% → alerta.
- [ ] Validar ou remover o legacy session-work heuristic com shares reais; não tratá-lo como probabilidade, confiança ou saúde.

---

## 5. Plano de Backtest & Validação (cada fix tem prova)

| Fix | Como provar |
|---|---|
| E4 | Rodar suíte completa; `sha256sum data/war_room.sqlite` antes/depois idêntico |
| E3 | Script: abrir `/api/stream` 30s, contar eventos WORK_DELTA com mesmo `(ts,type,msg)` = 1 |
| E1 | Injetar `workerData` mock com `hashrate="0"` + `lastSubmission` recente → KPI > 0 via shares |
| E2 | `curl` real nas 3 APIs; market render com ≥2 offers reais; teste JS de formatação |
| E5 | Snapshot sem `wslb` → `luck.pool_luck_pct is None` |
| E6 | `cost_mode="none"` → `cost: $0` + tooltip; com `power` → valor > 0 |
| E8 | Restart do processo → `all_time_best_diff` restaurado (teste de integração existente) |

---

## 6. Delegação (Squads)

| Módulo | Squad | Tarefa | Critério de aceite |
|---|---|---|---|
| Core API | Alpha | E1 derivação por shares | KPI > 0 com shares recentes |
| DB/Tests | Alpha+Security | E4 isolamento + purge | DB prod intacto após pytest |
| HashMarket | Beta | E2 URLs/auth/unidade | ≥2 offers reais |
| Frontend | Delta | E3 dedup, E5/E6 tooltips | E2E verdes, sem duplicados |
| Arquitetura | Gamma+Ops | E7/3 agente local | Discovery automático |

---

## 7. Cronograma alvo

- **Dia 1-2:** Fase 0.5 (P0) — higiene.
- **Dia 3-6:** Fase 1 (P1) — hashrate real + market real.
- **Dia 7-10:** Fase 2 (P2) — lógica correta.
- **Dia 11-15:** Fase 3 (P3) — agente local + observabilidade.
- **Contínuo:** Fase 4 — research/features.

> **Veredicto do Chefe:** "O Fênix v1 era diagnóstico de sintomas. Este pipeline é a cura da doença — e cada cura tem um exame de sangue (backtest) antes de ser declarada curada."
