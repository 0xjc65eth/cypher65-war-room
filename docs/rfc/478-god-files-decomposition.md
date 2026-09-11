# RFC — Decomposição dos god files (`static/app.js` 13k / `app.py` 9.4k)

> Issue #478 · auditoria enterprise 2026-09-10 (achado M9) · Frontend + Backend
> Status: **APROVADO** (PR #488) — **Opção A** ratificada pelo mantenedor.
> Execução em andamento — frontend: PR 1 (build + extração do core `fmt`/`escape`) = Issue #489 (PR #491 · mergeada).
> Achado do PR 1: o espelho do `fmt` no harness divergia do fonte e escondia 3 
> defeitos reais de produção — corrigidos na Issue #490 (PR 2 do frontend).
> Backend: PR B1 (admin gate + `/api/admin/*`) = Issue #495 — 300 linhas movidas
> para `routes/admin_routes.py`, `url_map` idêntico, gate re-exportado por `app.py`.
> Achado do B1: `/api/admin/sessions` não usa o gate — Issue #496, **corrigida**
> (PR #498: a rota passa a usar `_admin_request_allowed()`, sem um PR-B de
> extração).
> Backend: PR B2 (SSE fan-out) = Issue #499 — `_sse_clients` +
> `broadcast_snapshot()` + `GET /api/stream` movidos para `services/sse.py`,
> `url_map` idêntico (178 regras).
> Backend: PR B3 (snapshot assembly) = Issue #501 — correção de premissa: o
> código **não** estava em `app.py` e sim em `services/user_polling.py`; a cache
> global + a camada de fetchers + `_build_snapshot` foram para
> `services/snapshot_assembly.py` (user_polling: 1.606 → 1.152 linhas).
> Backend: Issue #508 (sub-issue do B4) — `get_db()` passa a ser definido em
> `services/bootstrap.py` e `services/db.py` vira re-export (uma implementação
> só); o import de telemetria virou tardio dentro do `init_db()` para não fechar
> ciclo. A parte "reconciliar `config.DB_PATH` × `app.DB_PATH`" da issue era
> **premissa falsa** (a linha 27 é do `config.py`; o `app.py` já importa de lá).
> Backend: PR B4 (DB bootstrap) = Issue #507 — `SCHEMA_VERSION`,
> `_record_schema_version`, `init_db()` (576 linhas) e `purge_old()` para
> `services/bootstrap.py`; `app.py` 9.084 → 8.444 linhas. Achado: o `get_db` do
> `app.py` era uma **duplicata idêntica** de `services.db.get_db` — eliminada.
> **Postmortem da trilha backend: [`478-postmortem.md`](./478-postmortem.md)**
> (Issue #511) — divergências plano × realidade, achados por PR e lições
> acionáveis para os PRs de frontend 2–6.
> **Alerta ao executar o PR 2 (Market):** a descrição "orderbook, rent offers"
> desta tabela **não corresponde ao código** (não existe orderbook); o cluster é
> o grid de venues do `/api/market/*` + `market_data.offers`, espalhado em 4
> regiões disjuntas com o domínio Admin inteiro entre duas delas. Detalhes no
> postmortem, §7.

## 1. Contexto e problema

| Arquivo | Linhas | Consequência |
|---|---|---|
| `static/app.js` | 13.062 | Escopo global único; 171 `innerHTML` vs 294 `escapeHtml`; qualquer mudança de UI arrisca colisão de nome e regressão em domínio alheio |
| `app.py` | 9.435 | Bootstrap, SSE fan-out, snapshot assembly, gate de admin, licenças e rotas no mesmo módulo — todo PR de produto toca o monólito |

O objetivo **não** é reescrita: é extração mecânica e incremental, um domínio por PR, sem mudança de comportamento. O guard DOM (GUARD_REPORT por PR) é a régua: superfície XSS não pode crescer durante o split.

## 2. Restrições descobertas (investigação de 2026-09-10)

1. **Cache-bust single-file**: `dashboard.html` carrega `<script src="/static/app.js?v63" defer>` — uma tag, uma versão. Multi-arquivo exige bump de versão em todas as tags a cada PR (ou passos de build — rejeitados: custo $0 e zero-toolchain são princípios do repo).
2. **Harness JS core não importa o app.js**: `tests/test_app_js_core.js` **espelha** os helpers puros (re-implementações com o mesmo contrato) e `check_frontend.sh` roda `node --check static/app.js` — ambos assumem **um arquivo**.
3. **Sem bundler**: nenhuma build step hoje; manter assim.
4. **Contrato do backend é estável**: `routes/` já existe como padrão de extração provado (blueprints), e os guards DOM/mobile-XSS ignoram fronteiras de arquivo — operam por regex de conteúdo.

## 3. Estratégia proposta

### 3.1 Frontend — "concatenated modules" (zero build, zero risk de runtime)

Convencão por comentário-bloco + ordem de inclusão controlada. Duas opções tecnológicas:

- **Opção A (recomendada)**: um único `app.js` **gerado** por concatenação (`static/src/*.js` → `static/app.js`) via script `scripts/build_app_js.cjs` (Node puro, ~40 linhas, sem dependências), rodado no pre-commit e validado no CI por `git diff --exit-code` pós-build. Preserva: single `<script>` tag, `node --check` direto, harness existente, cache-bust `?v64+`.
- **Opção B**: múltiplos `<script src>` com convenção de namespace por arquivo (`window.C65.market = {...}`). Simples, mas multiplica tags de cache-bust e permite dependência implícita de ordem de carregamento escondida.

**Decisão pedida**: A vs B. Ambas mantêm escopo global (refactor puro); módulos ES `type="module"` ficam explicitamente fora do escopo (mudaria semântica de `defer` + this + hoisting — não é extração mecânica).

Ordem de extração (uma PR por domínio, cada uma ≤ ~1500 linhas movidas):

| PR | Domínio | Conteúdo aproximado |
|---|---|---|
| 1 | Infra de build + `fmt/escape` | ✅ #489 (PR #491) — `build_app_js.cjs`, `static/app.js` vira artefato gerado; a suíte core passa a carregar os helpers puros **do fonte** via `loadFragment()`, eliminando o drift do espelho |
| 1b | Correção dos defeitos revelados pelo PR 1 | ✅ #490 — `fmt.age` (`0h ago` para 1h-24h), `fmt.secsToHuman(null)` (TypeError) e `fmt.pct(null)` (`0.00%`) |
| 2 | Market | ✅ #513 — **premissa da tabela corrigida**: não existe `orderbook` no código (zero ocorrências em `static/`); o domínio real é o grid de venues do `/api/market/*` + `market_data.offers` + BUY afiliado + tendência 7d, e ele **não é contíguo** — estado, grid/render e controles/tendência estão em 3 regiões disjuntas com o domínio Admin (~1.050 linhas) e Decision Matrix/Command Center entre elas. Foram para `static/src/45-market.js` (455 linhas): `_mktFilter`…`_mktInstitutional`, `_fmtBtcPerTh`/`_mktUsdPerTh`/`_mktSourceLabel`/`_mktBestIndex`, `MKT_RENDER_CAP`/`_mktRenderCap`/`sortMarketVenues`/`renderMarketGrid` (+ `venueFreshness` aninhada), `renderMarket`, `initMarketControls`, `buildMarketTrendDatasets`/`loadMarketTrend`. `40-app-logic.js` 12.666 → 12.236 linhas. **Prova de movimento mecânico**: `static/app.js` gerado é uma permutação do anterior — 0 linhas perdidas, 25 adicionadas (todas comentário). Achado: o harness JS ainda espelha helpers do Market e carrega uma **suíte legada** do card grid substituído pelo redesign institucional (tratado à parte, Issue #515) |
| 3 | Rentals | P/L, worst-rig leaderboard, sweep/advisory UI |
| 4 | Fleet/AXE | device cards, telemetria, comandos remotos |
| 5 | Terminal/SSE | event stream, live terminal, reconexão |
| 6 | Alerts/Auto-Pilot | regras, cooldowns, arming UI |

### 3.2 Backend — continuar o padrão `routes/` + extrair módulos de domínio

O padrão já existe (`routes/*.py` com blueprints) — o RFC o estende:

| PR | Extração | De `app.py` para |
|---|---|---|
| B1 | Admin gate + licenças | ✅ #495 — gate `_admin_request_allowed` + 10 rotas `/api/admin/*` → `routes/admin_routes.py` (blueprint `admin_bp`), `app.py` re-exporta o gate. `issue_license` já vivia em `services/licensing.py`: nada a mover. Achado: `/api/admin/sessions` sem gate → #496 ✅ corrigida (gate aplicado, conjunto de rotas sem gate agora vazio) |
| B2 | SSE fan-out | ✅ #499 — `_sse_clients` + lock, `broadcast_snapshot()` e `GET /api/stream` → `services/sse.py` (blueprint `sse_bp`, sem `url_prefix`), `app._broadcast_snapshot` re-exporta o MESMO objeto. `url_map` provado idêntico (178 regras, mesmo path/método) e o `import queue` do `app.py` saiu junto. O módulo nasceu com contrato próprio (11 testes) — antes o SSE tinha **zero** cobertura, porque a única régua era um navegador |
| B3 | Snapshot assembly | ✅ #501 — **premissa corrigida**: a origem é `services/user_polling.py`, não `app.py` (o `app.py` só importava `_build_snapshot`). Foram para `services/snapshot_assembly.py`: cache global LRU + `_get_global`/`_update_global`/`_cached_user_fetch`, constantes de fetch, `btc_price_cache`, `_fetch_json`/`_fetch_text`, os 6 `_fetch_global_*`, `_fetch_user_data`/`_fetch_account` e `_build_snapshot` (528 linhas). `user_polling.py` 1.606 → 1.152 linhas e re-exporta os 24 nomes. **Caveat de monkeypatch**: o fetch layer resolve os nomes nos globals do módulo novo — quem patcheava `services.user_polling._fetch_*` passou a mirar `services.snapshot_assembly` (3 arquivos de teste retargetados, um deles passava *vacuamente* sem interceptar) |
| B4 | DB bootstrap/schema | ✅ #507 — `SCHEMA_VERSION` + `_record_schema_version` + **`init_db()` (576 linhas: tabelas, ALTERs guardados por `PRAGMA table_info`, índices, pragmas e o carimbo da revisão)** + `purge_old()` → `services/bootstrap.py` (678 linhas, sem importar `app`). Schema provado **idêntico** antes/depois (73 objetos no `sqlite_master`, mesmo SQL) e idempotente. O item **“WAL”** do RFC era o `get_db()` — que existia **duplicado**: `app.get_db` ≡ `services.db.get_db` (mesma expressão de fallback `os.environ.get("DB_PATH", "data/war_room.sqlite")`, mesmos pragmas). A duplicata morreu: `app.get_db is services.db.get_db`, uma implementação só. `app.py` 9.084 → 8.444 linhas |

Regra dura: **cada PR-B mantém o gate de cobertura 80% e não pode reduzir a cobertura de `app.py`** (linhas movidas continuam cobertas nos novos módulos — import re-export temporário em `app.py` permite migração sem big-bang).

Mecanismo fixado no B1 (#495): o módulo extraído entra no `--cov` do `ci.yml` (`--cov=routes.admin_routes`). O código sai de `app.py` mas **não** sai da régua — o conjunto medido continua sendo o mesmo, então o TOTAL não pode "melhorar por subtração". Cada PR-B acrescenta o módulo novo da vez ao mesmo `--cov`.

Nuance fixada no B2 (#499): se o destino já está dentro de um `--cov` agregado, **nada** é acrescentado — `services/` é medido inteiro por `--cov=services`, então `services/sse.py` (B2) e `services/snapshot_assembly.py` (B3) nasceram na régua. O `--cov` explícito por arquivo só é necessário para módulos **fora** de `services/` (caso de `routes.admin_routes` no B1).

## 4. Guardrails por PR (checklist de aceite)

- [ ] `node --check static/app.js` (ou `python -m flake8` no módulo novo) verde
- [ ] `tests/test_app_js_core.js` 100% verde (Opção A: passa a validar contrato extraído do fonte)
- [ ] `npm run check:frontend` completo verde
- [ ] GUARD_REPORT: superfície XSS (counts TL/concat/innerHTML) não cresce
- [ ] pytest completo verde, cobertura global ≥ 83% (não menor que a anterior)
- [ ] Nenhuma mudança de: rotas, ids DOM, contratos de fetch, formato de snapshot
- [ ] Diff do PR ≤ ~1500 linhas movidas (revisável em uma passada)

## 5. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Ordem de concatenação muda hoisting/ TDZ | Opção A mantém ordem atual dos blocos; `node --check` + suíte e2e pegam quebra |
| Drift entre arquivo gerado e fontes | CI roda build + `git diff --exit-code` (fonte des-sincronizada bloqueia merge) |
| Colisão de nomes entre domínios durante a migração | Nomes não mudam nesta fase (refactor puro); renames ficam para fase posterior opt-in |
| Cobertura cai com a mudança de módulo | Import re-export + `--cov` por módulo novo em cada PR-B |
| PRs interferindo (front × back) | Frontend e backend alteram arquivos disjuntos; sequência Front 1→6 e Back 1→4 pode rodar em paralelo |

## 6. Fora de escopo (explícito)

- Migrar para bundler/TS/ES modules
- Renomear identificadores ou reorganizar escopo global
- Mudar o protocolo SSE ou contratos de API
- Touch em `mobile/` (já modularizado; Knip + Biome cobrem)

## 7. Critério de sucesso

`static/app.js` torna-se artefato gerado; os domínios vivem em `static/src/*.js` de ≤ ~1500 linhas cada; `app.py` cai para ≤ ~4000 linhas (bootstrap + glue), com cada domínio em módulo testável isoladamente. Tudo isso **sem um único comportamento novo** entre PRs.
