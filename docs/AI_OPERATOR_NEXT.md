# AI Operator — Next Phase

## Current Status (Jul 2026)

The AI Operator panel in the CYPHER65 dashboard uses **keyword matching** with
9 hardcoded responses. It is NOT a real LLM-based assistant.

## What needs to change

Create a new backend endpoint:

```
POST /api/ai/query
```

Input: `{ "query": "...", "context": { ... } }`
Output: `{ "response": "...", "sources": [...] }`

### Approach

1. **Route the query** to a real LLM (OpenAI, Claude, DeepSeek, or local model)
   with the current snapshot data + device telemetry as system context.

2. **Tool usage**: The AI should be able to call backend functions:
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
