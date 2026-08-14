# Security, Bug Detection & UI/UX Audit

## 1. Security Code Review (OWASP + Trading/Crypto Specific)

### OWASP Top 10 Checklist

#### A01: Broken Access Control
- [ ] Toda rota protegida tem middleware de auth
- [ ] Validação de ownership (user só acessa seus próprios recursos)
- [ ] IDOR check (não aceitar `?userId=X` sem validação)
- [ ] JWT expiry configurado (< 24h para access, 7d para refresh)
- [ ] Role-based access control (RBAC) implementado

#### A02: Cryptographic Failures
- [ ] Senhas com bcrypt/argon2 (nunca MD5/SHA1)
- [ ] JWT assinado com RS256 ou ES256 (não HS256 com secret fraco)
- [ ] API keys/tokens em env vars ou secret manager (NUNCA no código)
- [ ] HTTPS forçado (redirect HTTP → HTTPS)
- [ ] HSTS header configurado
- [ ] Crypto wallet private keys NUNCA logadas, NUNCA em DB plaintext

#### A03: Injection
- [ ] Parameterized queries (SQL injection)
- [ ] Input sanitization (XSS)
- [ ] No `eval()` ou `new Function()` com user input
- [ ] No `dangerouslySetInnerHTML` sem sanitização
- [ ] Command injection (shell exec com user input)
- [ ] NoSQL injection (MongoDB $where, $expr)

#### A04: Insecure Design
- [ ] Rate limiting em todas as rotas de auth
- [ ] Account lockout após N tentativas falhadas
- [ ] CSRF tokens em forms
- [ ] CORS configurado com whitelist (não `*`)
- [ ] Security headers (Helmet.js)
- [ ] CSP (Content-Security-Policy) configurado

#### A05: Security Misconfiguration
- [ ] Debug mode OFF em produção
- [ ] Stack traces não expostos em produção
- [ ] Default credentials removidos
- [ ] Error messages genéricos (não vazar info do sistema)
- [ ] `.env` no `.gitignore`
- [ ] `.env.example` sem valores reais

#### A06: Vulnerable Dependencies
- [ ] `npm audit` passing (0 high, 0 critical)
- [ ] Dependabot/Renovate habilitado
- [ ] Lockfile commitado (`package-lock.json` / `yarn.lock`)
- [ ] Dependências atualizadas (< 6 meses de atraso)

#### A07: Auth Failures
- [ ] Session invalidation no logout
- [ ] Refresh token rotation
- [ ] 2FA disponível (TOTP)
- [ ] Password complexity enforcement
- [ ] No password reset via email inseguro (token com expiry)

#### A08: Software & Data Integrity Failures
- [ ] Subresource Integrity (SRI) em scripts de terceiros
- [ ] Webhook signature verification
- [ ] Signed commits (GPG)
- [ ] Dependency pinning (exact versions)

#### A09: Logging & Monitoring Failures
- [ ] Logs de auth (login success/failure)
- [ ] Logs de ações sensíveis (trade, withdraw, config change)
- [ ] Alertas em atividades suspeitas
- [ ] Log retention policy

#### A10: SSRF (Server-Side Request Forgery)
- [ ] URL validation em fetch/request server-side
- [ ] Allowlist de domínios para outgoing requests
- [ ] Block internal IPs (169.254.x.x, 10.x.x.x, 172.16.x.x, 192.168.x.x)

### Trading/Crypto/DeFi Specific Security

- [ ] Private keys em KMS/HSM ou encrypted at rest
- [ ] Transaction signing em ambiente isolado
- [ ] Slippage protection em trades
- [ ] Max position size limit
- [ ] Circuit breaker (pausa trading se loss > threshold)
- [ ] API rate limit respeitado (exchange APIs)
- [ ] WebSocket reconnection com backoff exponencial
- [ ] Order validation antes de submit (prevents fat finger)
- [ ] No hardcoded wallet addresses de teste em produção
- [ ] Gas price oracle (prevents overpaying)
- [ ] MEV protection (flashbots/private mempool se aplicável)
- [ ] Multi-sig para withdrawals manuais

## 2. Bug & Error Detection

### Checklist de Bugs Comuns

#### Logic Errors
- [ ] Race conditions em operações async (Promise.all sem erro handling)
- [ ] Off-by-one errors em loops
- [ ] Floating point comparison (`===` com floats)
- [ ] Null/undefined access sem optional chaining
- [ ] Array mutation em state (React: criar novo array)
- [ ] useEffect sem cleanup (memory leak)
- [ ] useEffect com dependencies incorretas
- [ ] Async operations sem abort signal (stale data)
- [ ] Error handling swallow (`catch {}` vazio)
- [ ] Promise sem catch (unhandled rejection)

#### Data Handling
- [ ] Integer overflow em cálculos financeiros
- [ ] Decimal precision em valores monetários (usar BigNumber/Decimal.js)
- [ ] Timezone handling (sempre UTC no backend, formatar no frontend)
- [ ] Date parsing (não usar `new Date(string)` sem validação)
- [ ] Number formatting (locale-aware)
- [ ] String encoding (UTF-8 consistente)
- [ ] SQL injection via ORM raw queries
- [ ] Type coercion bugs (`==` vs `===`)

