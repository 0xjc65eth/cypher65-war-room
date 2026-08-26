# Auditoria UX/UI operacional — CYPHER65 War Room

Data: 2026-08-26  
Escopo: código atual do Dashboard, Fleet, Live Mining, Probability, Profitability, Alerts, Automations e Admin  
Objetivo: permitir que um operador responda em poucos segundos se a operação está saudável, onde há perda, quanto custa, se os dados são atuais e qual diagnóstico seguro abrir.

## Resumo executivo

O produto já possui telemetria real, status global, Fleet detalhada, indicadores de stale e um Command Center advisory. O principal problema não era ausência absoluta de dados, mas dispersão: hashrate aparece em várias representações, enquanto saúde, exceções, perda, custo e frescor não formavam uma única decisão operacional.

A primeira tela priorizada é o Dashboard. O novo `Operational Overview` fica imediatamente após a barra de status e consolida fontes reais já existentes:

- snapshot: custo configurado, timestamp, flags stale e recomendações advisory;
- `/api/axe-fleet/health`: contagem por estado, health score, idade da telemetria e perda de hashrate;
- ação: navegação interna para diagnóstico, sem URL externa e sem execução de comando.

O cálculo de perda usa `hashrate_1h` quando disponível e o último hashrate conhecido para um dispositivo offline. Sem baseline, a interface mostra indisponível — não zero.

## 1. Problemas de hierarquia visual

1. A barra de status, quatro KPIs, Host Core e painéis repetem hashrate e estado antes de apresentar exceções. Isso exige comparação mental e empurra a decisão para baixo.
2. `O QUE FAZER AGORA?` é útil, mas mistura ações de natureza diferente e fica depois de estruturas de contexto. A ação operacional precisa ser visível antes da exploração analítica.
3. Métricas de mineração solo têm grande peso visual, embora saúde de hardware, perda e custo sejam mais urgentes durante um incidente.
4. Badges e labels usam muitas variações de caixa alta e densidade semelhante; severidade e contexto competem pela atenção.
5. A navegação apresenta módulos de operação, análise, aprendizado, suporte e administração no mesmo nível.

Decisão aplicada: o Dashboard começa com um resumo exception-first em seis sinais, seguido das métricas exploratórias já existentes.

## 2. Cards, tabelas e gráficos que não ajudam decisões

| Elemento atual | Problema operacional | Direção recomendada |
|---|---|---|
| KPIs de hashrate/best diff/share/pool | Repetem sinais encontrados na barra e no Host Core; não dizem se é preciso agir | Manter como drill-down, abaixo do resumo operacional |
| Host Core | Grande superfície para telemetria geral; não quantifica perda nem custo | Reduzir prioridade visual na próxima versão |
| Command Center | Boa camada advisory, mas pode incluir oportunidade comercial junto a incidente | Resumo operacional sempre prioriza exceção de frota e ignora URL externa |
| Fleet cards | Úteis individualmente, mas custosos para dezenas de ASICs | Exceções primeiro; tabela virtualizada/densa para escala |
| Hash Flow Raster | Ajuda investigação temporal, não a decisão inicial | Manter dentro de Live/Fleet, não no primeiro viewport |
| Gráficos de probabilidade | Podem dominar a atenção sem representar garantia de bloco | Reforçar rótulos probabilísticos e manter no módulo Probability |
| Tabelas de mercado | Muitas colunas e comparação difícil no mobile | Resumo de melhor alternativa + cards mobile; tabela para desktop avançado |

## 3. Informações ausentes

Antes desta implementação, faltavam no primeiro viewport:

- contagem consolidada de ASICs em `WARNING` ou `OFFLINE`;
- hashrate perdido com baseline e escopo observável;
- custo operacional diário explicitamente configurado ou ausente;
- idade combinada do snapshot e da telemetria da Fleet;
- distinção entre “zero medido” e “não calculável”;
- uma ação única que deixe claro que apenas abre diagnóstico.

Ainda faltam para uma versão futura:

