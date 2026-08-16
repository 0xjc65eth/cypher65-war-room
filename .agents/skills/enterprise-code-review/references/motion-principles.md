# Motion Principles: Skeleton, Lazy Loading, Smooth Animations

Baseado em [kylezantos/design-motion-principles](https://github.com/kylezantos/design-motion-principles) (v2.1.0).

## Três Lenses de Motion Design

Aplicar context-aware weighting baseado no tipo de projeto:

| Lens | Filosofia | Pergunta-chave | Melhor para |
|---|---|---|---|
| **Emil Kowalski** | Restraint & speed | "Should this animate at all?" | Productivity tools, alta frequência |
| **Jakub Krehel** | Production polish | "Is this subtle enough?" | Consumer apps, refinamento profissional |
| **Jhey Tompkins** | Creative experimentation | "What could this become?" | Kids apps, portfolios, contexts lúdicos |

### Weighting por Tipo de Projeto

| Tipo de Projeto | Primário | Secundário | Seletivo |
|---|---|---|---|
| SaaS dashboard / trading bot | Emil | Jakub | Jhey (empty states) |
| E-commerce | Jakub | Emil | Jhey (product showcase) |
| Marketing/landing page | Jakub | Jhey | Emil (forms, nav) |
| Kids app / Educational | Jakub | Jhey | Emil (high-freq interactions) |
| Mobile app | Jakub | Emil | Jhey (delighters) |

## Checklist Obrigatório de Motion/UI

### 1. Skeleton Loading (OBRIGATÓRIO em todo carregamento)

Toda interface que carrega dados assíncronos DEVE ter skeleton state. Nunca usar apenas spinner.

```css
/* Skeleton base */
.skeleton {
  background: linear-gradient(90deg,
    var(--skeleton-base, #e0e0e0) 25%,
    var(--skeleton-shine, #f0f0f0) 50%,
    var(--skeleton-base, #e0e0e0) 75%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s infinite;
  border-radius: 4px;
}

@keyframes skeleton-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Dark mode */
@media (prefers-color-scheme: dark) {
  .skeleton {
    --skeleton-base: #2a2a2a;
    --skeleton-shine: #3a3a3a;
  }
}
```

**Onde aplicar skeleton:**
- Cards de dados (preço, saldo, posição)
- Tabelas e listas
- Dashboards
- Modais com conteúdo async
- Imagens (blur-up placeholder)

### 2. Lazy Loading (OBRIGATÓRIO em tudo que é pesado)

```jsx
// React.lazy + Suspense
const Dashboard = React.lazy(() => import('./Dashboard'));

<Suspense fallback={<DashboardSkeleton />}>
  <Dashboard />
</Suspense>

// Intersection Observer para imagens
<img loading="lazy" src="..." alt="..." />

// Para componentes pesados (charts, maps)
const HeavyChart = React.lazy(() => import('./HeavyChart'));
```

**Verificar:**
- [ ] Imagens usam `loading="lazy"`
- [ ] Componentes pesados (charts, maps, editors) usam `React.lazy`
- [ ] Routes usam lazy loading
- [ ] Dados grandes usam virtualização (react-window, @tanstack/react-virtual)
- [ ] Web Workers para computação pesada (não bloquear main thread)

### 3. Smooth Enter/Exit Animations

#### Enter Animation (Jakub pattern)

```jsx
initial={{ opacity: 0, translateY: "calc(-100% - 4px)", filter: "blur(4px)" }}
animate={{ opacity: 1, translateY: 0, filter: "blur(0px)" }}
transition={{ type: "spring", duration: 0.45, bounce: 0 }}
```

#### Exit Animation (subtle - Jakub)

```jsx
// Exit SEMPRE mais sutil que enter
exit={{ translateY: "-12px", opacity: 0, filter: "blur(4px)" }}
// NUNCA: exit={{ scale: 0 }} — movimento não natural
```

#### AnimatePresence para exit animations

```jsx
<AnimatePresence mode="wait">
  {isVisible && (
    <motion.div
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9 }}
      transition={{ duration: 0.2 }}
    >
      Content
    </motion.div>
  )}
</AnimatePresence>
```

### 4. Loading & Progress Feedback

Todo botão/ação assíncrona deve ter:

| Estado | UI | Animação |
|---|---|---|
| Idle | Botão normal | — |
| Loading | Spinner + texto "Processando..." | Skeleton ou shimmer |
| Success | Check icon + cor verde | Scale-in do ícone |
| Error | X icon + cor vermelha + mensagem | Shake animation |

```jsx
// Progress bar para operações longas (deploy, upload, sync)
<motion.div
  initial={{ scaleX: 0 }}
  animate={{ scaleX: progress }}
  transition={{ type: "spring", stiffness: 100, damping: 20 }}
  style={{ transformOrigin: "left" }}
/>
```

### 5. Duration Guidelines

| Context | Duration |
|---|---|
| Productivity UI (trading dashboard) | < 300ms, ideal 180ms |
| Production polish (consumer app) | 200-500ms |
| Creative/playful | O que servir ao efeito |
| Hover states | 150ms |
| Modal/dialog open | 200-300ms |
| Toast notifications | 300ms in, 200ms out |
| Page transitions | 200-400ms |

### 6. Easing (NUNCA usar ease padrão do CSS)

```css
/* Custom Bezier curves (sempre) */
:root {
  --ease-out-expo: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-in-out-quart: cubic-bezier(0.76, 0, 0.24, 1);
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* Por contexto */
.enter { transition-timing-function: ease-out; }  /* elementos entrando */
.exit { transition-timing-function: ease-in; }     /* elementos saindo */
.state-change { transition-timing-function: ease-in-out; }
.progress { transition-timing-function: linear; } /* progress bars */
```

### 7. Accessibility — prefers-reduced-motion (OBRIGATÓRIO)

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

**Regra**: Toda animação deve ter fallback para reduced-motion. Sem exceções.

### 8. Anti-Patterns (AI-slop motion — FLAGGAR e CORRIGIR)

- Pulsing indicators em tudo
- Hover-scale em todos os elementos
- Stagger-spam (muitos elementos staggered sem propósito)
- Bounce em contextos profissionais/enterprise
- Animação de > 500ms em high-frequency interactions
- Scale from 0 (usar 0.9 com opacity)
- Animações que não podem ser interrompidas
- Linear easing em interações (parece robótico)

### 9. Audit Checklist de Motion

- [ ] Todo loading tem skeleton (não apenas spinner)
- [ ] Imagens e componentes pesados usam lazy loading
- [ ] Enter animations usam opacity + translateY + blur
- [ ] Exit animations são mais sutis que enter
- [ ] AnimatePresence envolve componentes condicionais
- [ ] Botões têm loading state com feedback visual
- [ ] Progress bars para operações longas
- [ ] Easing custom (não `ease` padrão)
- [ ] `prefers-reduced-motion` implementado
- [ ] Durações dentro do range do contexto
- [ ] Sem anti-patterns de AI-slop
- [ ] Origin-aware animations (transform-origin correto)
- [ ] Interruptible animations (CSS transitions ao invés de keyframes para state changes)
