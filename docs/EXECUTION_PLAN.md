# CYPHER65 War Room — Plano de Execução Oficial

> **Base:** auditoria de verificação real do repositório (clone `0xjc65eth/cypher65-war-room`),
> conferida item a item contra `app.py`, `services/`, `routes/`, `axe_fleet/`, `tests/` e pesquisa web.
> **Status atual (2026-08-06):** Fases 1–6 concluídas ✅.

---

## 0. Correção de rota do plano anterior (NÃO FAZER)

**Ação anulada:** o plano anterior recomendava `register_blueprint(dashboard_bp)` e
`register_blueprint(export_bp)` em `app.py` para "corrigir 404 de painéis em branco".

**Veredito da auditoria (FALSO):** todas as 9 rotas citadas (`/api/snapshot`, `/api/history`,
`/api/profitability`, `/api/halving`, `/api/mempool_fees`, `/api/leaderboard`,
`/api/diff_events`, `/api/share_timeline`, `/api/event_stats`) **já existem diretamente em
`app.py`** (ex.: L2834, L2904, L2953) e **retornam HTTP 200** ao vivo.

**Risco de executar a ação antiga:** registrar `dashboard_bp`/`export_bp` criaria **rotas
duplicadas** → conflito no Flask (`AssertionError: View function mapping is overwriting`) ou
comportamento imprevisível. A ação correta é **arquivar o código morto** (Fase 2), não registrá-lo.

---

## ✅ Fase 1 — Remover dados MOCK de produção (P0 · urgente) — CONCLUÍDA

> **Status:** implementado. `_auto_seed_axe_fleet()`, `_auto_seed_core_devices()` e
> `seed_test_devices()` todos gateados por `DEBUG_MOCK` (config.py). Purges de
> cleanup (`_purge_seed_marked_devices`, `_purge_core_seed_marked_devices`,
> `_purge_test_devices`) removem leftovers no boot. Testes: `test_seed_gating.py`.

**Problema (original):** `app.py` injetava devices falsos na inicialização sem nenhum gate:
- `_auto_seed_axe_fleet()` — def L501, call L762 — cria **4 devices mock** (3 online + 1 offline,
  com 10 pontos de telemetria histórica) quando o registry está vazio.
- `_auto_seed_core_devices()` — def L639, call L773 — idem para o registry core.
- `axe_fleet/routes.py:455` — `seed_test_devices()` — mesma lógica no blueprint.

**Impacto:** em qualquer deploy real sem mineradores, o dashboard exibe **telemetria
inventada como se fosse real** — exatamente o oposto da promessa "Honest Telemetry".

**Tarefas:**
1. **Reutilizar a flag existente `DEBUG_MOCK`** (`config.py:28`, hoje morta) como gate do seed
   — zero config nova, e ainda resolve a flag órfã listada como P1. Gating:
   `if getattr(config, 'DEBUG_MOCK', False) or os.environ.get('DEBUG_MOCK') == '1'`.
2. Gate os dois `_auto_seed_*` em `app.py` (def L501/L639, calls L762/L773) com essa flag.
3. Proteger `seed_test_devices()` em `axe_fleet/routes.py:455` com o mesmo flag (nunca expor via API pública).
4. **Auditar e atualizar os testes existentes que dependem do seed** — `tests/test_axe_routes_integration.py`
   e `tests/test_axe_routes_remote.py` podem ter asserções esperando os 4 devices mock;
   migrar para fixture explícita de seed (ou `monkeypatch`) em vez de depender do bootstrap global.
5. Confirmar que a UI tem **empty state explícito** quando a frota está vazia:
   - `static/app.js:1844` já seta badge `'NO DEVICES'` quando `total === 0` — validar fluxo completo.
   - Painel Fleet deve mostrar "Nenhum minerador conectado. Adicione via IP." com CTA, nunca `—`/`?`.
6. Escrever testes: (a) com `DEBUG_MOCK=0` e registry vazio → nenhum device criado; (b) com `DEBUG_MOCK=1` → 4 devices mock criados (para dev).

**Critério de aceite:** com DB vazio e sem `DEBUG_MOCK`, `/api/axe-fleet/health` retorna
`{devices: [], fleet_stats: {total: 0}}` e a UI mostra o empty state orientativo.

**Validação:**
```bash
venv/bin/python3 -m pytest tests/test_axe_routes_integration.py tests/test_axe_routes_remote.py -q --tb=short
node tests/test_app_js_core.js
curl -s http://127.0.0.1:8765/api/axe-fleet/health
```

