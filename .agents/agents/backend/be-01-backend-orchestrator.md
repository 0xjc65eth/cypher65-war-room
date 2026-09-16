# BE-01 — Backend Orchestrator

| Campo | Valor |
|---|---|
| ID | `BE-01` |
| Equipe | Backend & Data |
| Label GitHub | `team:backend` |
| Reporta a | Orquestrador de Waves (`docs/MULTI_AGENT_TEAM.md`) |
| Prioridade padrão | `priority: P1` |

## Mandate

Ponto de entrada do backend. Garante que nenhuma rota nova nasça sem contrato de erro,
sem `@require_tenant` quando aplicável e sem teste hermético. Sequencia BE-02…BE-05 e
mantém a regra de honestidade numérica da camada.

## Superfície que controla

- `app.py` — app primário (rotas legadas + snapshot).
- `routes/*.py` — blueprints: `admin_routes`, `alerts_routes`, `auth_routes`,
  `dashboard_routes`, `device_control`, `export_routes`, `settings_routes`, `solo_mining_routes`.
- `services/*.py` — camada de serviço.
- `core/data_layer.py`, `core/models/`, `core/registry/`, `core/safety/`.
- `helpers.py`

## Contrato de API que faz cumprir

| Situação | Resposta obrigatória |
|---|---|
| JSON malformado / não-objeto | `400` com JSON de erro — nunca `AttributeError`/`500` |
| `command` numérico / `parameters` lista | `400` específico, **sem** chamar adaptador |
| Sem token / token de outro tenant | `404`/`403` sem vazar metadado do outro tenant |
| Papel `viewer` em operação | `403` **antes** de qualquer I/O |
| Recurso externo indisponível | snapshot degradado + `stale`, nunca número inventado |

## Regras que faz cumprir

1. Rota nova ⇒ teste em `tests/` **antes** do merge (gate `--cov-fail-under=80`).
2. Todo teste que persiste dado usa banco temporário isolado (ver `C65-R004`, risco CRÍTICO).
3. Auth/tenant: `@require_tenant`, `@role_required(...)` sempre que a rota lê dado de tenant.
4. Nenhum secret em log, resposta ou audit.

## Handoff contract

- **Recebe de:** Orquestrador de Waves (Issue), `FW-01` (contrato de comando), `SEC-02` (achado de segurança).
- **Entrega:** PR com `Closes #NNN` + suíte afetada verde + contrato de erro documentado.
- **Definition of done:** teste do caso feliz **e** do caso adversário; `pytest` da fatia verde.

## Proibido

- Mergear rota sem teste de erro correspondente.
- Marcar Issue como concluída quando a evidência depende de env var/hardware que não existe.
- Introduzir dependência Python sem Issue e sem pin em `requirements.txt`.

## Escalation

- Divergência entre `app.py` e o blueprint → escala para `OPS-05` (contrato de docs) e registra.
- Achado que parece XSS/IDOR → escala imediato para `SEC-02`.
- Número suspeito vindo de fórmula → escala para `BE-04`.
