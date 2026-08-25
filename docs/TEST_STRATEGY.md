# Estratégia de testes — CYPHER65 War Room

## Objetivo e prioridades

O War Room processa telemetria operacional e produz estimativas financeiras;
portanto, a suíte deve prevenir quatro falhas: número/valor fictício,
comando físico indevido, acesso entre tenants e perda/corrupção de eventos.
O primeiro gate de cada PR é determinístico e sem rede. Integrações usam
adaptadores locais/fakes de protocolo, nunca ASICs, pools ou credenciais reais.
E2E roda contra a aplicação local com dados explícitos.

Os IDs `MF`, `API`, `OPS`, `TEL`, `SEC`, `CMD`, `AUD`, `PER`, `UI` e `LOAD`
permitem rastrear a exigência no CI e em incidentes. Os arquivos sugeridos são
o destino inicial; quando já houver cobertura equivalente, o teste deve ser
reforçado ali em vez de duplicado.

| ID | Tipo | Cenário | Entrada | Resultado esperado | Arquivo sugerido |
| --- | --- | --- | --- | --- | --- |
| MF-001 | Unitário | Probabilidade Poisson conhecida | hash do minerador = hash da rede; janela = 600 s | λ=1, `P(>=1)=1-e^-1`, complemento de `P(0)`, aviso de expectativa | `tests/test_mining_formula_contracts.py` |
| MF-002 | Unitário | Probabilidade com zero, negativo, `NaN`, `Infinity` e overflow | parâmetros de hashrate/duração inválidos ou extremos | resposta JSON finita e erro explícito; nunca promessa de bloco | `tests/test_mining_formula_contracts.py` |
| MF-003 | Unitário | Rentabilidade pool/rental/power por vetor conhecido | TH/s, recompensa, fees, BTC/USD e custos fixos | receita, custo e break-even seguem a fórmula e arredondamento contratado | `tests/test_pool_rental_break_even.py`, `tests/test_poll_compute.py` |
| MF-004 | Unitário | Dados insuficientes para rentabilidade | hashrate da rede 0, cotação ausente, custo 0 | sem divisão por zero e campos em fiat indisponíveis, não estimados | `tests/test_poll_compute.py` |
| API-001 | Integração HTTP | Corpo JSON malformado ou não objeto | JSON inválido, lista e escalar em comando | HTTP 400 JSON, sem `AttributeError`/500 | `tests/core/test_app_device_routes.py` |
| API-002 | Integração HTTP | Tipos e schema de comando inválidos | `command` numérico, `parameters` lista, comando desconhecido | HTTP 400 com erro específico; nenhum adaptador chamado | `tests/core/test_app_device_routes.py` |
| OPS-001 | Integração | ASIC offline recebe comando remoto | device `OFFLINE`, `restart` | HTTP 403, motivo `offline`, confirmação requerida e tentativa auditada | `tests/core/test_app_device_routes.py` |
| OPS-002 | Integração de poll | Pool/API de rede indisponível | timeout, 5xx ou payload sem hashrate/preço | snapshot degradado, dados anteriores marcados stale; nenhum lucro inventado | `tests/test_polling_integration.py` |
| OPS-003 | Integração | Reconexão após queda do ASIC/pool | falha transitória seguida de payload válido | estado `offline` → `online`, backoff respeitado e uma única transição auditada | `tests/test_polling_reconnection.py` |
| TEL-001 | Integração de armazenamento | Telemetria repetida/replay | mesmo `device_id`, timestamp e idempotency key | apenas um ponto/histórico; agregados não duplicam | `tests/test_telemetry_idempotency.py` |
| TEL-002 | Unitário + integração | Telemetria inválida ou fora de faixa | chaves ausentes, tipos errados, temperatura/hashrate não finitos | rejeição/quarentena com motivo, sem alterar último dado bom | `tests/test_telemetry_validation.py` |
| TIME-001 | Unitário | Conversão de timestamp e DST | UTC antes/depois de mudança de horário em `America/Sao_Paulo` e `Europe/Brussels` | persistência em UTC; ordenação e duração idênticas na UI | `tests/test_timezones.py` |
| NUM-001 | Unitário | Divisão por zero de shares/custos | total shares, TH/s, preço e rede iguais a 0 | campos contratuais `0`/`None`, nunca exceção ou infinito | `tests/test_mining_formula_contracts.py`, `tests/core/test_safety.py` |
| NUM-002 | Property-based | Valores extremos mas finitos | floats entre limites operacionais e bordas IEEE-754 | invariantes: probabilidades em [0,1], saída serializável e sem `NaN` | `tests/test_numeric_properties.py` |
| SEC-001 | Integração | Isolamento por tenant | token do tenant A tentando ler device/log do B | HTTP 404/403 sem metadados do tenant B | `tests/test_tenant_b2_isolation.py` |
| SEC-002 | Integração | RBAC de leitura vs operação | viewer/operator/admin em `POST /command` | só papel autorizado pode executar; nega e audita as demais tentativas | `tests/test_rbac_device_commands.py` |
| CMD-001 | Integração | Comando remoto em dry-run | `POST /api/devices/:id/test` com restart | `simulated=true`; adaptador, rede e ASIC não são acionados | `tests/core/test_app_device_routes.py` |
| CMD-002 | E2E + integração | Confirmação humana para ação destrutiva | restart/pause e texto/token de confirmação correto, incorreto e reuso | incorreto/reuso não executa; correto é único, vinculado a ação/device/tenant e auditado | `tests/e2e/live-mining.spec.js`, `tests/test_device_confirmation.py` |
| AUD-001 | Integração | Audit log de sucesso, bloqueio e erro | comandos permitidos/bloqueados e falha de adaptador | actor, tenant, device, comando, resultado e UTC persistidos; append-only | `tests/core/test_app_device_routes.py`, `tests/test_audit_log.py` |
| PER-001 | Integração SQLite | Reinício da aplicação | device, telemetria, configuração e audit gravados; reabrir registry | estado e tenant sobrevivem sem duplicar pontos ou segredos | `tests/core/test_registry.py`, `tests/test_persistence_restart.py` |
| UI-001 | E2E visual | Responsividade das telas críticas | viewports 320, 375, 768, 1024 e 1440 px | sem overflow horizontal, controles alcançáveis e dados essenciais visíveis | `tests/e2e/responsive.spec.js` |
| UI-002 | E2E acessibilidade | Dashboard e fluxo de comando | teclado, focus trap, labels, contraste e `prefers-reduced-motion` | Axe sem violações críticas; foco e anúncio de estado corretos | `tests/e2e/accessibility.spec.js` |
| LOAD-001 | Performance | Resumo com muitos ASICs | 100 e 500 devices; telemetria atual e stale | p95 do resumo abaixo do SLO acordado, memória limitada, contagens corretas | `tests/performance/test_fleet_scale.py` |
| LOAD-002 | Performance + integração | Ingestão concorrente de telemetria | 10k eventos, duplicatas e 50 devices concorrentes | sem perda/duplicação fora da política; latência e backlog dentro do SLO | `tests/performance/test_telemetry_ingest.py` |

## Gate de execução

1. Em todo PR: unitários alterados, `git diff --check`, `make lint-sec` e
   `npm run check:frontend`.
2. Para rota, persistência ou tenant: suíte Python integral com o gate de
   cobertura e o E2E afetado via `bash run-e2e.sh --file=...`.
3. Para poll, telemetria ou escala: os testes de integração acima e o perfil
   de performance; falhar se exceder o SLO aprovado, não apenas registrar a
   medição.
4. Antes de deploy: `make build` e revisão do contrato de segurança. Nenhum
   teste de dry-run pode usar credenciais, adaptadores ou hardware reais.

## Implementado neste lote

`MF-001`, `MF-002`, parte de `MF-003`/`NUM-001`, `API-001`, `API-002`,
`OPS-001`, `CMD-001` e a verificação de histórico para `AUD-001` foram
adicionados ou reforçados neste lote. Os demais IDs definem a sequência de
implementação e devem ganhar uma Issue própria antes de alteração de código.

O fluxo de confirmação humana completo (`CMD-002`) permanece bloqueado até a
integração da confirmação server-side das PRs encadeadas #364/#365; o master
atual apenas sinaliza `requires_confirmation` no SafetyEngine.