**Risco de regressão:** telas que dependiam do seed para "demonstração" ficarão vazias —
mitigado pelo empty state e pelo modo `DEBUG_MOCK=1` documentado no `run.sh` de dev.

---

## ✅ Fase 2 — Liquidar código morto (P1 · baixo risco) — CONCLUÍDA

> **Status:** implementado. Headers `⚠️ DEPRECATED` nos dois arquivos.

**Problema (original):** `routes/dashboard_routes.py` (15 rotas) e `routes/export_routes.py` (3 rotas)
**nunca são importados** em lugar nenhum (grep: zero referências) e duplicam rotas já
definidas em `app.py`. São dívida de manutenção: duas implementações divergentes da mesma API.

**Decisão (resolve contradição com Fase 6):** os arquivos **não são deletados** — são mantidos
parados como referência de assinatura e reutilizados na Fase 6. Em vez de `git mv` (que criaria
dois arquivos enredados), a Fase 2 apenas **documenta o estado morto** e adiciona um header
`# DEPRECATED — rotas duplicadas em app.py; preenchido na Fase 6 (EXECUTION_PLAN.md)` nos dois arquivos.

**Tarefas:**
1. Adicionar header de depreciação em `routes/dashboard_routes.py` e `routes/export_routes.py`
   (sem mudar nenhuma rota — zero risco de quebra).
2. Registrar o estado no README/docs para que ninguém edite os dois arquivos até a Fase 6.
3. Verificar com grep que nenhum import quebra (deve permanecer zero):
   ```bash
   grep -rn 'dashboard_routes\|export_routes' app.py routes/ services/ axe_fleet/ core/ --include='*.py'
   ```

**Critério de aceite:** suíte Python + JS + E2E verdes, zero imports quebrados, diff limpo.

**Validação:**
```bash
venv/bin/python3 -m pytest tests/ -q --tb=line
node tests/test_app_js_core.js
npx playwright test --project=chromium --workers=1 --reporter=line
```

**Risco de regressão:** praticamente nulo (código não referenciado). Git preserva o histórico.

---

## ✅ Fase 3 — Hardening do Hash Market (P1) — CONCLUÍDA

> **Status:** implementado. Cache TTL 60s/15s (`_FETCH_CACHE` + `_cached_fetch`),
> retry/backoff linear (1×, 0.15s base), `source`/`estimated` no `NormalizedOffer`,
> badge ESTIMATED no frontend, provider KissMyHash removido, real-first sort key.

**Problemas (originais):**
- KissMyHash **não tem API pública** (research web: é frontend/agregador). O endpoint antigo
  (`/api/v1/market`) morreu (404) e a nova API exige autenticação (`x-api-key` — `/api/hashrate`,
  `/api/quote`). O provider e o fallback NiceHash+10% foram **removidos** (fabricavam uma cotação
  ESTIMATED que poluía o grid). Reintegração = feature nova com a API autenticada + credencial.
- Sem cache dedicado → risco de estourar rate limit (429) das 3 APIs reais.

**Tarefas:**
1. Adicionar cache TTL (ex.: `functools.lru_cache` + timestamp ou `cachetools.TTLCache` com 60-120s)
   em `services/hashrate_market.py` para os fetchers Braiins / MRR / NiceHash.
2. Rotular cada oferta com `source` (braiins / mrr / nicehash / parasite) na resposta da API.
3. No frontend, exibir badge de origem + "(estimado)" quando `estimated == true` (parasite).
4. Implementar backoff simples nos fetchers (retry com 429/5xx).
5. Confirmar contrato com a UI: `renderMarket()` já usa `price_per_th_day` + derive `is_best`
   (client-side) — manter alinhado.

**Critério de aceite:** 3 requisições consecutivas ao market em < 2s (cache ativo),
nenhum 429 em loop, UI distingue cotação real de derivada.

**Validação:**
```bash
venv/bin/python3 -m pytest tests/test_market_intelligence.py tests/test_opportunity_engine.py -q --tb=short
curl -s http://127.0.0.1:8765/api/market | python3 -m json.tool | head -40
```

**Risco de regressão:** cache pode servir dado levemente defasado — aceitável para 60-120s;
sem o cache, rate limit quebra o módulo.

---

