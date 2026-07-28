# CYPHER65 — Design System v2

## Mission Control · Industrial Telemetry · Data-First

> Proposta para aprovação. Após confirmada, gero o HTML/CSS completo.

---

## 1. Filosofia de Design

Este não é um dashboard. É um **painel de telemetria de operação crítica**.
Cada elemento visual existe exclusivamente para comunicar estado do sistema —
nada é decorativo, nada é "bonito por ser bonito".

**Referências de direção:**
- SpaceX Dragon Mission Control (dados densos, hierarquia tipográfica extrema)
- Bloomberg Terminal (informação máxima, Zero decoration)
- NASA JPL telemetry consoles (dados em monospace, status por cor de LED)
- SCADA industrial (bordas retas, repetição de padrão, sem surpresas visuais)

**Regra única:** Se um elemento não ajuda o operador a tomar uma decisão em
≤2 segundos, ele não pertence à interface.

---

## 2. Paleta de Cores

Reduzida de **12 cores de acento** para **5 cores totais** (1 base + 1 marca +
3 funcionais). Nada mais.

### Base (monocromática)

| Token | Hex | Uso |
|-------|-----|-----|
| `--bg-deep` | `#070808` | Background da página |
| `--bg-surface` | `#111213` | Sidebar, superfícies |
| `--bg-elevated` | `#1A1B1D` | Cards/panels |
| `--bg-hover` | `#222426` | Hover state |
| `--border-subtle` | `#2A2C2E` | Bordas de painéis |
| `--border-default` | `#35373A` | Bordas de tabelas/inputs |
| `--text-primary` | `#EAEAEB` | Títulos, valores |
| `--text-secondary` | `#909296` | Labels, sub-textos |
| `--text-tertiary` | `#5C5E62` | Metadados, footnotes |

### Marca (1 cor)

| Token | Hex | Uso |
|-------|-----|-----|
| `--brand` | `#F7931A` | Logo, sidebar active indicator, Bitcoin |

### Status (3 cores funcionais)

| Token | Hex | Uso |
|-------|-----|-----|
| `--green` | `#00C853` | Operacional, online, healthy, shares found |
| `--amber` | `#FFB300` | Atenção, warning, high temp, stale shares |
| `--red` | `#FF1744` | Crítico, offline, error, reject rate |

**Todas as cores eliminadas:**
~~accent-blue, accent-purple, accent-teal, accent-biolume, accent-organic,
accent-spore, accent-tendril, accent-colony, todas as variantes bg glow,
todos os gradientes orgânicos, glass highlights, noise texture, scanlines,
vignette, matrix rain.~~

> Se a cor não for preto, cinza, branco, laranja (BTC), verde (ok),
> âmbar (alerta) ou vermelho (crítico) — ela não existe mais.

---

## 3. Sistema Tipográfico

### Fontes

| Uso | Fonte | Fallback | Weight |
|-----|-------|----------|--------|
| **Dados numéricos** (hashrate, diff, shares, valores) | `JetBrains Mono` | `SF Mono`, monospace | 500 (regular), 700 (bold) |
| **Labels, nav, headers** | `IBM Plex Sans` | `SF Pro Text`, system-ui | 400 (regular), 500 (medium), 600 (semibold) |
| **Código, timestamps, hashes** | `JetBrains Mono` | monospace | 400 |

> **Por que JetBrains Mono?** Já está carregado no projeto, tem suporte a
> ligaduras opcionais, peso visual consistente e hinting agressivo para
> legibilidade em tamanhos pequenos.
>
> **Por que IBM Plex Sans em vez de Inter?** IBM Plex Sans tem caráter
> mais técnico (terminal/hardware), menos genérico que Inter. Se não quiser
> carregar mais uma fonte, usamos Inter mesmo — mas com tracking
> (letter-spacing) mais apertado para parecer menos "app consumer".

### Escala Modular

| Nome | Tamanho | Line-height | Tracking | Uso |
|------|---------|-------------|----------|-----|
| `--fs-micro` | 10px | 1.3 | 0.03em | Timestamps, badges, footnotes |
| `--fs-xs` | 11px | 1.4 | 0.02em | Tabelas, labels de métrica, sidebar |
| `--fs-sm` | 12px | 1.4 | 0.01em | Eyebrow headers, tooltips, context |
| `--fs-base` | 13px | 1.5 | 0 | Body text, labels de painel |
| `--fs-md` | 14px | 1.4 | -0.01em | Valores secundários, stat__val |
| `--fs-lg` | 16px | 1.3 | -0.02em | Títulos de seção, h2 |
| `--fs-xl` | 20px | 1.2 | -0.03em | Hero values (best diff, hashrate) |
| `--fs-2xl` | 28px | 1.1 | -0.04em | Metric__value principal |
| `--fs-3xl` | 40px | 1.05 | -0.05em | Host Core headline (raro) |

