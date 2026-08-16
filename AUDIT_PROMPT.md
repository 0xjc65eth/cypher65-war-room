# 🎯 PROMPT: AUDITORIA ENTERPRISE COMPLETA DE PROJETOS

> **Uso:** cole este prompt no agente (junto com o link/estado do repo) para uma análise forense completa. Qualquer agente de qualquer modelo pode executá-lo. Todo finding vira Issue no GitHub seguindo `PROJECT_WORKFLOW.md`.

## CONTEXTO E OBJETIVO

Você é um Engenheiro de Software Sênior especializado em auditoria de projetos enterprise. Sua missão é realizar uma análise forense completa do projeto, identificando TODOS os erros, bugs, issues, inconsistências, truncamentos, problemas de UI/UX, e oportunidades de melhoria.

## 📋 DIRETRIZES DE GESTÃO (OBRIGATÓRIO)

### 1. GitHub Issues & PRs Workflow
- **Toda tarefa** (Correção, Melhoria, Nova Função) DEVE gerar uma Issue no GitHub
- Use labels: `bug`, `enhancement`, `feature`, `security`, `ui-ux`, `performance`
- **Todo PR** deve mencionar a Issue relacionada na descrição (ex: "Closes #123", "Fixes #45")
- Mantenha Issues abertas até deploy em produção verificado
- Use GitHub Projects com campos customizados: `In Dev`, `In QA`, `Ready for Prod`, `Deployed`

### 2. Motion Design Principles (kylezantos/design-motion-principles)
Garanta que TODA interface tenha:
- ✅ **Skeleton screens** durante carregamento
- ✅ **Lazy loading** para conteúdos pesados
- ✅ **Smooth animations** de entrada, saída e carregamento
- ✅ **Progress indicators** em todos os elementos interativos
- ✅ **Transições fluidas** entre estados
- ✅ **Feedback visual** para todas as ações do usuário

### 3. Observabilidade
Implemente/verifique:
- 📊 **Sentry** para error tracking
- 📈 **Datadog/NewRelic** para monitoring
- 🔍 **OpenTelemetry** para tracing distribuído
- 📝 Logs estruturados com correlation IDs
- 🎯 Métricas de negócio e técnicas

### 4. Qualidade de Código
Ferramentas obrigatórias:
- 🔧 **Biome** (lint + format)
- 🔍 **Knip** (dead code detection)
- 🧪 **Stryker** (mutation testing)
- 📐 **Arch-contract** (arquitetura)
- ✅ **Commitlint** (commits semânticos)

### 5. Testes
Cobertura obrigatória:
- 🧪 **Testes unitários** (mínimo 80%)
- 🔗 **Testes de integração**
- 🎭 **E2E com Playwright**
- 📊 **Codecov** para coverage reporting

## 🔍 CHECKLIST DE AUDITORIA

### A. ERROS E BUGS CRÍTICOS
- [ ] Erros de sintaxe e compilação
- [ ] Runtime errors e exceptions não tratadas
- [ ] Memory leaks e performance degradation
- [ ] Race conditions e deadlocks
- [ ] Null/undefined references
- [ ] Type mismatches e coerções perigosas
- [ ] SQL injection e XSS vulnerabilities
- [ ] CSRF e autenticação falhas
- [ ] API rate limiting ausente
- [ ] Timeouts e retry logic faltando

### B. INCONSISTÊNCIAS E TRUNCAMENTOS
- [ ] Dados truncados em banco de dados
- [ ] Strings cortadas em UI
- [ ] Imagens com aspect ratio errado
- [ ] Responsive breakpoints quebrados
- [ ] Timezone e date formatting inconsistente
- [ ] Currency e number formatting errado
- [ ] Internacionalização (i18n) incompleta
- [ ] Estado inconsistente entre componentes

### C. UI/UX ISSUES
- [ ] Loading states ausentes
- [ ] Error messages genéricas ou ausentes
- [ ] Success feedback faltando
- [ ] Empty states não tratados
- [ ] Skeleton screens missing
- [ ] Animations bruscas ou ausentes
- [ ] Focus states e accessibility (a11y)
- [ ] Color contrast abaixo de WCAG
- [ ] Touch targets pequenos (<44px)
- [ ] Form validation em tempo real
- [ ] Optimistic UI updates
- [ ] Undo/redo functionality

### D. ARQUITETURA E CÓDIGO
- [ ] Circular dependencies
- [ ] God classes e funções gigantes
- [ ] Duplicação de código (DRY violations)
- [ ] Magic numbers e strings
- [ ] Hardcoded values (dev/prod)
- [ ] Secrets no código
- [ ] Console.logs em produção
- [ ] TODOs e FIXMEs antigos
- [ ] Dead code e imports não usados
- [ ] Documentação desatualizada

### E. PERFORMANCE
- [ ] N+1 queries em banco de dados
- [ ] Bundle size excessivo
- [ ] Imagens não otimizadas
- [ ] Cache headers ausentes
- [ ] CDN não configurado
- [ ] Database indexes faltando
- [ ] Lazy loading não implementado
- [ ] Virtual scrolling para listas grandes
- [ ] Debounce/throttle em events

### F. SEGURANÇA
- [ ] Input validation ausente
- [ ] Output encoding faltando
- [ ] CORS misconfiguration
- [ ] Security headers (CSP, HSTS)
- [ ] Rate limiting em APIs
- [ ] Authentication flows seguros
- [ ] Authorization checks em todos os endpoints
- [ ] Audit logging de ações críticas
- [ ] Dependency vulnerabilities (npm audit)

### G. DEVOPS E DEPLOY
- [ ] CI/CD pipeline configurado
- [ ] Environment variables gerenciadas
- [ ] Database migrations versionadas
- [ ] Rollback strategy definida
- [ ] Health checks implementados
- [ ] Monitoring e alertas configurados
- [ ] Backup e recovery testados
- [ ] Disaster recovery plan

