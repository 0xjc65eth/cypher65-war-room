# Issue #836 — Original read-only Mini War Room

## Scope and boundaries

Dedicated `/mini-war-room` compact monitor, with transparent-background
`?presentation=obs`. This is original CYPHER65 code: no fork, copied source,
restricted design asset, external service or dependency was introduced.
Thermal Timeline (#838) and Energy Advisor (#837) are separate increments.

The page loads only its dedicated CSS/module, not the dashboard's private
snapshot, wallet, device command or account surfaces. No hardware, provider,
purchase, payment, overclock or mutable fleet endpoint is invoked.

## Contract and operational meaning

`GET /api/mini-war-room` queries the existing initialized fleet registry with
the resolved nonempty tenant and `with_telemetry=True`. An empty tenant must
never select the registry's unscoped administrator view. Tombstones remain
excluded by the registry. The response is constructed from an allowlist:

- `schema_version=1`, `generated_at` (UTC Unix seconds), `stale_after_s=900`;
- state: `empty`, `unknown`, `stale`, `offline`, `partial`, `current`;
- mutually exclusive device counts: total/current/stale/offline/unknown;
- metrics: hashrate sum (H/s), power sum (W), maximum temperature (°C).

Each metric carries finite value or null, unit, contributor count, oldest and
newest observation timestamps, age of oldest contributor, fixed source
`fleet_telemetry`, aggregation, and `window_s=null`: the firmware averaging
window is not established. It is a latest-observation-per-device aggregate,
not a synchronized sample, physical-health attestation or measured energy.

Only ONLINE/IDLE/HASHING rows with valid timestamps no more than 900 seconds
old and not in the future can contribute. OFFLINE/PAUSED are counted together
as offline/paused, never as zero measured capacity. Missing/nonfinite/negative/
boolean/numeric-string metrics are unavailable. Genuine measured zero remains
zero. An overflowing sum becomes unavailable, retaining contributor metadata.
Partial observations never imply the entire registered fleet was measured.

## Authentication, privacy and failure behavior

Existing tenant resolution, viewer RBAC and self-host open mode apply. An
explicit invalid/expired/revoked bearer or API key fails closed even in open
mode or localhost; mismatched bearer/key tenants are rejected. No share token,
query credential, extra credential storage or new auth bypass exists. The HTML
shell contains no private data. Credentials remain in the existing browser
session mechanism, and the monitor sends only its access token, not refresh
tokens, license keys or unrelated account metadata.

OBS browser sources have a separate browser profile unless the operator
establishes a session in that same context. Logging in to ordinary Chrome does
not authenticate OBS. Use the existing panel login in the OBS browser context;
do not embed a token in the URL or make a private cloud tenant publicly shared.
If that context cannot authenticate, the source intentionally stays unavailable.
Production OBS/session integration is NOT RUN; browser fixtures prove UI only.

The two paths return `Cache-Control: no-store, private, max-age=0`, `Pragma:
no-cache`, and vary by Authorization/Cookie/X-API-Key, including auth/error/405
responses. The service-worker fetch handler does not intercept either path,
including query variants, so it cannot store or recover them from its cache.
The exclusion decodes percent-escaped path components and normalizes duplicate
slashes, including Flask redirect aliases. Malformed encoding is network-only.
An independent review reproduced the initial literal-only exclusion failure;
the fix has production-handler alias regressions and a real service-worker
browser probe with a synthetic preseeded private cache entry.
`Vary` also includes `*`: the [Service Workers Cache.put specification](https://w3c.github.io/ServiceWorker/#cache-put)
requires rejecting such responses. A real Chromium control confirmed that
no-store alone is still stored by Cache API, whereas Vary:* rejects the put.
This protects first visits controlled by an older installed worker that lacks
the new exclusions; it may emit a rejected-cache-put diagnostic in that older
worker, but the online response still reaches the caller. This is a privacy
guard, not a claim to repair all pre-existing dashboard caching behavior.
Other pre-existing service-worker caching behavior is outside this increment.

## Client lifecycle and motion

One in-flight GET at a time; 8-second total deadline includes JSON body reading.
Abort is best-effort, and a generation/session fingerprint fence prevents old
responses from publishing even when a transport ignores cancellation. Polling
is normally every 15 seconds; failures back off to 30 then at most 60 seconds.
401/403 stops automatic retry until user/session activity. Invalid local session
storage never silently falls back to anonymous access. Refresh, pause, offline,
pagehide and cross-tab session invalidation clear displayed measurements.
Source expiry also clears observations independently of the polling interval.
The browser's clock is used conservatively; a clock ahead of the server can
make a legitimate observation unavailable, not fabricate freshness.

Emil-primary/Jakub-secondary: one 180ms opacity/6px-translation/2px-blur initial
entry, no continuous numeric/status animation, static skeleton, immediate
keyboard feedback and full reduced-motion path. Native keyboard controls,
44px targets, text status, units/UTC/observation age and contributor coverage
remain visible on mobile and OBS. No heavy images/components need lazy loading.

## Read-only audit before implementation (Portuguese)

1. **Veredito:** entrega parcial não executável: havia rota/template, mas serviço,
   assets e testes não estavam presentes. Checkout do usuário foi preservado.
2. **Evidências/limites:** contrato real em `axe_fleet/registry.py` e
   `axe_fleet/models.py`; nenhuma integração física ou fornecedor validado.
3. **Achados:** FATO — dados antigos/ausentes não provam capacidade atual;
   HIPÓTESE — a entrega parcial pretendia excluir esses dados, sem serviço para
   verificar; RECOMENDAÇÃO — projeção allowlisted e testes de freshness/tenant.
4. **Métricas:** H/s, W, °C, `ts` UTC, origem frota; janela média desconhecida.
5. **Segurança:** somente leitura, sem comandos/credenciais novas; exigir tenant
   não vazio, autenticação explícita fail-closed e cache privado.
6. **Testes na auditoria:** NOT RUN — serviço e suítes não estavam disponíveis.
7. **Aceite proposto:** contrato/isolação Python, controlador real JS e navegador
   desktop/mobile/OBS com dados sintéticos e sem endpoints mutáveis.
8. **Produção:** exigir gates reais e aprovação independente; evidência local
   não equivale a merge autorizado, CI por commit ou validação OBS física.

The read-only audit ended before implementation under the separately authorized
Issue #836. No code was changed as an action of the mining-review skill.

## Reproduction and gates

```bash
python -m pytest tests/test_mini_war_room.py -q \
  --cov=services.mini_war_room --cov=routes.mini_war_room --cov-fail-under=80
node --test tests/test_mini_war_room_js.js
node tests/test_app_js_core.js
PORT=8816 bash run-e2e.sh --file=mini-war-room.spec.js
git diff --check
```

The asynchronous source-backed JS suite is included in the existing core gate
via an awaited child process, before its legacy `process.exit`. The explicit CI
E2E list includes both desktop and mobile projects for the new spec. Backend
coverage includes the new route module explicitly without reducing the 80% gate.
Tests use actual SQLite registry queries for cross-tenant/tombstone isolation;
browser presentation tests use API fixtures and establish no physical-device
support. A separate SW-enabled browser test uses real local routes/cache APIs
and proves aliases are neither cached nor recovered offline. The HTML fallback
remains visible with JavaScript disabled; entry motion is progressive enhancement.

Observed local results and any review follow-ups are recorded in the delivery
checkpoint. Exact-head remote CI and independent GitHub approval remain separate
required gates. Baseline mobile dependencies (#844/#845) are not changed here.
