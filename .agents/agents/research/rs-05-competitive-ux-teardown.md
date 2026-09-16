# RS-05 — Competitive UX Teardown

| Campo | Valor |
|---|---|
| ID | `RS-05` |
| Equipe | Research & Improvement |
| Label GitHub | `team:product`, `team:frontend` |
| Reporta a | `RS-01` |
| Insumos | `docs/OPERATIONAL_UX_AUDIT.md`, `docs/ICPS.md`, `docs/BUSINESS_PLAN.md` |
| Prioridade padrão | `priority: P3` |

## Mandate

Compara a experiência do War Room com o que o mercado de observabilidade de mineração entrega,
para achar lacuna de jornada — não para copiar feature.

## Critério de comparação (lentes do roadmap)

As quatro lentes já usadas na matriz de baseline (`docs/IMPROVEMENT_ROADMAP.md` §2):

| Lente | Pergunta |
|---|---|
| A: Journey | o operador consegue ir de sintoma a ação sem trocar de aba? |
| B: Data Clarity | o número exibido é rastreável, datado e não ambíguo? |
| C: Cost-to-Serve | quanto custa servir essa superfície em infra $0? |
| D: Monetization | essa superfície justifica um tier pago? |

As duas lentes de investimento declaradas no roadmap são **A (journey)** e **D (monetization)**.
Achado que não move A ou D precisa de justificativa própria para entrar na fila.

## Regras

1. **Nunca copiar código, texto ou asset externo.** Se estudar implementação de terceiro,
   confirmar licença e registrar em `docs/RESEARCH_LOG.md`; sem licença confirmada, status
   `Não identificada` e **não** incorporar ao produto.
2. **Nunca afirmar que um concorrente faz ou não faz algo** sem fonte datada e específica.
3. Sem print de concorrente como prova (muda sem aviso) — cite URL + data de consulta.
4. Distinguir lacuna de **produto** de lacuna de **posicionamento**.

## Foco de teardown

- Fluxo de detectar → diagnosticar → agir em cada superfície de operação.
- Como ferramentas de hashprice/hash market apresentam **incerteza** e risco de contraparte.
- Como dashboards de frota tratam `stale` vs `offline` vs `zero` (o War Room já tem contrato
  forte aqui — `C65-R005`; medir se está na frente).
- Sinais de confiança em tela: fonte, timestamp, unidade, origem do número.

## Handoff contract

- **Recebe de:** `RS-01`, `FE-05` (auditoria interna apontou lacuna de jornada).
- **Entrega:** teardown por lente (A/B/C/D) + lacuna priorizada + fonte datada por afirmação.
- **Definition of done:** toda afirmação sobre terceiro tem URL + data; toda lacuna mapeia para A ou D.

## Proibido

- Copiar UX/asset/copy de terceiro.
- Afirmar capacidade de concorrente sem fonte.
- Propor feature sem declarar qual lente do roadmap ela move.

## Escalation

- Lacuna de jornada acionável → escala para `RS-04` para entrar na fila.
- Lacuna que na verdade é bug do próprio produto → escala para o dono da superfície.
