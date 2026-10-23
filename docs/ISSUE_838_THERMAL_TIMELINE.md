# Issue #838 — Thermal Timeline / operational evidence lens

## Outcome and boundaries

An original read-only timeline at `/thermal-timeline`, reachable by a real
dashboard sidebar link. Four synchronized SVG lanes show temperature,
hashrate, power and measured fan RPM; a keyboard-accessible common cursor
selects one timestamp and displays its values, separate PWM, voltage and
frequency. Observed focus fits the real time extent without compressing gaps;
the full requested window remains available explicitly. Gray intervals mark
missing observations, not a diagnosis or a fabricated zero.

This is independent CYPHER65 code, not a fork or copied restricted source,
design or assets. No new dependency, external service or subscription. It
builds on the completed implementation/local validation of #836, not its
release authorization. No merge, deploy, hardware/provider call, automatic
purchase, payout change, firmware operation or command replay is authorized.

## Data flow and honest semantics

Existing collection → `axe_telemetry` → tenant/device/time-bounded SQL reader
→ strict allowlisted projection → dedicated API → native SVG and evidence cards.
There are no outgoing requests in the reader. Endpoints:

- `GET /api/thermal-timeline/devices`: at most100 live tenant device IDs/names,
  plus explicit truncation; no IP/MAC/credentials/raw telemetry.
- `GET /api/thermal-timeline?device_id=...&hours=1|6|24`: at most300 stored rows
  examined after a301-row peek, deterministic timestamp/ID ordering, at most200
  maintenance records after201-row peek. SQL limits oversized JSON before it
  enters Python; JSON payload budget64KiB per selected record.
- `GET /thermal-timeline`: public shell without injected private information.

The response identifies its local-history source, UTC query time, per-sample
UTC stored observation timestamp, unknown firmware averaging window, age,
freshness900s, discarded row count, gaps and truncation. A fresh historical
sample is not proof of continuous hashing or physical health. Historical
observations remain historical when old/offline; the display never promises
current capacity, failure dates, remaining life or profit.

| Field | Unit | Accepted domain |
| --- | --- | --- |
| temperature_c | °C | canonical -40..150 |
| hashrate_hs | H/s | 0..1e18, required for a trusted measured sample |
| fan_rpm | RPM | 0..100000; never derived from PWM |
| fan_speed | PWM % | 0..100, independent of measured RPM |
| power_watts | W | finite nonnegative; not kWh |
| voltage_mv / frequency_mhz | mV / MHz | finite nonnegative observations, not commands |

Boolean/numeric-string/nonfinite/out-of-domain values are unavailable, not
zero. Genuine zero and valid subzero Celsius remain representable. Heartbeat,
malformed or oversized records are excluded; a skipped invalid observation
between valid samples breaks continuity even below900s. Gaps over900s and
missing metric values are not interpolated. Same-timestamp rows use the latest
arrival; no temporal smoothing/forecast is invented. The existing stored `ts`
does not prove an independent firmware or collector clock; dual timestamps are
a future evidence-capture proposal, not implemented retroactively.

## Maintenance ownership migration and association

The two registries have distinct identifiers. Name/IP is never a join key.
Maintenance context is associated only when canonical valid MAC has exactly
one active Axe record and one Core record within the same tenant. MAC is
operator/producer-reported cadastral evidence, **not cryptographic or physical
attestation**. Missing/ambiguous associations are explicit.

An idempotent additive migration adds nullable `maintenance_records.tenant_id`.
Legacy rows remain NULL: ownership is not backfilled by guessing. The existing
authorized maintenance POST now passes its resolved tenant to the writer;
legacy direct callers remain unattributed. Response contracts are unchanged.
The new reader returns only matching explicitly scoped timestamp/type markers;
notes, actors, raw IDs and command parameters are omitted. Legacy rows are
excluded and their unscoped availability is disclosed only after association.

Compound tenant/device/time indexes bound ordered telemetry and scoped
maintenance queries; EXPLAIN regression asserts use of the telemetry index.
The migration was tested on a synthetic legacy DB, repeated idempotently,
and verified through the actual maintenance POST. Deployment/large production
DB index-build time is NOT measured. Rollback application code may ignore the
additive column/indexes; do not DROP ownership data automatically.

Configuration-change markers compare valid observed voltage/frequency/PWM on
adjacent samples, only across continuous evidence. They mean “observed value
changed”, not “a command ran” or “this caused the temperature change”. No
configuration history is fabricated when measurements are missing.

## Security and lifecycle

Existing tenant resolution/viewer RBAC/open-self-host policy applies. Explicit
invalid bearer/API keys, expired/revoked/refresh tokens and conflicting
credential tenants fail closed, including localhost/open mode. Empty tenant
cannot select an unscoped registry view. Removed/cross-tenant device requests
return404. Errors are generic with safe structured observability events.

Private responses, auth failures and405s carry no-store/private and
`Vary: Authorization, Cookie, X-API-Key, *`. The star prevents Cache API storage
by an older installed SW as well. New SW exclusions decode percent escapes and
merge repeated slashes before cache/fallback access. This is scoped protection,
not an audit/repair of every pre-existing dashboard cache surface.

Each loader has one active request and coalesces rapid selections to the latest
intent. Eight-second total timeout includes JSON; abort-ignoring responses are
fenced by generation, selection and session identity. Polling30s, failure
backoff capped60s, no automatic auth retry. Restricted storage including a
throwing `window.localStorage` getter becomes an explicit session state, never
anonymous fallback. Session changes/pagehide/offline clear private presentation.

## UX and original motion

