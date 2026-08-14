# Contribuindo para o CYPHER65 War Room

Obrigado por querer contribuir! Este guia mantém o projeto consistente e a
suíte (1.000+ testes) verde.

## ⚠️ FLUXO OBRIGATÓRIO (leia primeiro)

> **Todo trabalho entra por Issue e é entregue via PR — nunca push direto para `master`.**
> Deploy = merge do PR em `master` (automático).

A fonte de verdade é **`PROJECT_WORKFLOW.md`** (raiz — lido por qualquer agente
de qualquer modelo; apontador curto em **`AGENTS.md`**). O detalhamento com
comandos `gh` está em **`docs/AGENT_WORKFLOW.md`**.

Antes de todo merge, rode o skill **`enterprise-code-review`**
(`.agents/skills/enterprise-code-review` — security + bugs + UI/UX + motion +
observability + quality + tests por equipe). Para auditorias profundas, use o
prompt de **`AUDIT_PROMPT.md`** (raiz).

Resumo em 4 passos:
1. Crie/use a **Issue** (`gh issue create`, labels `bug|enhancement|feature` + `priority: P1-P3`).
2. **Branch** `tipo/NNN-slug` a partir de `master`.
3. **PR** mencionando a Issue (`Closes #NNN` / `Fixes #NNN` / `Refs #NNN`) na descrição.
4. CI verde → **merge** → deploy automático no Render.

## Setup

```bash
./run.sh                      # cria .venv, instala deps, sobe o servidor
pip install -r requirements-dev.txt   # ferramentas de dev (opcional)
pre-commit install            # hooks de higiene (opcional, não-gate)
```

## Como rodar os testes

```bash
make test                     # pytest completo (usa .venv)
python -m pytest tests/test_seu_arquivo.py -q   # teste isolado
node tests/test_app_js_core.js                   # suíte JS espelhada (873+)
bash run-e2e.sh --file=dashboard.spec.js         # E2E Playwright
```

Regra de ouro: **todo teste é hermético** — nenhum toca em
`data/war_room.sqlite` (o conftest redireciona `DB_PATH` para um scratch
dir). Novos testes devem seguir o mesmo padrão.

## Padrões do projeto

- **Workflow obrigatório**: toda mudança entra por Issue e é entregue via PR
  (`PROJECT_WORKFLOW.md` + `docs/AGENT_WORKFLOW.md`). Os docs definem as
  regras de **qualidade de interface** (motion/skeleton/lazy/loading — skill
  `design-motion-principles`) e **qualidade técnica** (observabilidade
  Sentry/logs JSON, lint Biome/Knip/commitlint, mutation testing, Codecov) e
  o **code review pré-merge** (skill `enterprise-code-review`).
- **Honest telemetry**: o app bota com zero estado e só mostra dados reais.
  Nunca insira mocks/seed de devices em produção.
- **Env-gating**: features sensíveis são off-by-default via env var
  (ex.: `REVOKED_TOKENS_DB=1`, `PRO_LICENSE_KEYS`). Siga esse padrão.
- **Config única**: env vars são lidas em `config.py`; `app.py` e `services/`
  importam de lá — nunca redeclare `os.environ.get(...)`.
- **Boas práticas de boot**: threads de background vivem em
  `_start_background_threads()` (app.py), chamado no `__main__` ou via
  `python -m services.workers`. Importar `app` NUNCA pode spawnar threads
  (ver `tests/test_boot_threads.py`).

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(auth): add REVOKED_TOKENS_DB persistence
fix(poll): watchdog replaces hung lock
docs(deploy): document two-process gunicorn option
```

## Antes do PR

1. Rode a suíte Python + JS (acima).
2. Se mexeu em IDs de DOM, rode `node scripts/validate-dom-ids.cjs`.
3. Atualize `CHANGELOG.md` (seção `Unreleased`) para mudanças notáveis.
4. Se é um fix/feature sensível (auth, device control, dados), adicione um
   teste de regressão no padrão dos existentes.