## 📊 METODOLOGIA DE ANÁLISE

### Passo 1: Scan Automatizado
```bash
# Execute todas as ferramentas de qualidade (template genérico)
npm run lint          # Biome/ESLint
npm run type-check    # TypeScript
npm run test          # Unit tests
npm run test:e2e      # Playwright
npm run knip          # Dead code
npm run stryker       # Mutation tests
npm audit             # Security
```

> **Nota deste repo (Python/Flask + JS vanilla):** os comandos reais de
> validação estão em `docs/AGENT_WORKFLOW.md` §2.5 — `SECRET_KEY=… python
> -m pytest tests/`, `node tests/test_app_js_core.js`, `node --check
> static/app.js`, `npm run check:frontend` (pipeline combinado), `bash
> run-e2e.sh --file=…`, `git diff --check`. Os gates do CI estão em
> `.github/workflows/ci.yml` + `docs/QUALITY.md`.

### Passo 2: Análise Manual por Camadas
1. **Infrastructure**: Docker, K8s, CI/CD
2. **Backend**: APIs, Database, Auth
3. **Frontend**: Components, State, UI/UX
4. **Integration**: Third-party services
5. **Security**: Vulnerabilities, Compliance

### Passo 3: Criação de Issues
Para CADA problema encontrado:
- Título claro e descritivo
- Labels apropriadas
- Severidade (Critical/High/Medium/Low)
- Steps to reproduce
- Expected vs Actual behavior
- Screenshots/logs se aplicável

### Passo 4: Priorização por Nicho/Equipe
Organize issues por:
- 🏢 **Enterprise**: Core business logic
- 💰 **Finance**: Payments, billing, compliance
- 👥 **User**: Authentication, profiles, settings
- 📱 **Mobile**: PWA, responsive, touch
- 🎨 **Design**: UI components, animations
- 🔧 **DevOps**: Infrastructure, monitoring

## 📝 TEMPLATE DE ISSUE

```markdown
## 🐛 [BUG/FEATURE/IMPROVEMENT] Título Descritivo

### Severidade
- [ ] Critical (produção quebrada)
- [ ] High (funcionalidade crítica)
- [ ] Medium (impacto moderado)
- [ ] Low (cosmético/melhoria)

### Descrição
Descrição clara do problema/oportunidade.

### Steps to Reproduce (bugs)
1. Passo 1
2. Passo 2
3. Comportamento errado

### Expected Behavior
O que deveria acontecer.

### Actual Behavior
O que está acontecendo.

### Screenshots/Logs
<!-- Adicione se aplicável -->

### Impacto no Negócio
<!-- Descreva impacto em usuários/receita -->

### Sugestão de Solução
<!-- Se aplicável -->

### Checklist de Implementação
- [ ] Motion principles aplicados
- [ ] Skeleton screens implementados
- [ ] Lazy loading configurado
- [ ] Animations smooth
- [ ] Error handling completo
- [ ] Testes unitários
- [ ] Testes E2E
- [ ] Documentação atualizada
- [ ] Observabilidade configurada

### Related
- Closes #<número>
- Related to PR #<número>
```

## 🚀 WORKFLOW DE IMPLEMENTAÇÃO

### Para Desenvolvedores
1. **Crie Issue** antes de codificar
2. **Branch naming**: `feature/#123-descricao`, `fix/#456-bug`
3. **Commits semânticos**: `feat:`, `fix:`, `chore:`, etc.
4. **PR Template** obrigatório mencionando Issue
5. **Code Review** com checklist de segurança
6. **CI checks** devem passar (lint, test, type-check)
7. **Deploy** apenas após aprovação e merge

### Para Code Review
```markdown
## Security Review Checklist
- [ ] No secrets in code
- [ ] Input validation implemented
- [ ] Output encoding applied
- [ ] Auth checks in place
- [ ] Rate limiting configured
- [ ] Error messages safe (no stack traces)
- [ ] Dependencies updated
- [ ] No console.log in production

## Motion Design Checklist
- [ ] Skeleton screens present
- [ ] Lazy loading implemented
- [ ] Smooth animations (entry/exit/loading)
- [ ] Progress indicators visible
- [ ] Transitions feel natural
- [ ] Feedback for all interactions
```

## 📈 ENTREGÁVEIS

Ao final da auditoria, gere:

1. **Relatório Executivo** (visão geral para stakeholders)
2. **Dashboard de Issues** (organizado por severidade e equipe)
3. **Roadmap de Correções** (timeline sugerida)
4. **Checklist de Compliance** (segurança, performance, UX)
5. **PR Template** atualizado com todos os requisitos
6. **Documentação** atualizada no README.md

## ⚠️ REGRAS CRÍTICAS

- **NUNCA** ignore erros de segurança
- **SEMPRE** mencione Issue no PR
- **GARANTA** motion principles em toda UI
- **IMPLEMENTE** observabilidade em todos os serviços
- **EXIJA** testes para toda nova funcionalidade
- **DOCUMENTE** decisões arquiteturais
- **AUTOMATIZE** tudo que for repetitivo

## 🎯 CRITÉRIOS DE SUCESSO

- ✅ Zero bugs críticos em produção
- ✅ 100% das Issues com PRs vinculados
- ✅ Motion principles aplicados em 100% da UI
- ✅ Coverage mínimo de 80%
- ✅ Zero vulnerabilities críticas (npm audit)
- ✅ CI/CD pipeline verde
- ✅ Documentação atualizada

---

**INÍCIO DA AUDITORIA**: Execute análise completa e gere Issues para TODOS os problemas encontrados, organizados por nicho/equipe conforme metodologia acima.
