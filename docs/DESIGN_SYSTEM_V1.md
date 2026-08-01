# 🎨 CYPHER65 DESIGN SYSTEM v1

> Design tokens e padrões visuais do **Cypher65 War Room** — dashboard de mineração Bitcoin
> Inspirado em Bloomberg Terminal + cyberpunk hacker aesthetic + SpaceX mission control
> **3 de agosto de 2026**

---

## 1. CORES

### 1.1 Paleta Base (Backgrounds)

| Token | Valor | Uso |
|-------|-------|-----|
| `--bg-deep` | `#0C0B0A` | Fundo mais profundo (fora do grid, matrix canvas) |
| `--bg-base` | `#141311` | Fundo principal do dashboard |
| `--bg-surface` | `#1C1A18` | Cards, painéis, superfícies elevadas |
| `--bg-elevated` | `#24211D` | Hover de painéis, modais |
| `--bg-hover` | `#2D2925` | Hover de botões, itens de lista |
| `--bg-glass` | `rgba(20, 19, 17, 0.78)` | Efeito glass (backdrop-filter: blur) |

### 1.2 Bordas

| Token | Valor | Uso |
|-------|-------|-----|
| `--border-subtle` | `rgba(255,255,255,0.06)` | Borda invisível (separação sutil) |
| `--border-default` | `rgba(255,255,255,0.10)` | Borda padrão de painéis |
| `--border-strong` | `rgba(255,255,255,0.16)` | Borda de destaque, inputs focados |
| `--border-accent` | `rgba(247,147,26,0.25)` | Borda com acento BTC (hover) |

### 1.3 Texto

| Token | Valor | Uso |
|-------|-------|-----|
| `--text-primary` | `#EDE8E3` | Títulos, valores principais, labels |
| `--text-secondary` | `#9D968D` | Subtítulos, métricas secundárias |
| `--text-tertiary` | `#5E5952` | Placeholders, timestamps, legendas |
| `--text-disabled` | `#383430` | Itens desabilitados |

### 1.4 Cores de Acento

| Token | Valor | Significado |
|-------|-------|-------------|
| `--accent-btc` | `#F7931A` | Bitcoin orange — valor financeiro, profit, destaque principal |
| `--accent-green` | `#10B981` | Verde — sucesso, online, positivo |
| `--accent-red` | `#EF4444` | Vermelho — erro, offline, alerta crítico |
| `--accent-blue` | `#3B82F6` | Azul — informação, network, links |
| `--accent-purple` | `#8B5CF6` | Roxo — eventos especiais, high-diff, raridade |
| `--accent-teal` | `#14B8A6` | Teal — métricas de pool, secundário |

### 1.5 Fundos de Acento (10% opacidade)

Cada cor de acento tem um fundo correspondente com 10% de opacidade: `--accent-{color}-bg`

> **Exemplo:** `--accent-btc-bg: rgba(247, 147, 26, 0.10)`

### 1.6 Gradientes

| Local | Gradiente | Uso |
|-------|-----------|-----|
| Gauge canvas | `#00ff9f → #06d6f0 → #f5b942` | Arco de progresso nos semicírculos |
| Topbar | Linear horizontal sutil | Barra superior |
| Botões primários | Variação do accent-btc | Botão de ação principal |

### 1.7 Shadow

| Token | Valor | Uso |
|-------|-------|-----|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.5)` | Cards, badges |
| `--shadow-md` | `0 4px 16px rgba(0,0,0,0.6)` | Painéis, modais |
| `--shadow-lg` | `0 8px 40px rgba(0,0,0,0.7)` | Modais grandes, overlays |
| `--shadow-glow` | `0 0 28px rgba(247,147,26,0.12)` | Glow BTC em hover/destaque |
| `--glass-highlight` | `inset 0 1px 1px rgba(255,255,255,0.05)` | Brilho sutil no topo de painéis glass |

---

## 2. TIPOGRAFIA

### 2.1 Font Stacks

| Token | Stack | Uso |
|-------|-------|-----|
| `--font-mono` | `'JetBrains Mono', 'SF Mono', 'Fira Code', 'Cascadia Code', monospace` | Código, terminal, hashes, valores numéricos, timestamps |
| `--font-sans` | `'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif` | Body, labels, texto corrido |
| `--font-display` | `'Space Grotesk', var(--font-sans)` | Títulos, hero, cabeçalhos de painel |

### 2.2 Escala Tipográfica

