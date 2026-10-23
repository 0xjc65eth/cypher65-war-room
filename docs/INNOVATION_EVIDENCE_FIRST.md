# CYPHER65 — Evidence-first operational intelligence

**Date:** 2026-10-22. **Agent:** @FeatureArchitect. **Status:** proposals, not delivered features or measured results. No service, dependency, account or hardware operation was selected.

## Resumo executivo

A inovação recomendada é tornar a operação explicável: timeline térmica (#838), replay de incidentes e comparação energética (#837), sempre com origem, idade e lacunas dos dados. Benefícios são hipóteses a validar; não há lucro prometido, diagnóstico causal por IA ou comando automático. As fontes são fundamentos técnicos consultados hoje, não evidência de uma novidade lançada em 2026.

## Key insight and evidence

The opportunity is **operational context with visible uncertainty**. Grafana documents time-aligned states, null gaps and annotations: an established pattern, not CYPHER65's invention. [State timeline](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/state-timeline/).

OpenTelemetry separates event time from observation time. Reuse that semantic distinction in existing JSON, not a new OTel deployment or a causal-diagnosis claim. [Logs data model](https://opentelemetry.io/docs/specs/otel/logs/data-model/).

Home Assistant distinguishes measurements, forecasts, power and energy; its MQTT docs warn that retained replay can revive expired state. Validate source freshness independently of transport availability. [Sensor entities](https://developers.home-assistant.io/docs/core/entity/sensor/), [MQTT sensors](https://www.home-assistant.io/integrations/sensor.mqtt/).

## Three actionable proposals

### 1. Thermal Timeline / “Operational X-Ray” — #838, current implementation target

**Problem / differentiation:** Separate charts lose context; align tenant history without hiding gaps. No competitor exclusivity is established.

**MVP:** bounded read-only projection → aligned temperature/hashrate/power lanes + actual maintenance markers → accessible evidence table. Keep units/time/age, break gaps; no PWM-to-RPM inference, damage prediction or invented threshold. Maintenance is context, not causality. SVG/HTML suffices.

**Effort:** Medium. **Criteria:** Zero Friction (alignment), Visual Impact (synchronized lanes). **Experiment:** five seeded incidents; every missing interval stays unknown. Counterbalanced operator study targets 50% faster interval discovery without lower accuracy, **unmeasured**; no 10x claim. Root owns implementation/QA; this brief is rationale only.

### 2. Incident Evidence Replay — proposed follow-up, separate Issue required

**Problem:** A mutable dashboard cannot reproduce exactly what an operator saw.

**MVP:** tenant-allowlisted snapshot + source/observation times + reducer version → frozen replay → source-linked cards. No arbitrary log-body export, secret/address exposure or command replay. Hashes establish byte identity, not sensor truth. Start with fixtures; actual historical coverage depends on retained evidence.

**Effort:** Medium. **Criteria:** Zero Friction (packet assembly), Visual Impact (synchronized scrubbing). **Experiment:** identical packets yield identical states; late/out-of-order data is labelled. Target 50% faster evidence assembly across five incidents, **unmeasured**.

### 3. Energy Scenario Lens — #837, after #838

**Problem:** Stale tariff, power or solar data can make invalid scenarios look cheap.

**MVP:** operator tariff + measured W + scenario duration + optional local solar input → side-by-side grid/profile costs. Show currency, assumptions, age and missing inputs. Compute tariff × valid kWh, never W-as-kWh. No revenue/profit forecast, automatic application or “free solar” assumption; disclose missing export/opportunity cost. LAN inputs require a local agent.

**Effort:** Medium, higher with integration. **Criteria:** Zero Friction (recomputation), Visual Impact (comparable scenarios). **Experiment:** verify units/currency; retained, stale, out-of-order or absent inputs block recommendations. Target correct preset comparison within 30 seconds without weaker assumption recall, **unmeasured**.

## Shared release and data gates

Tenant isolation, bounded history, timeout/backoff, session cancellation, private/no-store and SW exclusions, finite numbers, independent freshness, reduced motion. Python contracts/isolation, real-source JS and desktop/mobile E2E must pass. Drafts only; exact-head CI and independent review remain required. No merge/deploy, hardware or payments.

## Source audit appendix

Three Exa searches × five requested results: **sources_reviewed = 15** is a requested-result metric, not full reads. Fifteen distinct URLs screened; older/alias versions and repository copies consolidated; **four canonical pages fetched/read fully**. No affiliate/roundup source or recent-publication window. Vendor docs establish their semantics, not comparative superiority.

| Source | Quality and date evidence | Bounded use |
|---|---|---|
| Grafana state timeline | Maintainer documentation; undated living page; older version results confirm this is foundational, not a new 2026 invention | Null gaps, time-aligned states and annotations |
| OpenTelemetry logs data model | Official specification; explicitly marked Stable; publication date not established | Event-time versus observation-time semantics; no stack adoption |
| Home Assistant MQTT Sensor | Official integration docs; search metadata says 2024-02-07, but page publication date not independently confirmed | Retained-message replay, availability and expiry caveats |
| Home Assistant Sensor entity | Official developer docs; undated living page | Read-only sensor semantics and power/energy/state-class distinctions |

**Boundary:** Sources support patterns, not CYPHER65 completeness, benefit, causality, competitor gaps or production reliability.
