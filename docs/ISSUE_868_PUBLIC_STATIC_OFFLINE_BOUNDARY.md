# Issue #868 — public-static-only offline storage

Date: 2026-10-24. Base: `f479382750f608b44d3a8dfd6a163ab87ae97d6a`.
Issue: <https://github.com/0xjc65eth/cypher65-war-room/issues/868>.
Branch: `security/868-private-offline-cache`.

## Finding and bounded decision

The generic worker previously cached successful same-origin GET responses and
searched all CacheStorage entries on network failure. Actual Flask
`GET /api/settings` with a synthetic tenant JWT returns tenant-specific settings,
`Cache-Control: no-cache, no-store, must-revalidate`, and
`Vary: Accept-Encoding`. The browser Cache API nevertheless admits that response;
`no-store` is not an automatic admission rule for explicit `cache.put()`.
Unowned matching can therefore retrieve a previous identity's response offline.
This is a hermetically reproduced local risk, not evidence of production leakage.

The correction is a single explicit **public-static-only** policy. It does not
attempt to encrypt, partition or authorize private offline observations. Those
would require a separate ownership, invalidation and freshness contract.

## Policy and compatibility

- One exact path/MIME allowlist contains `style.css`, `app.js`, `manifest.json`,
  and the existing 32-, 192- and 512-pixel PNG icons under `/static/`.
  Other files require an explicit future policy change; a `.js` suffix alone
  does not authorize storage. The worker script itself is not cached.
- `/`, login, every API (including health), other documents and unknown paths
  bypass `respondWith` before either fetch or fallback. All existing Mini War
  Room, Thermal Timeline and Energy Advisor page/API exclusions are subsumed.
- Navigation/document requests, requests with any Authorization header value,
  and requests using the `no-store` cache mode also bypass the worker entirely.
- URL parsing requires the exact origin, no embedded credentials/fragment, a
  single decoded allowlisted path and at most the existing bounded `?v763` or
  `?v=763` version query. Malformed/double-encoded/private paths and arbitrary
  query parameters do not gain a fallback. Canonical keys omit only an accepted
  static version query.
- Admission **and fallback reads** reject non-200, redirected, opaque,
  cross-origin/different-resource responses; private/no-store cache directives;
  `Vary: *`, Authorization or Cookie; and unexpected/missing MIME types.
  A fetched network response is returned normally even if ineligible for storage.
- Fallback reads only the canonical key in current owned `cypher65-v14`.
  There is no global `caches.match()` or foreign/old-generation fallback.
- Install warms these public files without cookies and applies the same response
  defenses. Activation removes obsolete exact `cypher65-v<digits>` generations
  and awaits `clients.claim()`. Foreign caches, similarly prefixed non-generation
  names, localStorage, IndexedDB and preferences are not deleted.

**Offline HTML navigation is deliberately unavailable.** This is not a complete
offline application: a new launch cannot load the private dashboard document
offline. Public files remain resilient for an already-loaded document. No private
shell, stale account page, fake successful API result or synthetic snapshot is
substituted. Online Flask authentication/authorization remains unchanged.

The root template is server-rendered and contains configuration bindings; it is
not classified as a public shell. The test fetches that real document without
executing its scripts. It does not assert that this particular fixture root
currently renders a private wallet value.

## Regression and evidence

Checkout/evidence: `/private/tmp/cypher65-868.DoMOA0/`. Existing Node 22.22.0,
Chromium/Playwright dependency tree and Python 3.14.6 environment were reused;
no dependency installation, provider access, real credentials or hardware.