- tendência da perda (15 min/1 h/24 h) persistida no servidor;
- custo atribuído por ASIC/site, não apenas pelo modelo global;
- impacto financeiro da perda em tempo real;
- SLA por fonte (pool, preço, rede, agente local e ASIC);
- agrupamento por site/rack para operações maiores.

## 4. Estados de carregamento, vazio, erro e offline

| Estado | Comportamento requerido no resumo operacional |
|---|---|
| Loading | Skeletons e `aria-busy=true`; não exibir zeros provisórios |
| Frota vazia | `NO FLEET`, zero dispositivos registrados, perda indisponível e CTA para Fleet |
| Endpoint Fleet em erro | `UNAVAILABLE`, contagem/perda indisponíveis e indicação de snapshot parcial |
| ASIC offline | Exceção crítica; último hashrate vira baseline de perda, nunca produção ativa |
| Snapshot stale | `STALE DATA` mesmo quando a saúde observada era boa |
| Telemetria Fleet stale | `STALE DATA` quando a maior idade observada excede 150 s |
| Custo ausente | `NOT CONFIGURED`; nunca assumir energia gratuita |
| Baseline ausente | Perda `—`; nunca inferir 0 H/s perdido |
| Operação nominal | `HEALTHY`; CTA desabilitado quando não há ação advisory nem configuração pendente |

## 5. Acessibilidade e responsividade

Problemas atuais:

- textos auxiliares de 8–9 px são densos para leitura prolongada;
- cores carregam parte importante da severidade;
- idioma alterna entre português e inglês;
- alguns canvas dependem do contexto visual para interpretação;
- tabelas e painéis avançados ainda exigem revisão com zoom de 200%;
- áreas clicáveis antigas nem sempre comunicam semântica de botão.

Medidas na tela priorizada:

- região nomeada por `aria-labelledby`;
- `aria-busy` durante a primeira carga e status textual com `aria-live=polite`;
- severidade sempre escrita (`HEALTHY`, `ATTENTION`, `CRITICAL`, `STALE DATA`), nunca somente cor;
- CTA é um `button`, possui estado `disabled` real e não é um card inteiro clicável;
- layout 3 colunas no desktop, 2 no tablet e 1 em telas estreitas;
- números tabulares, quebra de texto e `min-width: 0` evitam overflow;
- métricas de polling não recebem animação; scroll respeita `prefers-reduced-motion`.

## 6. Fluxos de ação perigosos ou confusos

1. Reinício, pause/resume, alteração de frequência/voltagem e power cycle são ações de risco e devem permanecer exclusivamente nos fluxos de Fleet protegidos por permissão, confirmação humana e audit log.
2. Uma recomendação não deve parecer execução automática. O novo CTA usa “OPEN DIAGNOSTIC” e declara “no command is executed”.
3. Cards do Command Center podem conter URL comercial. O resumo operacional lê apenas `target` e `panel`, nunca abre `url`.
4. Dados stale não devem sustentar recomendação irreversível. O estado stale sobrepõe o headline saudável.
5. Custo ausente não pode ser tratado como custo zero. A ação segura é abrir a configuração/diagnóstico, não calcular lucro fictício.

## 7. Proposta de navegação

Agrupar a navegação sem remover funcionalidades:

1. **Operate**: Dashboard, Fleet, Live Mining, Alerts, Automations.
2. **Analyze**: Probability, Economics (Profitability + Hash Market + Rentals).
3. **Account**: Wallet e configurações da operação.
4. **Admin**: visível apenas para administradores.
5. **Resources**: Docs, Learning e Support em uma área utilitária secundária.

O Dashboard responde “preciso agir?”. Fleet e Live respondem “onde e por quê?”. Probability e Economics respondem “qual o cenário e o custo?”.

## 8. Proposta por tela

### Dashboard — prioridade 1, implementada

- Operational Overview no primeiro viewport.
- Exceções e stale vencem estados nominais.
- KPI/Host Core abaixo, como contexto e drill-down.
- Ação abre o módulo/painel apropriado sem comando remoto.

### Fleet

- Linha superior com online/warning/offline, perda e potência.
- Lista exception-first, filtros por site/modelo/status e busca.
- Detail drawer com causa provável, idade de cada sinal e histórico.
- Controles remotos agrupados em uma zona de risco com dry-run, confirmação e resultado auditável.

