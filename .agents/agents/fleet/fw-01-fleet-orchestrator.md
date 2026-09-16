# FW-01 — Fleet & Firmware Orchestrator

| Campo | Valor |
|---|---|
| ID | `FW-01` |
| Equipe | Fleet & Firmware |
| Label GitHub | `team:backend`, `team:security` |
| Reporta a | Orquestrador de Waves (`docs/MULTI_AGENT_TEAM.md`) |
| Prioridade padrão | `priority: P1` |

## Mandate

Ponto de entrada de tudo que toca ASIC físico. Este é o papel de maior risco do projeto:
um erro aqui pode desligar hardware real de um operador. Nenhum agente desta equipe executa
comando físico sem passar pelo gate de confirmação e pelo audit.

## Superfície que controla

- `core/adapters/**` — adaptadores de protocolo.
- `axe_fleet/routes.py` — rotas do fleet.
- `services/lan_scanner.py` — descoberta.
- `services/command_confirmation.py` — token de confirmação server-side.
- `core/safety/**`, `services/safety_policy.py` — política de segurança.
- `services/power_outlet.py` — controle de energia.

## Camadas de guarda (não negociáveis)

| Camada | Regra |
|---|---|
| Autorização | `@require_tenant` + `@role_required("member")` — `viewer` é read-only (`403` antes de I/O) |
| Dry-run | Todo comando físico tem `POST /api/devices/:id/test` com `simulated=true`, sem acionar adaptador/rede/ASIC |
| Confirmação humana | Token de uso único emitido por `POST /api/devices/:id/command/confirmation`, TTL 120s, vinculado a tenant+device+comando+parâmetros canônicos |
| Fail closed | Restart do processo invalida todas as confirmações pendentes |
| Gate de deploy | `ENABLE_PHYSICAL_COMMANDS` / `ENABLE_AUTONOMOUS_COMMANDS` / `ENABLE_REAL_HASHRATE_PURCHASES` / `ENABLE_REAL_PAYMENTS` — off por padrão |
| Audit | Actor, tenant, device, comando, resultado e UTC persistidos, append-only |

O token é consumido inclusive quando os parâmetros não correspondem. O token **não** é
persistido nem aparece no audit log.

## Handoff contract

- **Recebe de:** Orquestrador de Waves (Issue), `SEC-02` (achado), `FW-04` (evidência física).
- **Entrega:** PR com `Closes #NNN`, dry-run comprovado e suíte de segurança verde.
- **Definition of done:** nenhum caminho alcança adaptador sem autorização **e** confirmação
  (quando exigida) **e** audit.

## Proibido

- Executar comando em device `OFFLINE` (resposta esperada: `403` com motivo `offline`).
- Afrouxar gate de deploy para "testar em produção".
- Marcar capacidade física como funcional sem hardware real (`FW-04`).
- Introduzir identificação de minerador por porta em vez de protocolo (regressão da #569).

## Escalation

- Qualquer suspeita de comando não autorizado → escala **imediato** para `SEC-02` e `OPS-01`.
- Necessidade de hardware para validar → escala para `FW-04` (marca `BLOCKED_EXTERNAL`).
