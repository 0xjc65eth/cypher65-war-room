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

```bash
LOG_JSON=1 python app.py          # logs JSON estruturados
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
| **flake8 + black** | Python | ✅ existente (pre-commit) | advisory |

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
| Unit/integration (Python) | pytest | 1859 testes, `--cov-fail-under=65` | ✅ blocking |
| JS core (mirror do app.js) | node --test | 1261 testes | ✅ blocking |
| E2E (browser) | **Playwright** | specs chromium + mobile-chrome | ✅ job `e2e` |
| Cobertura pública | **Codecov** (free p/ repo público) | upload do coverage.xml | ✅ non-blocking |

### Codecov

O CI gera `coverage.xml` e envia pro Codecov (repo público = free tier).
`fail_ci_if_error: false` — sem token, o upload falha silencioso (não bloqueia
merge). Badge no README reflete a cobertura pública.

#### Token (CODECOV_TOKEN) — 1x por repo

Sem o token o CLI falha com `Token required - not valid tokenless upload`
(log: `Token length: 0`) e o badge fica sem dados. Para ativar:

1. app.codecov.io → Sign in with GitHub (conta dona do repo) → autorize o
   GitHub App p/ `cypher65-war-room`.
2. Abra o repo → **Settings** → **General** → **Repository Upload Token** → copie.
3. `gh secret set CODECOV_TOKEN` (no diretório do repo) — o step do CI já
   referencia `token: ${{ secrets.CODECOV_TOKEN }}`.
4. Rode o CI de novo e confira no log: `Upload queued for processing complete`
   SEM a linha `Token required`. O badge `codecov.io/gh/<owner>/<repo>/branch/master/graph/badge.svg`
   passa a mostrar a % real após o 1º upload.

> **Render NÃO precisa do token** — o Render roda a app e nunca envia cobertura;
> o upload acontece só no GitHub Actions. Não commitar o segredo no render.yaml.

```bash
make test                        # pytest completo
node tests/test_app_js_core.js   # JS core
bash run-e2e.sh --file=dashboard.spec.js   # Playwright
```

---

## 4. Referências

- Observabilidade: `services/observability.py` · `app.py` (Sentry env-gated)
- CI: `.github/workflows/ci.yml` (pytest+JS core+coverage) ·
  `execution-pipeline.yml` (validate/build/integration/diagnose-render)
- Issues: #28 (testes) · #29 (lint) · #30 (observabilidade)
- Regra de ouro: ver `docs/AUDITORIA_ESTRATEGICA.md`
