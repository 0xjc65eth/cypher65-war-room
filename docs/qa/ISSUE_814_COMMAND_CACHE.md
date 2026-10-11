# Issue #814 — publicação de status de comandos

Checkpoint: 2026-10-11, Europe/Brussels. Base: `fd683ecda08d2d867bf9f02d708d7b040e49a725`, integração externa da #815.

## Problema e correção

O publisher de telemetria podia ler ONLINE e parar antes do callback. Um comando
gravava PAUSED no banco e diretamente no cache; depois o callback antigo gravava
ONLINE sobre esse cache. O banco permanecia PAUSED. É uma corrida de publicação,
sem troca de identidade ou corrupção de histórico demonstrada.

`DeviceRegistry.publish_device_state(device_id, tenant_id)` reutiliza a leitura
do estado comprometido e o lock do publisher de telemetria. Os caminhos de pause
direto, pause enfileirado e resume direto chamam essa API somente depois de
`update_device` retornar sucesso. A rota não transmite um status capturado antes
de adquirir o lock e não escreve o dicionário compartilhado diretamente.

Se o callback antigo já estiver em andamento, a publicação do comando espera seu
término e relê o banco. Se uma amostra posterior tiver mudado o estado, essa
publicação usa o estado atual. Tenant incorreto ou dispositivo removido não é
publicado. Não são criadas amostras, timestamps de medição ou eventos de ingestão.

## Contratos preservados

- Pause enfileirado continua intenção otimista, com ACK/reconciliação pendentes.
- Resume enfileirado aguarda telemetria; não confirma ONLINE antecipadamente.
- Resume direto conserva a derivação de estado da leitura do conector.
- Erro de transporte conserva ACK/reconciliação desconhecidos e não confirma pause.
- Falha do callback é best-effort: não converte despacho concluído em erro.
- Confirmação, política de comandos físicos, SafetyEngine, ledger e auditoria
  permanecem nos caminhos existentes; os testes usam conectores simulados.

## Revisão de arquitetura

/advisor avaliou substituir a escrita direta, adicionar outro lock ou introduzir
outbox. Recomendou uma API pública curta sobre o publisher existente: menor
acoplamento e risco, sem migração/dependência nova. O teste de aceitação interrompe
o callback real, confirma a alteração no SQLite, libera o callback e compara cache
final com o banco. A revisão por subagente não é approval no GitHub.

## Revisão adversarial

/devil reproduziu a corrida com SQLite real, threads e função real de cache.
Com a correção, o comando espera o callback em execução e relê PAUSED; banco e
cache convergem. Verificou isolamento de tenant/remoção, ausência de novas
amostras/eventos, ACK/ledger e falha best-effort. Não demonstrou CRITICAL, HIGH
ou MEDIUM novo na delta. A latência de um callback em execução é herdada pela
publicação do comando; não ocorreu deadlock nas provas. A prova negativa e as
15 regressões mantêm cobertura real de cache antes testada com mocks.

## Limites

A ordenação vale para callbacks dessa instância/processo. Não há outbox,
sincronização de caches de outros workers nem garantia linearizável global.
A atualização do próprio banco derivada de um repoll de resume pode ficar tardia;
esta unidade corrige a publicação, não esse contrato. Remoção/DHCP após a leitura
e antes do callback conserva o limite documentado da #813. Publicar cache não
atesta execução física nem reconciliação operacional.

## Validação

- PASS: 110 testes focados, 2,14 s (`/tmp/c65-814-focused.log`).
- PASS: 15 novas regressões; QA executou 37 casos com pause existente, 0,95 s.
- PASS independente /devil: 15 casos novos e 61 casos pause/atomic, total 76.
- PASS: E2E Fleet manual, 8 casos desktop/mobile, 10,3 s (`/tmp/c65-814-e2e.log`).
- PASS: Black em 107 arquivos do gate, Flake8, Bandit `-ll`, monkeypatch guard
  e diff check; nenhum bypass foi adicionado.
- PROVA NEGATIVA: código antigo carregado apenas em memória falhou em 4/5
  casos concorrentes; o caso de erro de transporte continuou passando. QA
  reproduziu cache ONLINE versus banco PAUSED no caminho direto, evidência
  `/tmp/c65-814-old-publication-negative.log`. Nenhum arquivo de produção foi
  revertido para essa prova.
- PASS: suíte completa, **4325 passed, 2 skipped, zero failures/errors**,
  **85,59%** de cobertura, 184,93 s. Gate mínimo 80%.
  JUnit: 4327 casos, zero falhas/erros. Evidência `/tmp/c65-814-full.log`,
  `/tmp/c65-814-full-tests.xml` e `/tmp/c65-814-full-coverage.xml`.
  Skips: integração Gist privada sem credenciais e SDK Sentry ausente no Python
  local. Não são apresentados como integrações comprovadas.

E2E Fleet manual verifica a interface existente em desktop/mobile; não é prova
de execução em miner. O fluxo HTTP de comandos e a corrida são cobertos por
SQLite real, threads/barreiras e conectores simulados nos testes Python.

## Publicação

Closes #814; referência de dependência #815. CI do SHA exato e approval GitHub
são gates separados. Nenhum merge/deploy foi executado por este agente.
