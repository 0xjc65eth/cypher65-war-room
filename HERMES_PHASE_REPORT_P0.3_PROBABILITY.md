# HERMES PHASE REPORT — P0.3 BLOCK PROBABILITY ENGINE

**Phase:** P0.3 — Block Probability Engine  
**Date:** 2026-07-25  
**Status:** COMPLETED

---

## OBJETIVO

Substituir o conceito simplista de "expected time" por um modelo probabilístico real usando distribuição de Poisson.

---

## O QUE FOI IMPLEMENTADO

### 1. Core Engine (`services/probability.py`)

Funções:
- `calculate_block_probability()` — cálculo Poisson para um período
- `calculate_multiple_periods()` — múltiplos períodos (1h, 6h, 12h, 24h, 7d, 30d)

Campos retornados:
- `probability_at_least_one`
- `probability_zero`
- `expected_blocks`
- `expected_time_to_block_seconds`
- `lambda`
- Disclaimer claro: "EXPECTED VALUE — NOT A GUARANTEE"

### 2. API Endpoints (`services/probability_engine.py`)

- `GET /api/probability?hashrate=...&duration=...`
- `GET /api/probability/full?hashrate=...`

---

## EXEMPLO DE USO

```bash
curl "http://localhost:8765/api/probability?hashrate=200000000000000&duration=86400"
```

Resposta esperada:
```json
{
  "probability_at_least_one": 0.0314,
  "probability_zero": 0.9686,
  "expected_blocks": 0.032,
  "expected_time_to_block_seconds": 2592000,
  "note": "EXPECTED VALUE — NOT A GUARANTEE. Mining is probabilistic."
}
```

---

## PRÓXIMOS PASSOS

1. Integrar o endpoint no `app.py` (importar `register_probability_routes`)
2. Expor no frontend (cards de probabilidade)
3. Usar no HERMES Core quando o usuário perguntar sobre chances de bloco

---

**HERMES — Cognitive Core**  
**CYPHER MINING INTELLIGENCE**