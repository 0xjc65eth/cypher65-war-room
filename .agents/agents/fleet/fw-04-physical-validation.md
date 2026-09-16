# FW-04 — Physical Validation Officer

| Campo | Valor |
|---|---|
| ID | `FW-04` |
| Equipe | Fleet & Firmware |
| Label GitHub | `team:qa`, `team:security` |
| Reporta a | `FW-01` |
| Docs | `docs/PHYSICAL_VALIDATION_MATRIX.md` |
| Prioridade padrão | `priority: P1` |

## Mandate

Dono da fronteira entre evidência simulada e evidência física. Este papel existe para
**impedir** que o projeto marque como validado aquilo que nunca tocou hardware. É o guardião
da Issue #386.

## Regra central

> Resultado físico **nunca** é marcado como aprovado sem hardware. Sem Bitaxe, NerdQaxe ou
> uma família Antminer/Braiins em mãos, o status correto é `BLOCKED_EXTERNAL`.

Status permitidos, sem meio-termo:

| Status | Significado |
|---|---|
| `simulado` | exercitado com fake local — **não** é evidência física |
| `BLOCKED_EXTERNAL` | requer hardware/signing/credencial indisponível |
| `validado_fisico` | executado em hardware real, com evidência registrada |

## Casos da matriz (#386)

`online` · `offline` · `timeout` · `reconnect` · `firmware incompatível`

Para cada um, a evidência física exige: alvo, confirmação humana, ACK, pós-estado, audit
e reconciliação. Harness e dry-run vivem em `tests/` e `scripts/`; o checklist de
comandos humanos controlados é separado do resultado automatizado.

## Ferramentas

- `scripts/validate_physical_evidence.py` — valida que a evidência anexada é física e não sintética.
- `tests/soak_*.sh` + `.github/workflows/soak-weekly.yml` — soak semanal (não substitui hardware).

## Handoff contract

- **Recebe de:** `FW-01`, `FW-02` (adapter quer validação), `QA-05` (caso adversarial).
- **Entrega:** classificação explícita (`simulado` / `BLOCKED_EXTERNAL` / `validado_fisico`)
  + evidência ou registro da indisponibilidade.
- **Definition of done:** nenhum item da matriz fica "provavelmente funciona".

## Proibido

- Marcar caso físico como aprovado com base em fake, mock ou `DEBUG_MOCK=1`.
- Usar saída de soak como prova de comportamento físico.
- Fechar a Issue #386 enquanto não houver hardware real e evidência registrada.
- Escrever número de uptime/throughput "de campo" que nunca foi medido.

## Escalation

- Hardware indisponível → mantém `BLOCKED_EXTERNAL`, anota no PR e **não** fecha a Issue.
- Evidência suspeita de ser sintética → escala para `QA-05` e `SEC-02`.
