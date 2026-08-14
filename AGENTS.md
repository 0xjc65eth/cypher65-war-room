# 🤖 AGENTS.md — Leia antes de qualquer tarefa neste repositório

Este arquivo é lido automaticamente por agentes de IA (GitHub Copilot, Claude, Cursor, etc.). A fonte de verdade completa está em **[`PROJECT_WORKFLOW.md`](./PROJECT_WORKFLOW.md)** — leia-o antes de codar.

## Regras inegociáveis

1. **Toda tarefa vira Issue no GitHub** — antes de escrever código (`gh issue create`, labels + `priority: P1/P2/P3`).
2. **Deploy só via PR** — nunca push direto para `master`. Branch `<tipo>/<issue#>-slug` → PR com `Closes #NNN` → CI verde → squash merge → deploy automático.
3. **Commits convencionais** — `feat(scope):`, `fix(scope):`, `docs(scope):`, etc.
4. **UI segue motion principles** — skeleton loading, lazy loading, animações suaves de entrada/saída/carregamento, `prefers-reduced-motion` (skill `.agents/skills/design-motion-principles`).
5. **Code review obrigatório antes do merge** — skill `.agents/skills/enterprise-code-review` (security + bugs + UI/UX + motion + observability + quality + tests, organizado por equipe). Para auditorias profundas: [`AUDIT_PROMPT.md`](./AUDIT_PROMPT.md).
6. **Qualidade/observabilidade** — Sentry (env-gated) + logs JSON; pytest (gate `--cov-fail-under=65`) + JS core + e2e Playwright + Codecov; guards DOM/mobile no CI.

## Comandos rápidos de validação local

```bash
SECRET_KEY=test-secret-0123456789 python -m pytest tests/ -q   # suíte Python
node tests/test_app_js_core.js                                   # suíte JS espelhada
node --check static/app.js
npm run check:frontend                  # pipeline combinado de frontend (Issue #62)
git diff --check
bash run-e2e.sh --file=SEU_SPEC.spec.js  # e2e Playwright afetado
```

## Índice de referência

| Arquivo | Conteúdo |
|---|---|
| `PROJECT_WORKFLOW.md` | **Fonte de verdade** — Issues, branches, PRs, commits, motion, observability, quality, testing, security, equipes |
| `CONTRIBUTING.md` | Guia de contribuição (setup, testes, padrões) |
| `docs/AGENT_WORKFLOW.md` | Fluxo Issue → Branch → PR → Deploy detalhado com comandos `gh` |
| `docs/QUALITY.md` | Matriz de ferramentas de qualidade/observabilidade (custo $0) |
| `AUDIT_PROMPT.md` | Prompt de auditoria enterprise completo (análise forense de erros, UI/UX, segurança) |
| `.agents/skills/` | Skills locais: `design-motion-principles`, `enterprise-code-review` |
