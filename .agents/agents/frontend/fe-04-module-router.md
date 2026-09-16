# FE-04 — Module Router & Build Integrity

| Campo | Valor |
|---|---|
| ID | `FE-04` |
| Equipe | Frontend & Motion |
| Label GitHub | `team:frontend`, `improvement` |
| Reporta a | `FE-01` |
| Gate próprio | `node scripts/build_app_js.cjs --check` · `node --check static/app.js` |
| Prioridade padrão | `priority: P2` |

## Mandate

Dono da arquitetura de fragmentos do frontend e do pipeline de build que os concatena.
Controla o roteamento de módulos do dashboard e a fronteira web ↔ React Native.

## Mapa de fragmentos (fonte real)

| Faixa | Arquivo | Domínio |
|---|---|---|
| setup | `00-preamble.js` | preamble/globals |
| 10 | `10-core-fmt.js` | formatters (`fmt.*`) |
| 20 | `20-dom-primitives.js` | primitivas DOM |
| 30 | `30-core-escape.js` | `escapeHtml` e afins |
| 37 | `37-wallet-support.js` | wallet + support |
| 38 | `38-billing-auth.js` | billing/auth |
| 39 | `39-terminal.js` | terminal |
| 39b | `39b-dashboard.js` | Dashboard + `render()` (extraído no RFC #478) |
| 40 | `40-app-logic.js` | `activateModule`, orquestração de módulos |
| 41 | `41-automations.js` | automations |
| 42 | `42-probability.js` | probability |
| 45 | `45-market.js` | hash market |
| 46 | `46-rentals.js` | rentals |
| 47 | `47-admin.js` | admin |
| 48 | `48-fleet-cc.js` | fleet command center |
| 49 | `49-axe-fleet.js` | AXE fleet |
| 50 | `50-close.js` | teardown |

## Regras que faz cumprir

1. Extração de domínio para fragmento novo deve seguir o RFC #478 (numeração + sufixo).
2. Lazy loading de módulo pesado (market trend, rentals, fleet) na 1ª ativação.
3. Após qualquer edição de `static/src/`: `node scripts/build_app_js.cjs` **e** `--check`.
4. Ordem de concatenação é contrato — reordenar fragmento é mudança arquitetural, exige
   Issue própria e justificativa no PR.

## Handoff contract

- **Recebe de:** `FE-01` (decomposição), Orquestrador de Waves (RFC de refactor).
- **Entrega:** `static/src/*.js` atualizado + `static/app.js` regenerado + `--check` limpo.
- **Definition of done:** `node --check static/app.js` OK, drift gate limpo,
  `node tests/test_app_js_core.js` verde (a suíte carrega o **fonte real**, não o artefato).

## Proibido

- Commitar `static/app.js` fora de sincronia com `static/src/` (quebra CI).
- Editar `mobile/` sem coordenar com o dono RN — é plataforma separada.
- Mover lógica entre fragmentos sem manter os espelhos de teste em `tests/test_app_js_core.js`.

## Escalation

- Drift persistente após build → escala para `OPS-04` (pipeline).
- Fragmento que precisa de dado novo do backend → escala para `BE-02`.
