# Revisão da interface terminal — Issue #746

Data: 2026-10-03. Base: `60eda10d3c9fbd6373029e73750bff41bdd1b3ad`.
Direção escolhida pelo usuário: **terminal técnico compacto, alta densidade e aparência de console**.

## Problema e resultado

O dashboard repetia métricas em HUD, status, KPIs e hero, com painéis largos e tipografia de contexto muito pequena. A revisão estabelece uma superfície principal para o worker, mantém o contexto global compacto, agrupa os 13 módulos na navegação e apresenta pool/rede em colunas quando há espaço. O painel detalhado do worker começa fechado e abre por teclado via `<details>` nativo; seus IDs e renderizadores permanecem disponíveis.

Valores recebem prioridade visual com cores neutras. Participação na rede aparece numericamente, sem os três semicírculos que duplicavam os mesmos números. Atualizações e trocas de módulo são imediatas; os skeletons e caminhos de movimento reduzido dos diálogos existentes continuam em uso. Os títulos simples de painéis usam `h2`.

A navegação móvel revelou sobreposição da topbar sobre o início do drawer. A correção remove seu z-index elevado no modo terminal móvel. Filtros de logs agora podem quebrar linha. O estado vazio de diagnósticos diz “Sem diagnósticos”, sem afirmar que os sistemas estão saudáveis quando a telemetria não permite essa conclusão.

## Validação local

- `npm run check:frontend`: PASS; bundle sincronizado, guards DOM/a11y/tokens/mobile-XSS, 1.585 testes JS core, auditoria visual e axe-core desktop/mobile sem violações nos cenários exercitados.
- `terminal-console.spec.js`: 8/8 PASS nos projetos Chromium e mobile-chrome. Composição desktop/mobile, rótulos sem corte, teclado/expansão, todos os 13 módulos, movimento reduzido, tema claro, estado sem worker/wallet e reflow de zoom CSS 200%.
- Regressão de telemetria, snapshots fora de ordem, KPIs, navegação/loading, Fleet sem agente e topbar: 39 PASS, 1 SKIP previsto pelo spec no projeto mobile. Esta rodada antecedeu os ajustes finais de stacking do drawer e apresentação numérica dos gauges.
- Regressão adicional de dashboard/modais/acessibilidade na versão final: 86/86 PASS nos projetos Chromium e mobile-chrome.
- `git diff --check`: PASS. O novo spec integra o gate E2E existente no CI.

Capturas reais do Playwright com o mesmo fixture sintético antes/depois: desktop 1440, mobile 390, tema claro e zoom CSS. Valores do fixture **não representam uma operação real**. O zoom CSS é um teste controlado de reflow; zoom nativo de browser a 200% não foi certificado. Estes checks não comprovam acesso a ASIC físico, LAN do cliente, sucesso de mineração ou cobertura de todos os estados de produção.

## Revisão por equipe

| Equipe | Verificação | Resultado |
|---|---|---|
| Frontend / Product | Hierarquia, densidade, navegação e responsividade | Correções no escopo #746; detalhes secundários continuam acessíveis |
| QA | Dados canônicos, teclado, estados vazios e reflow | Testes dedicados e regressões acima; IDs e unidades preservados |
| Motion | Operação frequente, reduced-motion, loading | Sem stagger nas trocas de módulo; skeletons e diálogos existentes preservados |
| Security / Backend | Entradas, auth, APIs, modelos e dependências | Sem alteração de autenticação, endpoints, cálculos ou dependências; strings novas de diagnóstico são constantes |
| Observability | Eventos e erros | Mecanismos existentes preservados; não afirma Sentry habilitado em produção |
| DevOps | Issue → branch → PR → checks → aprovação → squash | Issue #746 criada antes do código; branch `enh/746-compact-terminal`; merge/deploy dependem dos gates reais |

Risco principal: estilo compartilhado e hierarquia do dashboard afetam vários módulos; mitigado pelos testes de navegação, reflow, modais e regressões. A revisão acima é autorrevisão e **não substitui aprovação independente**. As regras ativas exigem uma aprovação e os oito checks obrigatórios verdes. O bloqueio mobile conhecido permanece na Issue #737; nenhum gate foi removido, ignorado ou enfraquecido. O spec novo acrescenta cobertura ao workflow.

## Limite da entrega

O checkout original `test/609-telemetry-validation` e suas alterações locais foram preservados. Esta revisão foi implementada no worktree isolado, a partir do master confirmado. As capturas documentam a implementação local; não são evidência de publicação em Render. Publicação deve acontecer pelo PR aprovado, após CI completo verde.
