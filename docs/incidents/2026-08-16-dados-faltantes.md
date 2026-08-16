# 🔍 INCIDENTE — Dados Faltantes, Erros e Degradação de Informação

> **Data:** 16/08/2026 · **Severidade:** Sev-1 (múltiplos mecanismos sistêmicos)
> **Método:** investigação sênior forense de código (arquivo:linha) + rastreamento de fluxo end-to-end (origem → API → CSV → UI)
> **Status:** aberto — Issues #200-#206 criadas, aguardando PRs (fluxo `docs/AGENT_WORKFLOW.md`)

---

## 1. Resumo Executivo

O sistema não tem "um bug isolado": tem **quatro mecanismos sistêmicos** que produzem os sintomas descritos.

- **(a)** A ingestão MRR busca **uma única página** (`limit` sem loop de paginação): aluguéis além dos 50 mais recentes **não existem para o sistema** — painel, alertas P/L e CSV.
- **(b)** Exports têm **LIMIT silencioso** (5.000 no export genérico, 200 no CSV de rentals) sem metadado de truncamento.
- **(c)** O padrão sistêmico `x or 0` converte "sem dado" em "zero real" (datas → epoch-0, hashrate → 0.0) antes de chegar à UI.
- **(d)** A telemetria só agrega **ERROR/CRITICAL** — WARNING e `except: pass` são zona morta: degradação gradual nunca alerta.

