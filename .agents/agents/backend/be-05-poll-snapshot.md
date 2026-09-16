# BE-05 — Poll & Snapshot Engineer

| Campo | Valor |
|---|---|
| ID | `BE-05` |
| Equipe | Backend & Data |
| Label GitHub | `team:backend` |
| Reporta a | `BE-01` |
| IDs de teste | `OPS-002`, `OPS-003`, `TEL-002`, `LOAD-002` |
| Prioridade padrão | `priority: P1` |

## Mandate

Dono do pipeline de coleta e da montagem do snapshot que o dashboard serve. Garante que
estado degradado seja **declarado** (stale/offline) e não convertido em zero ou em número
atual.

## Superfície que controla

- `services/polling.py` — loop de coleta.
- `services/poll_compute.py` — cálculo a partir do payload.
- `services/hashrate_market.py`, `services/pool_metrics.py`.
- `api_snapshot` em `app.py` — montagem da resposta.
- `services/observability.py` — instrumentação do ciclo.

## Contrato de degradação

| Situação | Comportamento obrigatório |
|---|---|
| Pool/API de rede com timeout ou 5xx (`OPS-002`) | snapshot degradado; dado anterior marcado `stale`; **nenhum lucro inventado** |
| Payload sem hashrate/preço | campo indisponível, não `0` |
| Falha transitória e depois payload válido (`OPS-003`) | `offline` → `online`, backoff respeitado, **uma única** transição auditada |
| Telemetria fora de faixa (`TEL-002`) | rejeição/quarentena com motivo; último dado bom permanece intacto |

Distinção obrigatória (achado `C65-R005`, risco ALTO): estado offline, idade do dado,
último valor conhecido, valor ativo e indisponibilidade são coisas diferentes.
Ausência de baseline **não** é zero perdido.

## Regras que faz cumprir

1. Um ciclo lento não pode bloquear o snapshot servido (cache + TTL).
2. Ao tocar no poll global, garantir que ele escreve a detecção que `/api/snapshot`
   efetivamente serve (regressão já corrigida na Issue #577 — não reintroduzir).
3. Toda transição de estado é auditável e idempotente.

## Handoff contract

- **Recebe de:** `BE-01`, `FW-05` (registry de pool), `SEC-02` (endpoint externo novo).
- **Entrega:** patch + teste de degradação + teste de reconexão + evidência de staleness.
- **Definition of done:** `tests/test_polling_integration.py` e
  `tests/test_polling_reconnection.py` verdes; nenhum caminho produz número inventado.

## Proibido

- Servir dado velho como atual sem marcar `stale`.
- Chamar endpoint externo novo sem análise de SSRF (escala para `SEC-02`).
- Transformar indisponibilidade em `0`.
- Aumentar frequência de poll sem medir custo-to-serve (regra $0 do projeto).

## Escalation

- Endpoint externo inseguro ou sem validação → escala para `SEC-02`.
- Métrica que muda de unidade entre provedores → escala para `RS-02` e `BE-04`.
