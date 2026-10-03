# Painel operacional premium — Issue #746

Data: 2026-10-03. Worktree: `enh/746-compact-terminal`, PR #747.
Direção confirmada pelo usuário: mais informação operacional, gráficos e painel premium.

## Resultado e contratos

A operação apresenta indicadores com escopo, visualização dominante, atividade/cobertura e tabela investigável. Superfícies grafite, contraste, tipografia e hierarquia diferenciam o painel da composição plana anterior. Os 14 módulos e os controles existentes permanecem acessíveis. A comparação e o contexto da pool são independentes da telemetria local.

No modo pool, as barras usam exclusivamente hashrates dos workers identificados no payload `all_workers` ou a observação individual selecionada quando não há lista. Dados ausentes não viram zero; zero real permanece um valor válido. Os quatro indicadores mostram hashrate do worker, melhor share histórica, workers observados e idade da última submissão. O hashrate global da pool fica no contexto lateral. Não há curva histórica atribuída ao worker a partir de `/api/chart-data`: esse contrato global não comprova identidade de cada ponto.

No modo local, o gráfico lê `/api/axe-fleet/devices/:id/history?limit=120` via `authFetch`, no tenant autenticado. O usuário escolhe o equipamento e a métrica (hashrate, temperatura ou potência). Timestamps inválidos/futuros e valores ausentes/booleanos são tratados como desconhecidos. Lacunas de medição e intervalos maiores que 150 segundos não são ligados; zero real é desenhado. Um ponto produz um ponto, sem linha artificial. A idade apresentada e o último valor usam a última medição válida para a métrica, sem confundir coleta recente nula com valor antigo.

A série é validada contra o `device_id` solicitado. Um contador invalida respostas antigas ao trocar equipamento ou contexto de sessão. HTTP 503 mantém somente o histórico anterior do mesmo equipamento, identificado como consulta indisponível e com sua idade real. HTTP 401/403/404 limpa as observações. Trocar tenant ou fazer logout também limpa o cache e invalida a consulta pendente. O gráfico não envia comandos operacionais.

Hashrate e potência atuais agregam apenas equipamentos elegíveis com amostra recente e estado alcançável; potência offline/antiga não entra no total. Cada agregado identifica quantos equipamentos contribuíram. A cobertura apresenta contagens, sem inferir uptime. Falha da consulta de saúde mantém linhas e último estado, com atualidade não confirmada, independentemente da consulta de histórico.

O contexto Bitcoin exibe preço, altura e dificuldade recebidos no snapshot, com cache explicitado; não calcula retorno financeiro. A tabela preserva filtros, estado, idade e detalhe nativo com Escape/retorno de foco. Os indicadores navegáveis são botões nativos com destinos pertinentes: atividade/shares/worker em Eventos; melhor share em Modelos.

## Responsividade e acessibilidade

No desktop pool, gráfico e primeiro registro cabem no viewport de 1440×900. No celular, os quatro indicadores usam uma grade 2×2 e a comparação de workers cabe antes da tabela; atividade e cobertura ficam num disclosure nativo. O histórico tem eixos dimensionados à largura real, e todas as até 120 amostras desenhadas possuem alternativa textual em tabela expansível. Não depende de hover para investigar dados. Tema claro e reflow com zoom CSS 200% foram exercitados.

Operação, seleção de fonte/métrica e polling são imediatos. O diálogo mantém a entrada por ponteiro de 160 ms e desativa animação para teclado/reduced-motion. Skeleton acompanha a primeira leitura do histórico. Não há novas dependências ou endpoints, nem motion decorativo.

## Verificação local e revisão

- JS core: **1.632 PASS**, executando o fonte real. Regressões cobrem ausência/zero, escopo por worker, potência offline/antiga, timestamp, segmentos com lacuna e reset de sessão/cache/nonce.
- Python afetado: **71 PASS** (`test_command_center`, `test_dashboard_routes_migration`, `test_sentry_frontend`). O Python completo da reconstrução anterior passou 4.154 testes e 85,51% de cobertura; isso é evidência anterior, não reexecução desta alteração visual.
- E2E: **69 PASS / 1 SKIP** na rodada console/auth/WebLN/header/command-accessibility; **48 PASS** após correções de idade, alternativa textual e botões, incluindo KPI determinístico e auth. A rodada final passou **26/26** cenários do painel, incluindo login/logout pela interface com respostas simuladas e consulta pendente.
- Frontend: pipeline de bundle, DOM, a11y, tokens, XSS mobile, visual/overflow/skeleton, axe-core e guards/mutations passou. A primeira auditoria detectou hierarquia de headings; foi corrigida; a rodada final passou com **zero violações axe-core** em desktop/mobile, proxy 100/100, sem overflow/erros/skeletons presos.
- Astra inspecionou código e capturas, reconheceu a direção premium e apontou três P2 de idade, teclado e equivalência textual, corrigidos com regressões. No parecer pós-correção, a Astra não identificou novos bloqueios materiais; o texto fica no pacote local. Não equivale a aprovação no GitHub.

| Equipe | Revisão |
|---|---|
| Frontend / Product | Hierarquia, gráficos source-backed, indicadores, contexto e tabela; desktop/mobile/light/zoom |
| QA / Data | Zero real, lacunas, timestamp da última medição válida, erro de consulta e escopo de equipamento/sessão |
| Security / Backend | GET autorizado, `device_id`, nonce, cache limpo ao sair/trocar tenant, textos escapados, nenhum comando novo |
| Motion / Acessibilidade | Fluxos instantâneos; botões nativos; diálogo; eixos responsivos; tabela alternativa completa; reduced-motion |
| Observability | Falhas expostas separadamente; mecanismos Sentry/logs existentes preservados, sem alegar habilitação em produção |
| DevOps | Issue → branch → PR → checks do head exato → aprovação independente → squash/deploy |

As capturas Playwright são da implementação real com **fixtures sintéticas**, sem acesso a ASIC, LAN ou operação de produção. O checkout original e suas alterações foram preservados. Correções mobile já publicadas por outra tarefa foram incorporadas por fast-forward; não foram escritas por esta revisão. CI e aprovação devem ser verificados no novo head antes de merge/deploy; não contornar gates.