#### State Management
- [ ] State updates em loop infinito
- [ ] Stale closure em event handlers
- [ ] State não sincronizado entre componentes
- [ ] Cache invalidation incorreta
- [ ] Optimistic UI sem rollback em erro
- [ ] WebSocket data não atualiza UI corretamente

#### API Integration
- [ ] Retry sem backoff (thundering herd)
- [ ] No timeout em requests externos
- [ ] Response não validado (schema validation)
- [ ] Error response não tratado (assumir success sempre)
- [ ] Pagination não tratada
- [ ] Rate limit não respeitado
- [ ] WebSocket não reconecta em disconnect

## 3. Inconsistency Detection

- [ ] Nome de variáveis inconsistentes (camelCase vs snake_case misturados)
- [ ] Estrutura de resposta de API inconsistente (algumas com `data`, outras direto)
- [ ] Error handling inconsistente (alguns try/catch, outros .catch(), outros nada)
- [ ] Imports misturados (CommonJS e ESM no mesmo projeto)
- [ ] Config duplicada (hardcoded em vez de centralizada)
- [ ] Tipos inconsistentes (algumas funções retornam string, outras number para mesmo conceito)
- [ ] Naming de rotas inconsistente (RESTful vs RPC style misturados)
- [ ] Date format inconsistente entre endpoints
- [ ] Status codes HTTP incorretos (200 para erros, 500 para not found)
- [ ] Console.log em produção (usar logger estruturado)

## 4. UI/UX Audit

### Truncamento e Overflow
- [ ] Texto longo trunca com ellipsis (`text-overflow: ellipsis`)
- [ ] Tabelas têm scroll horizontal em mobile
- [ ] Cards têm `overflow: hidden` ou `min-width`
- [ ] Modais não excedem viewport em mobile
- [ ] Imagens têm `max-width: 100%` e `object-fit`
- [ ] Long numbers (saldo, P&L) não quebram layout
- [ ] Selectores/dropdowns não overflow em telas pequenas
- [ ] Tooltips não saem da tela
- [ ] Notificações/toasts não sobrepoem conteúdo crítico

### Responsividade
- [ ] Breakpoints: mobile-first (375px → 768px → 1024px → 1440px)
- [ ] Touch targets mínimo 44x44px
- [ ] Font size mínimo 14px em mobile
- [ ] Safe area insets (notch) respeitados
- [ ] Layout não quebra com zoom 200%
- [ ] Tabelas têm versão card em mobile
- [ ] Sidebar vira drawer/bottom nav em mobile

### Loading States
- [ ] Skeleton em todo carregamento de dados (ver motion-principles.md)
- [ ] Empty states com ilustração + call to action
- [ ] Error states com retry button
- [ ] Loading buttons desabilitados (prevent double submit)
- [ ] Offline indicator
- [ ] Progressive loading (mostrar dados parciais quando possível)

### Accessibility (WCAG 2.1 AA)
- [ ] Semantic HTML (`<button>` não `<div onClick>`)
- [ ] ARIA labels em elementos não semânticos
- [ ] Focus visible (outline não removido)
- [ ] Focus trap em modais
- [ ] Alt text em imagens
- [ ] Color contrast ratio > 4.5:1 (texto normal), > 3:1 (texto grande)
- [ ] Keyboard navigation funcional (Tab order lógico)
- [ ] Screen reader testing
- [ ] `prefers-reduced-motion` respeitado
- [ ] `prefers-color-scheme: dark` suportado

### Visual Consistency
- [ ] Design system/tokens (cores, espaçamentos, tipografia centralizados)
- [ ] Espaçamento consistente (8px grid)
- [ ] Border radius consistente
- [ ] Shadow scale definida
- [ ] Font scale definida
- [ ] Color palette com semântica (success, warning, error, info)
- [ ] Dark mode completo (não apenas fundo escuro)

### UX Patterns
- [ ] Confirmação em ações destrutivas (delete, withdraw)
- [ ] Undo para ações reversíveis
- [ ] Toast feedback para toda ação do usuário
- [ ] Breadcrumbs em navegação profunda
- [ ] Page title dinâmico (router-based)
- [ ] Favicon
- [ ] 404 page customizada
- [ ] Loading bar no topo da página (NProgress ou similar)

## 5. Improvement Research

Após completar todos os checks acima, pesquisar ativamente:

### O que pesquisar
- [ ] Novas libs que resolvem problemas existentes no projeto
- [ ] Patterns de projetos similares (trading bots, DeFi dashboards)
- [ ] Performance optimizations (bundle size, lazy loading, code splitting)
- [ ] DX improvements (faster builds, better tooling)
- [ ] Security best practices atualizadas
- [ ] Browser support matrix (caniuse para features usadas)
- [ ] A11y improvements (axe-core, Lighthouse)
- [ ] SEO/SSR se aplicável
- [ ] PWA capabilities
- [ ] Monitoring improvements (better alerts, dashboards)

### Como reportar melhorias

```
| Melhoria | Categoria | Impacto | Esforço | Issue Sugerida | Prioridade |
|---|---|---|---|---|---|
```

Prioridade: P0 (urgente), P1 (próximo sprint), P2 (backlog), P3 (nice to have)
