// CYPHER65 Mobile — Design Tokens (Issue #239)
// =============================================
// Espelha o DSv2 do web (static/style.css :root). Este arquivo é a ÚNICA
// fonte de cores do app React Native: NUNCA use #hex literal fora daqui —
// o guard scripts/check-tokens-hex.sh falha o CI (mobile/ virou GATE,
// theme.ts é excluído do scan, como style.css é no web).
//
// Nomenclatura por papel (não por tom): bg.* / text.* / brand.* /
// green|amber|red|purple seguem o DSv2 (--bg-surface, --text-primary…).

export const theme = {
  // Fundos
  bg: {
    deep: '#0b0f19',        // fundo principal das telas
    surface: '#111827',     // cards, inputs, tab bar, list rows
    elevated: '#1f2937',    // chips de filtro, bubble do AI, inputs elevados
    overlay: '#1e293b',     // abas / agrupamentos (Rentals)
    brand: '#0ea5e9',       // botões primários, aba ativa, switch ativo
    red: '#7f1d1d',         // logout, badges CRITICAL/OFFLINE, risco high
    amber: '#713f12',       // badge WARNING, risco medium
    amberDeep: '#422006',   // badge GOLD
    green: '#064e3b',       // badge ONLINE/SUCCESS, risco low
    brandDeep: '#0c4a6e',   // badge INFO
  },
  // Bordas
  border: {
    subtle: '#1f2937',      // borda superior da tab bar
    strong: '#374151',      // track do switch (inativo)
  },
  // Texto
  text: {
    primary: '#f8fafc',
    secondary: '#64748b',
    tertiary: '#94a3b8',
    muted: '#cbd5e1',       // métricas de apoio
    faint: '#e2e8f0',       // labels, texto de alerta
    onBrand: '#ffffff',     // texto sobre fundo brand
    onDeep: '#0b0f19',      // texto escuro sobre brand (aba ativa)
  },
  // Marca (ciano)
  brand: {
    DEFAULT: '#38bdf8',
    strong: '#0ea5e9',
    deep: '#0c4a6e',
  },
  // Semânticos
  green: {
    DEFAULT: '#34d399',
    strong: '#4ade80',
    dim: '#10b981',         // barras do gráfico de shares
  },
  amber: {
    DEFAULT: '#facc15',
    soft: '#fbbf24',        // badge GOLD (texto)
  },
  red: {
    DEFAULT: '#f87171',
  },
  purple: '#a855f7',        // linha de target do gráfico / CTA P(block)
} as const;

export type Theme = typeof theme;
export default theme;
