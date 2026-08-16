# Observability, Quality, Linting & Testing Stack

## 1. Observability

### Sentry (Error Tracking)

**Setup obrigatório:**

```bash
npm install @sentry/react @sentry/node @sentry/tracing
# ou Python
pip install sentry-sdk
```

**Checklist Sentry:**
- [ ] DSN configurado via env var `SENTRY_DSN`
- [ ] Source maps enviados em build de produção
- [ ] Release tracking habilitado (`Sentry.setRelease(commitSha)`)
- [ ] User context setado em login (`Sentry.setUser({ id, email })`)
- [ ] Breadcrumbs habilitados (fetch, console, click)
- [ ] Performance monitoring habilitado (tracesSampleRate)
- [ ] BeforeSend hook para PII scrubbing (remover tokens, senhas)
- [ ] Tags customizadas (environment, version, route)
- [ ] Integrado com GitHub (auto-create Issues do Sentry)
- [ ] Alertas configurados no Slack/Discord

### Datadog / New Relic (APM & Metrics)

**Checklist APM:**
- [ ] APM agent instalado (dd-trace para Node, dd-trace-py para Python)
- [ ] Service map visível
- [ ] Trace por request HTTP
- [ ] Custom metrics para regras de negócio (ordens executadas, P&L, latência)
- [ ] Dashboards para: CPU, Memory, Event Loop Lag, Request Rate, Error Rate, p95/p99 latency
- [ ] Alertas SLO/SLI (error rate > 1%, p99 > 500ms)
- [ ] Log correlation (trace ID in logs)
- [ ] Synthetic monitoring nos endpoints críticos

### OpenTelemetry (Distributed Tracing)

```bash
npm install @opentelemetry/api @opentelemetry/sdk-node \
  @opentelemetry/auto-instrumentations-node \
  @opentelemetry/exporter-trace-otlp-http
```

**Checklist OpenTelemetry:**
- [ ] SDK inicializado antes do app (no entrypoint, antes de imports)
- [ ] Auto-instrumentação habilitada (HTTP, Express, pg, redis, ioredis)
- [ ] OTLP exporter configurado (para Jaeger, Tempo, ou Datadog)
- [ ] Custom spans em funções de negócio (`tracer.startSpan("executeTrade")`)
- [ ] Propagação de contexto entre serviços (W3C Trace Context headers)
- [ ] Resource attributes (service.name, service.version, environment)
- [ ] Metrics API uso para contadores/histogramas custom

### Estrutura de Logs

```typescript
// Estrutura JSON estruturada obrigatória
{
  "timestamp": "2026-08-14T10:46:00Z",
  "level": "info|warn|error|debug",
  "service": "cypher65-backend",
  "traceId": "...",
  "spanId": "...",
  "message": "Trade executed",
  "userId": "...",
  "orderId": "...",
  "metadata": { ... }
}
```

**Regras de logging:**
- [ ] NUNCA logar secrets (API keys, passwords, JWT tokens, wallet private keys)
- [ ] Logs estruturados (JSON), não `console.log` puro em produção
- [ ] Log levels apropriados (debug em dev, info+ em prod)
- [ ] Request/response logging com ID correlation
- [ ] Error logs incluem stack trace completo

## 2. Quality & Lint

### Biome (Linter + Formatter)

```bash
npm install --save-dev @biomejs/biome
```

```json
// biome.json
{
  "linter": {
    "enabled": true,
    "rules": {
      "recommended": true,
      "security": {
        "noDangerouslySetInnerHtml": "error",
        "noGlobalEval": "error"
      },
      "suspicious": {
        "noExplicitAny": "warn",
        "noArrayIndexKey": "warn"
      },
      "style": {
        "useImportType": "error",
        "useConst": "error"
      },
      "complexity": {
        "noExcessiveCognitiveComplexity": "warn"
      }
    }
  },
  "formatter": {
    "enabled": true,
    "indentStyle": "space",
    "indentWidth": 2,
    "lineWidth": 100
  },
  "organizeImports": { "enabled": true }
}
```

**Checklist Biome:**
- [ ] `biome.json` na raiz do projeto
- [ ] Script `lint` no package.json: `biome check .`
- [ ] Script `format`: `biome format --write .`
- [ ] Pre-commit hook com `biome check --staged`
- [ ] CI gate: `biome ci` falha o build se houver erros
- [ ] Regras de segurança habilitadas

### Commitlint

```bash
npm install --save-dev @commitlint/cli @commitlint/config-conventional
```

```javascript
// commitlint.config.js
export default {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [2, 'always', [
      'feat', 'fix', 'improvement', 'security', 'docs', 'test', 'chore', 'refactor', 'perf', 'ci', 'build'
    ]],
    'subject-max-length': [2, 'always', 72],
    'body-max-line-length': [1, 'always', 100],
  },
};
```

**Checklist Commitlint:**
- [ ] `commitlint.config.js` configurado
- [ ] Husky `commit-msg` hook: `npx --no-install commitlint --edit $1`
- [ ] Types customizados alinhados com tipos de Issue

### Knip (Dead Code Detection)

```bash
npm install --save-dev knip
```