Emil-primary/Jakub-secondary: one180ms initial header entry using opacity,
translation and blur. No looping numeric/status animation or animated cursor;
keyboard inspection is immediate. Reduced-motion disables entry. Skeleton,
loading/error/empty/stale/offline/session states and disabled async controls
are explicit; the page and noscript fallback remain visible without JavaScript.
Native lightweight bounded SVG/HTML needs no heavy chart library or image load.
Styling follows CYPHER65 industrial monochrome/Bitcoin accent and2px radii.
Both picker and maintenance truncation are visible, not silently expanded.

## Read-only audit before implementation (Portuguese)

1. **Veredito/escopo:** histórico existente reutilizável, associação entre
   registries e ownership legado insuficientes para uma junção irrestrita.
2. **Evidência/limites:** `axe_fleet/registry.py` limita histórico e declara
   unidades; `app.py` manutenção usa Core; bootstrap legado não tinha tenant.
   Nenhum equipamento, fornecedor ou secret foi acessado.
3. **Achados:** FATO — IDs distintos e manutenção sem tenant; HIPÓTESE — junção
   por nome/IP poderia misturar contextos; RECOMENDAÇÃO — associação cadastral
   única e migração sem atribuição retroativa, verificadas com SQLite sintético.
4. **Métricas:** °C/H/s/W/RPM/PWM%/mV/MHz, ts UTC, origem histórico local;
   janela média do firmware desconhecida; missing não é zero.
5. **Segurança:** só leitura, sem comandos/SSRF; exigir tenant, credencial
   explícita válida, no-store e exclusão do cache inclusive aliases.
6. **Testes na auditoria inicial:** NOT RUN; inspeção de código e contratos.
   Validações abaixo ocorreram depois, na implementação autorizada da #838.
7. **Aceite:** isolamento/tombstone/migração/limites/gaps em Python, controller
   real JS e navegador desktop/mobile com fixtures identificadas.
8. **Produção:** gates por commit e aprovação independente continuam
   obrigatórios; MAC cadastral e fixtures não certificam hardware.

The mining-review skill ended read-only before the separately authorized
implementation. No migration/write was performed as an audit action.

## Arena challenge and decisions

| Proposal | Alternative / challenge | Decision / evidence |
| --- | --- | --- |
| Align actual observations and gaps | Smooth/interpolate a prettier curve | Keep gaps; source-backed segmentation tests and browser lane assertions |
| Associate contextual maintenance | Join names/IP or assign old tenant | Unique tenant/MAC association; NULL legacy migration and actual SQLite isolation tests |
| Keep credential-free shell and private API | Public share token for convenience | Existing authenticated browser context only; explicit credential/cache tests |
| Single-flight latest-intent loading | Parallel fetch on every change | Coalesce/cancel; delayed-JSON and rapid-selector tests |
| Recover after picker failure | Reviewer reproduced placeholder as a fake device ID | Empty placeholder values; desktop/mobile RED then GREEN |
| Handle restricted storage | Reviewer reproduced uncaught getter before helper try | Lazy getter and loader guard; two red browser cases then explicit auth/no-request green |
| Display bounded results honestly | Reviewer found hidden picker/maintenance caps | Visible100/200 truncation warnings and browser regressions |
| State link assurance accurately | Reviewer challenged “physical proof” wording | Explicitly database association, not physical attestation |

Independent initial source/browser review was completed. The requested second
review turn hit an account usage limit, so **final independent re-review is
BLOCKED**, not silently approved. Root verified fixes with real-source tests and
browser regressions; this does not replace independent GitHub approval.

## Validation and reproduction

```bash
python -m pytest tests/test_thermal_timeline.py tests/test_bootstrap_schema.py \
  tests/core/test_maintenance.py -q --cov=services.thermal_timeline \
  --cov=routes.thermal_timeline --cov-fail-under=80
node --test tests/test_thermal_timeline_js.js
node tests/test_app_js_core.js
PORT=8817 bash run-e2e.sh --file=thermal-timeline.spec.js
git diff --check
```

Observed:56 selected Python tests PASS,98.97% selected module coverage (not
global); full Python4496PASS/4SKIP/642warnings,85.85% updated CI coverage scope,
268.72s. Counts differ from #836 because these are isolated branches from the
same master, not a combined implementation. JS core1695 assertions includes
the awaited source-backed child suite. Final JS/browser results and SHA are in
the delivery checkpoint. Initial browser run12PASS/2FAIL retained; separate
blocked-storage reproduction2FAIL retained; neither is called green.

CI explicitly includes the new route in the unchanged80% coverage gate and the
new spec in both browser projects. Exact remote-head CI remains distinct from
local green. Browser fixtures, a real local SW/Cache API probe, synthetic legacy
SQLite and native HTML controls establish contracts, not ASIC/provider/production
OBS support, native-device certification, causal benefit or measured10x gains.

The business/controller/validation/segmentation functions live in
`static/thermal-timeline-core.js`, imported by the real DOM entry module and
by the Node tests. This is source reuse, not a test mirror. Node coverage for
this business module is measured separately from the browser DOM presentation;
an earlier unsplit-file Node report included unexecuted browser-only code and
is retained as an intermediate result, not silently called80% coverage.

## Innovation research

[Evidence-first innovation brief](INNOVATION_EVIDENCE_FIRST.md), researched on
2026-10-22, contains at most three experiments with primary sources and a
Portuguese executive summary. Operational X-Ray is this prototype; Incident
Evidence Replay remains a proposal needing a separate Issue; Energy Scenario
Lens belongs to later #837. The patterns are established, not claimed as a
new2026 invention or exclusive competitive moat. Efficacy targets are unmeasured.
