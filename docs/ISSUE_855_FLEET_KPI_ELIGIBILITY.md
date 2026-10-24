# Issue #855 — Fleet KPI eligibility and production-source regressions

## Scope and provenance

Issue: <https://github.com/0xjc65eth/cypher65-war-room/issues/855>.
Branch: `fix/855-fleet-kpi-eligibility`.

The implementation started from `633b0d1202f6d83e7dd8e5d98398be5750c65893`.
Before final local validation, the isolated checkout was fast-forwarded to
`f479382750f608b44d3a8dfd6a163ab87ae97d6a`, preserving the uncommitted patch.
Those upstream changes touched backend, mobile and documentation, not the
Fleet fragment, affected frontend tests or CI command changed here.

This patch aligns the existing Fleet Command Center measurements with the
reachable-status contract in `core/models/device.py::device_status_is_online`.
It adds no panel, motion, command, endpoint, dependency or paid service.

## Metric contract

| Input | Temperature, power, J/TH, shares and latency | Existing status bucket |
| --- | --- | --- |
| `ONLINE`, `HASHING` | Include available measurements | Online |
| `WARNING` | Include available measurements | Warning, never healthy/recovered |
| `OFFLINE`, `STALE`, `PAUSED`, unknown or absent status | Exclude historical measurements | Unchanged |

Hashrate remains endpoint-authoritative: the aggregator sums supplied current
`_telemetry.hashrate_hs` values across the response without re-inferring them
from status. It never reads `last_known_hashrate_hs`. A synthetic unit case
preserving a supplied offline hashrate tests this consumer boundary; it does
not assert that an offline physical miner produces work.

Metric eligibility is case-insensitive. The unchanged rendered status counters
consume canonical uppercase backend statuses; this patch does not normalize
their buckets or add a new lowercase counter contract.

The existing numeric guard retains measured zero and rejects absent, boolean,
empty and non-finite values. The backend's
`axe_fleet/routes.py::_probe_miner_latency_ms` rounds a successful TCP probe to
integer milliseconds, so a valid result may be `0`. The aggregator now accepts
non-negative numeric latency through that guard, rather than converting
missing values to zero or discarding a successful rounded-zero measurement.
Negative latency is excluded. Existing count-based zero-power semantics were
already correct before this patch and are not claimed as a newly repaired bug.

This work does not change status counters, alert/recovery semantics, freshness
labels, request ordering, authentication or the backend summary contract.

## Regression design

`tests/test_app_js_core.js` suite 26d now loads `_ccKpiAgg` from the canonical
`static/src/48-fleet-cc.js` using the existing `loadFragment` harness. Its copied
aggregator and copied numeric guard were removed. The empty response expectation
is now the production contract (`totalHr: null`), not the obsolete mirror's zero.

Source-level cases cover reachable and excluded statuses, lowercase input,
mixed fleets, absent telemetry, invalid numeric values, measured zeros, share
counters, latency and endpoint-authoritative hashrate. The source-loaded DOM
harness exercises the actual fetch/render path and verifies that WARNING
remains in its own counter bucket.

`tests/e2e/fleet-kpi-eligibility.spec.js` exercises the generated application
bundle in Chromium desktop and mobile-chrome. All API responses are synthetic
fixtures. Existing navigation analytics is fulfilled locally; every other
non-GET request is blocked and asserted absent. Service workers are blocked
for this fixture test, so it is not a service-worker regression test. The
workflow explicitly runs the new spec in both projects.

## Local evidence

Logs are retained outside the repository at
`/private/tmp/cypher65-fleet855.FZhbr2/`. These are local results, not remote
exact-head CI results, Codecov approval or physical-device certification.

### Regression-first baseline (`633b0d12`, unchanged production logic)

