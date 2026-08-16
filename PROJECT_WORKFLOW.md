# PROJECT_WORKFLOW.md — Padrão de Desenvolvimento (Obrigatório para Qualquer Agente de IA)

> **ATENÇÃO:** Este documento é a fonte de verdade para o fluxo de desenvolvimento. Qualquer agente de IA (Claude, GPT, Gemini, Grok, ou qualquer outro modelo) que trabalhe neste projeto DEVE seguir estas regras. Não há exceções.

---

## 1. GitHub Issues — Toda Tarefa Vira Issue

Antes de escrever qualquer linha de código, criar uma Issue no GitHub.

### Tipos de Tarefa (Labels)

| Label | Quando Usar |
|---|---|
| `correction` | Bug, fix, hotfix, erro em produção |
| `improvement` | Refactor, performance, code quality, DX |
| `new-feature` | Nova funcionalidade, novo endpoint, nova página |
| `security` | Vulnerabilidade, hardening, compliance |
| `ui-ux` | Interface, animação, acessibilidade, responsividade |
| `observability` | Sentry, Datadog, logs, tracing, alertas |
| `testing` | Unit tests, E2E, coverage, mutation testing |
| `devops` | CI/CD, deploy, Docker, infra |
| `documentation` | README, docs, comentários |

### Estrutura de Issue

```text
## [Tipo] Título Claro e Curto

### Contexto
Por que esta tarefa existe? Qual problema resolve?

### Critérios de Aceitação
- [ ] Critério mensurável 1
- [ ] Critério mensurável 2
- [ ] Testes escritos e passando
- [ ] Documentação atualizada

### Arquivos Afetados
- `caminho/do/arquivo.ts`

### Severidade
CRITICAL | HIGH | MEDIUM | LOW

### Equipe
Frontend | Backend | DevOps/SRE | Security | QA | Product | Data/AI
```

## 2. Branches

```text
<tipo>/<issue-number>-descricao-curta

Exemplos (prefixos reais deste repo — ver histórico e docs/AGENT_WORKFLOW.md):
fix/123-fix-login-redirect            # correção de bug
enh/456-optimize-query-performance    # melhoria
feat/789-add-wallet-connect           # nova funcionalidade
security/101-remove-hardcoded-api-keys
ops/202-enable-gist-backup            # infra/deploy
```

> **Equivalência com os tipos de Issue:** `correction` → branch `fix/`;
> `improvement` → `enh/`; `new-feature` → `feat/`. Um único padrão de
> prefixos evita ambiguidade entre agentes.

- **NUNCA** fazer push direto para `main`/`master`
- **SEMPRE** criar branch a partir da main atualizada
- **UMA Issue por branch** (se precisar de múltiplas, criar sub-Issues)

## 3. Pull Requests — Deploy só via PR

### Regras

- Todo PR DEVE mencionar a Issue: `Closes #XX` ou `Refs #XX`
- Todo PR PRECISA de pelo menos 1 approval
- CI DEVE estar verde (lint, tests, build)
- Estratégia: **Squash and merge**

### Template de PR

```text
## Descrição
O que este PR faz e por quê.

## Issue Relacionada
Closes #XX

## Tipo de Mudança
- [ ] correction
- [ ] improvement
- [ ] new-feature
- [ ] security

## Checklist
- [ ] Issue criada e referenciada (`Closes #XX`)
- [ ] Lint passing (Biome)
- [ ] Testes unitários adicionados/atualizados
- [ ] E2E atualizado (se fluxo crítico)
- [ ] Sem segredos no código
- [ ] Skeleton/loading states (se UI)
- [ ] prefers-reduced-motion respeitado (se UI)
- [ ] Documentação atualizada
```

## 4. Commits (Commitlint)

```text
<type>(<scope>): <description>

