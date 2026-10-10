# DUPLICATE DEVICE INCIDENT REPORT — Issue #777

Data: 2026-10-10. Classificação: **HIGH / P1; Wave 1A incompleta**.

Contrato autorizado pelo mantenedor: [comentário da #777](https://github.com/0xjc65eth/cypher65-war-room/issues/777#issuecomment-6027936913).
MAC válida, normalizada e tenant-scoped permite convergência; IP é locator.
Ausência de MAC e aliases/rows ambíguas exigem conflito explícito. Esse contrato
não é approval de PR nem autorização para alterar dados históricos.

## Checkpoint e decisão de escopo

- Master observada: `b89c903e733c62f80b883497b4ea189af3a1a72e`.
- Hotfix #805 observado: `5b9128eb06a4bd4a6676c536ae0250056a40f01a`.
- Reproduções do executor: checkout composto sobre `155dcc7`, com os patches
  locais de frontend, #799, #802 e #803. Isso não representa master integrada.
- Revisão /devil: hotfix #805, Flask test client, JWT de teste, SQLite temporário
  e connectors mockados. Sem hardware, credentials de produção ou DB de usuário.
- WIPs preservados: `/private/tmp/cypher65-777-clean` e
  `/Users/juliocesar/cypher65-777-device-identity`. A branch solicitada
  `fix/777-device-identity` já pertence ao segundo WIP; esta recuperação usa
  `fix/777-agent-identity-evidence`, criada da master acima.

Decisão: **SEPARATE PR**, vinculada por `Refs #777`. A unidade atual recupera
apenas transporte da MAC reportada no Agent. Não fecha #777, não corrige o
resolver ou persistência do servidor, não autentica MAC e não reassocia histórico.
O binding completo deve preservar as primitives de #805 quando integradas,
em vez de importá-las novamente neste diff.

## Cadeia causal demonstrada

| Severidade | Fato reproduzido | Causa no snapshot #805 | Consequência |
|---|---|---|---|
| HIGH | Registro sem MAC no IP de A recebeu HTTP 201 e alterou metadata de A. | `_identity_device_tx` aceita fallback por IP quando falta MAC; `agent_register_devices` usa upsert sem evidência obrigatória. | Reporter desconhecido pode alterar metadata da row identificada, mantendo seu ID/MAC. |
| HIGH | A muda de IP; retry no endereço antigo cria outra row sem MAC. Se B ocupa o endereço antigo, a amostra de A é salva no ID de B, mesmo enviando ID/MAC de A. | `agent_telemetry` resolve por IP, ignora MAC/ID e auto-upserta quando o locator está vazio. | Duplicata sintética ou contaminação de telemetria/estado. |
| HIGH | Polling de uma row com MAC A persistiu amostra cujo connector reportou MAC B. O Agent também retornou essa amostra. | `poll_device` e `_poll_telemetry` não verificam troca física antes de aceitar a medição. | A row pode receber dados de outro ocupante do IP. |
| MEDIUM | Registro com MAC diferente no mesmo IP retorna HTTP 500. | `DeviceIdentityConflict` não é capturado na boundary de register. | Falha de batch/retry em vez de conflito JSON explícito. |

Controle positivo independente: 16 registros simultâneos, oito workers e
conexões SQLite independentes, com mesma MAC/tenant, produziram **um ID e uma
row**. A serialização existente deve ser preservada.

O executor confirmou no SQLite temporário: cadastro sem MAC alterou o modelo
da row identificada; DHCP conservou ID; B recebeu outro ID ao ocupar o IP antigo;
a amostra enviada ao IP antigo ficou com B: **zero amostras em A, uma em B,
123.000.000.000 H/s**. Log local: `/tmp/c65-777-proof.json`.

**UNKNOWN em produção:** não foram fornecidos grupos reais de duplicatas,
snapshot sanitizado ou evidência de ocorrências. Os defeitos sintéticos são
demonstrados; frequência, causa de cada incidente real e dados afetados não são.

## Mapa de criação, atualização e histórico

| Caminho | Owner / persistência | Verificação pendente da #777 |
|---|---|---|
| Add manual/probe | `routes.add_device` → `registry.add_device` → `_persist_registered_device` | Mesmo resolver MAC do Agent; ausência de evidência sem criação/convergência. |
| Discovery Agent | `agent._run_main` → `/agent/register` → `upsert_agent_device` | Conflito explícito; tenant e identidade dentro de transação. |
| Telemetria Agent | `_poll_telemetry` → `_build_telemetry_event` → `/agent/telemetry` → `save_agent_telemetry` | Identidade/locator da amostra revalidados na transação de write. |
| Polling servidor | `registry.poll_device` → `save_telemetry` / `update_device` | MAC observada deve ser compatível com a identidade alvo. |
| Update/DHCP | `_identity_device_tx` / `_write_device_tx` | Conservar ID e não migrar samples/commands automaticamente. |
| Remove/restore/GC | `remove_device`, `clear_tombstone`, `gc_tombstones` | Preservar proteção/history/alias e fixes da #805; corrida de tombstone não grava amostra. |
| Comandos | `enqueue_agent_command` → `pending_agent_commands` → pull/ack | Histórico mantém `device_id`; esta unidade não altera execução/capabilities. |

Schema inspecionado: `axe_devices.id` é PK; não há constraint física única na
row de devices. `axe_device_identity_aliases` tem PK `(tenant_id, mac_normalized)`
e índice `(tenant_id, device_id)`, sem FK declarada. `axe_telemetry` declara FK
para devices e índice único parcial `(tenant_id, device_id, idempotency_key)`;
a eficácia da FK depende de `foreign_keys` em cada conexão. `axe_agent_commands`
tem PK de comando e guarda tenant/device_id sem FK declarada. Transações reais
de criação usam `BEGIN IMMEDIATE`; lookup de rota e gravação de telemetria são
operações separadas, permitindo mudança de locator entre elas.

## Consultas somente leitura propostas

Não executadas em produção. Executar apenas sobre snapshot sanitizado autorizado,
sem expor IP/MAC/tenant reais. A primeira query lista candidatos, não prova MAC
válida/unicast nem autoriza merge. A validação estrutural da MAC usa a normalização
Python; esse procedimento não autentica hardware.

```sql
PRAGMA query_only = ON;
BEGIN;
SELECT tenant_id, UPPER(REPLACE(REPLACE(TRIM(mac_address), ':', ''), '-', '')) AS candidate,
       COUNT(*) AS rows_total, SUM(CASE WHEN COALESCE(removed_at,0)=0 THEN 1 ELSE 0 END) AS active_rows
FROM axe_devices
WHERE TRIM(COALESCE(mac_address, '')) <> ''
GROUP BY tenant_id, candidate HAVING COUNT(*) > 1;

SELECT tenant_id, ip_address, COUNT(*) AS active_rows
FROM axe_devices WHERE COALESCE(removed_at,0)=0
GROUP BY tenant_id, ip_address HAVING COUNT(*) > 1;

SELECT COUNT(*) AS orphan_aliases
FROM axe_device_identity_aliases AS a
LEFT JOIN axe_devices AS d ON d.id=a.device_id AND d.tenant_id=a.tenant_id
WHERE d.id IS NULL;

SELECT COUNT(*) AS orphan_samples
FROM axe_telemetry AS t
LEFT JOIN axe_devices AS d ON d.id=t.device_id AND d.tenant_id=t.tenant_id
WHERE d.id IS NULL;

SELECT COUNT(*) AS orphan_commands
FROM axe_agent_commands AS c
LEFT JOIN axe_devices AS d ON d.id=c.device_id AND d.tenant_id=c.tenant_id
WHERE d.id IS NULL;
ROLLBACK;
```

Reconciliação futura: classificar cada grupo com evidência física/tenant,
preservar snapshots e referências de samples/commands/auditoria, produzir plano
com rollback verificável e revisão separada. Grupos ambíguos ficam UNKNOWN.
Não há migração, fusão, apagamento ou reparo automático nesta recuperação.

## Unidade Agent e regressões

`_build_telemetry_event` recebe MAC opcional e a inclui no envelope. O main loop
prefere `telemetry.mac` quando a chave existe, inclusive vazio/None, para não
ocultar uma resposta divergente com a MAC de discovery em cache. Sem essa chave,
transporta a evidência de discovery; se não existe, preserva ausência. Não há
normalização nem inferência de identidade física no emissor.

O timestamp e idempotency key são gerados uma vez e o mesmo evento segue todos
os retries. Heartbeat vazio continua permitido. O servidor atual ignora o campo
aditivo; o bug de binding permanece aberto até a próxima unidade de servidor.

Regressões antes do patch: os seis testes iniciais falharam por ausência do
argumento/campo MAC. Após o patch e três casos adicionais de evidência atual
divergente/vazia/None: **9 passed**. Testes reais do main loop, emissor e retry.
Fixtures de protocolo/main loop na master apresentam quatro falhas reproduzidas
também com o código original do Agent; reparos estão no PR #808 e não foram
duplicados aqui. Logs: `/tmp/c65-777-regression-before.log`,
`/tmp/c65-777-baseline-mainloop.log`, `/tmp/c65-777-baseline-protocol.log`.

Revisão independente /devil: **9 passed** e sete verificações adicionais de
evidência raw, ausência, cópia e retry; nenhum CRITICAL/HIGH introduzido nesta
unidade. /advisor confirmou o escopo e os limites. Ambos revisaram o documento;
as queries foram corrigidas para incluir `removed_at=NULL`, conforme aplicação.
Isso não representa approval no GitHub.

Gates locais: sintaxe, Flake8 `E9,F63,F7,F82`, guard de monkeypatch, Black do
novo teste e diff check **PASS**. Varredura adicional de `agent/agent.py` com
Bandit `-ll`: **FAIL B310/MEDIUM** no `urlopen` preexistente, reproduzido também
no Agent original de master, sem diff nessa chamada. Não é apresentado como
security PASS; o gate padrão de CI verifica `agents/`, não este script `agent/`.

Suíte composta com esta unidade: **1 failed, 4.269 passed, 2 skipped, 85,59%**,
236,20 s, `/tmp/c65-recovery-777-full.log`. Falha:
`test_actual_registry_auth_summary_and_store_invariants[mixed]`, transporte
interceptado pelo guard. A suíte anterior sem esta unidade havia passado;
essa rodada permanece FAIL, sem usar cobertura suficiente para apagar a falha.

Retomada: o trace capturou `detect_firmware` em uma thread de um teste anterior
de inclusão manual que não mockava os probes. /devil confirmou o método original
com HTTP/TCP negados: a thread continuava após o teste terminar. O reparo da
fixture conserva registry/auth/201 reais, verifica ID/MAC persistidos e registra
zero tentativas sob os mesmos guards. Como #808 foi integrado externamente antes
de receber esse reparo, ele segue na **Issue #811**, em PR separada.

Revalidação composta final, sem instrumentação: **4.270 passed, 2 skipped,
zero failures/errors, 85,58%, 230,23 s**. JUnit: 4.272 casos;
`/tmp/c65-recovery-777-final-tests.xml`, cobertura
`/tmp/c65-recovery-777-final-coverage.xml`, log
`/tmp/c65-recovery-777-final.log`. Isso inclui o patch Agent desta PR e a fixture
#811, além da recuperação Fleet #805 ainda separada. Não equivale a CI do SHA
isolado nem fecha os HIGH da #777. Skips continuam Gist privado sem credenciais
explícitas e Sentry SDK ausente no Python local.

Aceite restante para servidor: ausência/invalid MAC, MAC divergente, alias órfão,
legado ambíguo, isolamento tenant, DHCP e IP reuse; corrida remove/restore/update
entre preflight e persistência; retry atrasado não cria row nem escreve em outra
identidade; polling verifica evidência atual; controles concorrentes mantêm um
ID e todo histórico. **Todos permanecem obrigatórios para concluir #777.**
