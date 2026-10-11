# Issue #813 — Identidade e ingestão atômica do Fleet

Data do checkpoint: 2026-10-11, Europe/Brussels. Base integrada: `b2a4c223e0f7c1dd9c9d0d2026e63ff45964f44d` (PR #805, merge externo). [Issue #813](https://github.com/0xjc65eth/cypher65-war-room/issues/813) continua a implementação autorizada na [#777](https://github.com/0xjc65eth/cypher65-war-room/issues/777#issuecomment-6027936913), encerrada externamente. Branch: `fix/813-atomic-device-identity`. Sem merge/deploy deste agente.

## Contrato e compatibilidade

MAC válida de seis octetos unicast, normalizada e tenant-scoped é a evidência aprovada para convergência. MAC não autentica o hardware. IP é locator mutável, nunca chave física. Registro manual/probe e Agent usam o mesmo resolver transacional; MAC ausente/inválida, alias órfão/contraditório e legado ambíguo causam conflito explícito, sem alterar rows ou histórico.

`POST /api/agent/register` exige `devices[].mac` e informa conflitos por item em `blocked`/`code`, conservando os itens aceitos e HTTP 201 do lote. `POST /api/agent/telemetry` exige `{ip, mac, telemetry}` de identidade previamente registrada e locator atual. Não autocadastra pelo IP. MAC ausente/inválida, locator antigo, outro ocupante, ID contraditório ou MAC contraditória na amostra retornam JSON 409; identidade removida retorna 410. Tenant vem da autenticação. Eventual `device_id` no envelope/amostra deve coincidir com o ID resolvido pelo servidor.

Clientes antigos sem MAC deixam de ser aceitos. Agent standalone verifica MAC válida para todos os tipos; CGminer/Braiins sem essa evidência permanecem sem identidade verificada. O Agent não inventa MAC a partir de IP, hostname ou métrica. AxeOS com MAC observada diferente/ausente fica em conflito até nova descoberta; o loop não envia heartbeat usando a antiga identidade para esconder a contradição.

Chamadas internas por ID que omitem MAC e locator continuam possíveis para testes/instrumentação histórica, mas conferem ID, tenant e registro ativo. Não representam prova física. As boundaries de produção Agent e polling sempre passam MAC e locator. Tombstones por IP ou MAC continuam bloqueando ressurreição automática; restore é explícito. DHCP com a mesma MAC conserva ID, telemetria e comandos. Não há migração/reassociação automática de legado.

## Escrita e publicação

Um núcleo com uma conexão SQLite e `BEGIN IMMEDIATE` resolve identidade, tenant, locator e tombstone, consulta baseline, aplica idempotência, grava amostra, atualiza status/last_seen/ownership e limpa quarentena elegível. Falha de SQL após INSERT desfaz todos os efeitos. Amostra inválida grava apenas metadata de quarentena após revalidar identidade na própria transação.

Replay idêntico confirma o estado persistido sem duplicar history/eventos, renovar presença, limpar uma quarentena posterior ou publicar sample antiga. Chave reutilizada com payload diferente permanece conflito. Heartbeat, zero, PAUSED e staleness mantêm seus contratos. Polling local não ganha ownership Agent; erro de rede tardio revalida identidade/locator antes de marcar OFFLINE. Enriquecimento manual também valida tenant/MAC/IP/registro ativo depois do probe.

Eventos/cache ocorrem após commit. O publisher serializa callbacks por instância com RLock, relê row ativa e amostra atual numa read transaction e fecha essa conexão antes do callback. Um publisher atrasado relê a versão nova; rowid permite suprimir eventos de uma amostra já superada. O loop real `_poll_axe_fleet` não recacheia o retorno antigo do poll. O wrapper de `save_telemetry` do app aceita a chave e devolve o bool real.

**Limites:** o RLock não é ordenação global entre processos nem outbox durável. Existe janela entre o fechamento da leitura e o callback em que uma remoção/DHCP pode confirmar; não se afirma publicação atomicamente acoplada a qualquer alteração posterior. SQLite é a implementação validada; sem prova PostgreSQL, hardware ou produção.

## Revisões e regressões

As três falhas HIGH originais de registro sem MAC, associação por IP e polling divergente estão cobertas por regressões. /advisor recomendou o núcleo privado transacional em vez de importar o WIP inteiro. /devil reproduziu HIGH adicional em publisher atrasado sobrescrevendo leitura nova; corrigido com publicação serializada e releitura. /devil reproduziu MEDIUM em enrichment manual após DHCP; corrigido com binding. /advisor encontrou HIGH no segundo cache do loop de polling; removido e coberto pelo loop real com duas threads.

`tests/test_device_identity_atomic.py` usa SQLite temporário, conexões independentes, ThreadPool/barreiras, falha por trigger SQL, API Flask/JWT de teste, app/loop reais e connectors mockados. Abrange MAC ausente/inválida/contraditória, legacy/aliases, manual+múltiplos Agents, tenants, DHCP/history/commands, tombstones, rollback, quarentena, replay, publisher tardio, ownership e erro de rede tardio. Fixtures nominais e benchmarks sintéticos declaram MAC explicitamente; isso não é dado de hardware. Nenhum guard de transporte ou assert de segurança foi desabilitado.

## Quality gates

| Estado | Execução | Evidência |
|---|---|---|
| PASS | Suíte completa Python, localhost autorizado | **4310 passed, 2 skipped, zero failures/errors, 85,57%, 219,69 s.** JUnit 4312 casos. |
| PASS | Focado atomicidade/polling/Fleet/quota | 93 testes, 1,89 s; novas regressões de cache incluídas. |
| PASS | QA fixtures antes da publicação final | 355 testes em 17 arquivos, 34,40 s. |
| PASS | E2E Fleet agentless/manual add | 8 testes desktop/mobile, 14,9 s; Flask e SQLite descartáveis. |
| PASS | Static gates | Black 107 arquivos, Flake8, Bandit padrão sem MEDIUM/HIGH, guard monkeypatch e diff. |
| FAIL ambiental inicial | Suíte sob sandbox restrito | 4225 PASS, 72 FAIL, 12 ERROR, 2 SKIP, 85,25%; 83 PermissionErrors de socket local e uma fixture de quota sem MAC, corrigida. Não contado como PASS. |
| NOT RUN neste checkpoint | Hardware, produção, signing/TestFlight e SLO externo | Fixtures, exports e CI não substituem essas provas. |
| PENDING | CI do SHA publicado e approval GitHub | Reviews por subagente não equivalem a approval. |

Os dois skips condicionais são Gist privado sem credencial explícita e SDK Sentry ausente no Python local. Logs: `/tmp/c65-813-full-authorized.log`, `/tmp/c65-813-full-tests.xml`, `/tmp/c65-813-full-coverage.xml`, `/tmp/c65-813-finalfocused.log`, `/tmp/c65-813-fixture-final.log`, `/tmp/c65-813-e2e-authorized.log`. Artefatos /tmp são locais; o CI fornece evidência remota por SHA.

## Dívida e rollout

Duplicatas reais em produção continuam UNKNOWN sem DB/evidência sanitizada. Reconciliação histórica preservando history/commands/audit/rollback permanece proposta separada no incidente #777; este patch não reassocia dados. Validar atualização do Agent que carrega MAC antes de ativar o contrato estrito. Nenhum merge, deploy ou comando físico foi executado por este agente.

Reauditoria final: /devil executou 51 testes (1,90 s), confirmou a remoção do cache duplicado e não demonstrou HIGH na delta. /advisor confirmou o desenho e pediu assert de que A já estava publicada antes de B; assert acrescentado e 51 testes passaram novamente (1,64 s), sem nova mudança em produção.

Finding separado: [#814](https://github.com/0xjc65eth/cypher65-war-room/issues/814), MEDIUM/P2: status de comando `_mark_cache_status` escreve fora do publisher e pode ser sobrescrito por callback atrasado. Não altera ID/MAC/histórico. Requer contrato/revisão de comando próprios; não se alega consistência global de todos os writers.