| Token | Tamanho | Uso |
|-------|---------|-----|
| `--fs-hero` | `clamp(1.6rem, 3.5vw, 2.4rem)` | Hashrate hero, big numbers |
| `--fs-h1` | `clamp(1.25rem, 2.5vw, 1.75rem)` | Títulos de seção |
| `--fs-h2` | `clamp(1.1rem, 2vw, 1.35rem)` | Subtítulos, painel header |
| `--fs-body` | `clamp(0.8rem, 1vw, 0.9rem)` | Texto padrão, valores |
| `--fs-mono` | `clamp(0.7rem, 0.8vw, 0.8rem)` | Terminal, timestamps, dados densos |
| `--fs-micro` | `clamp(0.6rem, 0.7vw, 0.7rem)` | Badges, legendas, footnotes |

### 2.3 Pesos

| Peso | Uso |
|------|-----|
| `400` (normal) | Valores, body, labels |
| `500` (medium) | Subtítulos, destaques |
| `600` (semibold) | Títulos de painel |
| `700` (bold) | Hero, big numbers, badges |

---

## 3. ESPAÇAMENTO E LAYOUT

### 3.1 Border Radius

| Token | Valor | Uso |
|-------|-------|-----|
| `--radius-xs` | `3px` | Badges, tags, indicadores |
| `--radius-sm` | `6px` | Botões pequenos, inputs |
| `--radius-md` | `10px` | Painéis, cards, modais |
| `--radius-lg` | `14px` | Painéis grandes, hero panel |
| `--radius-xl` | `20px` | Efeito especial (raro) |

### 3.2 Grid Layout

O dashboard usa um grid CSS de 4 colunas em desktop:

```
Desktop (1400px+):    4 colunas
Tablet (1100px):      3 colunas
Tablet (768px):       2 colunas
Mobile (480px):       1 coluna
```

### 3.3 Painéis

Cada painel segue a estrutura:

```html
<section class="panel" id="{id}">
  <header class="panel__header">
    <div class="panel__eyebrow">section label</div>
    <h2 class="panel__title">Título</h2>
    <div class="panel__badges">
      <span class="badge badge--{variant}">status</span>
    </div>
  </header>
  <div class="panel__body">
    <!-- conteúdo -->
  </div>
</section>
```

### 3.4 Padding Padrão

| Elemento | Padding |
|----------|---------|
| `.panel` | `16px` |
| `.panel__header` | `0 0 12px 0` |
| `.panel__body` | `0` (herda do panel) |
| `.btn` | `6px 14px` (sm), `10px 20px` (md) |
| `.badge` | `2px 8px` |
| `.field__input` | `4px 10px` |

---

## 4. COMPONENTES

### 4.1 Botões

| Classe | Variante | Cor |
|--------|----------|-----|
| `.btn` | Padrão | `--accent-btc` bg |
| `.btn--ghost` | Ghost | Transparente, texto `--text-secondary` |
| `.btn--mini` | Mini | Tamanho reduzido, padding `2px 6px` |
| `.is-loading` | Loading | Animação pulse + label oculto |

Estrutura:
```html
<button class="btn btn--{variant} {modifiers}" id="{id}">
  {icon} {label}
</button>
```

### 4.2 Badges

| Classe | Variante |
|--------|----------|
| `.badge` | Padrão (neutro) |
| `.badge--green` | Sucesso / online |
| `.badge--red` | Erro / offline |
| `.badge--gold` | High diff / conquista |
| `.badge--mute` | Placeholder / inativo |

Estrutura:
```html
<span class="badge badge--{variant}" id="{id}">{text}</span>
```

### 4.3 Modais

```html
<div class="modal modal--hidden" id="{id}">
  <div class="modal__panel">
    <div class="modal__header">
      <h3 class="modal__title">{title}</h3>
      <button data-close>×</button>
    </div>
    <div class="modal__body">{content}</div>
    <div class="modal__footer">
      <span class="badge" id="modal-status"></span>
      <button id="modal-save">SAVE</button>
    </div>
  </div>
</div>
```

Estados: `modal--hidden` (display:none), visível (display:flex).

### 4.4 Toast Notifications

```html
<div class="cypher-toast cypher-toast--success">{message}</div>
```

| Estado | Classe |
|--------|--------|
| Aparecendo | `.cypher-toast--show` |
| Sumindo | `.cypher-toast--hide` |
| Tipo | `.cypher-toast--success` / `.cypher-toast--error` |

Auto-destroi após 2.5s. Posicionado no topo central.

### 4.5 Cards de Worker (Live Mining)

```html
<div class="lm-grid">
  <div class="wd-card wd-card--{status}" data-id="{id}">
    <div class="wd-card__header">Worker name</div>
    <div class="wd-card__stat">hashrate</div>
    <div class="wd-card__stat">shares</div>
    <div class="wd-card__stat">best diff</div>
  </div>
</div>
```

Estados: `online`, `offline`, `stale`.