## ✅ Fase 4 — Auditoria e decisão de Auth (P2) — CONCLUÍDA (B1 + B2)

> **Status:** implementado. B1: login multi-key (`TENANT_API_KEYS`), `sub=tenant_id`,
> `resolve_tenant_for_api_key()`. B2: tabelas `tenants`/`users`, `tenant_id` em
> alerts/automations/core, `@require_tenant` nas rotas, `test_tenant_b2_isolation.py`.

**Fato verificado (original):** `services/auth.py` era **single-admin**.
Não existe `tenant_id`, `user_id` ou isolamento de dados por conta. O requisito
"multi-usuário com isolamento" do go-live **não está implementado**.

**Decisão (aprovada — Opção B em 2 etapas):** verificado no código que a base de
isolamento **já existe esboçada** no axe_fleet — `_get_tenant_id()`/`require_tenant` em
`axe_fleet/routes.py`, filtro por `tenant_id` em `axe_fleet/registry.py`, colunas
`tenant_id` em `axe_devices`/`axe_telemetry` (migration em `app.py`) e isolamento de
snapshot por sessão (`services/session_manager.py`). Portanto a Opção B custa menos que
as 2-3 semanas estimadas originalmente. Estratégia em 2 etapas:

**Etapa B1 (implementada ✅):** login multi-key com `sub=tenant_id` ativando o isolamento
que já existe no axe_fleet — sem tocar nos demais módulos.
- `config.py`: `TENANT_API_KEYS` (JSON dict tenant_id → api_key), com fallback para a
  `API_KEY` legada (tenant "default").
- `services/auth.py`: `resolve_tenant_for_api_key()`; `authenticate_with_api_key()` usa o resolver.
- `routes/auth_routes.py`: login emite `create_token(subject=tenant_id)` e expõe `tenant_id`
  na resposta; refresh preserva o `sub` original.
- `axe_fleet/routes.py`: `_get_tenant_id()` agora decodifica o Bearer token diretamente
  (via `verify_token`), então rotas protegidas só por `require_tenant` isolam por conta.
- `tests/test_tenant_auth.py`: resolver, login por tenant, refresh, `_get_tenant_id`
  Bearer e isolamento real do `DeviceRegistry` (A não vê devices de B).

**Etapa B2 (pós-go-live, planejada):** estender o isolamento aos demais módulos.
1. Modelo `users` no SQLite + tabela `tenants` (1 tenant = 1 usuário/equipe).
2. `require_tenant` aplicado às rotas de dados restantes (core, alerts, automations).
3. `tenant_id` nas queries de `core/`, `services/state.py` (além do axe_fleet).
4. Testes de isolamento completos: usuário A não vê dados do usuário B em todos os módulos
   (e2e ou integração).

**Critério de aceite:** dois usuários logados não compartilham nenhuma linha de dados; refresh não mistura contas.

**Validação:**
```bash
venv/bin/python3 -m pytest tests/ -q --tb=short -k "auth or session or token"
```

**Risco de regressão:** alto se feito às pressas — exige freeze de features durante a migração
(conforme pipeline de go-live Fase 1).

---

## 🔄 Fase 5 — Telemetria de devices (P2 · diferencial) — EM ANDAMENTO

> **Status (2026-08-06):** BitaxeAdapter completo (todos os campos). CgminerAdapter
> enriquecido com `fan_rpm`, `voltage`, `power`, `pool_status`, `pool` dict.
> `normalize_telemetry()` preenche `NOT_AVAILABLE`. Pendente: avaliação do `pyasic`.

**Pesquisa web (fonte: docs AxeOS/Braiins OS):**
- **AxeOS/Bitaxe (REST):** `GET /api/system/info` → power, voltagem ASIC+VR, temperatura ASIC+VR,
  hashrate 1m/10m/1h, fan RPM. `GET /api/system/statistics` (histórico, exige `statsFrequency>0`).
  `PATCH /api/system` → fan mode, core voltage, frequência (config remota).
- **Braiins OS (BOSminer):** `temps`, `fans`, `tunerstatus` (consumo/power limits), `tempctrl` — superset do cgminer.
- **cgminer (TCP :4028):** `summary`, `devs`, `pools`, `stats`, `version`.
- **Biblioteca `pyasic`** abstrai as firmwares — avaliar como camada do adapter.

**Tarefas:**
1. Auditar `core/adapters/bitaxe_adapter.py` e `cgminer_adapter.py` — quais campos do
   `/api/system/info` já são coletados vs. ausentes (chip temp, VR temp, hashrate 1h, stats).
