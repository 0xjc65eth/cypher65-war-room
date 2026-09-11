# RFC — Decomposição dos god files (`static/app.js` 13k / `app.py` 9.4k)

> Issue #478 · auditoria enterprise 2026-09-10 (achado M9) · Frontend + Backend
> Status: **APROVADO** (PR #488) — **Opção A** ratificada pelo mantenedor.
> Execução em andamento: PR 1 (build + extração do core `fmt`/`escape`) = Issue #489 (PR #491 · mergeada).
> Achado do PR 1: o espelho do `fmt` no harness divergia do fonte e escondia 3 
> defeitos reais de produção — corrigidos na Issue #490 (PR 2 do frontend).

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
| 2 | Market | orderbook, rent offers, BUY button, `_mktRenderCap` |
| 3 | Rentals | P/L, worst-rig leaderboard, sweep/advisory UI |
| 4 | Fleet/AXE | device cards, telemetria, comandos remotos |
| 5 | Terminal/SSE | event stream, live terminal, reconexão |
| 6 | Alerts/Auto-Pilot | regras, cooldowns, arming UI |

### 3.2 Backend — continuar o padrão `routes/` + extrair módulos de domínio

O padrão já existe (`routes/*.py` com blueprints) — o RFC o estende:

| PR | Extração | De `app.py` para |
|---|---|---|
| B1 | Admin gate + licenças | `_admin_request_allowed`, `issue_license`, rotas `/api/admin/*` → `routes/admin_routes.py` + `services/licensing_routes.py` (após PR #486, o gate tem testes próprios — momento ideal) |
| B2 | SSE fan-out | `_sse_clients`, broadcast, `/api/stream` → `services/sse.py` |
| B3 | Snapshot assembly | `_build_snapshot` e agregações → `services/snapshot_assembly.py` (o `poll_compute.py` de 100% de cobertura prova o padrão) |
| B4 | DB bootstrap/schema | init_db, índices, WAL, purges → `services/bootstrap.py` |

Regra dura: **cada PR-B mantém o gate de cobertura 80% e não pode reduzir a cobertura de `app.py`** (linhas movidas continuam cobertas nos novos módulos — import re-export temporário em `app.py` permite migração sem big-bang).

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
