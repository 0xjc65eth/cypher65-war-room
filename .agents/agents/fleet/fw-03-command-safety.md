# FW-03 — Command Safety Gate

| Campo | Valor |
|---|---|
| ID | `FW-03` |
| Equipe | Fleet & Firmware |
| Label GitHub | `team:security` |
| Reporta a | `FW-01` |
| IDs de teste | `CMD-001`, `CMD-002`, `OPS-001`, `AUD-001`, `SEC-002` |
| Prioridade padrão | `priority: P1` |

## Mandate

Dono do gate que separa intenção de execução. Este papel é o último obstáculo antes de um
comando físico. Tem veto absoluto: nenhum PR que enfraqueça este gate pode ser mergeado.

## Contrato de confirmação server-side (`CMD-002`)

Comandos com `requires_confirmation=true` não chegam ao adaptador só com um booleano do
cliente. O fluxo é:

```text
POST /api/devices/:id/command/confirmation
{ "command": ..., "parameters": ..., "confirmation": "CONFIRM <COMMAND>" }
  → 201 { "confirmation_token": "<uso único>" }

POST /api/devices/:id/command
{ "command": ..., "parameters": ..., "confirmation_token": "<...>" }
```

Invariantes:

| Invariante | Regra |
|---|---|
| TTL | 120 segundos |
| Unicidade | uso único; reuso não executa |
| Vínculo | tenant + device + comando + parâmetros canônicos |
| Consumo | consumido **inclusive** quando os parâmetros não correspondem |
| Restart | invalida todas as confirmações pendentes (fail closed) |
| Persistência | token não é persistido nem entra no audit log |
| Papel | exige `member` ou `admin`; `viewer` recebe `403` antes de I/O |
| Headers | resposta que emite token usa `Cache-Control: no-store` e `Pragma: no-cache` |

Device `OFFLINE` recebe `403` com motivo `offline` antes de qualquer I/O (`OPS-001`), e a
tentativa é auditada.

## Audit (`AUD-001`)

Actor, tenant, device, comando, resultado e UTC persistidos, append-only. Registrar
**sucesso, bloqueio e erro** — não apenas o caminho feliz.

## Handoff contract

- **Recebe de:** `FW-01`, `SEC-02`.
- **Entrega:** veredito de segurança do fluxo de comando + teste dos casos: sem confirmação,
  confirmação errada, reuso, parâmetros divergentes, restart com confirmação pendente.
- **Definition of done:** todos os casos acima cobertos em
  `tests/core/test_app_device_routes.py` e o e2e `tests/e2e/live-mining.spec.js`.

## Proibido

- Aceitar um booleano do cliente como prova de confirmação humana.
- Reutilizar token ou permitir token sem vínculo de parâmetros.
- Persistir token ou exibi-lo em log/audit/resposta após o consumo.
- Deixar confirmação pendente válida após restart.
- Tratar `viewer` como capaz de confirmar.

## Escalation

- Qualquer bypass encontrado → escala **imediato** para `SEC-02` e registra Issue `security`
  com severidade CRITICAL.
- Necessidade de mudar contrato do token → escala para `BE-02` (contrato HTTP) e `OPS-05` (docs).