### 4.6 CFO Monte Carlo Panel

Seletor de horas + botão RUN + grid de resultados com:

- P(≥1 block) — probabilidade principal
- Expected blocks — média da simulação
- Median blocks — mediana
- P10 / P90 — percentis
- Distribution bars — barras de distribuição
- Footnote com λ, D, HR

### 4.7 Simulation Mini-Form

Formulário interativo com:
- Hashrate input + unit selector (TH/s / PH/s / GH/s)
- Duration input + unit selector (horas / dias)
- Monte Carlo checkbox toggle
- Result area com fade-in animado

---

## 5. ANIMAÇÕES

### 5.1 @keyframes

| Nome | Propósito | Duração |
|------|-----------|---------|
| `pulse` | Pulsação suave (loading, atenção) | 2s infinite |
| `panel-enter` | Entrada de painéis no load | 0.45s backwards |
| `value-flash` | Flash verde ao atualizar valor | 420ms |
| `fadeIn` | Fade-in de resultados de simulação | 300ms |
| `spin` | Spinner de carregamento | 1s linear infinite |

### 5.2 Transitions

| Propriedade | Duração | Easing |
|-------------|---------|--------|
| `all`, `background` | `--dur-fast` (120ms) | `--ease-out` |
| `color`, `border-color` | `--dur-base` (200ms) | `--ease-out` |
| `width`, `opacity` | `--dur-slow` (400ms) | `--ease-out` |
| `stroke-dashoffset` | `--dur-glacial` (800ms) | `--ease-out` |

### 5.3 Easing Functions

| Token | Curva |
|-------|-------|
| `--ease-out` | `cubic-bezier(0.16, 1, 0.3, 1)` |
| `--ease-spring` | `cubic-bezier(0.175, 0.885, 0.32, 1.275)` |

### 5.4 Motion Respect

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## 6. BREAKPOINTS

| Largura | Colunas | Alvo |
|---------|---------|------|
| > 1400px | 4 | Desktop wide |
| 1100–1400px | 4 | Desktop |
| 768–1100px | 3 | Tablet landscape |
| 480–768px | 2 | Tablet portrait |
| < 480px | 1 | Mobile |
| ≤ 600px | Compacto | Mobile charts |
| ≤ 900px | Stack vertical | Painéis específicos |

---

## 7. INTERAÇÕES

### 7.1 Shortcuts

| Tecla | Ação |
|-------|------|
| `R` | Refresh snapshot |
| `Escape` | Fechar modal ativo |
| Click fora | Fechar modal via `[data-close]` |

### 7.2 Feedback Visual

| Ação | Feedback |
|------|----------|
| Refresh | Skeletons → dados |
| Value change | `value-flash` (flash verde) |
| Count-up | Animação cubic-bezier 420ms |
| Hover botão | Cor mais clara, glow BTC |
| Hover painel | `--bg-hover` sutil |
| Pref salva | Toast "salvo com sucesso" 2.5s |
| Erro API | Toast "erro ao salvar" |
| Simulação | Loading pulse → resultado fade-in |

### 7.3 Modos de Atualização

Painel CFO/USD tem polling a cada `POLL_MS` (15s padrão). Não há ainda modos de economia de bateria — todo o dashboard atualiza junto.

---

## 8. ICONOGRAFIA

O projeto **não usa** bibliotecas de ícones externas. Todo ícone é texto unicode:

| Símbolo | Significado |
|---------|-------------|
| `⚡` | Hashrate, energia, simulação |
| `🎲` | Monte Carlo, simulação |
| `🔴` | Alerta crítico |
| `⭐` | High-value, gold |
| `×` | Fechar modal |
| `⟳` | Refresh |
| `⋯` | Loading / more |
| `•` | Status dot |
| `⏱` | Timer |
| `#` | Block number |
| `⊕` | Live indicator |

---

## 9. PADRÕES DE CÓDIGO

### 9.1 Nomenclatura CSS

| Padrão | Exemplo |
|--------|---------|
| BEM (Bloco__Elemento--Modificador) | `.panel__header--compact` |
| Prefixo `.panel--` para variantes de painel | `.panel--hero`, `.panel--cfo` |
| Prefixo `.badge--` para variantes de badge | `.badge--green`, `.badge--gold` |
| Prefixo `.btn--` para variantes de botão | `.btn--ghost`, `.btn--mini` |
| Prefixo `.is-` para estados | `.is-loading`, `.is-active`, `.is-online` |
| Prefixo `.has-` para presença | `.has-data` |

### 9.2 Nomenclatura JS (app.js)

