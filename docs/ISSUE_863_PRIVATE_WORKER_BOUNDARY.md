# Issue #863 — Composed private Service Worker boundary

## Current integration — 2026-10-25

Target master: `e616a0169659a8f5c8c70c5f13e67f300b86075c` (PR #871).
Its public-static-only v14 policy already subsumes the original three private
families. This PR preserves that production worker byte-for-byte; it must not
reintroduce the earlier v13 policy or generic API/document offline caching.

All seven composed source cases and both browser projects remain active. Their
contract now matches v14: current-owned-cache reads, MIME/header defenses,
obsolete v12/v13 migration, API bypass, allowed version query, unknown static
network unavailability and allowed-but-uncached static 503. Private aliases are
still reseeded after activation in old/current/foreign caches before denial.
The original tests against v14 first failed (4 passed / 3 failed); the explicit
contract migration is preserved rather than deleting or skipping assertions.

Thermal and composed-worker source suites run directly as an awaited shell
`node --test` CI step, not status-only nested children. This avoids depending on
the not-yet-merged #867 helper while retaining every test in those files. The
existing Mini/Energy core sites are unchanged; #867 owns their separate fix.
Remote exact-head CI and independent approval remain required before squash.

Current-base local validation:49 source/feature tests PASS; the exact new
standalone CI command executes19 tests (Thermal12 + composed7), independently
repeated on Node20; four browser cases PASS in34.8s (both worker probes on desktop
and mobile). The reviewer confirmed zero production-worker/core diff against
master. These are local results, not a substitute for checks on the published SHA.

## Historical v13 implementation and evidence

The following describes the original pre-#871 candidate, not the current
production policy or current-head test result.

## Scope and confirmed regression

Base: `f479382750f608b44d3a8dfd6a163ab87ae97d6a` (`master`).

The composed worker retained only the Energy Advisor private-route exclusion.
Existing Mini War Room and Thermal Timeline production-source tests failed
before this change. This is a confirmed worker-policy regression, not evidence
that production tenant data was leaked. Server-side `Cache-Control: no-store,
private` and `Vary: *` protections remain unchanged.

The restored boundary covers the following same-origin families:

| Feature | Page family | API family |
| --- | --- | --- |
| Mini War Room | `/mini-war-room` and descendants | `/api/mini-war-room` and descendants |
| Thermal Timeline | `/thermal-timeline` and descendants | `/api/thermal-timeline` and descendants |
| Energy Advisor | `/energy-advisor` and descendants | `/api/energy-advisor` and descendants |

Each GET request is parsed with `URL`, checked using exact origin equality, then
classified after one percent-decoding pass, repeated-slash normalization and
trailing-slash removal. Query parameters do not change the pathname boundary.
Malformed URLs or percent encodings bypass interception. Segment lookalikes such
as `/api/mini-war-room-extra` retain their previous public behavior. Foreign
origins, including origin-prefix lookalikes, are not intercepted.

Private requests return before `respondWith`, worker-side `fetch`, cache admission
or offline fallback. The browser therefore uses normal network behavior and
cannot recover those requests from worker caches while offline. This is not a
global privacy classification for every API, the root HTML document or other
routes; unchanged public API/static offline behavior remains in place.

## Cache migration and operational tradeoff

The generation changes from `cypher65-v12` to `cypher65-v13`. During activation,
only names matching `/^cypher65-v\d+$/`, other than the current generation, are
deleted. `clients.claim()` is awaited after deletion within the activation
lifetime. This invalidates obsolete owned caches that may contain older private
entries instead of relying solely on current response-admission headers.

Unrelated caches and quasi-prefix names such as `cypher65-v12-other-app` are
preserved. The migration does not delete localStorage, IndexedDB, server data or
user configuration. Public assets from obsolete generations are invalidated as
well; current install assets are precached, while non-preloaded resources need a
successful network retrieval before becoming available offline again. No global
offline or API caching removal is introduced.

## Reproducible checks

Use the repository Node runtime and existing locked dependencies; no dependency
or lockfile changes are required.

```bash
node --test tests/test_private_worker_routes.js tests/test_mini_war_room_js.js tests/test_thermal_timeline_js.js tests/test_energy_advisor_js.js
node tests/test_app_js_core.js
node --experimental-test-coverage --test-coverage-include='**/static/sw.js' --test tests/test_private_worker_routes.js
npx playwright test tests/e2e/private-worker-routes.spec.js --project=chromium --project=mobile-chrome
node --check static/sw.js
git diff --check
```

The combined VM suite executes the actual composed `static/sw.js`, not a copied
classifier. It covers all three families and aliases, page/API descendants,
origin-prefix attacks, malformed encodings, non-GET bypass, obsolete owned-cache
eviction, foreign-cache preservation, private seeded offline denial and public
static/API controls. The JS-core entry point awaits the combined suite and the
Thermal Timeline suite; existing Mini War Room and Energy Advisor suites remain
enabled. CI explicitly runs the browser spec on Chromium and mobile Chrome.

The browser spec serves the unchanged production worker and public assets from
an ephemeral loopback HTTP fixture. It seeds private entries before activation
to test migration, then **re-seeds them after activation and client claim** into
obsolete, current and foreign caches. After setting the browser context offline,
all private probes must fail rather than return any seeded response. A versioned
public CSS response and query-stripped manifest remain available, while an
uncached public asset returns 503. Foreign caches and a synthetic localStorage
preference survive migration. Online fixture responses with `Vary: *` are also
rejected by the real browser Cache API.

## Measured evidence and limits

- RED, existing feature suites: 30 passed / 2 failed; Mini and Thermal worker
  guards exposed the regression.
- RED, new combined worker suite: 1 passed / 6 failed before the worker fix.
- GREEN, combined worker and three feature suites: 39 passed.
- GREEN, JS core: all 1,697 legacy assertions passed, with awaited child suites.
- GREEN, actual Service Worker/browser Cache API: 2 passed across Chromium and
  mobile Chrome. An independent reviewer also reproduced both browser cases,
  the 39 source tests and JS core on the same production worker.
- GREEN, focused V8 coverage run: 7 passed; whole-worker coverage is **56.11%
  lines, 96.55% branches, 77.78% functions**. The 17 nonblank added diff lines
  fall outside the measured uncovered-line ranges. This incremental count
  includes comments and syntax and is not an executable-statement coverage rate.
  Unchanged push/message/notification-click code and the install-error fallback
  remain outside this focused test run; no whole-worker 80% claim is made.
- GREEN, worker syntax and diff whitespace checks.

The fixture is evidence of worker interception, Cache API and offline behavior,
not Flask authentication, tenant authorization, production headers, TLS,
provider availability or hardware safety. No provider, hardware or financial
operation is performed. Full Python coverage, remote exact-head CI, GitHub
approval, merge and deployment are separate gates and are not certified here.
