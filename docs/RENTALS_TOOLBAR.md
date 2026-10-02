# Rentals toolbar layout

Issue: [#722](https://github.com/0xjc65eth/cypher65-war-room/issues/722)

## Contract

The Rentals header keeps Buy, Backtest, simple CSV, analysis CSV and Refresh
available at every supported viewport. At widths up to 768px, the title and
toolbar occupy separate flex rows and toolbar items wrap without clipping or
horizontal document scrolling. Mobile buttons have at least 44px touch targets.
Desktop keeps the existing single-row arrangement and action handlers.

Explicit Portuguese accessible names and a visible keyboard focus ring preserve
the DOM order across wrapped rows. This sizing-only change introduces no new
animation and leaves existing skeleton/loading and reduced-motion behavior
unchanged. The generated `static/app.js` does not change because no JavaScript
source changes are required.

## Regression test

`tests/e2e/rentals-toolbar.spec.js` opens the real sidebar and activates Rentals
with synthetic rental/CSV responses; it does not require provider credentials,
wallets or production readings. Explicit 375px and 1440px viewports run even in
the chromium-only CI selection. Assertions cover:

- Document width and every toolbar item remaining within the viewport.
- Mobile touch targets and desktop single-row layout.
- Accessible button names, Tab order and visible focus.
- Keyboard-triggered simple/analysis CSV downloads and a real refresh request.
- Completed skeleton loading and reduced-motion behavior.

Run against an isolated local app:

```bash
BASE_URL=http://127.0.0.1:8803 npx playwright test tests/e2e/rentals-toolbar.spec.js
```

The baseline at `c597304efb867716c0b8cf45ec72d1de8a98dc53` produced a 465px
document at a 375px viewport, with analysis export and refresh beyond the right
edge. Keep bounds checks after module activation: auditing only the initial
dashboard can miss this defect while Rentals is hidden.

## Historical pre-integration checkpoint (2026-10-02)

The following 12-case / 1,544-assertion record predates the integrated head
validated below. Its exact candidate execution SHA cannot be reconstructed from
the preserved local logs. It is historical context, not exact-head evidence for
`e154832` or the implementation SHA inspected by the earlier reviewer.

- Baseline: the mobile bounds test fails with `documentWidth=465` and
  `viewportWidth=375` at the exact baseline commit above.
- Candidate: 12 affected E2E cases passed across Chromium/mobile-chrome
  (8 new toolbar checks and 4 existing simple/analysis CSV export checks).
  The activated mobile document remains exactly 375px wide.
- `npm run check:frontend` passed against an isolated app at port 8803:
  1,544 JS core assertions, DOM/a11y/token/mobile-XSS guards and self-tests,
  visual audit, axe-core and fetcher-unit/mutation checks. The visual audit
  reported no overflow, truncation, page errors or stuck skeletons; axe-core
  reported zero violations and a 100/100 proxy score in both viewports.
- Bundle drift, syntax and `git diff --check` passed. No generated bundle
  replacement was needed. Mobile and desktop screenshots were visually
  inspected in addition to the automated bounds checks.

Enterprise self-review: Frontend/QA scope only; no changes to security,
auth, provider calls, financial logic or async state. The motion skill's
productivity restraint keeps this layout correction animation-free. No local
blocking finding was identified. Independent review, exact-head GitHub CI and
required approvals remain mandatory before merge; this checkpoint is not a
merge approval or a claim of production validation.

That historical general visual audit could allow a PWA service worker to
intercept its injected snapshot failure. Its green output did not establish
that the failure route was exercised. Issue #721's fix, merged through #725,
is present in the integrated head below, where interception was actually
observed. The toolbar E2E blocks service workers and directly activates Rentals.

## Integrated validation (2026-10-02)

Measured head: `e154832fb8d27740107b9a04666bcc89ed9ad73a`, containing master
`31e108a6d9ff1f57fdce9d9245954c9b2d0eb797` after #723, #724 and #725.
Safe fast-forward preserved the externally integrated commits. The local app
used isolated port 8804, fresh SQLite state and no operational credentials;
browser rental responses were synthetic. This documentation-only follow-up
does not claim that its new commit was remeasured.

- Actual `rentals-toolbar`, `rentals` and `rentals-evidence` Playwright specs:
  **40 passed, two skipped**, zero unexpected/flaky results, 106.074 seconds.
  The run began at `2026-10-02T20:18:29.292Z`. Both skipped cases require live
  provider credentials/history and remain unvalidated.
- Activated mobile width was 375/375px, with every control in bounds and at
  least 44px mobile targets; desktop was 1440/1440px with a single-row toolbar.
  Keyboard names/focus, both CSV downloads, refresh, skeleton completion and
  reduced-motion passed. Mobile and desktop screenshots were inspected.
- Rental/evidence/performance functional tests: **220 passed**. JS core:
  **1,560 assertions passed**. Bundle drift, syntax and diff checks passed;
  `static/src/` and generated `static/app.js` match the integrated master.
- Strict `npm run check:frontend` exited zero, including DOM/a11y/token/mobile-XSS
  guards, self-tests, visual audit, axe and fetcher-unit/mutation checks. The
  actual audit observed **one intercepted snapshot HTTP 500 and zero remaining
  skeletons per viewport**, at 1440×900 and 375×812. Its failure-path helper's
  nine tests passed; these results are not the historical unproven boot probe.
- Axe reported zero violations and button-name failures, with a 100/100 proxy
  score per viewport. The mobile result retained **one incomplete check**;
  this is not complete accessibility certification.

Evidence remains out of tree in
`/private/tmp/cypher65-722-e154-runtime.6RQSJU/`, including the independently
checked `VALIDATION.md`. These are local retained artifacts, not GitHub CI
results or production/customer-LAN validation. Normal boot's public market
reads are not claimed to be synthetic independent telemetry. Logs retain
environment warnings and intended negative-fixture messages.

| Artifact | SHA256 |
| --- | --- |
| `e2e-results.json` | `e7fbbe8f6585a01fd0f9dc1bf502b356e52e69db9014ed00c7aa2aa0e5e3cd09` |
| `rentals-functional.xml` | `2160ececad2435bd1b2b63d02d47bdd320d71c69e0f571f04c7a5f43422fd685` |
| `frontend.log` | `13d7f5343941586ce950adcb2ac59e2a0693042fb05040e2ff66e919e4fa726b` |
| Mobile `e2e-report/data/6d0da67a3cdeafca0f98b70a81e8f10453b21a78.png` | `c48652cd5ac3342b5c72505333e13e6ef8c6a50afaa0cb9c4de336b1c380679b` |
| Desktop `e2e-report/data/31bad99e1d3f5c59ca7c3d70a7815a697f0079c7.png` | `aa7f8543ec61a3fe1509a8db4bc00da013a86e42feaea6d6f63cf9b6a012f793` |

Independent engineering review of the retained validation does not constitute
the repository-required GitHub approval. Exact-current-head GitHub CI,
independent review and required approvals remain merge gates. Local preparation
did not rerun heavy tests or modify GitHub. Publication through a reviewable PR
does not approve or deploy code.

## Independent engineering review

A separate enterprise/Security reviewer inspected implementation commit
`fcc0a9f27a1cd8e20eb859d7623919d28a8134de` against `c597304` in read-only mode
and reported no actionable P0/P1/P2. Review covered selector scoping, desktop
layout, 44px mobile targets, names/focus, reduced-motion, activated-module test
coverage and synthetic-data limits. The reviewer did not repeat the browser
tests; that SHA records source inspection, not the unreconstructable historical
candidate execution SHA. This record is not the repository-required GitHub
approval.
