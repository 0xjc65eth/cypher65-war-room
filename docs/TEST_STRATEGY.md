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
| SEC-002 | Integração | RBAC de leitura vs operação | viewer/member/admin em `POST /command` | só `member`/`admin` pode confirmar ou executar; nega `viewer` antes do adaptador | `tests/core/test_app_device_routes.py` |
| CMD-001 | Integração | Comando remoto em dry-run | `POST /api/devices/:id/test` com restart | `simulated=true`; adaptador, rede e ASIC não são acionados | `tests/core/test_app_device_routes.py` |
| CMD-002 | E2E + integração | Confirmação humana para ação destrutiva | restart/pause e texto/token de confirmação correto, incorreto e reuso | incorreto/reuso não executa; correto é único, vinculado a ação/device/tenant e auditado | `tests/core/test_app_device_routes.py`, `tests/e2e/live-mining.spec.js` |
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

`MF-001`, `MF-002`, `MF-003`, `MF-004`, parte de `NUM-001`, `API-001`, `API-002`,
`OPS-001`, `SEC-002`, `CMD-001` e a verificação de histórico para `AUD-001` foram
adicionados ou reforçados no lote de fórmulas (MF-003/MF-004 completos em 2026-09-17,
vetor de fórmula completa + indisponível ≠ 0). A Issue #368 implementa
`CMD-002` e reforça `AUD-001`: as tentativas sem confirmação, os reusos, as
falhas do adaptador e as execuções aprovadas passam pelo audit persistente.
Os demais IDs definem a sequência de implementação e devem ganhar uma Issue
própria antes de alteração de código.

## Contrato de confirmação server-side (CMD-002)

Comandos com `requires_confirmation=true` não chegam ao adaptador apenas com
um campo booleano do cliente. O operador deve digitar a frase devolvida pelo
servidor e chamar:

```text
POST /api/devices/:id/command/confirmation
{ command, parameters, confirmation: "CONFIRM <COMMAND>" }
```

A resposta 201 devolve `confirmation_token` de uso único. O cliente o envia
somente na chamada seguinte a `POST /api/devices/:id/command`. O token expira
em 120 segundos, é consumido inclusive quando os parâmetros não correspondem,
e está vinculado ao tenant, device, comando e parâmetros canônicos. Reiniciar
o processo invalida todas as confirmações pendentes (fail closed). O token não
é persistido nem incluído no audit log.

Campos de credenciais (senha, secret, token, chave privada e autorização) são
redigidos nas respostas, no histórico de comandos e no audit log. A resposta
que emite o token usa `Cache-Control: no-store` e `Pragma: no-cache`.

Os endpoints de confirmação e execução exigem papel RBAC `member` (ou
`admin`); `viewer` é somente leitura e recebe HTTP 403 antes de qualquer I/O.

---

## Mapa de cobertura — auditoria de 2026-09-16 (wave W3)

A tabela do início deste documento é o **plano**. Esta seção registra o **estado real** de cada ID
depois da wave W3 (`docs/MULTI_AGENT_TEAM.md` §8). A distinção existe porque as duas divergiam em
silêncio: o plano lista 24 IDs e o §"Implementado neste lote" declara apenas onze deles.

