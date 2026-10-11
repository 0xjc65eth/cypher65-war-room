# Issue #787 — retained Session Evidence validity

Issue: https://github.com/0xjc65eth/cypher65-war-room/issues/787

Base: `fd683ecda08d2d867bf9f02d708d7b040e49a725`; branch
`fix/787-evidence-validity`. Prior PR #793 connected the panel to the snapshot;
this follow-up completes numeric and temporal validity. No frontend production
fragment or generated bundle changes are needed.

## Contract

- A valid difficulty observation is a finite, positive float, excluding booleans,
  zero, negatives and unrepresentable integers. `valid_share_history` copies valid
  entries; the source timeline and cumulative counter remain intact. Evidence and
  the legacy live calculations use the same filter.
- Percentiles sort valid difficulty values. Trend compares means of the oldest
  and newest retained groups in input order. Scaling the positive mean prevents
  overflow when the sum exceeds float range but the mean remains representable.
- `session_share_count` / `session_shares` are cumulative counters.
  `sample_count` / `valid_modeled_shares` count valid retained observations.
  Evidence coverage uses the latter, keeping the existing threshold of 100.
  The live deque retains at most 120 observations; GOOD COVERAGE describes that
  retained evidence, not all historical shares or physical device health.
- A complete, positive, finite, nondecreasing timestamp sequence can establish
  the observed span. With a valid observation clock, no timestamp may be future.
  Age is calculated once and used for both the displayed age and classification.
- Missing, invalid, partial, reversed or future timestamps cannot establish
  age/window. A supplied or live fallback age is permitted only for nonempty
  history without timestamp fields. An empty history has unknown age/window.
  A fresh hint never overrides a stale retained timestamp or repairs an invalid
  sequence. Legacy rolling calculations also reject incoherent time windows.
- Unknown age prevents GOOD COVERAGE but does not assert STALE. With valid
  hashrates, no observations are INSUFFICIENT, unknown age is PARTIAL, known age
  above 3600 s is STALE, and at least 100 valid fresh observations give GOOD
  COVERAGE. Missing hashrates retain NO DATA / INSUFFICIENT semantics.
- Data gaps remain unknown. These labels are not block probability, progress,
  predictions, health guarantees or operational approvals.

## HTTP boundary

`/api/block-probability-lab/session-evidence` accepts GET/POST and
`/api/block-probability-lab/evidence-state` retains its GET alias. An absent body
uses live state; malformed JSON, non-object JSON or non-JSON supplied POST data
returns 400 JSON. Supplied history accepts a list of objects or comma-separated
numbers; malformed history structure returns 400. Invalid individual difficulty
values are excluded, consistently with live retained history.

Measurements reject booleans, negatives, non-finite values and float overflow.
Counts must be integral, preserving exact integers beyond 2**53. Decimal parsing
preserves fractional JSON values before validation: `100.0000000000000000001`
is rejected rather than rounded into a count. Negative underflow such as
`-1e-9999` is rejected before float conversion. Extreme JSON exponents are caught
as a controlled 400. Missing optional measurements remain unknown; a window must
be positive and finite. Supplied history never borrows the live session clock.

This is the Session Evidence boundary. Other historical probability endpoints
and unrelated legacy probability calculations are not redefined by this PR.

## Regression evidence

`tests/test_session_evidence_validity.py`: **145 new cases**, covering the public
Flask endpoint, pure evidence service and full `compute_proximity` entry point
with all worker inputs present. Cases include unknown fields, booleans, invalid
and huge difficulties, future/reversed/mixed clocks, stale/fresh consistency,
scaled averages, exact counts, fractional counts, extreme exponents, negative
underflow and preservation of the raw timeline.

The first 92-case batch was also run against the base implementation loaded in
memory: **48 FAIL / 44 PASS**. It demonstrates the old defects; it is not a
failure of the final change and the baseline source was never edited.

Focused suites: **207 PASS** in the QA service/API/proximity batch. An independent
/devil run passed **198 tests** with HTTP/TCP denied, followed by seven public
compute probes with byte-identical timeline state. No remaining CRITICAL, HIGH
or MEDIUM was demonstrated in the scoped delta.

`tests/e2e/session-evidence-validity.spec.js`: four desktop/mobile tests call the
real HTTP calculation and inject that returned evidence into a snapshot handled
by the actual page renderer. They verify future clocks stay unknown, valid
observations recover coverage, stale observations override a fresh hint and
unknown gaps remain an em dash. Together with existing probability WHAT-IF
tests: **10 PASS, 13.7 s**. The snapshot interception uses synthetic inputs; this
proves calculation-to-render integration, not physical ingestion or production.

Static gates: Black 25.1.0 (107 production files), CI-scope Flake8 and Bandit
`-ll`, monkeypatch guard and diff check PASS. JS core: **1694 PASS**; all 17 bundle
fragments are in sync. Full pytest/coverage: **4455 PASS, 2 SKIP, zero failures/errors; 85.79%, 192.95 s**. JUnit records 4457 cases with no failures/errors. Skips are the conditional private Gist integration and absent local Sentry SDK.

Local evidence logs: `/tmp/c65-787-validity-final.log`,
`/tmp/c65-787-validity-baseline.log`, `/tmp/c65-787-full.log`,
`/tmp/c65-787-full-tests.xml`, `/tmp/c65-787-full-coverage.xml`,
`/tmp/c65-787-e2e-final.log`, `/tmp/c65-787-js-core.log`,
`/tmp/c65-787-bundle.log`, `/tmp/c65-787-black-ci.log`,
`/tmp/c65-787-flake8-ci.log`, `/tmp/c65-787-bandit-ci.log`, and
`/tmp/c65-787-monkeypatch.log`. Temporary local logs are not remote CI artifacts.

## Acceptance and publication gates

The existing renderer plus this patch covers all five #787 criteria, with the final full-suite PASS recorded above; exact-head remote CI remains pending. /advisor recommends `Closes #787`
after the final validation passed. Subagent review is not GitHub approval.
No Issue is closed manually. No merge, deploy, physical command, production or
hardware validation was executed. Remote CI and independent GitHub review remain
publication gates and must be checked for every changed head/base.
