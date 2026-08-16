# GitHub Workflow: Issues, PRs e Deploys

## Padrão Obrigatório para Qualquer Agente de Qualquer Modelo

Este documento estabelece o fluxo de trabalho padrão para todo o projeto. Qualquer agente de IA (Claude, GPT, Gemini, Grok, ou qualquer outro) DEVE seguir estas regras.

## 1. Toda Tarefa Vira Issue

Antes de escrever qualquer código, criar uma Issue no GitHub. Toda Issue deve ter:

### Tipos de Issue (Labels)

| Label | Descrição | Cor Sugerida |
|---|---|---|
| `correction` | Correção de bug, fix, hotfix | Vermelho |
| `improvement` | Melhoria de código, performance, refactor | Azul |
| `new-feature` | Nova funcionalidade, nova função | Verde |
| `security` | Vulnerabilidade de segurança | Vermelho escuro |
| `ui-ux` | Problema de interface ou experiência | Roxo |
| `observability` | Monitoring, logging, tracing | Amarelo |
| `testing` | Cobertura de testes, E2E, unit | Ciano |
| `devops` | CI/CD, deploy, infraestrutura | Laranja |
| `documentation` | Docs, README, comentários | Cinza |

### Template de Issue

```markdown
## [Tipo: Correção/Melhoria/Nova Função] Título Curto

### Contexto
Descrição do problema ou necessidade.

### Comportamento Esperado
O que deveria acontecer.

### Comportamento Atual (se aplicável)
O que está acontecendo de errado.

### Critérios de Aceitação
- [ ] Critério 1
- [ ] Critério 2
- [ ] Testes escritos e passando
- [ ] Documentação atualizada

### Arquivos Afetados
- `path/to/file.ts`

### Equipe Responsável
- [ ] Frontend
- [ ] Backend
- [ ] DevOps/SRE
- [ ] Security
- [ ] QA

### Severidade
- [ ] CRITICAL (bloqueia produção)
- [ ] HIGH (bloqueia merge)
- [ ] MEDIUM (próximo release)
- [ ] LOW (backlog)
```

## 2. Branch Naming Convention

```
<tipo>/<issue-number>-descricao-curta

Exemplos:
correction/123-fix-login-redirect
improvement/456-optimize-query-performance
new-feature/789-add-wallet-connect
security/101-remove-hardcoded-api-keys
```

## 3. PR Obrigatório para Deploy

### Regras do PR

1. **Nenhum push direto para `main`/`master`** — sempre via PR
2. **PR deve mencionar a Issue** — usar `Closes #XX`, `Fixes #XX`, ou `Refs #XX`
3. **PR precisa de pelo menos 1 approval** antes do merge
4. **CI deve estar verde** — lint, tests, build passando
5. **Squash and merge** como estratégia padrão

### Template de PR

```markdown
## Descrição
Descrição clara do que este PR faz e por quê.

## Issue Relacionada
Closes #XX

## Tipo de Mudança
- [ ] Correção de bug (correction)
- [ ] Nova funcionalidade (new-feature)
- [ ] Melhoria (improvement)
- [ ] Security fix
- [ ] Breaking change

## Checklist
- [ ] Issue criada e referenciada (`Closes #XX`)
- [ ] Código segue o padrão de lint (Biome)
- [ ] Testes unitários adicionados/atualizados
- [ ] Testes E2E atualizados (se fluxo crítico)
- [ ] Sem segredos no código (API keys, tokens)
- [ ] Skeleton/loading states implementados (se UI)
- [ ] Animações respeitam `prefers-reduced-motion` (se UI)
- [ ] Documentação atualizada
- [ ] Changelog atualizado

## Screenshots / Demo (se aplicável)
[Anexar screenshots ou GIF do antes/depois]

## Notas para Reviewer
Pontos de atenção, decisões de design, trade-offs.
```

## 4. Deploy Flow

```
Issue → Branch → Desenvolvimento → PR → Code Review → CI/CD → Staging → QA → Production
                ↑                    ↑                              ↑
            Referenciar Issue    Mentionar Issue no PR       Deploy via PR merge
```

### Ambientes

| Ambiente | Branch | Quando | Quem |
|---|---|---|---|
| Development | feature branches | Durante desenvolvimento | Developer |
| Staging | `staging` (merge de PRs aprovados) | Pré-produção | CI automático |
| Production | `main`/`master` (merge de staging após QA) | Release | Release manager |

### Regras de Deploy

1. **Deploy para production só após PR aprovado e merge para main**
2. **Rollback automático** se health check falhar após deploy
3. **Feature flags** para features grandes ou arriscadas
4. **Database migrations** rodam antes do deploy da aplicação
5. **Sempre manter `staging` o mais próximo possível de `production`**

## 5. Convenção de Commits (Commitlint)

```
<type>(<scope>): <description>

feat(wallet): add MetaMask connector
fix(trading): resolve race condition in order execution
improvement(performance): optimize WebSocket reconnection
security(auth): remove hardcoded JWT secret
docs(readme): update deployment instructions
test(e2e): add Playwright tests for checkout flow
chore(deps): bump react to 19.1.0
```

### Types Permitidos

`feat`, `fix`, `improvement`, `security`, `docs`, `test`, `chore`, `refactor`, `perf`, `ci`, `build`

## 6. Project Board

Usar GitHub Projects (Kanban) com as seguintes colunas:

```
Backlog → Triaged → In Progress → In Review → Approved → Done
```

Cada coluna pode ter WIP limits:
- In Progress: máx 3 por pessoa
- In Review: máx 5 no total
- Approved: aguarda deploy window