| Padrão | Exemplo |
|--------|---------|
| `_` prefix para privado | `_prevAlertIds`, `_swRegistration` |
| `$` prefix para DOM | `$simForm`, `$simResult` |
| `dom` cache object | `dom.mHashrate`, `dom.statusPill` |
| `render*` para renderização | `renderAlerts`, `renderProximity` |
| `load*` para fetch inicial | `loadProfilePrefs`, `loadSettings` |
| `init*` para initialization | `initCharts`, `initMatrix` |

---

## 10. ACESSIBILIDADE

| Prática | Implementação |
|---------|---------------|
| Reduzir movimento | `@media (prefers-reduced-motion: reduce)` |
| Contraste | Texto primário #EDE8E3 sobre bg #141311 (ratio ~14:1) |
| Roles | Toast tem `role="status"` e `aria-live="polite"` |
| Semântica | `<section>`, `<header>`, `<h2>`, `<button>` |
| Foco visível | Botões e links têm foco padrão do browser |
| Labels | Inputs têm `<label>` ou `aria-label` |
| Print | `@media print` esconde matrix, animações, elementos não essenciais |

---

## 11. COMPONENTES MAPEADOS (dashboard.html)

```text
PANELS (24 seções):
├── hero-worker       (L56)   — Hashrate, best diff, status
├── prefs-panel       (L109)  — Preferências (moeda, risco)
├── sim-panel         (L154)  — Simulação interativa
├── proximity-panel   (L224)  — Proximity meter (SVG arc)
├── pool-overview     (L404)  — Pool hashrate, workers, blocks
├── account-panel     (L451)  — Lightning, total diff, rank
├── network-panel     (L486)  — Network height, difficulty
├── halving-panel     (L524)  — Halving countdown
├── fees-panel        (L559)  — Mempool fees
├── profit-panel      (L574)  — Profitability (BTC/fiat)
├── gauge-panel       (L643)  — 3 semi-circular gauges
├── milestones-panel  (L677)  — Badges/milestones
├── live-mining-panel (L688)  — Workers grid + best share
├── cfo-panel         (L824)  — CFO Monte Carlo
├── chart-hashrate    (L871)  — Hashrate chart
├── chart-pool        (L886)  — Pool HR chart
├── chart-bestdiff    (L900)  — Best diff chart
├── chart-net         (L914)  — Network diff chart
├── events-panel      (L928)  — High-diff events table
├── timeline-panel    (L953)  — Timeline feed
├── leaderboard-panel (L993)  — Top miners table
├── logs-panel        (L1016) — System terminal
├── alerts-panel      (L1028) — Critical alerts
└── terminal-panel    (L1039) — Solo terminal
```

---

## 12. MATRIX RAIN (Background Effect)

Canvas no fundo da página com:
- Font: `13px JetBrains Mono`
- Characters: `01アイウエオカキクケコサシスセソタチツテトABCDEF123456789#$%&*+<=>?`
- Colors: `#06d6f0` (padrão), 5% chance `#00ff9f`, 1.5% chance `#a855f7`
- Opacity trail: `rgba(4, 6, 10, 0.07)` overlay a cada frame
- Pausa automática quando `document.hidden`

---

## 13. USABILIDADE — AUDIT REPORT (03/08/2026)

### Testado no navegador: ✅ 18/18 PASS

| Item | Status |
|------|--------|
| Console errors | ✅ ZERO |
| Page load | ✅ |
| Data display | ✅ (dados reais após sync) |
| Hero panel | ✅ |
| Simulation panel | ✅ |
| Proximity meter | ✅ |
| Pool/Network/Profit | ✅ |
| Charts | ✅ |
| Live Mining | ✅ |
| Alerts | ✅ |
| Terminal | ✅ |
| Timeline | ✅ |
| Settings + Export modals | ✅ |
| Keyboard shortcuts | ✅ |
| Matrix animation | ✅ |
| Responsive (375px) | ✅ |
| Service Worker | ✅ |
| Notification permission | ✅ |

### Fricções Identificadas (melhorias futuras)

| Fricção | Prioridade | Sugestão |
|---------|-----------|----------|
| Placeholder `—` aparece brevemente até o primeiro poll completar | P3 | Adicionar estado de loading mais explícito |
| Sem modo BATTERY_SAVER (polling fixo 15s) | P3 | Implementar os 3 modos (LIVE/BALANCED/BATTERY_SAVER) |
| Tabelas em viewport <600px podem ter overflow horizontal | P3 | Adicionar scroll horizontal ou cards responsivos |
| Simulação não persiste resultados entre recarregamentos | P4 | Cache localStorage do último resultado |
| Sem contraste auditado para daltônicos | P4 | Adicionar labels/icons além de cor |
| Botão de notificação permissão não tem feedback visual | P4 | Mostrar badge de status da permissão |
