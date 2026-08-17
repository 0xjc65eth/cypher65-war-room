# Validação do Funil de Conversão — Produção (2026-08-17)

**Status:** ✅ validação executada · ⚠️ funil **vazio por design** · 🔴 achado de segurança no gate admin

## Método

- **Fonte:** servidor de produção `https://cypher65-war-room.onrender.com` (healthz 200)
- **Endpoint:** `GET /api/admin/conversion?days=30&weeks=8` → `funnel_report()` + `ltv_cac_report()` + `funnel_weekly_report()` + `detect_feature_overconcentration()`
- **Payload bruto:** salvo em `/tmp/funnel_prod.json` (este relatório)

## Resultados reais (produção)

### Funnel (30d)
| Métrica | Valor |
|---|---|
| `stages` | `{}` — **zero eventos** |
| `visitors` (tenants distintos) | 0 |
| `paid_count` | 0 |
| `conversion_rate_pct` | 0.0 |
| `drop_off` | `[]` |
| `weekly` (8 semanas) | `[]` — zero em todas as semanas |
| `feature_alert` | `null` |

### Economia (LTV/CAC)
| Métrica | Valor |
|---|---|
| `ltv_usd` | **101.52** (estimativa: 9 × 12 × 0.94) · `ltv_source: estimate` |
| `has_renewal_data` | false · `cohorts: []` |
| `cac_usd` | `null` (sem `MARKETING_SPEND_USD`) |
| `ltv_cac_ratio` / `payback_months` | `null` |
| `paid_count` | 0 |

## Diagnóstico — funil vazio é **por design**, não tracking quebrado

1. **Paywall nunca ativado em produção.** O gate de licensing é **off-by-default**
   (`services/licensing.py`): sem `PRO_LICENSE_KEYS` / `LEMON_SQUEEZY_API_KEY` /
   `PRO_KEYS_DB`, `pro_required` é no-op — nenhum endpoint bloqueia.
2. `paywall_view` só é trackeado **dentro do caminho do gate ativo**
   (`services/licensing.py:289-302`). Com o gate aberto, o evento nunca dispara →
   **zero eventos em produção é o comportamento esperado do open mode**.
3. Contraste: o DB local tem `conversion_events` com `modal_open × 1` (evento de
   dev/teste) — o pipeline de tracking e os relatórios funcionam; falta apenas o
   paywall ligado.
4. Consequência de negócio: sem gate → sem funil → sem conversão → LTV/CAC sem
   base real. É exatamente o gap P4 da monetização (`docs/MONETIZATION_BTC_PROGRAMS.md`).

## 🔴 Achado de segurança (novo) — gate admin inefetivo no Render

- `GET /api/admin/conversion` responde **200 sem `X-API-Key`** e com key inválida
  (`X-API-Key: nope` → 200) a partir de um cliente remoto.
- Causa: o gate (`app.py:5451-5456` e idêntico em `/api/admin/licenses:5388-5393`)
  trata `request.remote_addr in ("127.0.0.1", "::1", "localhost")` como local — e o
  proxy do Render entrega `remote_addr` como loopback → **as rotas admin ficam
  públicas em produção**.
- Impacto hoje: baixo (funil anonimizado + CSV semanal). **Impacto futuro: alto** —
  o mesmo gate protege `POST /api/admin/licenses` (emissão de chaves PRO/PREMIUM):
  quando o paywall ativar, qualquer pessoa emitiria chaves de graça.
- Fix sugerido: exigir `X-API-Key` quando houver proxy (checar `X-Forwarded-For`
  presente), ou usar secret fixo do operator para o `local` em ambiente Render.

## Próximos passos

1. **Corrigir o gate admin** antes de ativar o paywall (Sev-2, pré-requisito P4).
2. Ativar licensing (PRO_KEYS_DB ou Lemon Squeezy / BTCPay #248) para o funil
   começar a coletar `paywall_view → key_activated`.
3. Re-validar após ativação: funil deve mostrar as 5 etapas; `ltv_cac_report`
   precisa de `MARKETING_SPEND_USD` para calcular CAC/LTV:CAC/payback.
4. Métrica de sucesso P4 (`docs/MONETIZATION_BTC_PROGRAMS.md`): conversion rate
   paywall→paid ≥ 2% e LTV:CAC ≥ 21:1 medidos com dados reais.
