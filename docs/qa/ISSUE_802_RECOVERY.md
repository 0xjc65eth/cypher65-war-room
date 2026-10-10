# Issue #802 — Recuperação de contratos de QA

## Causa e mudanças

A suíte no runtime parcial de Fleet registrou 21 falhas (`/tmp/c65-fleet-recovery-pytest.log`, 4191 PASS, 2 SKIP). Este lote corrige os contratos de teste abaixo; não modifica o agente, o registry nem as rotas de produção. As primitivas ausentes e a restauração segura pertencem à Issue #799.

| Contrato | Antes | Depois e garantia preservada |
|---|---|---|
| Loop/poll AxeOS | Fixtures declaravam `bitaxe` sem MAC; `_identity_unresolved` corretamente bloqueava o polling e retornava `{}` | Fixtures de telemetria usam MAC do payload oficial/probe virtual; novo teste de loop confirma que um Bitaxe sem MAC não é consultado nem enviado, enquanto o peer continua |
| Fallback standalone | Fixtures de hashrate inválido sequer alcançavam o parser por falta de identidade | Identidade conhecida é construída pelo parser real, então N/A/NaN/Inf/negativo/overflow continuam exigindo `None` e `_invalid_fields`, nunca zero |
| Guarda de identidade | Não havia proteção explícita contra enfraquecer a guarda ao corrigir fixtures | Teste parametrizado confirma Bitaxe/Braiins sem MAC retornam `{}` sem sequer chamar `_probe_axeos` |
| DHCP/SQLite | Fixture criava à mão uma versão antiga de `axe_devices`, sem a tabela de aliases | `DeviceRegistry.ensure_tables()` instala o schema real; continuam obrigatórios o mesmo ID e o novo IP |
| Pause inicial | Probe recente com 100 GH/s era comparado com IDLE | Espera ONLINE, conforme a telemetria positiva; após pause continuam obrigatórios PAUSED e hash zero/obsoleto tratado corretamente |
| Resposta de pause | MagicMock preparava método `find_device_for_identity` que a rota não chama; `get_device_by_ip` retornava outro MagicMock não serializável | Prepara o método efetivamente chamado com row concreta; resposta deve continuar refletindo PAUSED persistido |
| CLI de medição | Entrada interna `--worker` executava dentro do processo compartilhado de pytest; falhou com `transport guard was called` no lote completo e passou sozinha | Executa a CLI real em subprocesso descartável, como o launcher de produção documenta; exige workload stale, zero tentativas externas e banco intacto. Casos inválidos e testes diretos dos guards permanecem |
| Guards de inclusão manual | Mocks de registry retornavam um MagicMock truthy para `get_removed_by_ip`; a rota corretamente rejeitava inclusão como tombstone (409) | Fixtures de dispositivo novo declaram resultado vazio; a guarda de restore da #799 permanece intacta e as verificações de probe/registro continuam |
| Isolamento por tenant | Fixture fazia soft-delete no DB compartilhado entre casos; os IPs repetidos preservavam tombstones e eram corretamente bloqueados | Cada teste ganha SQLite em `tmp_path` com schema real, registry novo e owners de módulo/app/rotas atualizados. Nenhum tombstone é apagado para liberar o teste seguinte; cache e snapshot prévios são restaurados |
| MF-005 | Requisito no plano sem marcador nem linha no mapa de cobertura | `TestEnergyRewardCadence` calcula vetores independentes para hashrate, recompensa/bloco, energia e break-even; preço ausente continua indisponível |

A origem exata da tentativa interceptada no processo compartilhado da CLI ainda não foi demonstrada. Concorrência/poluição entre testes é hipótese apoiada na diferença entre execução isolada e completa. A mudança segue o contrato documentado de isolamento e mantém os testes em processo de `run_workload` com banco, JWT, tenant e guards reais; não desativa nenhuma guarda.

A validação composta inicial das correções (#798/#799/#802 e recuperação de qualidade) terminou com **12 FAIL, 4249 PASS, 2 SKIP e cobertura 85,49%**. Nove falhas revelaram os mocks truthy no novo guard de tombstones; três revelaram reutilização de SQLite com soft-delete na fixture de tenant. Essas correções adicionais afetam somente `tests/integration/test_braiins_fleet.py`, `tests/test_axe_routes_integration.py` e `tests/test_fleet_tenant_scope.py`, sem mudança em produção.

## MF-005: premissas explícitas

O modelo usa 144 blocos/dia (600 segundos/bloco), rede de 5 EH/s, fees de pool de 1,5%, orphan de 0,5%, taxa de transação de 0,05 BTC/bloco e cotação USD de 100.000. Três vetores variam hashrate (50/100/200 TH/s), subsídio (1,5625/3,125/6,25 BTC), potência e custo/kWh, inclusive potência zero. Valores esperados são calculados diretamente dessas entradas, não do payload retornado. Um quarto teste preserva custo de energia conhecido com cotação indisponível e exige receita fiat/break-even `None`.

## Validação registrada

- **PASS**: testes próprios de loop, matemática e rastreabilidade em #802: 34 testes, 0,78 s.
- **PASS**: validação focada com registry/rotas #799 previamente importados somente para leitura: 191 testes, 10,02 s. **FAIL esperado por dependência**: subprocesso CLI importou o checkout #802 sem a primitiva `normalize_device_mac` da #799 (1 teste).
- **PASS**: CLI original `test_worker_cli_and_argument_errors` sozinha no checkout #799: 1 teste, 1,23 s. Isto não prova ausência de interferência na suíte completa.
- **PASS**: Black nos novos testes e demais arquivos alterados; testes matemáticos preexistentes preservados exatamente (sem gate Black desse arquivo). Flake8 `E9,F63,F7,F82` e `git diff --check` passaram.
- **PASS**: validação composta focada de todos os testes próprios e três arquivos adicionais de fixtures: **311 testes, 31,89 s**, `/tmp/c65-802-final-focused.log`.
- **PASS final composto**: 4.261 passed, 2 conditional skips, zero failures/errors, 188,32 s; cobertura 85,59% no gate de 80%.
- **Review**: /devil revisou o patch inicial e executou 192 testes com sucesso. Os três arquivos adicionais foram revisados pelo executor principal; a última repetição independente foi interrompida pelo limite de uso do subagente.

Logs locais: `/tmp/c65-802-runtime-focused.log`, `/tmp/c65-802-focused.log`. A validação por importação não altera nenhum arquivo de #799 e não substitui a validação composta final. O checkout base sem #799 permanece incapaz de executar os testes que dependem das primitivas de identidade.

## Limites

Mocks de protocolo são servidores descartáveis em loopback; não houve acesso a mineradores físicos, pools, credenciais, banco operacional ou histórico real. Não houve commit, push, merge ou deploy por este agente. A Issue #777 continua responsável pelo redesenho completo de identidade e migração; estes ajustes mantêm os contratos de segurança existentes.

## Evidência final do executor

Suite completa: `/tmp/c65-recovery-combined-final.log`; JUnit `/tmp/c65-recovery-final-tests.xml` (4.263 casos, zero erros/falhas); cobertura `/tmp/c65-recovery-final-coverage.xml`. Skips: integração privada de Gist sem credenciais explícitas e Sentry SDK ausente no Python local. `pip-audit -r requirements.txt`: PASS, nenhuma vulnerabilidade conhecida. Os skips não provam integração externa/Sentry; a dependência de produção permanece declarada em requirements. CI do PR isolado ainda depende dos reparos #799/#803; o resultado composto não significa CI remoto verde.
