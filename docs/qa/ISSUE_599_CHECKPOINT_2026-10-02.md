# Issue #599 implementation checkpoint — 2026-10-02

Status at initial checkpoint: implemented locally, not merged or deployed. The
complete frontend pipeline and exact-head CI were **not green**. A subsequently
completed frontend rerun is recorded below; exact-head GitHub CI remains pending.

## Scope and isolation

- Issue: <https://github.com/0xjc65eth/cypher65-war-room/issues/599>.
- Branch: `feat/599-rental-delivery-evidence`.
- Base: `c597304efb867716c0b8cf45ec72d1de8a98dc53`.
- Isolated checkout: `/private/tmp/cypher65-issue599.cAi2PE`.
- The original `test/609-telemetry-validation` checkout and its unowned changes
  were not edited, reset, staged or included in this delivery.

The MVP records destination-pool API observations for Parasite sessions, not
marketplace-reported delivery or independently measured accepted shares. Rental
identity, contract and exclusive worker association are operator declarations.
Unknown pool averaging intervals/measurement timestamps remain unknown. See
[`RENTAL_EVIDENCE.md`](../RENTAL_EVIDENCE.md) for architecture and limits.

## Real team work and review

- `issue599_frontend`: real frontend implementation, scoped Playwright coverage,
  synthetic-fixture desktop/mobile inspection and matched baseline diagnostics.
- `pr720_independent_review`: backend regression coverage, including real-SQLite
  atomic alert rollback/replay, oversized response and late reply cases.
- `security710_upstream_patch_audit`: independent review found two P2 issues:
  dedup committed before alert feed insertion, and unbounded upstream response
  ingestion. Both were fixed and independently rechecked as adequate; the agent
  reported no new #599 blocker before moving to its #710 audit.
- Root integrated the work, reviewed source scope and ran the full Python,
  affected E2E and local static/core validation.

This is engineering review evidence, not a GitHub approval and not permission
to bypass the repository's required independent review or CI.

## Validation ledger

| Check | Result | Boundary |
| --- | --- | --- |
| Full Python suite with coverage gate | **4001 passed, 3 skipped**, 85.57% coverage | Final source; isolated Python 3.13 runtime; authorized socket-capable execution |
| Focused evidence/polling/fetcher/snapshot tests | 113 passed; new evidence module 95.24% coverage | Real SQLite, synthetic upstream fixtures |
| Affected Playwright run | **32 passed, 2 skipped** | Actual application server/bootstrap; two legacy cases require live credentials |
| New evidence Playwright suite | 14/14 desktop/mobile passed | Also repeated on parity server after final UI/bundle synchronization |
| JS core | 1560 passing assertions | Real generated/source fragments, not copied implementation |
| Generated bundle drift + JS syntax | Passed | `node scripts/build_app_js.cjs --check`, `node --check static/app.js` |
| Monkeypatch-target guard | Passed | `python scripts/check-monkeypatch-targets.py` |
| Bandit / Flake8 / Black | Passed in the **CI source scope** | Bandit 1.9.4, Flake8 7.1.1, Black 25.1.0 |
| `git diff --check` | Passed | No whitespace errors |
| `npm run check:frontend` | **Failed** | Earlier run: one mobile skeleton-cleanup finding (40 leftovers); not reclassified as green |
| Final combined frontend rerun | **Not executed** | Automatic approval reviewer hit account usage limit; no workaround used |
| Exact-head GitHub Actions / approval | **Pending** | No PR existed at the checkpoint |

The full Python result includes existing warnings; it is not evidence that the
application is warning-free. An earlier sandbox-only run had socket-bind
`PermissionError` failures, and an earlier environment lacked Hypothesis. Those
runs are not green. Local dependency versions are not a substitute for the CI
runner's pinned environment.

The Black command matching CI is:

```sh
python -m black --check app.py helpers.py solo_mining.py services core axe_fleet routes agents
```

An additional out-of-gate `black --check ... tests` experiment reported existing
test-formatting drift (108 files). No unrelated test-formatting rewrite was
performed and that broader check is not green.

## Baseline QA findings — separate Issues

Matched baseline/candidate diagnostics did not reproduce the original pipeline
failure, but revealed two pre-existing defects:

1. [#721](https://github.com/0xjc65eth/cypher65-war-room/issues/721): the HTTP 500
   skeleton audit may report success with zero intercepted requests when a
   service worker controls the page. Blocking service workers exercised one
   failing request and cleanup in both builds. The audit needs an interception
   assertion; its current green result is not sufficient failure-path evidence.
2. [#722](https://github.com/0xjc65eth/cypher65-war-room/issues/722): activating
   Rentals at viewport 375px produces document width 465px in both builds due
   to the existing toolbar. The independent-evidence card fits the viewport.

No production pool readings or wallets were used for these UI comparisons.
Reduced-motion inspection found no evidence-card animation. Motion/accessibility
skills informed the skeleton, stale/error states, keyboard controls and scoped
entry transition; enterprise review informed the two security/reliability fixes.

## Evidence locations and integrity

These are local temporary artifacts, not uploaded CI artifacts. Preserve/copy
them before cleaning the temporary checkouts.

- `/private/tmp/cypher65-599-pytest-final.xml`
  SHA-256: `c36052f35ebf922f2f83c26440ea83280b8cdd9de150ae9b9c62ab479b6062eb`.
- `/private/tmp/cypher65-599-coverage-final.xml`
  SHA-256: `b69f7472c120b81fb0142c6b4fda37e0b2f3fdf8552adddd2d8929b329fad5b3`.
- `/private/tmp/cypher65-599-ui-baseline-comparison.md`.
- `/private/tmp/cypher65-599-evidence-desktop.png`.
- `/private/tmp/cypher65-599-evidence-mobile.png`.
- `e2e-report/index.html` and `test-results/` in the isolated checkout.

## Resume gates

1. Resolve #721 in its own Issue branch and independently validate the full
   frontend pipeline; do not suppress its failure or silently weaken guards.
2. Publish this branch as a draft PR when the approved network/approval path is
   available. Carry forward the limitations and this validation ledger.
3. Recheck current `master`, conflicts, rulesets and CI on the exact final PR
   head. The open mobile node-forge issue #710 may affect repository-wide CI.
4. Obtain the required independent GitHub approval. Only then consider the
   authorized squash merge. No merge/deploy was attempted at this checkpoint.

## Resumed frontend validation

After the current usage query returned `ordinaryUsageAllowed: true`, execution
resumed through the same approval path. A first attempt failed to start because
the shell lacked `python`; this environment failure is not a source-test result.
Activating `/private/tmp/cypher65-runtime599` resolved the executable boundary.

`source /private/tmp/cypher65-runtime599/bin/activate && npm run check:frontend`
then completed with exit 0 against implementation commit
`065cda9e2441d98a4225947948f564b0316e1547`: bundle drift, DOM/a11y/token/mobile
guards and their self-tests, JS core (1560 assertions), SW push, desktop/mobile
visual audit, axe (100/100 at both viewports), fetcher-unit and mutation guards
all passed. The earlier failed run remains recorded, not reclassified.

This rerun used the existing audit, whose HTTP 500 interception reliability
defect is still tracked in #721. A green command does not erase that limitation;
the strengthened guard must be independently tested and run in exact-head CI.
The baseline toolbar defect #722 is likewise independent of this passing boot
audit, which does not activate Rentals.
