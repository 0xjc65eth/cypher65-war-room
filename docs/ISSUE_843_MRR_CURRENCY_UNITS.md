# Issue #843 — MRR currency, unit and Bitcoin-model boundaries

Base: master 9d4123e. Branch: fix/843-mrr-currency-units. Draft only.

## Contract and correction

The [official MRR API v2 contract](https://www.miningrigrentals.com/apidocv2)
(accessed 2026-10-21) separates payment currency, hashrate scale and rig algorithm.
Its examples do not authorize treating every paid amount as BTC or applying
Bitcoin economics to arbitrary algorithms. No account or authenticated call was
used. Historical zero averages can also be pruned data, not proven zero delivery;
this change does not certify provider retention or refund entitlement.

The original normalization put price.paid into price_paid_btc regardless of
currency and retained unknown hashrate units as raw TH/s. The detail endpoint
and browser independently multiplied that payment by 1e8. Clearing only the
backend field was insufficient: the browser could recompute a null cost.

Changes:

- Preserve original finite, nonnegative amount/currency, provider provenance and
  an explicitly unknown observation timestamp. Only explicit BTC becomes sats.
- Convert declared hash/kH/MH/GH/TH/PH/EH scales; unknown/negative/nonfinite/bool
  values remain unavailable. EH/s is 1e6 TH/s.
- Require raw provider rig.type=sha256 for the Bitcoin work/cost/yield model.
  Unsupported, absent and unverified aliases are not silently assumed Bitcoin.
  Original raw detail/rig fields and contractual timestamps are preserved.
- Guard analysis, refunds, P/L, history, alerts, provider rankings and portfolio
  calculations. Explicit non-BTC currency overrides a contradictory legacy BTC
  field. Mixed summaries qualify partial BTC coverage and use only priced work
  in the cost denominator; unknown spend is not zero.
- Preserve nulls through the real generated browser bundle; show original
  currencies and unavailable economics. Do not resurrect server null cost.

Compatibility: pre-existing typed price_paid_btc rows without a currency key
retain their BTC contract. This cannot repair already-persisted mislabeled rows
without original evidence; no speculative data migration or historical FX rate
was invented. Missing raw algorithm now intentionally blocks derived Bitcoin
economics. The old nominal fixture using an unverified sha256ab alias now uses
the official sha256 example; unsupported aliases have explicit negative tests.

Motion scope: numeric/text qualification only, no new animation or transition.
Existing skeleton/reduced-motion behavior is preserved. Synthetic browser tests
use reduced motion; no visual or physical compatibility certification is claimed.

## Regression and gate checkpoint

Evidence directory: /private/tmp/cypher65-issue843.OIL3mC/.

- Initial currency/unit red: 29 failures /4 passes.
- Adversarial algorithm and unknown-history-spend red: 6 failures /40 passes.
- Service plus existing rental suite after follow-up: 220 PASS, 3.05s.
- Canonical-source JS regression is wired into the existing JS-core CI entry:
  1694 existing assertions plus currency/unit/detail guards PASS.
- New Playwright desktop + mobile: 10 PASS, 25.9s. All provider APIs synthetic;
  no purchase/payout/physical transport dispatched.
- Initial expanded regression: 544 PASS, but whole rental module coverage
  **63.66% FAIL** against80. This is not relabeled a passing coverage gate.
- Black25.1.0 (the CI formatter), Flake8, Bandit on changed source, generated
  bundle drift, JS syntax and diff whitespace PASS.
- Full repository exact-denominator coverage and independent GitHub review are
  required separately. No merge, deploy, issue closure or hardware validation.

Full local follow-up completed: **4504 PASS /4 SKIPPED**,642 warnings,232.28s.
The unchanged CI denominator reached **85.74% PASS** against80; the complete
rental module reached88% in this run. Warnings remain visible. This supersedes
the limited regression's coverage result as the full-suite observation; it does
not erase the earlier failure or replace remote exact-head CI/independent review.
Logs: full-final-global.log and coverage-final-global.xml. Temporary compatible
Hypothesis was supplied outside the user's venv to run the complete suite.

Final compatibility challenge: the new MRR-only algorithm prerequisite initially
also hid the existing normalized Braiins contract economics in the shared view.
A real-source regression reproduced it; the guard is now scoped to MRR while an
explicit Braiins response retains its existing provider-average/P-L contract.
JS-core1694 plus the new regression pass. The unchanged existing Braiins detail
browser test passes2/2 (desktop/mobile) after the fix. The new currency/unit spec
is added to the existing CI E2E command; no previous test or gate was removed.
Changed executable Python-line diagnostic:69/70,98.57%; this is additional
information, not a substitute for the whole-suite85.74% coverage gate.

A wider legacy rentals.spec run also encountered a live/unconfigured-provider CTA
failure. That diagnostic began before the shared-view fix and is not presented
as an all-green final browser suite. Its cause/baseline comparison must be kept
separate from the synthetic currency and Braiins regressions above.

On final source the new spec passed10/10 again (1.6m). Its final log SHA256 is
fac0d272296432108201fdc4660d0fc949b471d0558a7a5005779815e286c010.
The old broad run ended15PASS/3FAIL/2SKIP: one confirmed pre-fix Braiins guard
regression (fixed and2/2green), plus two CTA failures during navigation.
The same CTA test on exact master9d4123e passed2/2,25.9s; this does not prove a
deterministic baseline defect. Keep it recorded as an unresolved intermittent
navigation observation, not silently removed or declared fixed.

## Independent security / numeric follow-up

A fresh independent reviewer found a new P1 in the draft: original provider
currency was formatted as text but interpolated without escaping into rental
card HTML. Numeric character entities could survive uppercasing in an event
handler. The existing detail table already escaped text; the card did not.
The card sink now applies the canonical escapeHtml and the bundle is rebuilt.
The reviewer authored an original canonical-renderer regression, using real
30-core-escape.js and46-rentals.js; RED1FAIL/2PASS, then GREEN3PASS. No payload
was executed, browser account accessed or production exposure claimed.

The XSS regression runs in a child process inside the existing JS-core gate so
its node:test callbacks cannot be skipped by that gate's explicit process.exit.
Current JS-core1695 assertions plus3renderer tests PASS. A literal SVG-currency
browser case confirms external currency stays text without injecting an element.
Current browser matrix: **12 PASS**,11.2s, desktop/mobile, synthetic APIs only.

Root also reproduced unrepresentable hashrate-duration work yielding Infinity
and false zero cost. Explicit finite work/unit-cost helpers now guard MRR
detail/history/analysis/rankings/alerts/portfolio and browser fallback. Positive
underflow is not a measured zero; measured zero hashrate remains zero. Derived
percent overflow is unavailable. Regression-first numeric matrix:5FAIL/47PASS
before fix; expanded rental plus numeric suite226PASS after fix. Full-suite
follow-up is recorded separately; no blanket all-arithmetic certification.

Complete Python follow-up: **4510 PASS /4 SKIP**,642warnings,147.62s;
configured CI coverage **85.76% PASS** against80. Logs full-security-final.log
(SHA25632e95671aef5e102b942a42dbc06f33c6a6870750dccf233e6ef731da9569707)
and coverage-security-final.xml
(SHA25612caa2dddae9fe10567810339e589a1b79151ffaaf0c42cf0df25cd0d790582b).
Exact CI Black/Flake8/Bandit, monkeypatch guard, DOM guards, bundle and JS syntax
also pass. The independent reviewer found no remaining P0/P1 in that delta;
this is not a GitHub approval or a waiver of new exact-head CI.

The same review identified a lower-severity short Braiins-series boundary:
duration is rounded for display, but valid backend delivered work is not.
Root reproduced the hidden-cost case before correction. The shared view now
uses finite normalized Braiins work instead of discarding it when displayed
duration rounds to zero. Canonical-fragment regression passes; no claim about
actual provider sampling cadence or real short contracts is made. MRR raw work
continues to use strict finite duration/product guards.

Public metadata is not a quote: no FX, fee, duration, capacity or executable
profitability guarantee was added. No new external call or background process.

## Reproduction

```sh
python -m pytest tests/test_mrr_currency_units.py tests/test_rental_performance.py -q
node tests/test_app_js_core.js
node scripts/build_app_js.cjs --check
node --check static/app.js
PORT=18843 CI=false bash run-e2e.sh --file=rentals-currency-units.spec.js
git diff --check
```

For full coverage, use the unchanged CI denominator:

```sh
python -m pytest tests/ -q --tb=short \
  --cov=app --cov=helpers --cov=axe_fleet --cov=services --cov=core \
  --cov=routes.admin_routes --cov-report=term --cov-fail-under=80
```

## Evidence SHA-256

```text
2a0e55f6fd539a4f6961d6c7c35b1f042e922264a15d918d8267e10f61765763  red.log
6e6eed7274b678c7165c7fde4282e53cd4c98a0eadbb9466c9681be421d6a798  red-adversarial-model-history.log
a84e42281e9545ebbb1f210036daba78bf5ccdc1e11f1f7c44ecc9a082499341  e2e-currency-units.log
aa4d31826d4c85952fd90ff59d59756da93dc8238597c6ccc75d8c027e548f31  js-core-final.log
4ef5de12b6138b6751233c492c72b4d187042f3e68009d181fcb48581f67d9db  full-final-global.log
843d4c684e4341a1737a4a73cf551f1404965c275cee30a2001eb443edb56e08  coverage-final-global.xml
```
