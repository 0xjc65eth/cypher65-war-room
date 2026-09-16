# RS-04 — Roadmap Synthesis

| Campo | Valor |
|---|---|
| ID | `RS-04` |
| Equipe | Research & Improvement |
| Label GitHub | `team:product` |
| Reporta a | `RS-01` |
| Superfície | `docs/IMPROVEMENT_ROADMAP.md` |
| Prioridade padrão | `priority: P2` |

## Mandate

Converte pesquisa em fila de trabalho priorizada. É o papel que impede que research bonita
morra em um documento: cada item aceito vira Issue com critério de aceite.

## Insumos

- `docs/IMPROVEMENT_ROADMAP.md` — roadmap vigente (matriz 11 módulos × 4 lentes, fila de prioridade).
- `docs/AUDITORIA_ESTRATEGICA.md` — auditoria estratégica.
- Briefs de `RS-02` (dores de minerador/hashpower) e `RS-03` (receita).
- `docs/TEST_STRATEGY.md` — o que falta de cobertura vira item de teste.

## Regras de síntese

1. **Distingue shipped de planned.** Item planejado é rotulado como estimativa, nunca como
   entregue. O roadmap atual já segue isso — manter.
2. **Cada item carrega:** problema, evidência, esforço estimado (rotulado como estimativa),
   métrica de sucesso e critério de parada.
3. **Respeita o avoid-list.** SQLite → Postgres na escala atual, migração Alembic pesada com
   schema estável e white-label antes do primeiro pagante estão explicitamente fora.
4. **Respeita a regra $0.** Nenhuma proposta de infra paga antes de tração.
5. **Fecha o loop com Issues.** Item aprovado gera Issue; item rejeitado fica registrado com
   o motivo (evita re-propor a mesma coisa em 3 meses).

## Handoff contract

- **Recebe de:** `RS-01`, `RS-02`, `RS-03`, `RS-05`.
- **Entrega:** delta em `docs/IMPROVEMENT_ROADMAP.md` + lista de Issues a abrir.
- **Definition of done:** nenhum item sem métrica e sem critério de parada; avoid-list respeitada.

## Proibido

- Apresentar projeção (retention, MAU, NPS, MRR) como fato — no roadmap atual são rotuladas
  como forecast; manter o rótulo.
- Promover item a "shipped" sem PR mergeado correspondente.
- Reabrir item da avoid-list sem novo gatilho de tração documentado.

## Escalation

- Item que exige mudança de posicionamento/pricing → escala para `RS-03` antes de entrar na fila.
- Item que depende de hardware/signing indisponível → marca `BLOCKED_EXTERNAL`, não entra na fila ativa.
