# AI Operator — Next Phase

## Current Status (Aug 2026)

✅ **Implemented since Jul 2026** — `services/ai_operator.py` is a REAL LLM
assistant: DeepSeek (default) or OpenAI via `AI_PROVIDER`, SSE streaming at
`POST /api/ai/query`, snapshot-grounded system prompt, hashrate/difficulty
formatting helpers. No more keyword matching.

## What's next (evolution, not creation)

Enhance the existing LLM assistant:

### Approach (built on the existing LLM endpoint)

1. **Tool usage**: The AI should be able to call backend functions:
   - `get_snapshot()` — current pool/worker/network data
   - `get_device_telemetry(device_id)` — miner telemetry
   - `get_fleet_health()` — fleet summary
   - `run_diagnostics(device_id)` — diagnostics engine
   - `get_block_hunt()` — probability math
   - `get_alerts()` — recent alerts

3. **System prompt** should ground the AI in:
   - Current snapshot data
   - Available device telemetry
   - Fleet health metrics
   - Alert state
   - Safety rules (can't exceed temperature/frequency limits)

### Rate limiting

- Max 10 queries/min per user
- Cache similar queries within 30s window
- Respect external API rate limits

### UI changes

- Add loading/streaming state
- Add context panel with live system state
- Mark responses with confidence level or "estimated" vs "confirmed"

### Not in scope for initial AI Operator

- Autonomous action execution (AI executing commands without user confirmation)
- Multi-turn conversation memory
- Training on historical fleet data

---

## Auto-Pilot · Dry-Run (Issue #76 · Fase 3) — leia antes de armar

Entre o **advisory** (Fase 2: o piloto *sugere* — Issue #20) e o **armado de
verdade** (Fase 1), existe o **dry-run**: uma execução **simulada** do que o
piloto FARIA com as regras ativas, com resultados previstos — sem executar
nada.

### Endpoints (tenant-scoped)

- `GET /api/automation/dry-run` — **AGORA**: roda o pipeline real do
  `evaluate_rules` (condições + cooldown + conflitos + budget por tenant)
  sobre a telemetria atual. **Zero side effects**: não executa, não audita,
  não consome cooldown/budget (repetir a simulação nunca atrasa um disparo
  real). Cada ação simulada traz:
  - regra + device + condição (**valor real vs limiar**)
  - **resultado previsto** (ex: restart → hashrate volta em ~60-120s;
    pause → ASIC esfria)
  - **veredito do SafetyEngine (simulado)**: approved / blocked + motivo
  - status de budget (`would_consume` / `rate_limited`) e conflitos
    cancelados (`cancelled_by_conflict`)
- `GET /api/automation/dry-run/replay?hours=24&limit=288` — **REPLAY 24h**:
  simulação **pura** sobre o histórico real de telemetria (axe registry),
  aplicando cooldown + resolução de conflitos + budget por janela → quantas
  vezes cada regra TERIA disparado (fires / rate_limited / first-last ts).

### Garantias

- Funciona **desarmado** (é o objetivo: ensaiar antes de armar).
- Nunca chama o executor, nunca grava audit trail, nunca muta estado.
- Budget simulado **sequencial** (espelha o engine real): com 2 slots
  restantes e 3 regras, as 2 primeiras mostram `would_consume` e a última
  `rate_limited`; usa o engine do boot, então o budget reflete o consumo
  real do tenant.
- Fail-closed por tenant: erro de coleta → resposta vazia (500 com corpo
  honesto), nunca ação real.
- Limite honesto do replay: o histórico de telemetria não carrega `status`,
  então regras com condição de `status` não são simuláveis nas últimas 24h
  (o replay assume o device acessível em cada amostra).

### UI

Painel **AUTO-PILOT · DRY-RUN** no módulo Automations: badge `SIMULAÇÃO`
(nada é executado), bloco **AGORA — O QUE O PILOTO FARIA** (cards por ação
com outcome previsto + chip de safety) e **REPLAY 24H — TERIA DISPARADO**
(resumo por regra).
