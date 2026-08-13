# 🔍 AUDITORIA COMPLETA — Erros, Inconsistências e Melhorias

> **Data:** 13/08/2026 · **Método:** forense de código (arquivo:linha) + suíte
> completa (pytest 1878 ✅ · JS core 1261 ✅) + auditoria visual via Playwright
> (console errors, overflow, truncamento, DOM pós-render) + gates de CI.
> **Padrão:** Issue → Branch → PR → Deploy (`docs/AGENT_WORKFLOW.md`).

---

## 1. Resumo executivo

O sistema está **saudável**: suíte 100% verde, JS core íntegro, zero console
errors no boot, zero overflow horizontal de página, motion tokens + skeletons +
`prefers-reduced-motion` já presentes. Porém a auditoria encontrou **1 bug
crítico invisível** (painel hero destruído após o 1º render — os valores eram
preenchidos e apagados no mesmo ciclo, então ninguém via o erro em testes
existentes), **2 bugs médios** (XSS potencial + IDs duplicados), **1 problema
de UI** (overflow de endereços) e **1 inconsistência de docs**.

**5 Issues criadas (#47-#51), todas corrigidas no PR #52.**

---

## 2. Lista priorizada de Issues

| # | Impacto | Tipo | Problema | Solução aplicada |
|---|---|---|---|---|
| **#51** | Crítico | bug | `DashboardCore.setText('hero-worker', …)` fazia `textContent` na **section** `#hero-worker`, apagando todas as métricas hero (`m-hashrate`, `m-state`, `hc-*`) do DOM | Removeu o setText destrutivo; `renderHero()`/`renderHostCore()` seguem donos dos slots |
| **#48** | Médio | bug | XSS potencial: `fmt.shortAddr()`/`fmt.diff()` sem `escapeHtml` em `renderEvents`/`renderLeaderboard` (dados de API externa) | Envolveu com `escapeHtml()` |
| **#50** | Médio | bug | IDs duplicados `solo-expected-time`/`solo-blocks-year` (profit strip + solo cards) — `getElementById` acertava o nó errado | Renomeou o painel solo-cards (`solo-cards-*`) + `setAll` dedicado |
| **#49** | Baixo | ui-ux | `.support-method-addr` overflow de até **402px** (max-width/ellipsis ignorados em span inline) | `display:inline-block` + `title` com endereço completo |
| **#47** | Baixo | inconsistency | README `45%` coverage floor vs gate real `65%`; contagens de testes 1866/1859/1684 vs reais 1878/1261 | README + QUALITY.md alinhados |

**Não-bugs (verificados e descartados):** `netStatus: "fetching"` é estado
legítimo de primeiro load; os `except Exception` massivos são defensivos por
design (workers nunca morrem); endereços na status bar usam ellipsis
intencional; `m-hashrate` "(missing)" era efeito do #51.

---

## 3. Sugestões de melhorias de UI/UX (próximos passos)

1. **Skeletons nos módulos tardios** — `skel-overlay` existe no boot, mas os
   módulos market/rentals/fleet mostram `awaiting data…`/vazio enquanto
   carregam na 1ª ativação. Aplicar o mesmo shimmer (transform-only).
2. **Toast acessível** — `showToast` usa estilo inline e some por timeout sem
   `role="status"`/`aria-live`; migrar para o sistema de tokens (--dur/--ease)
   + `aria-live="polite"` para leitores de tela.
3. **Skeleton das tabelas** — `events-tbody`/`lb-tbody` renderizam
   `awaiting data…`; skeleton de linhas daria a mesma sensação de fluidez dos
   módulos com overlay.
4. **Stagger nos cards do fleet** — grid de devices aparece de uma vez;
   entrada em cascata (delay incremental por índice) alinhada aos motion
   tokens já existentes.
5. **Estado vazio dos rentals** — quando não há histórico, o painel mostra
   "sem dados"; um empty-state ilustrado com CTA (ex: "comprar hashrate")
   converte melhor.

---

## 4. Sugestões de melhorias de funções e ferramentas

1. **Guard de IDs duplicados no CI** — `grep -oE 'id="…"' | sort | uniq -d`
   no template como check do CI (evita regressão do #50).
2. **Audit de `innerHTML` sem escape** — script CI (ou test) que garanta
   nenhuma interpolação de dado externo sem `escapeHtml` (regressão do #48).
3. **Ferramenta de diagnóstico visual reutilizável** — o script Playwright
   usado na auditoria (console errors + overflow + truncamento) viraria
   `scripts/audit_ui.cjs` executável sob demanda.
4. **`renderProfit` e `renderSoloStats` compartilharem fonte** — os dois
   painéis escrevem os mesmos campos solo; um único renderer evitaria
   divergência futura (dívida pós-#50).

---

## 5. Próximos passos recomendados

1. **Merge do PR #52** (CI verde) — fecha #47-#51 e dispara o deploy.
2. Adotar **item 3.1** (skeletons tardios) como nova Issue `ui-ux` P2.
3. Adotar **item 4.1/4.2** (guards de CI) como Issue `enhancement` P3.
4. Repetir a auditoria visual a cada release (script reaproveitável).

---

## 6. Como a auditoria foi feita (reproduzível)

```bash
SECRET_KEY=test-secret-0123456789 python -m pytest tests/ -q        # 1878 passed
node tests/test_app_js_core.js                                       # 1261 passed
node --check static/app.js
RATE_LIMIT_PER_MINUTE=10000 python app.py &                          # servidor local
# script Playwright: console errors + overflow + truncamento + DOM pós-render
```

Referências: `docs/QUALITY.md` · `docs/AGENT_WORKFLOW.md` · PR #52