2. Adicionar campos ausentes ao modelo `core/models/device.py` (com fallback `NOT AVAILABLE`).
3. Se `axe_fleet/connector.py` promete "controle sem agente local", confirmar que usa REST do
   AxeOS (stateless) e não depende de TCP do cgminer.
4. Avaliar `pyasic` para unificar os 3 firmwares (decisão de arquitetura, não obrigatória).

**Critério de aceite:** cada device expõe temperatura (ASIC + VR), voltagem, fan RPM,
hashrate 1m/10m/1h e pool status — ou `NOT AVAILABLE` explícito.

**Validação:**
```bash
venv/bin/python3 -m pytest tests/test_bitaxe_adapter.py tests/test_core.py -q --tb=short
```

**Risco de regressão:** schema novo pode quebrar `renderAxeCard` — alinhar contrato backend→frontend
num único passo.

---

## ✅ Fase 6 — Refactor do monólito (P3 · contínuo) — CONCLUÍDA

> **Status (2026-08-06):** `export_bp` migrado (3 rotas). `dashboard_bp` migrado
> (14 rotas: snapshot, history, diff_events, leaderboard, share_timeline,
> event_stats, halving, mempool_fees, profitability, network_share, milestones,
> workers, monte_carlo, proximity). Enriquecimento do snapshot extraído para
> `services/snapshot_enrichment.py::enrich_snapshot` (helper compartilhado —
> payload idêntico entre app.py e blueprint). `/api/alerts` é servido apenas
> por `alerts_bp` (cópia shadowed de app.py removida). Contrato `/api/history`
> preservado (chave `rows`). Fix do preview de automação (engine construído
> com db_path+safety_engine + devices reais do registry core).

---

## Ordem de execução recomendada (atualizada 2026-08-06)

| Período | Fases | Entregável | Status |
|---|---|---|---|
| Semana 1 | F1 (mock) → F2 (dead code) → F3 (cache market) | Dados honestos + módulos estáveis | ✅ |
| Semana 2 | F4 (auth) → **F5 (telemetria)** → **F6 (refactor)** | Base p/ go-live real | 🔄 |

**Regra:** nenhuma fase avança sem suíte verde (pytest + JS + E2E).

---

## Checklist final (alinhado ao go-live)

- [x] F1: `DEBUG_MOCK` gateado; zero devices fake em produção; empty states explícitos *(implementado: gate + purge de marcadores em app.py; rota `/test-devices` 403; 16 testes seed-gating; 660 pytest + 666 JS verdes)*
- [x] F2: `dashboard_routes.py`/`export_routes.py` deprecated (header + docs); zero código morto ativo *(implementado: docstrings DEPRECATED nos dois arquivos; nenhum import quebra)*
- [x] F3: cache TTL + labels de origem (braiins/mrr/nicehash/derived/estimado) na UI + backoff/retry nos fetchers *(implementado: `_FETCH_CACHE` TTL 60s/15s em `services/hashrate_market.py`; `source`/`estimated` no `NormalizedOffer` + badge ESTIMATED no frontend; retry linear 1x com backoff 0.15s em `_cached_fetch`; `_sync_market_prices_to_state` expõe `source`/`estimated`; 695 pytest + 684 JS verdes)*
- [x] F4: decisão auth documentada — **Opção B em 2 etapas**; B1 implementada (login multi-key `sub=tenant_id` + isolamento axe_fleet ativo, `tests/test_tenant_auth.py`); **B2 implementada** (tabelas `tenants`/`users`, `tenant_id` em alerts/automations/device, `@require_tenant` nas rotas core/alerts/device_control, `tests/test_tenant_b2_isolation.py`)
- [x] F5: telemetria completa por device com `NOT AVAILABLE` explícito *(implementado: BitaxeAdapter completo; CgminerAdapter com fan_rpm/voltage/power/pool_status; normalize_telemetry() preenche NOT_AVAILABLE)*
- [x] F6: export + dashboard routes migradas → blueprints *(implementado: export_bp (3 rotas) + dashboard_bp (14 rotas) registrados; rotas removidas de app.py; snapshot_enrichment.py extraído; /api/alerts deduplicado com alerts_bp; 1508 pytest + JS verdes)*
- [ ] Suítes: pytest + JS + E2E verdes a cada commit