**Como a auditoria foi feita — e o que ela não fez.** A varredura foi por **arquivo sugerido** e
depois por **comportamento**, não por ID, porque nenhum teste do repositório cita um ID da matriz
(achado transversal abaixo). Para cada ID: (1) o arquivo sugerido existe? (2) se não, a exigência
está coberta sob outro nome — o que a própria matriz autoriza (*"quando já houver cobertura
equivalente, o teste deve ser reforçado ali em vez de duplicado"*)?

| ID | Estado | Evidência / Issue |
| --- | --- | --- |
| MF-001 | implementado | `tests/test_mining_formula_contracts.py`; declarado no §"Implementado neste lote" |
| MF-002 | implementado | idem |
| MF-003 | **implementado** | vetores de fórmula completa + arredondamento contratado em `tests/test_pool_rental_break_even.py` (2026-09-17, wave W3) → #613 |
| MF-004 | **implementado** | indisponível ≠ 0: cotação ausente/rede 0/worker 0/custo 0 nunca produzem fiat estimado nem divisão por zero (idem) → #613 |
| API-001 | implementado | `tests/core/test_app_device_routes.py` |
| API-002 | implementado | idem |
| OPS-001 | implementado | idem |
| OPS-002 | não auditado | `tests/test_polling_integration.py` existe; comportamento não verificado nesta rodada |
| OPS-003 | **lacuna** | `tests/test_polling_reconnection.py` não existe → #610 |
| TEL-001 | **lacuna** | nenhum teste de idempotência de telemetria de **device** → #608 |
| TEL-002 | **lacuna** | `tests/test_telemetry_validation.py` não existe → #609 |
| TIME-001 | **lacuna** | `tests/test_timezones.py` não existe; **0** usos de fuso nomeado no repo → #604 |
| NUM-001 | parcial | o plano declara *"parte de `NUM-001`"* |
| NUM-002 | implementado (PR #605 wave W3) | `tests/test_numeric_properties.py`: hypothesis sobre o núcleo numérico puro — solo prob, lender, break-even, `fiat_convert`; invariantes [0,1]/serializável/sem NaN + bordas IEEE-754 e Decimal |
| SEC-001 | não auditado | `tests/test_tenant_b2_isolation.py` existe; comportamento não verificado |
| SEC-002 | implementado | `tests/core/test_app_device_routes.py` |
| CMD-001 | implementado | idem |
| CMD-002 | implementado | Issue #368 |
| AUD-001 | **parcial** | o plano declara só *"verificação de histórico"*; `tests/test_audit_log.py` não existe → #611 |
| PER-001 | reconciliar | cobertura equivalente em `tests/test_persistence.py` (nome difere do sugerido) |
| UI-001 | reconciliar | cobertura equivalente parcial em `tests/e2e/topbar-responsive.spec.js` |
| UI-002 | **lacuna** | guardas de axe existem em outra camada; o spec e2e nomeado não → #612 |
| LOAD-001 | **lacuna** | `tests/performance/` **não existe** no repositório → #606 |
| LOAD-002 | **lacuna** | idem → #607 |

**Estados:** `implementado` (teste existe e corresponde ao critério) · `parcial` (cobre parte do
critério) · `lacuna` (Issue própria aberta) · `reconciliar` (cobertura existe sob outro nome —
reforçar ali, não duplicar) · `não auditado`.

### O que esta auditoria não conclui

- **Não** afirma que os testes marcados `implementado` estão corretos ou passando — só que existem e
  correspondem ao critério declarado. Nenhum teste foi executado para inferir os estados acima.
- **Não** cobre os IDs marcados `não auditado`. Eles **não** devem ser tratados como cobertos.
- **Não** mede cobertura de linha: a matriz é sobre exigências, e o gate de linha é outro
  (`--cov-fail-under=80`).

### Achado transversal

**Nenhum dos 24 IDs é referenciado em nenhum arquivo de `tests/`.** O esquema descrito no
§"Objetivo e prioridades" — *"os IDs ... permitem rastrear a exigência no CI e em incidentes"* —
**não está implementado**. Isso obrigou esta auditoria a inferir cobertura por nome de arquivo e
comportamento, um método mais frágil, que confunde cobertura equivalente com lacuna. Issue #614.

### Bloqueio declarado em `LOAD-001`/`LOAD-002`

Os dois critérios citam um **SLO acordado** (p95 do resumo; latência e backlog de ingestão).
Esse SLO **não existe** em nenhum documento do projeto. Sem o número, um teste de performance não
consegue falhar por mérito — e um gate que só registra medição é o tipo que se aprende a ignorar,
que é exatamente o problema que a Issue #588 descreveu para o caso do `mobile:`. Isso é um
**bloqueio**, não uma suposição: #606 e #607 só têm escopo executável depois do SLO declarado.