| Check | Result |
| --- | --- |
| New production-handler/precache regressions before implementation | Expected RED: 2 failed / 0 passed (`red-policy.log`) |
| Expanded production-worker VM tests | PASS: 10 tests |
| New worker + existing Mini/Thermal/Energy JS suites, run directly | PASS: 42 tests (`features-final.log`) |
| Direct legacy core runner | PASS: 1695 assertions plus its Energy child 10 tests (`core.log`) |
| Existing Mini/Thermal/Energy Python contracts | PASS: 200 tests (`python-features.log`) |
| Real SW/Cache API/Flask browser probe | PASS: desktop and mobile projects, initial corrected repeat 2 tests / 9.8 s (`browser-green.log`); final expanded repeat 2 tests / 5.6 s (`browser-final.log`) |
| Syntax, bundle drift, DOM/mobile XSS guards, Black/Flake8 fixture, YAML parse, diff whitespace | PASS |
| Full repository/global coverage, mobile audit, exact-head remote CI | NOT RUN for this branch; existing remote mobile failure is not waived |
| Independent source/unit/browser review | PASS: peer repeated 42 JS tests and final 2 browser projects / 12.5 s; no CRITICAL/HIGH finding, not a formal GitHub approval |
| Remote exact-head approval, merge, deploy | Not performed at implementation handoff; a draft PR is required to obtain remote CI |

The real browser probe verifies both synthetic A and B through production Flask
JWT/tenant/settings/database logic. It establishes actual private HTTP headers and
Cache API admission, then re-seeds actual private responses **after activation**
into generations 12/13/14 and a foreign cache. A/B/no-auth fetches for API and
document paths cannot retrieve them offline. Public CSS works offline; a foreign
public-path entry and current public-path entries with private/no-store/auth-Vary
headers cannot be served. Unrelated cache/localStorage/IndexedDB controls survive.
External browser requests are blocked and Flask background workers never start.
The fixture uses temporary SQLite and synthetic JWTs only; it is not production
account, native-device, OBS, broker or deployment certification.

The initial browser run failed 2 tests on an incorrect test-harness assumption:
it expected a synthetic wallet value in the root template. The real template uses
different configuration binding names; the corrected assertion checks the real
settings binding and no-store header, without changing application rendering.
That failed run remains in `browser.log`. An unavailable local PyYAML module was
not installed; the updated CI YAML parses using existing `js-yaml` instead.

V8 raw coverage for the executed **production VM policy/lifecycle/cache functions
before the Push section** reports 20/20 functions and 63/63 observed block ranges
exercised. These are raw function/range counts, **not** a global SW line/statement
coverage certificate. Push/notification handlers were unchanged and not exercised
by this scoped suite. Raw files remain in sibling `v8/`.

## Composition / handoff

- PR #865 / Issue #863 independently restores the three private families at
  generation 13. This patch starts from current master, **not** that feature
  branch, and intentionally supersedes its SW policy with a stricter generation
  14 allowlist. Do not silently cherry-pick both SW versions over one another.
- Rebase/compose explicitly after #865. Keep its source/browser suites active;
  update generation/public-control expectations to the new policy (no API cache,
  no arbitrary-query fallback), rather than deleting/skipping those assertions.
- Issue #867 owns the nested `node:test` runner correction. This branch does not
  modify that runner. Its two new CI steps run this policy suite directly and its
  browser probe in the prepared frontend job. After composition, independently
  confirm every existing Mini/Thermal/Energy suite actually runs at the exact SHA.
- The remote master mobile audit failure (Zod HIGH advisories) and missing formal
  reviews remain gates, not reasons to suppress tests or claim release readiness.
- Publish only a draft after local review; obtain exact-head CI and independent
  GitHub approval before merge. No operations, purchases, deploy or Issue closure are part of
  this implementation handoff.

Reproduce:

```sh
node --test tests/test_public_static_worker.js tests/test_mini_war_room_js.js \
  tests/test_thermal_timeline_js.js tests/test_energy_advisor_js.js
node tests/test_app_js_core.js
CYPHER65_TEST_PYTHON=/path/to/existing/python CI=false \
  node node_modules/@playwright/test/cli.js test \
  tests/e2e/public-static-worker.spec.js --project=chromium --project=mobile-chrome
git diff --check
```
