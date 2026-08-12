# 🤖 AGENT WORKFLOW — Issue → Branch → PR → Deploy

> **Regra universal para qualquer agente (qualquer modelo) trabalhando neste repositório.**
> Leia este documento ANTES de começar qualquer tarefa. Ele define como o código
> chega à produção neste projeto.

**Status:** ADOTADO — todo trabalho entra por **Issue** e é entregue por **PR**.
Deploy = merge em `master` (automático via Render autoDeploy).

---

## 1. O fluxo em uma linha

```
Issue (GitHub) → Branch nomeada → commits → push → PR (menciona a Issue) → CI verde → merge → deploy
```

**Nunca** fazer push direto para `master` com mudanças de código. O `master`
só recebe merges de PRs.

---

## 2. Regras obrigatórias

### 2.1 — Toda tarefa tem uma Issue
Antes de codar, garanta que existe uma Issue aberta. Tipos (labels):

| Tipo | Label | Exemplo de título |
|---|---|---|
| Correção | `bug` | `Fleet: card continua ONLINE após Pause` |
| Melhoria | `enhancement` | `Observabilidade persistente: logs estruturados` |
| Nova função | `feature` | `Auto-Pilot advisory mode` |
| Operação/infra | `ops` | `OPS: ativar backup gist no Render` |

Sempre acompanhe da label de prioridade: `priority: P1` (urgente), `priority: P2`
(roadmap 90 dias), `priority: P3` (gated por tração / contínuo).

Se a Issue não existe: **crie-a** (`gh issue create`) antes de escrever código.
A Issue deve ter **Critérios de aceite** verificáveis.

### 2.2 — Branch nomeada pela Issue
Padrão: `<tipo>/<numero-da-issue>-<slug>` — exemplo:

```bash
git checkout -b fix/13-fleet-status-paused      # Issue #13
git checkout -b feat/20-auto-pilot-advisory     # Issue #20
git checkout -b docs/12-issue-pr-deploy         # Issue #12
```

Tipos de prefixo: `feat/` (nova função), `fix/` (correção), `enh/` (melhoria),
`ops/` (infra), `docs/` (documentação), `test/` (testes).

### 2.3 — Commits convencionais
```bash
git commit -m 'fix(fleet): status PAUSED após pause reflete no registry'
git commit -m 'feat(rentals): serie temporal do portfólio'
git commit -m 'docs(workflow): padrao Issue-PR-Deploy'
```

### 2.4 — PR menciona a Issue (obrigatório)
Na **descrição do PR**, sempre referencie a Issue:

- `Closes #NNN` — fecha a Issue automaticamente no merge (feature/melhoria/docs)
- `Fixes #NNN` — fecha a Issue no merge (bug)
- `Refs #NNN` — Issue relacionada mas não fechada

Exemplo de descrição mínima:

```markdown
## O que
Resolve o status do card após pause (PAUSED em vez de ONLINE).

## Validação
- [ ] pytest: 1860 passed
- [ ] JS core: 1261 passed
- [ ] e2e frota: 37 passed (5 skips = harness)
- [ ] `git diff --check` limpo

Closes #13
```

### 2.5 — CI é o gate
Não mergear PR com workflow vermelho. O CI roda em `push` e `pull_request`
(`.github/workflows/ci.yml`). Antes de abrir o PR, rode localmente:

```bash
SECRET_KEY=test-secret-0123456789 python -m pytest tests/ -q   # suíte afetada primeiro
node tests/test_app_js_core.js                                   # suíte JS espelhada
node --check static/app.js
git diff --check
bash run-e2e.sh --file=SEU_SPEC.spec.js                          # e2e afetado
```

### 2.6 — Deploy
- Merge do PR em `master` → workflows disparam → Render redeploya automaticamente.
- Para **hotfix crítico em produção** sem passar por PR completo: exceção explícita,
  documentada no PR posterior (`Refs #NNN`).
- Toda mudança operacional (env vars, keys) também gera Issue `ops` + PR
  de documentação (`docs/DEPLOYMENT_OPS.md`).

---

## 3. Checklist do agente (executar em toda tarefa)

- [ ] 1. Issue existe? Se não, criar com critérios de aceite + labels.
- [ ] 2. Branch criada a partir de `master` com nome `tipo/NNN-slug`.
- [ ] 3. Implementação + testes (herméticos — nunca tocar `data/war_room.sqlite`).
- [ ] 4. Validação local (pytest afetado + JS core + e2e + diff --check).
- [ ] 5. Push da branch + `gh pr create` com `Closes/Fixes #NNN` na descrição.
- [ ] 6. Acompanhar CI até verde; corrigir se necessário.
- [ ] 7. Merge (com aprovação) → deploy automático.
- [ ] 8. Mover a Issue para `done` / fechar no merge (automático com `Closes`).

---

## 4. Comandos rápidos (gh CLI)

```bash
# criar issue
gh issue create --title '...' --label 'bug,priority: P1' --body '...'

# abrir PR mencionando a issue
gh pr create --base master --head fix/13-fleet-status-paused \
  --title 'fix(fleet): status PAUSED após pause' \
  --body '...\n\nCloses #13'

# checar CI do PR
gh pr checks --watch

# merge
gh pr merge 123 --squash --delete-branch
```

---

## 5. Referências
- Roadmap: `docs/AUDITORIA_ESTRATEGICA.md` (§5) · `docs/IMPROVEMENT_ROADMAP.md` (§8)
- Deploy/ops: `docs/DEPLOYMENT_OPS.md` · `render.yaml`
- Padrões de código e testes: `CONTRIBUTING.md`