Os guards de 1970-01-01/CSV-injection/Braiins-envelope já existem (Issues #193-#196) e **protegem as camadas certas** — mas a raiz (coerção prematura + caps invisíveis) continua.

## 2. Mapa de Fluxo + Ponto de Quebra

```
MRR API ──► fetch_mrr_rentals(limit=N, SEM paginação) ──► [P0-QUAEBRA-1: >N aluguéis descartados]
Braiins ──► fetch_braiins_contracts(envelope unwrap ok) ──► painel
  │
  ▼ normalize: hash→TH (ok) │ datas raw
  ▼ ingest_rentals → rental_history (SQLite)            [P2: epochs entram via ts or 0]
  ▼ painel /api/rentals (limit=50)  ─────────────────── [P0-QUAEBRA-1]
  ▼ CSV export (limit=200)  ──────────────────────────── [P1-QUAEBRA-2]
  ▼ export_routes LIMIT 5000 (snapshots/alerts) ──────── [P1-QUAEBRA-2]
  │
Hashrate market ──► fetch_all_offers (fail-closed: [] em falha)
  ▼ market_data vazio → {"updated_at": 0} ────────────── [P1-QUAEBRA-3: epoch-0 na API]
  ▼ UI: age=now-0 → payload tratado como stale ───────── [P3-QUAEBRA-4]
  │
Poll loop ──► last_submit_ts = ls_int or 0 ───────────── [P1-QUAEBRA-3: epoch-0 em estado]
  ▼ except Exception: pass (~20× em caminho quente) ──── [P1-QUAEBRA-5: falha invisível]
  ▼ error_metrics (só ERROR+) ─── alerta NUNCA dispara ─ [P1-QUAEBRA-5]
```

## 3. Achados por Camada e por Equipe

| Sev | Camada | Equipe Owner | Problema | Evidência | Issue |
|---|---|---|---|---|---|
| **Sev-1** | P0 Ingestão | Integrações | MRR sem paginação: `qparams["limit"]=N` é **uma página só** — painel (50), sweep de alertas P/L (50) e CSV (200) veem só o topo. `total` existe na resposta e é ignorado | `rental_performance.py:1656-1659`, `app.py:6815-6821`, `rental_performance.py:3520`, `app.py:7308-7316` | #200 |
| **Sev-1** | P3 API/CSV | Backend | Export genérico `LIMIT 5000` sem flag `truncated`/contador: 7d de `snapshots` (>10k rows a 1/min) sai **truncado silenciosamente** todo dia | `routes/export_routes.py:77-86` | #201 |
| **Sev-1** | P5 Obs | Platform/SRE | Falhas silenciosas invisíveis: ~20 `except Exception: pass` em caminho quente + `error_metrics` só agrega ERROR/CRITICAL → provider cai, market fica vazio, **nenhum alerta dispara** | `app.py:2854-2857, 2926`; `polling.py:424, 1007`; `hashrate_market.py:455-456`; `dashboard_routes.py:157`; `error_tracker.py:209` (`level=ERROR`) | #202 |
| **Sev-2** | P1 Transformação | Backend Core | Padrão sistêmico `x or 0`: "sem dado" vira "zero real" e é gravado/exibido como fato (hashrate 0, ts 0) | `helpers.py:249`; `polling.py:693-696`; `user_polling.py:321`; `snapshot_enrichment.py:153`; `app.js:3044` | #203 |
| **Sev-2** | P2 Persistência | Dados | Epoch-0 vaza para a API: market vazio envia `"updated_at": 0`; `last_submit_ts = 0` entra no timeline_state | `snapshot_enrichment.py` (branch vazio `updated_at: 0`); `polling.py:696` | #203 |
| **Sev-2** | P2 Persistência | Dados | Amostras com `ts=0` são **dropadas via `continue`** das séries de alerta sem contador (subconta silenciosa) | `routes/alerts_routes.py:573-575` | #204 |
| **Sev-3** | P4 Frontend | Frontend | `rentalsPayloadStale`: payload válido sem `updated_at` → `age=now-0` → marcado **stale** e escondido/re-buscado | `static/app.js:317-320` | #204 |
| **Sev-3** | P4 Frontend | Frontend | Buckets semanais do admin audit **descartam ts≤0 sem bucket "desconhecido"** — subconta do gráfico | `static/app.js:2967-2972` | #205 |
| **Sev-3** | P3 API | Backend | `meta` JSON corrompido → vira string via `except: pass` — eventos perdem detalhes sem log | `routes/dashboard_routes.py:152-158` | #205 |
| **Sev-3** | P5 Obs | SRE | **Sem SLO/SLI de completude** — nenhuma métrica expected-vs-received (MRR total vs 50; 3 providers vs 0; rows exportadas vs existentes) | ausência no código | #206 |
| **Sev-4** | P0 Ingestão | Integrações | DELETE de purge com `except: pass` — falha de DB invisível | `hashrate_market.py:455-456` | #202 |

**Já protegido (não regredir):** datas 1970-01-01 flagadas nos cálculos (`_is_epoch_date`, `rental_performance.py:1227-1237`); guard `ts<=0` no JS (`app.js:2972`); envelope Braiins `{bid:…}` (Issue #193); anti-formula-injection em CSV (`csv_neutralize`, #196); dedup de alertas no sweep (nunca engolir alerta, `user_polling.py:1296-1298`).

## 4. Causas Raiz vs Sintomas

| Sintoma | Causa Raiz | Raiz vs Sintoma |
|---|---|---|
| Aluguéis que "deveriam aparecer" não aparecem | **Cap único sem paginação** na ingestão MRR (painel=50, CSV=200) | **RAIZ** (#200) |
| CSV/export incompleto | **LIMIT sem metadado de truncamento** | **RAIZ** (#201) |
| Datas 1970-01-01, valores zerados | **Coerção `or 0` prematura** em ts/hashrate/count | **RAIZ** (#203) |
| `updated_at: 0` na API | fail-closed retorna sentinela epoch em vez de `null` | **RAIZ** (#203) |
| Erros recorrentes sem alerta | **Telemetria ERROR-only** + `except: pass` (WARNING é zona morta) | **RAIZ** (#202) |
| Painel mostrando "sem dados" quando há | distinção vazia-vs-erro apagada pelo fail-closed (docstring `rental_performance.py:13-15`) | sintoma de #203 |

## 5. Plano de Ação Priorizado

**Imediatas (mitigação):**
1. **#201** — Export genérico: adicionar flag `truncated` + `total` + contagem no CSV (uma linha de metadados ou header) — zero risco, alto valor.
2. **#203** — `updated_at: 0` → `null` no branch vazio de `market_data` + guard no `rentalsPayloadStale` (`age = updated_at ? now-upd : null`).
3. **#200** — Superfície honesta: expor `total` vs `rendered` no payload do painel ("50 de N") enquanto a paginação real não sai.
4. **#202** — Converter os ~6 `except: pass` de caminho quente (app.py:2854, polling, dashboard_routes, hashrate_market) para `log.warning`.

**Correções definitivas:**
5. **#200** — Paginação em loop no fetch MRR (page/offset) para painel + sweep + CSV; remover caps arbitrários.
6. **#203** — Política de sentinela: `None` atravessa ingestão→API; `or 0` só na fronteira de render, com flag `missing`. Guard centralizado (`_coerce_ts → Optional[int]`) como o `csv_neutralize` já centralizado.
7. **#204** — `alerts_routes`: contador de amostras descartadas + `updated_at`/`ts` nulos no frontend.

**Observabilidade (para não repetir):**
8. **#206** — SLI **completude rentals** = rentals processados ÷ `total` do MRR × 100 (target ≥ 99%) e SLI **frescura do market** = % ciclos com age < 5min (≥ 98%), expostas em `/api/snapshot.health`.
9. **#202** — Estender `error_metrics` para bucket de WARNING/degradation + alerta de taxa; contador de `except: pass` executados.

## 6. Lacunas de Ownership

1. **Política de normalização missing→0** — ninguém é dono; cada arquivo decide (Backend Core vs Dados).
2. **Alerting de WARNING/degradación** — `error_tracker` é ERROR-only *por design*; não há dono para o nível abaixo disso.
3. **Semântica de exportação além do LIMIT** — nenhuma decisão de produto (truncar vs paginar vs avisar) para `export_routes` e CSV de rentals.
4. **Trade-off rate-budget vs completude** do MRR (o sweep evita o rate limit *de propósito*, mas o custo é dados invisíveis) — sem dono explícito em Integrações.

## 7. Critérios de Qualidade da Investigação

- ✅ **Causa raiz isolada com evidência** (`arquivo:linha` em cada achado; paginação ausente provada em `rental_performance.py:1656-1659`; LIMIT provado em `export_routes.py:77-86`; coerção provada em `polling.py:696`).
- ✅ **Owner claro** em cada ação (tabela §3).
- ✅ **Mecanismo de detecção precoce** definido (§5.8-9 — SLIs + bucket de WARNING).
- ✅ **Zero achismos** — tudo rastreável a código; itens "ausência de X" são marcados como tal.

## Issues vinculadas

- #200 — Sev-1 · Ingestão MRR sem paginação (caps 50/200 silenciosos)
- #201 — Sev-1 · Export genérico LIMIT 5000 sem metadado de truncamento
- #202 — Sev-1 · Falhas silenciosas (`except: pass`) + telemetria ERROR-only
- #203 — Sev-2 · Coerção `x or 0` prematura + epoch-0 na API/estado
- #204 — Sev-2 · Amostras ts=0 dropadas + payload stale no frontend
- #205 — Sev-3 · Buckets admin dropam ts≤0 + meta JSON corrompido silencioso
- #206 — Sev-3 · SLIs/SLOs de completude de dados ausentes
