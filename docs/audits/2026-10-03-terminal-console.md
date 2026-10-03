# Console de operação — Issue #746

Data: 2026-10-03. Base: `60eda10d3c9fbd6373029e73750bff41bdd1b3ad`.
Direção escolhida pelo usuário: terminal técnico compacto, com alta densidade.

## Problema e resultado

O dashboard repetia hashrate e estado em várias superfícies, dava a mesma hierarquia a operação e contexto global e não oferecia uma tabela central de entidades observáveis. O console agora apresenta um único resumo, seguido pelos workers da pool ou equipamentos locais. A fonte selecionada define a cobertura: dados da pool não comprovam temperatura, potência ou saúde de um ASIC.

Sem equipamentos cadastrados, a tabela de workers continua útil. O resumo identifica o worker principal; seus valores não são distribuídos pelas demais linhas. Colunas sem informação no contrato `all_workers` foram retiradas da tabela. Rede, taxas, halving, ranking e cenários ficam em Análise. Os 13 módulos anteriores continuam disponíveis, com Análise como 14º módulo.

Com telemetria local, exceções aparecem primeiro. Hashrate histórico de equipamento offline permanece identificado e não entra no total atual. Dados ausentes, inválidos, antigos ou com timestamp futuro não viram zero saudável. A idade é calculada pela amostra, e continua avançando entre consultas HTTP.

Uma falha da consulta mantém as observações anteriores, inclusive o último estado online/offline e a idade real. A contagem de amostras recentes segue sua idade; a impossibilidade de confirmar o estado atual aparece separadamente. Hashrate atual e contagem de atenção ficam indisponíveis enquanto a consulta falha.

O detalhe usa diálogo nativo, foco contido, Escape e retorno de foco à linha atual, inclusive depois de uma atualização que substitua seu DOM. Apenas investigação é aberta; o novo console não envia comandos. Atualizações e navegação frequentes são imediatas. A entrada do detalhe por ponteiro usa 160 ms; teclado e movimento reduzido dispensam a animação. Skeletons, lazy loading e os fluxos existentes continuam em uso.

No celular, cada linha mostra nome/estado e hashrate/idade. Temperatura, potência e demais leituras ficam no detalhe. O teste verifica que o primeiro worker completo cabe no primeiro viewport. O menu permanece no cabeçalho e não cobre a tabela. Configurações, atualização e tema são diretos; ações secundárias ficam no disclosure nativo Mais.

## Validação local

- `npm run check:frontend`: PASS na versão final. Bundle sincronizado, guards DOM/a11y/tokens/mobile-XSS, auditoria visual sem overflow/erros/skeletons presos; axe-core desktop/mobile com zero violações nos cenários exercitados.
- JS core: 1.612 PASS. As regressões do console executam o fragmento real, incluindo ausência versus zero, escopo por worker, timestamp futuro, idade entre consultas, hash histórico offline e consulta falha.
- Console, auth, WebLN e cabeçalho: 61 PASS, 1 SKIP previsto no projeto mobile para a sequência explícita de breakpoints. Inclui 14/14 cenários do console nos dois projetos; teclado, foco depois de refresh, falha/recuperação, dados antigos, todos os módulos, estado vazio, tema claro e zoom CSS 200%.
- Dashboard, modais, navegação/loading, telemetria e ordenação de snapshots: 110 PASS nos dois projetos. O caso de cabeçalho foi verificado na rodada acima após alinhar a expectativa ao tema escuro padrão, que usa ausência de atributo.
- Upgrade BTC e identidade da carteira: 20 PASS na rodada que também detectou os caminhos secundários depois corrigidos nos testes auth/WebLN. Compras/WebLN usam mocks; não houve pagamento real.
- Toolbar de aluguéis: 8 PASS, preservando alinhamento desktop, controles mobile e os dois downloads por teclado.
- Python completo: 4.154 PASS, 1 SKIP; cobertura 85,51%, acima do gate de 80%.
- `git diff --check` e `build_app_js --check`: PASS.

O vínculo de rastreabilidade `UI-001` foi preservado no spec de cabeçalho refeito. O teste Python do título dos diagnósticos continua exigindo contagens desconhecidas e identificação de somente leitura. Nenhum gate, limite ou requisito foi removido.

Capturas reais do Playwright usam fixtures sintéticas; não representam uma operação real. Zoom CSS é uma verificação controlada de reflow, sem certificação do zoom nativo do navegador. Testes e screenshots não comprovam ASIC físico, LAN do cliente ou integrações de produção.

## Revisão por equipe

| Equipe | Evidência | Resultado |
|---|---|---|
| Frontend / Product | Tabelas, resumo com entidade, cobertura, mobile e contexto em Análise | Astra revisou as capturas finais e não identificou bloqueios visuais materiais |
| QA | Fragmento real, E2E, foco com polling, estados antigos/falha e regressões preservadas | Verificações acima; fixtures explicitamente sintéticas |
| Motion / Acessibilidade | Operação imediata; diálogo nativo, teclado, reduced-motion, skeleton e axe-core | PASS nos cenários exercitados |
| Security / Backend | Nomes/IDs escapados; contratos API e auth preservados; sem endpoint ou dependência nova | Novo console não executa comandos; os testes de auth/WebLN mantêm suas asserções funcionais |
| Observability | Erros das fontes explícitos; mecanismos existentes preservados | Não afirma Sentry habilitado em produção |
| DevOps | Issue → branch → PR → CI → aprovação → squash | #746 / `enh/746-compact-terminal` / PR #747; aprovação independente e checks obrigatórios continuam exigidos |

Esta autorrevisão e o parecer visual Astra não substituem aprovação independente no GitHub. O risco principal é a alteração da apresentação compartilhada entre módulos, mitigada pelas regressões de navegação, modais, carteira e toolbar.

## Publicação

O checkout original `test/609-telemetry-validation` e suas alterações foram preservados. A implementação fica no worktree isolado e no PR #747. As imagens são evidência local, sem alegação de publicação em Render. A falha mobile conhecida é acompanhada na Issue #737; a reconstrução não altera dependências mobile nem contorna gates. O estado de CI e aprovação deve ser verificado no head exato antes de merge/deploy.
