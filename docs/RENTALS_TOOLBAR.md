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

## Verification checkpoint (2026-10-02)

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

The older general visual audit can allow a PWA service worker to intercept
its injected snapshot failure. Its green output does not establish that the
failure route was exercised; audit determinism is tracked independently in
Issue #721. The new toolbar E2E blocks service workers and directly activates
Rentals, so its bounds and action checks do not depend on that audit path.

## Independent engineering review

A separate enterprise/Security reviewer inspected implementation commit
`fcc0a9f27a1cd8e20eb859d7623919d28a8134de` against `c597304` in read-only mode
and reported no actionable P0/P1/P2. Review covered selector scoping, desktop
layout, 44px mobile targets, names/focus, reduced-motion, activated-module test
coverage and synthetic-data limits. The reviewer did not repeat the browser
tests. This record is not the repository-required GitHub approval.
