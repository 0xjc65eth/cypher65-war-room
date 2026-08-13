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
| Inconsistência | `inconsistency` | `docs divergem do código — README 45% vs gate real 65%` |
| Interface/UX | `ui-ux` | `endereços de suporte estouram o container (overflow 402px)` |

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
node scripts/check-dom-regression.cjs   # guards DOM: ids duplicados + XSS innerHTML
node tests/test_dom_guards.js           # self-test do próprio guard (casos adversários)
node scripts/check-mobile-xss.cjs       # guards XSS mobile (React Native)
node tests/test_mobile_xss_guards.js    # self-test do guard mobile (22 casos)
git diff --check
bash run-e2e.sh --file=SEU_SPEC.spec.js                          # e2e afetado
```

> **Ao tocar em `templates/*.html` ou em `.innerHTML`/`.outerHTML`/
> `insertAdjacentHTML`/`textContent` no `static/app.js`**: o
> `scripts/check-dom-regression.cjs` (gate do CI) vai bloquear o merge se
> (1) um `id=""` duplicar outro no template, ou (2) uma interpolação — em
> template literal `${...}` OU em concatenação com `'+'` (ex:
> `'<td>' + x.msg + '</td>'`) — ler campo de registro externo (`e.msg`,
> `a.category`, `m.tier`, `entry.worker`) sem `escapeHtml(...)`. Dados externos
> SEMPRE passam por `escapeHtml` antes de virar HTML; nunca construa HTML de
> strings de API/banco sem escapar. O guard também segue **identificadores
> nus** até a declaração que os constrói (`el.innerHTML = rows` /
> `insertAdjacentHTML('beforeend', rows)` — o HTML pré-construído é varrido)
> e **builders locais** (`function _xHtml(...)`) até o corpo. E `textContent`
> com markup HTML (`'<b>' + x.name`) é anti-padrão → bloqueará o merge;
> use `textContent` só para texto puro (dados crus são seguros ali) e HTML
> vai em `innerHTML`/`insertAdjacentHTML` com `escapeHtml`. Detalhe do scanner
>
> **Ao tocar em `mobile/src` / `mobile/App.tsx`** (React Native): o
> `scripts/check-mobile-xss.cjs` (gate do CI) vai bloquear o merge se um vetor
> RN for introduzido — WebView `source={{ html: … }}`/`source={{ html }}`/
> `injectedJavaScript` com interpolação `${…}` de dado externo SEM builder
> whitelisted (`escapeHtml`/`buildSafeHtml`/`sanitizeHtml`/…),
> `dangerouslySetInnerHTML`/`react-native-render-html`/`eval(`/`new Function(`
> (uso = review gate), ou `Linking.openURL('javascript:…')`/URL interpolada.
> Literais puros e builders whitelisted passam; o guard segue identificadores
> nus até a declaração que os constrói e cobre blocos multi-linha. Regra: dado
> externo em valor WebView SEMPRE passa por builder — nunca monte HTML/JS de
> strings de API/banco. Detalhe do scanner
> de concatenação: formatters do allowlist (`fmt.age`/`fmt.hashrate`/
> `acFormatTime`/…) são removidos do operando antes da caça a campos (o
> argumento nunca é interpolado), mas `fmt.diff`/`fmt.shortAddr` ecoam string
> crua e continuam exigindo `escapeHtml` mesmo dentro de concatenação.

---

## 3. Qualidade de Interface (obrigatória em toda mudança de UI)

Qualquer alteração em `static/app.js`, `static/style.css` ou `templates/`
DEVE seguir os princípios de motion do repo
(`github.com/kylezantos/design-principles` — skill local em
`.agents/skills/design-motion-principles`; no dashboard, peso **Emil**
<300ms + **Jakub** polish sutil, `transform`/`opacity`/`filter` only).

Checklist de UX:
- [ ] **Skeleton loading** — containers que carregam dados (market/rentals/
      fleet e o boot) mostram shimmer em vez de vazio/"carregamento bruto".
- [ ] **Lazy loading** — módulos pesados (market trend, rentals, fleet)
      carregam na 1ª ativação, com skeleton enquanto o fetch roda.
- [ ] **Animações suaves** — entrada/saída de módulos (stagger), abertura/
      fechamento de modais, estado de carregamento em botões (spinner),
      progresso em barras.
- [ ] **Feedback visual** — todo elemento interativo tem hover/active/pressed
      e estado de loading/erro/empty explícito.
- [ ] **Acessibilidade** — `prefers-reduced-motion` desativa animações;
      foco visível; contraste adequado.

Regra prática: **só animar `transform`/`opacity`/`filter`** (nunca layout) e
manter entrada <300ms (peso Emil). Interfaces estáticas ou com sensação de
"carregamento bruto" são reprovadas no review.

---

## 4. Qualidade Técnica, Observabilidade e Testes

Referência completa: `docs/QUALITY.md` (matriz de ferramentas, custo $0).
Aplicar o que for aplicável à mudança:

- **Observabilidade**: backend `SENTRY_DSN` (env-gated) + logs JSON
  (`LOG_JSON=1`, `services/observability.py`); frontend Sentry automático
  quando o operador configura o DSN. Datadog/NewRelic/OTel documentados como
  não-adotados (regra de ouro CFO: custo $0).
- **Lint/qualidade**: Biome (mobile + advisory no app.js), Knip (dead code),
  commitlint (Conventional Commits), mutmut/Stryker (mutation testing sob
  demanda). Pre-commit: `flake8` + `black` + `commitlint`.
- **Testes**: unit/integration pytest (gate `--cov-fail-under=65`), JS core
  (`node tests/test_app_js_core.js`), e2e Playwright (job `e2e` no CI),
  cobertura no Codecov (badge dinâmico no README).
- **Auditoria visual** (mudanças de UI): `node scripts/audit_ui.cjs --all`
  (console errors, overflow, truncamento, skeletons presos) — exit code
  CI-friendly, flags `--mobile`/`--strict`.
- **Mutation testing** (quando pedido): `mutmut run --use-coverage
  --disable-mutation-types string` — rodar em background (tmux) e validar
  cada mutante sobrevivente com `mutmut apply <id>` + teste que o mata;
  **restaurar o arquivo** com `git checkout -- <arquivo>` ao terminar
  (mutmut deixa mutantes aplicados no disco) e limpar `.mutmut-cache`/
  `*.py.bak` (já no `.gitignore`).

---

## 5. Regras gerais de execução

- **Commits pequenos e atômicos**, mensagens descritivas (Conventional Commits).
- **Código limpo e manutenível**: reusar helpers existentes, seguir as
  convenções do arquivo vizinho, sem gambiarras.
- **Validar antes do PR**: lint + testes + `git diff --check`; cobertura e
  observabilidade quando aplicável.
- **Documentar decisões importantes** na Issue ou na descrição do PR
  (por que/alternativas/impacto).
- **Incremental e transparente**: mudanças pequenas, PRs revisáveis, nunca
  entregar solução incompleta ou improvisada.

---

## 6. Checklist do agente (executar em toda tarefa)

### 2.6 — Deploy
- Merge do PR em `master` → workflows disparam → Render redeploya automaticamente.
- Para **hotfix crítico em produção** sem passar por PR completo: exceção explícita,
  documentada no PR posterior (`Refs #NNN`).
- Toda mudança operacional (env vars, keys) também gera Issue `ops` + PR
  de documentação (`docs/DEPLOYMENT_OPS.md`).

---

## 7. Comandos rápidos (gh CLI)

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

## 8. Referências
- Roadmap: `docs/AUDITORIA_ESTRATEGICA.md` (§5) · `docs/IMPROVEMENT_ROADMAP.md` (§8)
- Deploy/ops: `docs/DEPLOYMENT_OPS.md` · `render.yaml`
- Padrões de código e testes: `CONTRIBUTING.md`