```json
// knip.json
{
  "entry": ["src/index.ts", "src/server.ts"],
  "project": ["src/**/*.ts", "src/**/*.tsx"],
  "ignore": ["src/**/*.test.ts", "src/**/*.spec.ts"],
  "ignoreBinaries": ["tsx"]
}
```

**Checklist Knip:**
- [ ] `knip.json` configurado com entry points corretos
- [ ] Script `knip` no package.json
- [ ] CI gate: `knip --no-progress` falha se houver dead code
- [ ] Zero exports não utilizados
- [ ] Zero arquivos órfãos

### Stryker (Mutation Testing)

```bash
npm install --save-dev @stryker-mutator/core
```

```json
// stryker.config.json
{
  "packageManager": "npm",
  "reporters": ["html", "clear-text", "progress"],
  "testRunner": "jest",
  "coverageAnalysis": "perTest",
  "mutate": ["src/**/*.ts", "!src/**/*.test.ts", "!src/**/*.spec.ts"],
  "thresholds": { "high": 80, "low": 60, "break": 50 }
}
```

**Checklist Stryker:**
- [ ] `stryker.config.json` configurado
- [ ] Script `mutation-test` no package.json
- [ ] Mutation score > 60% (mínimo), ideal > 80%
- [ ] Rodar em CI (pelo menos em PRs de lógica de negócio crítica)
- [ ] Mutantes sobreviventes viram Issues

### arch-contract (Architecture Enforcement)

```bash
npm install --save-dev arch-contract
```

**Checklist arch-contract:**
- [ ] Regras de dependência definidas (ex: frontend não importa de infra)
- [ ] Camadas respeitadas (UI → Service → Repository → DB)
- [ ] Sem imports circulares
- [ ] Banir imports cross-feature não permitidos
- [ ] CI gate verifica violações de arquitetura

## 3. Testing

### Unit Tests (Jest / Vitest)

**Checklist Unit:**
- [ ] Cobertura mínima 80% em lógica de negócio
- [ ] Cobertura mínima 60% em UI components
- [ ] Cada função pura tem pelo menos 3 test cases (happy path, edge case, error case)
- [ ] Mocks para dependências externas (API, DB, WebSocket)
- [ ] Snapshots para componentes UI estáveis
- [ ] Testes de trading logic (entry/exit, P&L calculation, position sizing)
- [ ] Testes de crypto/wallet (address validation, transaction signing)

### Integration Tests

**Checklist Integration:**
- [ ] Testes de API endpoints (request → response)
- [ ] Testes com DB real (testcontainers ou test DB)
- [ ] Testes de WebSocket connections
- [ ] Testes de auth flow (login → token → protected route → logout)
- [ ] Testes de third-party API integration com mocks (Hyperliquid, exchange APIs)
- [ ] Testes de Redis/queue workers

### E2E Tests (Playwright)

```bash
npm install --save-dev @playwright/test
```

```typescript
// playwright.config.ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: [['html'], ['junit', { outputFile: 'test-results/junit.xml' }]],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
    { name: 'firefox', use: { browserName: 'firefox' } },
    { name: 'webkit', use: { browserName: 'webkit' } },
  ],
});
```

**Checklist E2E:**
- [ ] Fluxos críticos cobertos: login, trade execution, wallet connect, checkout
- [ ] Multi-browser (Chromium, Firefox, WebKit)
- [ ] Mobile viewport tests
- [ ] Screenshot on failure
- [ ] Trace on first retry
- [ ] Roda em CI (GitHub Actions)
- [ ] DB reset entre testes (ou isolated test data)

### Codecov (Coverage Tracking)

**Checklist Codecov:**
- [ ] Coverage report gerado em CI (`--coverage` no test runner)
- [ ] Codecov badge no README
- [ ] Coverage threshold no `codecov.yml` (target 80%, fail 60%)
- [ ] Coverage diff em cada PR (Codecov comment)
- [ ] Patch coverage check (novas linhas devem ter > 80% coverage)

```yaml
# codecov.yml
coverage:
  status:
    project:
      default:
        target: 80%
        threshold: 5%
    patch:
      default:
        target: 80%
        threshold: 5%
```

## 4. CI/CD Pipeline Gates

```yaml
# .github/workflows/ci.yml (resumo dos gates)
name: CI
on: [push, pull_request]

jobs:
  quality:
    steps:
      - run: npm ci
      - run: npx biome check .          # Lint + format check
      - run: npx knip --no-progress      # Dead code check
      - run: npm run typecheck           # TypeScript check
      - run: npm run lint:arch           # arch-contract check

  test:
    steps:
      - run: npm ci
      - run: npm test -- --coverage      # Unit + integration
      - run: npx playwright test         # E2E
      - uses: codecov/codecov-action@v4  # Upload coverage

  security:
    steps:
      - run: npm audit --audit-level=high
      - uses: github/codeql-action/init@v3
      - uses: github/codeql-action/analyze@v3
      - run: npx stryker run              # Mutation testing (em PRs críticos)
```

### Gates que BLOQUEIAM merge:

1. Biome check falha → BLOCK
2. TypeScript errors → BLOCK
3. Knip encontra dead code → BLOCK
4. Test unit/integration falha → BLOCK
5. E2E falha → BLOCK
6. `npm audit` com vulnerabilidade high/critical → BLOCK
7. Codecov abaixo do threshold → BLOCK
