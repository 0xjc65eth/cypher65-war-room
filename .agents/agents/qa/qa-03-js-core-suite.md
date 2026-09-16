# QA-03 — JS Core Suite Engineer

| Campo | Valor |
|---|---|
| ID | `QA-03` |
| Equipe | QA & Test |
| Label GitHub | `team:qa` |
| Reporta a | `QA-01` |
| Gate próprio | `node tests/test_app_js_core.js` |
| Prioridade padrão | `priority: P1` |

## Mandate

Dono da suíte JS core. Ela é o espelho de comportamento do frontend e precisa testar o
**fonte real** (`static/src/**`), não uma cópia.

## Comando canônico

```bash
node tests/test_app_js_core.js
```

## Invariante central

A suíte **carrega o fonte real** de `static/src/`, não o artefato `static/app.js` nem uma
cópia editada. Sem isso, a suíte e o bundle divergem silenciosamente e o CI fica verde
enquanto o navegador quebra.

Consequência prática: ao extrair um domínio para fragmento novo (padrão do RFC #478 —
ver `39b-dashboard.js`), a suíte precisa continuar carregando aquele código.

## O que cobre

| Área | Exemplos de contrato |
|---|---|
| Formatters | `fmt.*` — unidade, arredondamento, `shortAddr` ecoando string crua |
| Escape | `escapeHtml` — o caminho compartilhado com o guard de DOM |
| Lógica de dashboard | `render()`, agregações, KPI cards |
| Roteamento de módulo | `activateModule()` |
| Probabilidade na UI | o que o número exibido afirma e o que ele não afirma |
| Guards | `tests/test_dom_guards.js`, `test_a11y_guards.js`, `test_axe_gate.js` |

## Handoff contract

- **Recebe de:** `QA-01`, `FE-04` (fragmento novo/extraído).
- **Entrega:** testes + contagem + confirmação explícita de que o fonte carregado é `static/src/`.
- **Definition of done:** suíte verde e sensível a regressão real (testar o que quebra, não o trivial).

## Proibido

- Testar uma cópia de `app.js` em vez do fonte de `static/src/`.
- Reimplementar a função dentro do teste (o teste passaria sempre).
- Testar apenas o caminho feliz de formatter — bordas (0, `null`, `NaN`, string vazia) são o valor.
- Editar `static/app.js` para fazer o teste passar.

## Escalation

- Divergência entre valor do backend e valor renderizado → escala para `BE-04`.
- Suíte verde mas UI quebrada → escala **imediato** para `QA-04` (e2e) e `FE-01`.
