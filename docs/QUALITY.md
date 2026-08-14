# 🛠 QUALITY ENGINEERING — observabilidade, lint e testes

> Rodada de engenharia de qualidade. Regra de ouro CFO/CRO: **custo $0**.
> Tudo aqui é free-tier ou open source.

---

## 1. Observabilidade

| Camada | Ferramenta | Status | Como ativar |
|---|---|---|---|
| Erros/tracing | **Sentry** (free 5k errors/mês) | ✅ integrado (env-gated) | `SENTRY_DSN` + opcional `SENTRY_TRACES_SAMPLE_RATE` |
| Logs estruturados | **JSON stdlib** (`services/observability.py`) | ✅ novo (Issue #30) | `LOG_JSON=1` |
| Métricas operacionais | Admin CFO + `/api/admin/sessions` | ✅ existente | sempre ativo |
| APM completo | Datadog / NewRelic / OTel | ⚪ documentado | ver matriz abaixo |

### Matriz de decisão (custo $0)

- **Sentry** — free tier suficiente para erros + traces. Já integrado em `app.py`
  (inicialização condicional, nunca quebra boot).
- **Datadog / NewRelic** — trials/paid; **não adotados** (regra de ouro CFO).
- **OpenTelemetry** — SDK é grátis, mas exige collector/backend; caminho futuro:
  exporter OTLP apontando pro Sentry quando houver tração (Issue #22 gated).
- **Logs JSON** — `LOG_JSON=1` → um JSON por linha (`jq`-able), compatível com
  qualquer aggregator futuro (Loki, CloudWatch, Datadog agent).
- **Correlação por `request_id`** (Issue #124) — todo request HTTP e toda
  passada de worker (poll/sweep) emite um id curto (`req-*`, `poll-*`,
  `sweep-*`) no campo `request_id` de cada linha JSON, permitindo rastrear um
  erro de ponta a ponta (webhook → DB → alerta) mesmo com multi-tenancy e
  retries. O id é ecoado no header de resposta `X-Request-ID` para
  correlação client-side. Exemplo de filtro:

```bash
LOG_JSON=1 python app.py          # logs JSON estruturados
# correlacionar uma requisição específica:
LOG_JSON=1 python app.py 2>&1 | jq -c 'select(.request_id == "req-ab12cd34ef56")'
SENTRY_DSN=... python app.py      # Sentry ativo (traces 0.1 default)
```

---

## 2. Lint & qualidade de código

| Ferramenta | Escopo | Status | Gate? |
|---|---|---|---|
| **Biome** (Rust, lint+format JS/TS) | `mobile/` (TS) + `static/app.js` | ✅ configurado | CI check (advisory 1º) |
| **Knip** (dead code) | `mobile/` | ✅ knip.json | CI check (advisory) |
| **commitlint** | mensagens de commit | ✅ config | CI check |
| **mutmut** (mutation Python) | `core/` + `services/` | ✅ dev-dep + doc | manual (advisory) |
| **Stryker** (mutation JS) | `mobile/` utils/hooks | ✅ config | manual (advisory) |
| **arch-contract** (TS layers) | — | ⚪ N/A nesta stack | — |
| **bandit** (segurança estática Python) | Python | ✅ gate (Issue #125) — 0 MEDIUM/HIGH | ✅ blocking |
| **flake8** (bug-codes) | Python | ✅ gate via `.flake8` (F821/F541/E9) | ✅ blocking |
| **black** | Python | ✅ presente, backlog 11.5k linhas | ⚪ advisory → Issue #133 |

### Static security gates (Issue #125) — bandit + flake8 + black

O job `pytest + JS core` do CI BLOQUEIA o merge com os mesmos comandos
abaixo (escopo: `app.py helpers.py solo_mining.py services core axe_fleet
routes agents`):

```bash
make lint-sec     # bandit -ll + flake8 (.flake8) — blocking
# bandit -r services core axe_fleet routes agents app.py helpers.py solo_mining.py -ll -q
# flake8 app.py helpers.py solo_mining.py services core axe_fleet routes agents
```

- **bandit `-ll`** — falha em QUALQUER achado MEDIUM/HIGH. Status: **0 achados**
  (fixes reais aplicados na Issue #125: `subprocess` sem shell no
  `agents/solo_mining_advisor/cli.py` — B605 HIGH; 11× `# nosec B608`
  justificados por whitelist fixa em routes/registry/auto_pilot; timeout
  numérico garantido no `axe_fleet/connector.py` — B113).
- **flake8 (bug-codes)** — `.flake8` seleciona só `F821` (nome indefinido),
  `F541` (f-string sem placeholder) e `E9` (sintaxe). Pegou bug real:
  `json.JSONDecodeError` sem `import json` no `braiins_adapter.py`. O backlog
  de estilo (E501 etc.) NÃO é gate — ver `make lint`.
- **black** — ADVISORY: reporta o backlog (~11.5k linhas, 49 arquivos) sem
  bloquear. O gate vira blocking após o cleanup dedicado (Issue #133).

### Instalação / uso

```bash
# Biome (mobile) — lint + format em um passo (substitui ESLint+Prettier)
cd mobile && npx @biomejs/biome lint . && npx @biomejs/biome format .

# Knip — dead code no mobile
cd mobile && npx knip

# commitlint — mensagens Conventional Commits
npx commitlint --from HEAD~1

# mutmut — mutation testing no backend (Python)
SECRET_KEY=test-secret-0123456789 mutmut run --paths-to-mutate core/ services/probability.py
mutmut results   # surviving mutants = testes que não pegam o bug

# Stryker — mutation no mobile (escopo em utils/hooks — RN é lento)
cd mobile && npx stryker run
```

### Notas

- **Biome no `static/app.js`** (9500 linhas legado): rodamos com report
  (`--reporter=json`) sem `--write` para não reformatar código estável; o gate
  real do JS continua sendo `tests/test_app_js_core.js`.
- **arch-contract** é TypeScript-only e o backend é Python → documentado como
  N/A. Se o `mobile/` ganhar camadas (domain/application/infra), adotamos lá.
- **Stryker em React Native** é lento por natureza — escopo em funções puras
  (hooks/utils), rodar sob demanda, nunca no gate do PR.

---

## 3. Testes (unitário / integração / e2e)

| Camada | Ferramenta | Cobertura | Gate CI |
|---|---|---|---|
| Unit/integration (Python) | pytest | 2192 testes, `--cov-fail-under=76` | ✅ blocking |
| JS core (mirror do app.js) | node --test | 1261 testes | ✅ blocking |
| E2E (browser) | **Playwright** | specs chromium + mobile-chrome | ✅ job `e2e` |
| Cobertura pública | **Codecov** (free p/ repo público) | upload do coverage.xml | ✅ non-blocking |
| Guards DOM (XSS/ids) | `scripts/check-dom-regression.cjs` | ids duplicados + innerHTML sem escape | ✅ blocking |
| Guards XSS mobile (RN) | `scripts/check-mobile-xss.cjs` | WebView html/injectedJavaScript + eval + openURL `javascript:` | ✅ blocking |
| Frontend (combinado) | `scripts/check_frontend.sh` (Issue #62) | guards DOM + XSS mobile + JS core + **audit visual** (console/overflow/truncamento) | ✅ blocking job `frontend-audit` |

### Mapa de cobertura por módulo (Issue #123) — TOTAL 77%

Medição `pytest --cov` com o comando exato do CI (arquivo de dados isolado;
`coverage report -m` local reproduz). Financeiros/controle ≥80% primeiro
(regra de ouro do gate: dinheiro e devices nunca regridem em silêncio):

| Módulo | Cobertura | Notas |
|---|---|---|
| `core/safety/safety_engine.py` | **100%** | cooldown, rates, overrides (Issue #123) |
| `services/poll_compute.py` | **100%** | helpers puros extraídos do `_do_poll` (Issue #135) |
| `services/payments.py` | **96%** | checkout env paths; restam 4 stmts do webhook |
| `services/rental_performance.py` | **89%** | preço de mercado real em SQL, auto-exclusão, forecast |
| `services/licensing.py` | **89%** | — |
| `services/auto_pilot.py` | **84%** | collectors fail-closed (Issue #123) |
| `services/user_polling.py` | **73%** | sweep paths: famílias reco/risk/auto + exceções (Issue #135) |
| `app.py` | **57%** | 3009 stmts — o maior buraco (resto do poll/rotas) |

**Roadmap do gate (incremental, sem bloquear deploys no meio):**

```
2026-08-01  53%  → gate 45   (baseline)
2026-08-03  66%  → gate 65   (+108 testes)
2026-08-14  76%  → gate 75   (financeiros ≥80% — Issue #123)
2026-08-14  77%  → gate 76   (poll_compute 100% + sweep paths — Issue #135)  ← estamos aqui
próxima      ~80% → gate 80   (app.py + user_polling primeiro)
```

Margem deliberada de ~1pp (77% real vs gate 76) — absorve variação de
ambiente sem deixar o gate frouxo. Para o próximo degrau: `app.py` (57%,
3009 stmts — resto do `_do_poll`: profitability/milestones/event-stats) e
`services/user_polling.py` (73% — fetchers globais `_fetch_global_*`) são os
dois maiores buracos; extrair os próximos blocos de computação pura para
helpers testáveis (mesmo padrão do Issue #135) é o caminho de menor esforço
por stmt coberto.

### Codecov — ✅ ATIVO (Issue #38 → PR #42)

O CI gera `coverage.xml` e envia pro Codecov (repo público = free tier).
`fail_ci_if_error: false` — sem token o upload falha silencioso (não bloqueia
merge). Badge no README reflete a cobertura pública.

**Status real (confirmado em 3 vias):**

| Sinal | Antes | Depois |
|---|---|---|
| Upload v4 probe | 404 `Repository not found` | 400 validação → token reconhecido |
| CI log | `Upload queued ... failed: Repository not found` | `Upload queued for processing complete` ✅ |
| API Codecov | `active: False` | `active: True` |
| Badge README | `unknown` | **73%** (gate 65% batido) |
| Check do PR | — | **`codecov/patch`** em todo PR |

O que resolveu:

1. **Token correto** no secret `CODECOV_TOKEN` (via `gh secret set`, 36 chars).
2. **`slug: 0xjc65eth/cypher65-war-room`** no `codecov-action@v5` (`.github/workflows/ci.yml`)
   — o action nunca erra a detecção do repo.

#### Regenerar o token (só se o upload voltar a falhar)

1. app.codecov.io → Sign in with GitHub (conta dona do repo) → repo
   `cypher65-war-room` → **Settings** → **General** → **Repository Upload Token** → copie.
2. `gh secret set CODECOV_TOKEN` (no diretório do repo) — o step do CI já
   referencia `token: ${{ secrets.CODECOV_TOKEN }}`.
3. Re-disparar: `gh workflow run ci.yml --ref master` e conferir no log
   `Upload queued for processing complete` SEM `Repository not found`.

> **Render NÃO precisa do token** — o Render roda a app e nunca envia cobertura;
> o upload acontece só no GitHub Actions. Não commitar o segredo no render.yaml.

```bash
make test                        # pytest completo
node tests/test_app_js_core.js   # JS core
bash run-e2e.sh --file=dashboard.spec.js   # Playwright
node scripts/audit_ui.cjs --all  # auditoria visual (console/overflow/truncamento)
node scripts/check-dom-regression.cjs  # guards DOM (ids duplicados + XSS innerHTML)
node scripts/check-mobile-xss.cjs      # guards XSS mobile (React Native — WebView/eval/openURL)
```

### Guards DOM de regressão — `scripts/check-dom-regression.cjs`

Guards estáticos **blocking** no job `gate` do CI (Issue #58):

- **GUARD 1 — `id=""` duplicado em `templates/*.html`**: dois elementos com o
  mesmo id quebram `querySelector`/`getElementById` (o primeiro vence).
- **GUARD 2 — innerHTML com dados externos sem `escapeHtml`**: varre as DUAS
  sintaxes de injeção de string — interpolações `${...}` em template literals
  E concatenação com `'+'` fora deles (ex: `rows.map(x => '<td>' + x.msg +
  '</td>')`). Qualquer leitura de campo de registro externo (`a.category`,
  `m.tier`, `e.block_height`, `entry.worker`, `x.msg`, ...) sem `escapeHtml(...)`
  é FLAGGED — é o que transforma uma string de API/banco em vetor de XSS.
- **GUARD 2 (sinks estendidos, Issue #66)**: além do `innerHTML` inline, o guard
  varre também:
  - **`insertAdjacentHTML('pos', HTML)`** — o 2º argumento é um sink de HTML
    (mesmo allowlist). Se o argumento for um **identificador nu**
    (`insertAdjacentHTML('beforeend', rows)`), o guard segue a declaração
    `const rows = …` mais próxima (delimitada pela função) e varre o HTML que
    ela constrói — o feed de timeline do dashboard tinha `ev.id`/`ev.severity`/
    `ev.event_type` crus exatamente assim e era invisível para o guard antigo.
  - **`innerHTML`/`outerHTML` com RHS identificador-nu** (`el.innerHTML = rows`)
    — o mesmo follow de declaração fecha o blind spot de HTML pré-construído.
  - **builders locais** (`function _xHtml(...) { return … }`) — o corpo é
    varrido (interpolações `${…}` + concat em cada `return`/`const x = …`).
  - **`textContent` com markup HTML** — sink de TEXTO é seguro por natureza
    (dados crus viram texto), mas atribuir TAGS (`'<b>' + x.name`) é
    anti-padrão (nunca renderiza e sinaliza confusão text/HTML) → FLAG. Dados
    crus (`el.textContent = x.name`) e literais de comparação
    (`'REPORTED < OBSERVED'`, sem forma de tag) continuam limpos.
  - No chain-detector, a ponte `ident || …) ` antes de um `.map(`/`.join(` é
    reconhecida como fonte de transformação (ex: `(c.providers || []).map(…)`
    não gera falso positivo).

Allowlist de expressões seguras (não precisam de escape): `escapeHtml(...)`,
formatters que só emitem números/unidades (`fmt.age`/`fmt.hashrate`/
`fmt.uptime`/`fmt.secsToHuman`/`fmt.pct`/`fmt.usd`/`fmt.expectedBlock` e
`acFormatTime(...)`), mapa local de classes `severityClass[...]`, literais
numéricos/strings, ternários de literais, e identificadores "pelados" que
carregam fragmentos pré-escapados (`rows`, `parts`). No scanner de
concatenação `'+'`, as chamadas de formatters do allowlist são REMOVIDAS do
operando antes da caça a campos (`fmt.age(x.ts)` → o argumento nunca é
interpolado — o formatter emite número/unidade), o que elimina falsos
positivos tipo `(e.ts ? fmt.age(e.ts) : '--:--:--')` no ticker.

> ⚠️ `fmt.diff()` e `fmt.shortAddr()`/`chunkAddr()` **NÃO** estão no allowlist:
> eles ecoam a string de entrada crua (vetor da Issue #48) — qualquer uso em
> `innerHTML` exige `escapeHtml(...)` explícito (inclusive dentro de operando
> de concatenação).

**Self-test do guard** (`node tests/test_dom_guards.js`, também no CI):
roda o guard REAL como subprocesso contra fixtures descartáveis em temp dir
(override `GUARD_TEMPLATES_DIR`/`GUARD_APP_JS`) e asserta os exit codes:
baseline → PASS, XSS injetado → FAIL, id duplicado → FAIL, `fmt.diff` sem
escape → FAIL, dados escapados + `fmt.age` + contador → PASS, e os casos de
concatenação `'+'` (Issue #64): `x.msg` cru → FAIL, mapa/join escapado +
ternário de literais → PASS, padrão carteira `(e.worker || '')` + `slice` →
FAIL, `fmt.age` dentro de operando → PASS (sem FP), `fmt.diff` dentro de
operando → FAIL, `m.color`/`m.icon` crus em `style=` → FAIL (config externa
é vetor de CSS injection). E os sinks estendidos (Issue #66):
`insertAdjacentHTML` inline cru → FAIL, `insertAdjacentHTML('…', rows)` com
`rows` construído cru → FAIL, mesmo padrão escapado → PASS, `innerHTML = rows`
escapado → PASS, `textContent` com `<b>` → FAIL, `textContent` com dado cru →
PASS, literal `'REPORTED < OBSERVED'` → PASS, builder local cru → FAIL.
Protege o próprio guard contra enfraquecimento futuro.

### Guards XSS mobile — `scripts/check-mobile-xss.cjs` (Issue #70)

Guard estático **blocking** no job `gate` do CI, mesma filosofia do guard
web aplicada aos vetores React Native do `mobile/`:

- **WebView `source={{ html: … }}` / `source={{ html }}` / `injectedJavaScript`**: o
  valor é analisado — literal puro → PASS; builder whitelisted
  (`escapeHtml`/`buildSafeHtml`/`sanitizeHtml`/`htmlEscape`/`stripHtml`/
  `buildHtmlSafely`) → PASS; interpolação `${…}` de dado externo → FAIL;
  `source={{ html }}` shorthand e RHS identificador-nu são **seguidos até a
  declaração** (`const rawHtml = …`) e o builder é varrido. Multi-linha
  (`source={{` + `html:` na linha seguinte) suportado (join de até 10 linhas).
- **`dangerouslySetInnerHTML` / `react-native-render-html`** (`renderHTML(`,
  `<RenderHTML`, import): uso = review gate → FAIL.
- **`eval(` / `new Function(`**: banidos (também rejeitados pelas lojas) → FAIL.
- **`Linking.openURL(...)`**: literal `javascript:` no argumento → FAIL
  (vetor XSS real); URL interpolada (`\`${…}\``) ou concatenada com dado
  externo → FAIL (gate de scheme). `source={{ uri: 'javascript:…' }}` → FAIL.

Deliberadamente mais estrito que o guard web (é uma **rede de prevenção** — o
`mobile/` tem 0 achados hoje): interpolações em valores WebView só passam via
builder whitelisted ou literal, nada mais.

**Self-test** (`node tests/test_mobile_xss_guards.js`, também no CI): 25 casos
rodando o guard REAL contra fixtures descartáveis (override
`GUARD_MOBILE_ROOT`): baseline → PASS, TL cru → FAIL, concat cru → FAIL,
literal → PASS, builder → PASS, bare-id cru/safe → FAIL/PASS, multi-linha cru
→ FAIL, `injectedJavaScript` cru/literal → FAIL/PASS, `dangerouslySetInnerHTML`
→ FAIL, `renderHTML` → FAIL, `eval`/`new Function` → FAIL, `openURL`
`javascript:`/literal/interp → FAIL/PASS/FAIL, uri `javascript:` → FAIL,
comentário citando sink (inline incluso) → PASS, shorthand safe/cru →
PASS/FAIL, interp escapada → PASS, concat openURL começando com literal →
FAIL, `+` dentro de literal URL (query) → PASS.

### Pipeline combinado de frontend — `scripts/check_frontend.sh` (Issue #62)

Um único comando roda **todos** os checks de frontend em sequência
(blocking), para dev local e como check do job `frontend-audit` no PR
(boota o Flask em 8765 com rate-limit alto, roda os guards + JS core + audit
visual, e derruba o servidor — `AUDIT_URL` pula o boot):

```bash
npm run check:frontend          # ou: bash scripts/check_frontend.sh
```

1. `check:dom` — guard estático DOM (ids duplicados + XSS) + report
2. `test:dom-guards` — self-test do guard DOM
3. JS core — `node --check static/app.js` + `tests/test_app_js_core.js`
4. `check-mobile-xss` + self-test — guard XSS mobile (React Native)
5. `audit_ui --all` — auditoria visual desktop + mobile (console errors,
   overflow, truncamento, skeletons presos)

Qualquer falha → exit ≠ 0 → merge bloqueado (job `frontend-audit` no CI).

### Auditoria visual (Playwright) — `scripts/audit_ui.cjs`

Auditoria reutilizável do dashboard (usada na rodada 2026-08): console errors,
page errors, overflow horizontal, elementos truncados, skeletons presos e
presença de skeleton nos módulos tardios. Exit codes CI-friendly
(0 pass / 1 issues / 2 fatal) e flags `--mobile`, `--all`, `--strict`.
Requer servidor local no ar (padrão `http://127.0.0.1:8765`, override
`AUDIT_URL`).

---

## 4. Referências

- Observabilidade: `services/observability.py` · `app.py` (Sentry env-gated)
- CI: `.github/workflows/ci.yml` (pytest+JS core+coverage) ·
  `execution-pipeline.yml` (validate/build/integration/diagnose-render)
- Issues: #28 (testes) · #29 (lint) · #30 (observabilidade)
- Regra de ouro: ver `docs/AUDITORIA_ESTRATEGICA.md`
