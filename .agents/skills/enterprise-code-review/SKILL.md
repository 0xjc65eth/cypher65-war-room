---
name: enterprise-code-review
description: "Comprehensive pre-merge/pre-deploy code review skill for enterprise projects. Use before merging any feature branch to main/master or before deploy. Covers: GitHub Issues/PR workflow, security vulnerabilities, bug detection, inconsistencies, UI/UX truncation and overflow, motion design (skeleton loading, lazy loading, smooth animations), observability (Sentry, Datadog, NewRelic, OpenTelemetry), code quality and linting (Biome, Commitlint, Knip, Stryker, arch-contract), testing (unit, integration, E2E with Playwright, Codecov), and improvement research. Organizes findings by enterprise teams (Frontend, Backend, DevOps/SRE, Security, QA, Product, Data/AI). Any AI agent of any model should follow this pattern."
---

# Enterprise Code Review (Pre-Merge / Pre-Deploy)

## Quando Usar

**Sempre** antes de fazer merge de uma feature branch para `main`/`master`, ou antes de deploy. O objetivo é pegar falhas de segurança, bugs, inconsistências, problemas de UI/UX, truncamentos, e regressões **ANTES** de virarem incidente em produção — não depois.

Use também em:
- Auditoria completa de release
- Sprint review / milestone review
- Onboarding de novos repositórios
- Auditoria de tech debt
- Pre-aquisição / due diligence técnica

## Modos de Operação

| Modo | Gatilho | O que faz |
|---|---|---|
| **Full Audit** | `--full` ou default | Roda todos os checks: security, bugs, UI/UX, motion, observability, quality, tests, enterprise |
| **Security Only** | `--security` | Apenas checklist de segurança |
| **UI/UX Only** | `--uiux` | Apenas motion + truncamento + responsividade |
| **Quick Gate** | `--quick` | Security + lint + tests blocking only |

## Fluxo de Execução

1. **Reconhecimento** — Ler a estrutura do projeto, identificar stack, dependências, e arquitetura
2. **GitHub Workflow Check** — Verificar se Issues e PRs seguem o padrão (ver `references/github-workflow.md`)
3. **Security Review** — Rodar checklist de segurança OWASP + trading/crypto-specific (ver `references/security-uiux-audit.md`)
4. **Bug & Inconsistency Detection** — Encontrar erros, bugs, issues lógicas, truncamentos (ver `references/security-uiux-audit.md`)
5. **UI/UX Audit** — Verificar skeleton, lazy loading, animações, truncamento, overflow (ver `references/motion-principles.md` e `references/security-uiux-audit.md`)
6. **Motion Design Review** — Garantir skeleton, lazy loading, smooth enter/exit/loading/progress animations (ver `references/motion-principles.md`)
7. **Observability Check** — Verificar Sentry, Datadog/NewRelic, OpenTelemetry (ver `references/observability-quality-testing.md`)
8. **Quality & Lint Check** — Verificar Biome, Commitlint, Knip, Stryker, arch-contract (ver `references/observability-quality-testing.md`)
9. **Testing Check** — Verificar cobertura unitária, integração, E2E Playwright, Codecov (ver `references/observability-quality-testing.md`)
10. **Improvement Research** — Pesquisar melhorias para o projeto, novas libs, patterns, otimizações
11. **Enterprise Report** — Organizar tudo por nicho/equipe (ver `references/enterprise-teams.md`)

## Output Esperado

Para cada finding, reportar:

```
| # | Severidade | Categoria | Equipe | Arquivo:Linha | Descrição | Risco | Correção Proposta | Issue Sugerida |
```

### Níveis de Severidade

| Nível | Significado | Ação |
|---|---|---|
| **CRITICAL** | Vulnerabilidade de segurança, data loss, crash em produção | Bloqueia merge/deploy |
| **HIGH** | Bug funcional, regressão, falha de UX crítica | Bloqueia merge |
| **MEDIUM** | Inconsistência, code smell, UX sub-ótima, falta de animação | Deve ser corrigido antes do próximo release |
| **LOW** | Sugestão de melhoria, refactor, otimização | Issue para backlog |
| **INFO** | Observação, documentação, pesquisa de melhoria | Documentar |

## Regras de Ouro

1. **Nada passa sem Issue** — Todo finding vira uma Issue no GitHub (Correção, Melhoria, ou Nova Função)
2. **PR sempre menciona Issue** — `Closes #XX` ou `Refs #XX` na descrição do PR
3. **Deploy só via PR aprovado** — Nenhum deploy direto na main
4. **prefers-reduced-motion é obrigatório** — Toda animação deve respeitar acessibilidade
5. **Skeleton em todo loading** — Nenhum spinner sem skeleton state
6. **Zero segredos no código** — API keys, tokens, passwords vão para env/secret manager
7. **Cobertura mínima 80%** — Unit tests em toda lógica de negócio
8. **E2E em fluxos críticos** — Login, trade, checkout, onboarding

## Reference Index

| File | Conteúdo | Carregar Quando |
|---|---|---|
| `references/github-workflow.md` | Padrão de Issues, PRs, deploys, labels, templates | Sempre (workflow base) |
| `references/motion-principles.md` | Skeleton, lazy loading, enter/exit animations, reduced-motion, audit checklist | Sempre que houver UI |
| `references/observability-quality-testing.md` | Sentry, Datadog, NewRelic, OpenTelemetry, Biome, Commitlint, Knip, Stryker, arch-contract, Playwright, Codecov | Sempre (full audit) |
| `references/security-uiux-audit.md` | OWASP checklist, bug detection, UI/UX QA, truncamento, overflow, responsividade, crypto/trading-specific risks | Sempre (security + UI/UX) |
| `references/enterprise-teams.md` | Organização por nichos/equipes, responsabilidades, handoff, templates de Issue por equipe | Sempre (enterprise report) |

## Integração com Motion Principles

Baseado em [kylezantos/design-motion-principles](https://github.com/kylezantos/design-motion-principles). Três lentes de motion design aplicadas com context-aware weighting:

- **Emil Kowalski** — Restraint & speed. "Should this animate at all?" (productivity tools)
- **Jakub Krehel** — Production polish. "Is this subtle enough?" (shipped consumer apps)
- **Jhey Tompkins** — Creative experimentation. "What could this become?" (playful contexts)

Ver `references/motion-principles.md` para recipes completos.

## Comandos de Invocação

```
# Full audit do projeto
Audite este projeto usando o skill enterprise-code-review --full

# Apenas segurança
Rode o checklist de segurança neste PR usando enterprise-code-review --security

# Apenas UI/UX + Motion
Audite a UI/UX e motion design deste projeto usando enterprise-code-review --uiux

# Quick gate (security + lint + tests)
Rode o quick gate pré-merge usando enterprise-code-review --quick
```

## Idioma

Todo output deve ser em **Português (BR/PT)** com termos técnicos em inglês quando aplicável, alinhado ao idioma do usuário.