feat(wallet): add MetaMask connector
fix(trading): resolve race condition in order execution
security(auth): remove hardcoded JWT secret
test(e2e): add Playwright tests for checkout
```

**Types:** `feat`, `fix`, `improvement`, `security`, `docs`, `test`, `chore`, `refactor`, `perf`, `ci`, `build`

## 5. Motion & UI — Padrões Obrigatórios

Baseado em [kylezantos/design-motion-principles](https://github.com/kylezantos/design-motion-principles). Skill local: `.agents/skills/design-motion-principles`.

### Obrigatório em Toda Interface

| Requisito | Status |
|---|---|
| Skeleton loading em todo carregamento de dados | OBRIGATÓRIO |
| Lazy loading de imagens e componentes pesados | OBRIGATÓRIO |
| Enter animation (opacity + translateY + blur) | OBRIGATÓRIO |
| Exit animation (mais sutil que enter) | OBRIGATÓRIO |
| Loading state em botões assíncronos | OBRIGATÓRIO |
| Progress bar para operações longas | OBRIGATÓRIO |
| `prefers-reduced-motion` | OBRIGATÓRIO |
| Custom easing (nunca `ease` padrão do CSS) | OBRIGATÓRIO |

### Anti-Patterns (Proibidos)

- Pulsing indicators em tudo
- Hover-scale em todos os elementos
- Stagger-spam sem propósito
- Bounce em contextos enterprise
- Scale from 0 (usar 0.9 + opacity)
- Animações > 500ms em high-frequency interactions

## 6. Observability — Stack Obrigatória

| Ferramenta | Uso | Obrigatório |
|---|---|---|
| Sentry | Error tracking + performance | SIM |
| Datadog ou New Relic | APM, metrics, dashboards | SIM (um dos dois) |
| OpenTelemetry | Distributed tracing | SIM |
| Structured logging | JSON logs com trace ID | SIM |

### Regras

- NUNCA logar secrets (API keys, tokens, private keys)
- Logs estruturados (JSON), não `console.log` em produção
- Trace ID em toda request
- Release tracking no Sentry
- Alertas configurados (error rate, latency p99)

> **Nota do projeto (regra de ouro CFO — custo $0):** neste repo, a stack adotada hoje é Sentry (env-gated) + logs JSON (`services/observability.py`). Datadog/NewRelic/OTel estão documentados como **não-adotados** em `docs/QUALITY.md` — qualquer adoção futura deve passar por Issue + decisão explícita.

## 7. Quality & Lint — Gates do CI

| Ferramenta | O que faz | Bloqueia merge? |
|---|---|---|
| Biome | Linter + formatter | SIM |
| TypeScript | Type checking | SIM |
| Knip | Dead code detection | SIM |
| Commitlint | Commit message format | SIM (pre-commit) |
| arch-contract | Architecture enforcement | SIM |
| Stryker | Mutation testing | Recomendado (PRs críticos) |

> **Nota do projeto:** gates reais deste repo em `.github/workflows/ci.yml` + `docs/QUALITY.md` — pytest com `--cov-fail-under=65`, JS core espelhado, e2e Playwright, guards DOM/mobile (`check-dom-regression.cjs`, `check-mobile-xss.cjs`), audit visual (`audit_ui.cjs --all`), Codecov (project + patch).

## 8. Testing — Cobertura Obrigatória

| Tipo | Ferramenta | Cobertura Mínima |
|---|---|---|
| Unit | Vitest / Jest | 80% lógica de negócio |
| Integration | Vitest + Supertest | Fluxos de API críticos |
| E2E | Playwright | Login, trade, checkout, onboarding |
| Coverage | Codecov | 80% total, 80% patch |

### Fluxos Críticos que PRECISAM de E2E

- Login → Dashboard
- Connect wallet → Execute trade
- Open position → Close position
- Settings → Save → Reload

## 9. Security — Pre-Merge Checklist

- Sem secrets no código (API keys, tokens, passwords)
- Input validation em todos os endpoints
- Auth middleware em rotas protegidas
- Rate limiting em rotas de auth
- CORS whitelist (não `*`)
- `npm audit` sem vulnerabilities high/critical
- Crypto private keys em KMS/encrypted
- No `eval()`, no `dangerouslySetInnerHTML` sem sanitização
- HTTPS forçado, HSTS configurado
- Security headers (Helmet.js)

## 10. Enterprise — Organização por Equipes

Toda Issue e todo PR deve ter a label da equipe responsável:

| Equipe | Label | Foco |
|---|---|---|
| Frontend | `team:frontend` | UI, motion, responsividade, a11y |
| Backend | `team:backend` | API, DB, trading logic, WebSocket |
| DevOps/SRE | `team:devops` | CI/CD, deploy, observability, infra |
| Security | `team:security` | OWASP, secrets, auth, crypto |
| QA | `team:qa` | Testes, coverage, E2E, mutation |
| Product | `team:product` | Requirements, UX flow, analytics |
| Data/AI | `team:data-ai` | AI integrations, models, backtesting |

## 11. Code Review Skill — Uso Obrigatório em Todo PR

Antes de aprovar qualquer PR, rodar o skill **`enterprise-code-review`** (`.agents/skills/enterprise-code-review`):

```text
# Full audit
Audite este PR usando enterprise-code-review --full

# Quick gate
Rode o quick gate pré-merge usando enterprise-code-review --quick
```

O audit cobre: security, bugs, inconsistências, truncamentos, UI/UX, motion, observability, quality, testing, e pesquisa de melhorias. Tudo organizado por equipe. Para auditorias profundas, usar também o prompt de auditoria enterprise (`AUDIT_PROMPT.md`).

---

## Resumo Visual do Fluxo

```text
Issue (GitHub)
  ↓
Branch (<tipo>/<issue#>-desc)
  ↓
Desenvolvimento (commits com Commitlint)
  ↓
PR (menciona Issue: Closes #XX)
  ↓
CI Gates (Biome, TypeScript, Knip, Tests, E2E, npm audit)
  ↓
Code Review (skill: enterprise-code-review)
  ↓
Approval (mín. 1 reviewer)
  ↓
Squash & Merge → main
  ↓
Deploy (automatizado via CI/CD)
  ↓
Sentry/Datadog monitoring ativo
```

> **Nota:** este documento deve viver na raiz do repositório como `PROJECT_WORKFLOW.md` (ou `AGENTS.md`/`CLAUDE.md`, conforme o padrão do projeto). Isso garante que qualquer agente de IA de qualquer modelo (Claude, GPT, Gemini, Grok, etc.) siga este padrão automaticamente. Qualquer mudança no processo deve passar por PR com review da equipe.
