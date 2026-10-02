# Deterministic snapshot HTTP 500 audit (#721)

## Defect and fix

The original visual audit installed a route on an already controlled page.
A service worker could bypass Playwright interception. Zero overlays could
therefore pass without injecting any failure; caught probe errors were silently
ignored as well. A matched baseline/candidate experiment on `c597304` showed
zero interceptions with service workers allowed and one when blocked.

The normal boot audit remains service-worker-enabled. Only the failed-fetch
probe uses a fresh context with `serviceWorkers: 'block'`. Its exact-origin,
exact-path `/api/snapshot` matcher allows query parameters, injects HTTP 500,
and registers the response waiter before navigation. Green requires an actual
matching HTTP 500 response, at least one completed interception and an integer
zero skeleton count. Missing interceptions, incomplete measurements, execution
errors and context-cleanup failures are blocking. The context closes in `finally`.

Network/navigation timeouts and the original three-second render settling
interval remain bounded. No production endpoint is changed, no skeleton check
is removed, and no service-worker application code is modified.

## Run and review

```sh
node --experimental-test-coverage --test tests/test_audit_failed_snapshot.cjs
npm run check:frontend
```

The self-test is a blocking step immediately before `audit_ui.cjs --all` in the
combined pipeline; existing CI therefore runs both unit and real-browser checks.

Local validation on 2026-10-02, isolated branch
`fix/721-deterministic-snapshot-error-audit`, base
`c597304efb867716c0b8cf45ec72d1de8a98dc53`:

- 9/9 self-tests passed. Helper coverage: 98.61% lines, 91.30% branches,
  83.33% functions (Node experimental test coverage; no copied implementation).
- Full `npm run check:frontend` passed using the isolated Python runtime and
  actual Flask application server/bootstrap. Desktop and mobile each recorded
  **1 HTTP 500 interception and 0 leftover skeletons**. Boot/market cleanup,
  overflow, truncation and page errors remained clear.
- JS core: 1544 assertions. DOM/a11y/token/mobile guards and self-tests,
  generated bundle drift/syntax, SW push, axe (100/100 both viewports), fetcher
  unit and mutation guards passed.
- `git diff --check` and new/changed JavaScript syntax checks passed.
- Independent Security/enterprise reviewer found no actionable P0/P1/P2 in
  the source diff, confirmed fail-closed semantics and isolation; the reviewer
  did not run a second browser pipeline. This is not a GitHub approval.

No source Python/mobile/runtime bundle changed. #710 remains a separate
repository-wide dependency-audit concern, and #722 covers activated Rentals
toolbar overflow, which this boot-only audit does not test. Exact-head CI and
the required GitHub approval are still required before squash merge/deploy.
