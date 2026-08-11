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
