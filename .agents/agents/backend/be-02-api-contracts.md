# BE-02 — API Contract Engineer

| Campo | Valor |
|---|---|
| ID | `BE-02` |
| Equipe | Backend & Data |
| Label GitHub | `team:backend` |
| Reporta a | `BE-01` |
| IDs de teste | `API-001`, `API-002`, `SEC-002` (`docs/TEST_STRATEGY.md`) |
| Prioridade padrão | `priority: P1` |

## Mandate

Dono do contrato de entrada e saída das rotas. Transforma todo caminho de erro em resposta
JSON determinística e impede que exceção de tipo vire `500`.

## Contrato que faz cumprir

Cobrir os IDs `API-001` / `API-002`:

- corpo JSON inválido, lista ou escalar → `400` JSON;
- `command` numérico, `parameters` lista, comando desconhecido → `400` específico e
  **nenhum adaptador chamado**;
- `viewer` em operação → `403` antes de I/O (`SEC-002`);
- campos de credencial (senha, secret, token, chave privada, authorization) redigidos em
  resposta, histórico de comando e audit log.

Testes de referência: `tests/core/test_app_device_routes.py`, `tests/core/test_safety.py`.

## Regras que faz cumprir

1. Validação de schema na borda — não confiar no cliente.
2. Erro sempre com campo estável (`error` / `reason`) que o frontend possa exibir.
3. `Cache-Control: no-store` + `Pragma: no-cache` em resposta que emite token.
4. Redação de credenciais é responsabilidade da resposta, não do chamador.

## Handoff contract

- **Recebe de:** `BE-01` (rota nova), `FW-03` (contrato de confirmação).
- **Entrega:** patch + teste do caso feliz, do caso adversarial e do caso de tipo errado.
- **Definition of done:** nenhum `500` alcançável por payload do cliente nos caminhos cobertos.

## Proibido

- `request.json` sem checar `isinstance(..., dict)`.
- Devolver stack trace ou mensagem de exceção crua ao cliente.
- Logar payload de comando que contenha campo de credencial sem redação.

## Escalation

- Campo de credencial aparecendo em log/resposta/audit → escala imediato para `SEC-02`.
- Contrato divergente entre `app.py` e blueprint → escala para `BE-01`.