> Escala baseada em potências de 2 (10, 11, 12, 13, 14, 16, 20, 28, 40) —
> sem clamp() flutuante, sem "design responsivo fluido". O painel tem
> breakpoints fixos, a tipografia muda no breakpoint, não a cada pixel.

---

## 4. Grid e Layout

### Estrutura base
- Sidebar fixa esquerda: **160px** (colapsada: 44px)
- Content area: flexível, padding lateral `clamp(12px, 1.5vw, 20px)`
- O grid interno continua 12 colunas — os IDs de painel não mudam

### Gutter
- Desktop: 8px entre painéis
- <1100px: 6px
- <768px: 4px

> Gutter mais apertado que o atual (12-18px → 8px) para aumentar densidade
> de informação. Painéis operacionais reais (Bloomberg, SCADA) têm gutters
> de 4-6px.

### Padding de painéis
- Desktop: 10px 12px
- <768px: 8px 10px
- <480px: 6px 8px

> Redução drástica do padding atual (16px → 10px). Cada pixel de espaço
> perdido é um dado que o operador não vê.

### Breakpoints

| Nome | Largura | Grid cols | Comportamento |
|------|---------|-----------|---------------|
| Desktop | >1100px | 12 | Layout completo, sidebar visível |
| Tablet | 768-1100px | 12 | Sidebar vira overlay, gutters reduzidos |
| Mobile | <768px | 12 | Sidebar overlay, todos panels span 12, topbar compacto |

---

## 5. Bordas, Cantos e Sombras

### Border-radius
- Painéis, cards, inputs: **2px** (consistente em tudo)
- Badges, pills: **4px**
- Botões: **2px**
- Nada de `border-radius: 999px` exceto LEDs

> Por que 2px? É o mínimo industrial. Não arredondamos nada por estética —
> apenas o suficiente para evitar pontas afiadas em elementos interativos.
> Painéis operacionais reais usam cantos retos ou 2px no máximo.

### Bordas
- Painéis: `1px solid var(--border-subtle)` — sem cor de acento, sem ::before
- Tabelas: `1px solid var(--border-default)` para linhas de header
- Inputs: `1px solid var(--border-default)`
- Foco: `1px solid var(--brand)` — único uso da cor de marca em borda

### Sombras
- Painéis: **sem sombra**
- Modais: `0 2px 16px rgba(0,0,0,0.5)` — única sombra do sistema
- Dropdowns/tooltips: `0 1px 8px rgba(0,0,0,0.4)`

> **Zero sombra em painéis.** Sombras criam hierarquia visual falsa.
> A hierarquia deve vir da tipografia e densidade, não de elevação simulada.
> Reserve sombra apenas para elementos que precisam literalmente flutuar
> sobre o conteúdo (modais, tooltips).

---

## 6. Iconografia

### Set escolhido: **Lucide** (https://lucide.dev)

**Por que Lucide:**
- Stroke-width consistente (2px)
- 1.000+ ícones técnicos
- Apenas SVG, zero emoji
- Pode ser carregado via CDN ou inline
- Visual "engineering blueprint", não "app consumer"

### Tamanhos de ícone
- Sidebar: 16px
- Topbar buttons: 14px
- Badges/indicadores: 12px
- Headers de painel: 14px

### Mapeamento de ícones (substituindo emoji)

| Atual (emoji) | Novo (Lucide) |
|---------------|---------------|
| ⌘ Command | `terminal` |
| ⚙ Fleet | `hard-drive` |
| ◈ Block Hunt | `target` |
| ⟐ Market | `trending-up` |
| ◆ AI | `brain-circuit` |
| ⚠ Alerts | `bell` |
| Ξ P&L | `bar-chart-3` |
| ⟳ Refresh | `refresh-cw` |
| 🚨 Alert Center | `bell` |
| ↓ Export | `download` |
| 🔇 Sound | `volume-x` |

---

## 7. Painéis — Novo Visual

### Antes vs Depois