| Check | Result | Evidence |
| --- | --- | --- |
| JS core with new source tests | **FAIL**, 30/1823 assertions; 29 KPI regressions plus the existing Mini War Room child failure | `red-core.log` |
| Source-loaded operational DOM | **FAIL**, 56 passed / 3 failed after correcting the new harness assertion's HR formatting assumption | `red-dom-confirmed.log` |
| Chromium HASHING case, original bundle | **FAIL**, temperature expected `60.0°C`, received unavailable | `red-browser.log`, `red-browser-evidence.tgz` |

The first browser green attempt also exposed a test-harness assumption: normal
navigation emits an analytics POST. The fixture was corrected to fulfill only
that exact endpoint locally; the prohibition on device/other mutations remains.
The intermediate failure log `green-browser.log` is retained, not hidden.

### Final validation on `f4793827` plus this patch

| Check | Result | Evidence |
| --- | --- | --- |
| Source-loaded operational DOM | **PASS**, 59 passed / 0 failed | `dom-current-master.log` |
| Chromium desktop + mobile-chrome | **PASS**, 10 passed in 23.6 s | `browser-current-master.log` |
| Generated bundle drift | **PASS**, 17 fragments synchronized | `bundle-current-master.log` |
| DOM regression guards | **PASS** | `dom-guard-current-master.log` |
| Mobile XSS guard | **PASS**, 59 files / 0 vectors | `mobile-guard-current-master.log` |
| Bundle syntax; whitespace | **PASS**, `node --check static/app.js`; `git diff --check` | Local command exit codes 0 |
| Full JS core | **FAIL**, 1833 passed / 1 failed out of 1834 | `core-current-master.log` |
| Scoped changed-logic V8 coverage | **PASS**, 8/8 functions and 41/41 executed block ranges | `coverage-kpi-current-master.json`, `v8-coverage-current-master/` |

The full JS-core failure is the independently reproduced baseline tracked by
**[#863](https://github.com/0xjc65eth/cypher65-war-room/issues/863)**: the Mini War
Room service-worker query-variant controller test fails. This patch neither
modifies `static/sw.js` nor weakens/skips that test. The suite is not green and
this failure is not waived by the passing scoped regressions.

Coverage is Node V8 block-range coverage of the real `_ccKpiAgg`, its nested
callbacks and shared `_numOrNull` guard, identified by the canonical VM source
filename. It exceeds the 80% changed-logic target; it is **not** whole-file,
repository, Istanbul branch/line or remote Codecov coverage. Collection ran
during the full JS suite, whose independent baseline failure remains visible.

Reproduction commands from the isolated checkout:

```sh
NODE_V8_COVERAGE=/private/tmp/cypher65-fleet855.FZhbr2/v8-coverage-current-master \
  node tests/test_app_js_core.js
node tests/test_operational_evidence_states.js
node scripts/build_app_js.cjs --check
node scripts/check-dom-regression.cjs
node scripts/check-mobile-xss.cjs
node --check static/app.js
git diff --check
BASE_URL=http://127.0.0.1:8877 node_modules/.bin/playwright test \
  tests/e2e/fleet-kpi-eligibility.spec.js \
  --project=chromium --project=mobile-chrome
```

The browser fixture used a localhost-only Flask import with `TESTING=True`, a
scratch database and no `_start_background_threads` invocation. API fixtures
prevented hardware/provider traffic. Existing dependencies were reused
read-only: Node 22.22.0, `@playwright/test` 1.62.0 and `axe-core` 4.13.0, the
latter two matching this checkout's root lockfile. No installation or shared
dependency modification was performed.

## Remaining gates and boundaries

- **NOT RUN here:** full Python suite, full frontend visual pipeline, mutation
  testing, remote CI/Codecov and physical hardware/provider integration.
- Independent review and exact-head CI remain required before merge. No local
  result constitutes an approval, authorized deploy or completed physical gate.
- Baseline #863 must be assessed separately; a red full JS gate must not be
  described as passed merely because this issue's new regressions are green.
- This evidence demonstrates deterministic software behavior with fixtures,
  not live ASIC health, pool reconciliation or deployment readiness.
