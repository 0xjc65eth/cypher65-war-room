# Enterprise Organization: Niches & Teams

## Estrutura de Organização

Todo finding do code review deve ser atribuído a uma equipe responsável. As equipes seguem o modelo enterprise por nicho.

## Equipes e Responsabilidades

### Frontend
**Responsável por:**
- UI components, páginas, rotas
- Motion design, animações, skeleton loading
- Responsividade, acessibilidade (WCAG)
- State management (React/Redux/Zustand)
- Performance frontend (bundle size, LCP, FID, CLS)
- Dark mode, design system, tokens

**Issues que pertencem ao Frontend:**
- Truncamento de texto, overflow
- Falta de skeleton/loading states
- Animações ausentes ou incorretas
- `prefers-reduced-motion` não implementado
- Erros de TypeScript em arquivos `.tsx`
- Acessibilidade (ARIA, focus, contrast)
- Responsividade quebrada

**Stack de Referência:**
- React/Vite, TypeScript
- Framer Motion / Motion
- TailwindCSS / CSS Modules
- Playwright (E2E)
- Vitest + Testing Library (unit)

---

### Backend
**Responsável por:**
- API endpoints, controllers, services
- Database models, migrations, queries
- WebSocket connections, real-time data
- Trading logic, order execution
- External API integrations (Hyperliquid, exchanges)
- Background jobs, queues, workers

**Issues que pertencem ao Backend:**
- Race conditions em operações async
- SQL injection, query safety
- Error handling (try/catch, error middleware)
- API response inconsistency
- Missing input validation
- Decimal precision em cálculos financeiros
- WebSocket reconnection logic
- Rate limiting ausente

**Stack de Referência:**
- Node.js/Express ou Python/FastAPI
- PostgreSQL, Redis
- WebSocket (ws/socket.io)
- Jest/Vitest (unit), Supertest (integration)

---

### DevOps / SRE
**Responsável por:**
- CI/CD pipeline, GitHub Actions
- Deploy, rollback, environments
- Docker, containerization
- Infrastructure (AWS/GCP/Vercel)
- Observability stack (Sentry, Datadog, OpenTelemetry)
- Secrets management
- Database backups, disaster recovery

**Issues que pertencem ao DevOps/SRE:**
- CI gates ausentes ou insuficientes
- Deploy manual (deveria ser automatizado)
- Missing health checks
- Missing env var validation
- Secrets no código ou `.env` commitado
- Sem rollback automático
- Logs não estruturados
- Missing trace IDs
- Missing uptime monitoring

**Stack de Referência:**
- Docker, Docker Compose
- GitHub Actions
- Sentry, Datadog/New Relic, OpenTelemetry
- Jaeger/Tempo (tracing)
- Grafana/Prometheus (metrics)

---

### Security
**Responsável por:**
- OWASP compliance
- Auth/authorization audit
- Dependency vulnerabilities
- Secrets management (KMS, Vault)
- Penetration testing recommendations
- Crypto/wallet security
- API security (rate limits, CORS, CSP)

**Issues que pertencem ao Security:**
- Hardcoded secrets (API keys, tokens)
- Missing auth middleware
- JWT configuration issues
- CORS misconfigured
- Missing CSRF protection
- Vulnerable dependencies (npm audit)
- Crypto private key exposure
- Missing rate limiting
- SQL injection risks
- XSS risks

**Stack de Referência:**
- npm audit, Snyk, GitHub Dependabot
- CodeQL (GitHub)
- OWASP ZAP
- Helmet.js, express-rate-limit

---

### QA (Quality Assurance)
**Responsável por:**
- Test coverage (unit, integration, E2E)
- Mutation testing (Stryker)
- Code coverage tracking (Codecov)
- Test data management
- E2E test maintenance (Playwright)
- Regression testing
- Bug reproduction and verification

**Issues que pertencem ao QA:**
- Missing tests para lógica crítica
- Coverage abaixo de 80%
- E2E flaky tests
- Missing edge case tests
- No snapshot tests
- Missing integration tests
- Mutation score abaixo de 60%

**Stack de Referência:**
- Vitest/Jest (unit)
- Playwright (E2E)
- Codecov (coverage)
- Stryker (mutation testing)
- Testing Library (component tests)

---

### Product
**Responsável por:**
- Feature requirements, acceptance criteria
- UX flows, user journey
- Product backlog prioritization
- User feedback integration
- Analytics tracking
- Roadmap alignment

**Issues que pertencem ao Product:**
- Missing acceptance criteria
- UX flow quebrado
- Feature sem tracking/analytics
- Inconsistência entre design e implementação
- Missing empty/error states
- Missing user feedback mechanism

---

### Data / AI
**Responsável por:**
- AI integrations (Grok, Claude, Gemini APIs)
- Trading strategy models
- Data pipeline, ETL
- Machine learning models
- Probability calculations (mining, trading)
- Statistical analysis, backtesting

**Issues que pertencem ao Data/AI:**
- AI prompt injection risks
- Missing model validation
- Backtesting gaps
- Data pipeline errors
- Missing statistical confidence intervals
- Model drift detection ausente
- AI API key management

**Stack de Referência:**
- Python (pandas, numpy, scikit-learn)
- OpenAI/Anthropic/Grok API
- Jupyter (analysis)
- Redis (caching model results)

---

## Handoff Matrix

Quando um finding toca múltiplas equipes:

| Origem → Destino | Motivo Comum |
|---|---|
| Frontend → Backend | Dados faltando na API para renderizar UI |
| Backend → DevOps | Env vars não configuradas, infra necessária |
| Security → Backend | Auth issue encontrado no código backend |
| Security → DevOps | Secrets expostos, secrets management necessário |
| QA → Frontend | E2E flaky por animation timing |
| QA → Backend | Integration test falha por API instability |
| Product → Frontend | UX flow não corresponde ao design |
| Data/AI → Backend | AI integration precisa de endpoint seguro |

## Template de Issue por Equipe

Cada Issue DEVE ter a label da equipe responsável:

```
Labels: [tipo], [equipe], [severidade]

Exemplos:
[correction] [frontend] [high] - Truncamento em card de saldo em mobile
[security] [backend] [critical] - API key hardcoded em trading service
[improvement] [devops] [medium] - Adicionar OpenTelemetry tracing
[testing] [qa] [low] - Adicionar test E2E para wallet connect
[new-feature] [product] [high] - Adicionar dark mode toggle
```

## Sprint Planning Input

Ao final do audit, gerar um resumo por equipe:

```
## Resumo do Audit por Equipe

### Frontend
- CRITICAL: 0 | HIGH: 2 | MEDIUM: 5 | LOW: 3
- Top prioridade: Skeleton loading em dashboard, Animação de modal

### Backend
- CRITICAL: 1 | HIGH: 3 | MEDIUM: 4 | LOW: 2
- Top prioridade: Race condition em order execution, Decimal precision

### DevOps/SRE
- CRITICAL: 0 | HIGH: 1 | MEDIUM: 3 | LOW: 1
- Top prioridade: Adicionar Sentry release tracking

### Security
- CRITICAL: 1 | HIGH: 2 | MEDIUM: 1 | LOW: 0
- Top prioridade: Remover hardcoded API keys

### QA
- CRITICAL: 0 | HIGH: 1 | MEDIUM: 2 | LOW: 1
- Top prioridade: Coverage abaixo de 80% em trading module
```