| Característica | Atual (v1) | Novo (v2) |
|---------------|------------|-----------|
| Fundo | Glass/blur | Sólido escuro |
| Borda superior | ::before com cor de acento (2px) | Sem acento, borda sutil 1px |
| Borda hover | Brilho/glow | Apenas `border-color` mais claro |
| Padding | 16px | 10px |
| Border-radius | 10px | 2px |
| Sombra | Múltiplas camadas | Nenhuma |
| Header bottom | 1px subtil | 1px sutil, tracking mais apertado |
| Fonte do header | `font-mono`, 9px | `font-sans`, 11px, medium |
| Cor do header | Text-tertiary | Text-secondary |
| Badge no header | Arredondado 999px | Badge retangular, border-radius 2px |

### Novo padrão de painel

```css
.panel {
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: 2px;
  padding: 10px 12px;
}
```

Sem ::before, sem ::after, sem backdrop-filter, sem animação de entrada,
sem box-shadow, sem overflow hidden.

---

## 8. Microinterações e Estado

Únicas animações permitidas:

1. **LED de status online** — `opacity` pulsando entre 0.4 e 1 em 2s
2. **Valor que muda** — flash sutil de borda (2px `var(--green)` na borda
   inferior do elemento, 300ms, fade out)
3. **Alerta novo** — slide-in da esquerda (200ms)
4. **Hover em botão** — cor do texto muda para brand (120ms)

Nada mais. Sem glow, sem pulse em nós orgânicos, sem shimmer, sem
partículas, sem matrix rain, sem scanlines, sem vignette.

---

## 9. Sidebar

### Antes
- Largura: 180px
- Brand: "65" em gradient box
- Navigation: emoji como ícones
- Active: ::before com dot laranja
- Border-right: sutil
- Background: bg-surface

### Depois
- Largura: 160px (colapsada: 44px)
- Brand: "CYPHER65" em brand color, sem caixa gradient
- Navigation: ícones Lucide SVG + texto
- Active: barra vertical de 2px na borda esquerda (brand color)
- Background: bg-surface, sem border-right (a diferença de tom do
  bg-deep já separa)
- Collapsed: apenas ícone, tooltip no hover

---

## 10. Status Bar

### Antes
- 5 blocos flex com border-top colorido
- backdrop-filter: blur(12px)
- Fundo glass
- Badges com border-radius 999px

### Depois
- 5 blocos flex, borda sutil, sem cor de acento
- Fundo sólido bg-elevated
- Valores em monospace bold, labels em sans-serif micro
- Sem blur, sem glass

---

## 11. Topbar

### Antes
- backdrop-filter: blur(20px)
- Múltiplos pills com border-radius 999px
- Botões com emoji

### Depois
- Fundo sólido bg-elevated, border-bottom
- Pills com border-radius 2px (não 999px)
- Botões com ícones Lucide SVG ou texto
- Altura reduzida: 38px

---

## 12. Resumo das Eliminações

O que **sai** do sistema:

- ❌ Glassmorphism / backdrop-filter
- ❌ Gradientes (em backgrounds, bordas, textos)
- ❌ Múltiplas cores de acento (mais de 1 + 3 status)
- ❌ Glow, sombras em painéis, neon
- ❌ Emoji como ícones
- ❌ Noise texture, scanlines, vignette
- ❌ Matrix rain canvas
- ❌ border-radius > 2px (exceto LEDs)
- ❌ padding excessivo (> 12px)
- ❌ Animações decorativas (shimmer, breathe, float)
- ❌ Blur effects
- ❌ Overflow hidden em panels
- ❌ ::before / ::after decorativos em panels

---

## 13. Próximos Passos

Após sua aprovação, eu gero:

1. **`static/style.css`** — completo, ~1500 linhas, substituindo o atual
   (2985 linhas) com zero regressão nos seletores de ID
2. **`templates/dashboard.html`** — ajustado: classes de painel limpas,
   ícones Lucide, estrutura de header simplificada, sem elementos
   decorativos, mantendo 100% dos IDs que o app.js renderiza
3. Remoção dos decorativos: scanlines, vignette, matrix canvas, noise,
   nós orgânicos, classes bio-luminescentes
4. Substituição de todos os emoji por ícones inline SVG (Lucide)
5. Ajuste do `static/sw.js` se necessário

**Zero mudanças no `static/app.js`** — todas as funções render*() continuam
funcionando porque os IDs que elas manipulam não mudam.

---

**Aprova?** Se sim, diga "APROVADO" e começo a gerar o código. Se quiser
ajustes, me diga o que alterar na proposta.
