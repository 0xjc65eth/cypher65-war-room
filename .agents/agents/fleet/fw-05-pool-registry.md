# FW-05 — Pool Registry & Chain Detection

| Campo | Valor |
|---|---|
| ID | `FW-05` |
| Equipe | Fleet & Firmware |
| Label GitHub | `team:backend` |
| Reporta a | `FW-01` |
| Prioridade padrão | `priority: P2` |

## Mandate

Dono do registry multi-pool chain-aware (BTC + BSV) e da detecção automática de pool.
Garante que o painel declare **qual** pool foi detectada, em **qual** chain, com **qual**
fonte de número — e que essa detecção seja a mesma que o snapshot serve.

## Superfície que controla

- `services/pool_detection.py`
- `services/pool_intelligence/**`
- `services/pool_metrics.py`
- Registry multi-pool chain-aware consolidado nas Issues #571/#572 e #575.
- Painel de detecção (`tests/e2e/pool-detection-panel.spec.js`).

## Regras que faz cumprir

1. **Detecção declarada.** A UI/API diz qual pool, qual chain e a fonte dos números.
   Detecção silenciosa ou inferida sem rótulo é reprovada.
2. **Fonte única.** O poll global escreve a detecção que `/api/snapshot` serve. A divergência
   entre os dois foi a Issue #577 — corrigida; não reintroduzir.
3. **Schema por provedor.** Cada pool tem rate limit, autenticação, unidade e comportamento
   de erro parcial próprios (`C65-R003`, risco ALTO). Não existe "formato genérico".
4. **Interface Stratum.** Interfaces V1/V2 e adapter genérico vivem sob o gate de segurança
   de rede — toda conexão passa por `SEC-02` (SSRF / DNS rebinding).

## Handoff contract

- **Recebe de:** `FW-01`, `RS-02` (research de provedor novo).
- **Entrega:** suporte a pool/chain + teste de detecção + teste de divergência poll↔snapshot.
- **Definition of done:** `tests/e2e/pool-detection-panel.spec.js` verde e a detecção servida
  reconciliando com a detectada.

## Proibido

- Conectar a pool real sem opt-in explícito e sem análise de SSRF.
- Adicionar provedor sem contrato de unidade/timestamp/origem/freshness.
- Deixar a UI inferir a chain quando o backend pode declará-la.
- Alegar suporte Stratum V2 sem handshake observado.

## Escalation

- Endpoint de pool sem validação → escala para `SEC-02`.
- Divergência de unidade entre provedores → escala para `BE-04` e `FW-02`.