### Live Mining

- Priorizar hashrate atual versus baseline, shares rejeitados/stale, latência e último share.
- Mostrar claramente desconexão de pool e reconexões.
- Terminal como diagnóstico secundário, não fonte principal de estado.

### Probability

- Separar probabilidade estatística, progresso observado e cenários.
- Exibir premissas, janela temporal e texto explícito “não é promessa de bloco/lucro”.
- Evitar linguagem de certeza em streaks e milestones.

### Profitability / Economics

- Custo configurado e fonte da cotação sempre visíveis.
- Receita bruta, taxas, custo e líquido em sequência reconciliável.
- Estados de preço stale, custo ausente e divisão por zero explícitos.

### Hash Market e Rentals

- Comparação orientada a decisão: preço efetivo, duração, risco e break-even.
- Link comercial identificado; não misturar com alerta operacional.
- Cards no mobile e tabela avançada no desktop.

### Alerts

- Inbox por severidade e recência, com origem e idade do dado.
- Acknowledge separado de resolver; histórico preservado.

### Automations

- Preview/dry-run primeiro, regra, condição, ação e alcance legíveis.
- Estado enabled não equivale a execução bem-sucedida.
- Mudanças exigem confirmação e apresentam última execução/audit id.

### Wallet

- Identidade/checksum e escopo do endereço antes das métricas.
- Troca de wallet deve mostrar “atualizando” até chegar snapshot correspondente.

### Admin analytics

- Acesso condicionado à role Admin.
- Métricas agregadas sem identificadores sensíveis.
- Loading, vazio e erro próprios, sem bloquear o painel operacional.

## 9. Componentes reutilizáveis necessários

- `OperationalSignal`: label, valor, detalhe, estado e skeleton.
- `FreshnessBadge`: idade, fonte e limiar por tipo de dado.
- `ExceptionSummary`: contagem, severidade e impacto mensurável.
- `SafeAction`: navegação advisory ou fluxo confirmado, com variante visual inequívoca.
- `MetricAvailability`: diferencia valor, zero, não configurado e indisponível.
- `SourceState`: loading/empty/error/offline/stale consistente.
- `RiskActionDialog`: dry-run, resumo de alcance, confirmação humana e audit id.
- `ResponsiveDataView`: tabela desktop e cards mobile a partir do mesmo contrato.

Nesta entrega, o Operational Overview implementa os contratos visuais desses componentes sem iniciar uma migração ampla do design system.

## 10. Critérios de aceitação visuais e funcionais

### Visuais

- Os seis sinais aparecem no primeiro viewport em desktop comum.
- Nenhum texto/valor transborda em 320, 375, 768, 1024 e 1440 px.
- O layout usa 3/2/1 colunas conforme o espaço.
- Severidade permanece compreensível em escala de cinza e com daltonismo.
- Focus ring do CTA é visível e zoom de 200% mantém leitura/ordem.
- Atualizações do polling não piscam nem movem o layout.

### Funcionais

- `WARNING + OFFLINE` determina a contagem de atenção.
- ASIC offline com amostra não contribui para hashrate ativo.
- Perda é `max(0, baseline - atual)`; baseline é 1 h ou último conhecido offline.
- Sem baseline, perda aparece como indisponível.
- Custo só aparece quando `cost_model_configured=true` e há valor finito não negativo.
- Snapshot ou Fleet acima de 150 s produz `STALE DATA`.
- Falha da Fleet produz estado parcial/indisponível sem apagar métricas válidas do snapshot.
- O CTA nunca lê/abre URL externa e nunca chama endpoint de comando.
- Operações remotas continuam sujeitas a role, dry-run/preview, confirmação humana e audit log.
- testes Python e JS, lint, typecheck/checks de frontend, build e E2E desktop/mobile passam.

## Fora do escopo desta entrega

- persistência de série histórica de baseline/perda;
- redesign de todas as telas;
- alteração de thresholds de saúde;
- novos comandos ou automações;
- cálculo financeiro por ASIC/site;
- migração do monólito JavaScript para componentes de framework.
