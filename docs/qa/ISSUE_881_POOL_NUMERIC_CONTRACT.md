# Pool numeric contract — Issue #881

## Scope and provenance

Base: `adbfcd7d120487c2b80558fc7e3599fc820034f5` (master, 2026-10-27).
Branch: `fix/881-pool-numeric-contract`. No merge/deploy is authorized.
The original checkout's unrelated dashboard changes were preserved.

The canonical implementation remains `services/pool_intelligence/stats.py`:
provider payload/injected fetcher → resolver → normalizer → `PoolWorkerStats`
→ `services.pool_detection.attach_pool_detection` → global/session snapshot
→ Flask JSON. The web pool strip consumes source/provider metadata from that
snapshot; it does not calculate these metrics. No additional mobile normalizer
or live provider API integration was added.

## Confirmed defect and contract

On the base revision, `parse_hashrate_to_hs("1e308T")` returns Infinity;
`normalize_ckpool_user` can emit both Infinity and NaN, causing
`json.dumps(result.to_dict(), allow_nan=False)` to raise ValueError.
The first regression run was RED: 53 failed / 8 passed. Keep that evidence;
later success does not rewrite the original result.

- Numeric metrics must be finite and nonnegative. Invalid/overflowing values
  are `None` (JSON null), not fabricated zero. Booleans are not measurements.
- Hashrate uses H/s. Existing supported numeric/SI string conversions remain.
- Explicit zero wins over conflicting legacy aliases. The first present,
  non-None canonical alias wins; an invalid canonical value is unavailable,
  not permission to silently select another value/window.
- Worker counters/hashrate are totals only with complete metric coverage;
  incomplete or overflowing sums are unavailable. Worker count is independent.
  Best difficulty/latest share remain the maximum of valid reported records.
- Numeric/SI best-difficulty display strings remain compatible; invalid text
  cannot advertise `nan`, `inf`, negative values or overflow as a record.
- `fields_found` is key provenance, not a claim that every value is valid.
- No timestamp/window/freshness is inferred or refreshed by normalization.
  This patch does not certify cross-worker averaging-window comparability.

## Verification and review

Environment: macOS, Python 3.14.6, Node 22.22.0; CI uses Python 3.13.
Existing read-only venv: pytest 9.1.1 / pytest-cov 7.1.0 / cryptography 50.0.0.
Hypothesis is supplied by the existing isolated test-deps directory, not a
runtime dependency. No dependency manifest or gate was changed.

- PASS: initial affected run, 156 tests / 93.44% stats coverage.
- PASS: expanded affected run, 164 tests / 94.98% stats coverage, including
  200 deterministic generated IEEE-754 examples and real Flask serialization.
- PASS: JS core 1,834 assertions; bundle drift (17 fragments), JS syntax,
  DOM/mobile guards, orphan monkeypatch guard, scoped Black/Flake8/Bandit.
- FAIL: initial full Python run: 5,148 passed / 1 failed / 4 skipped,
  86.38% coverage, 639 warnings, 109.72s. Failure was the unmodified
  `test_sample_coverage_distinguishes_zero_missing_invalid_and_unconfigured`:
  its synthetic completion is ~1.002s ahead of wall time, close to the real
  collector's one-second future-time rejection boundary. Isolated rerun passed.
  This is not recorded as an all-green suite; baseline proof and a separate
  test-clock repair are required. No timeout or collector guard is relaxed.
- NOT RUN locally: native mobile, signed iOS, physical ASIC and provider APIs.
  UI/motion changes: NOT APPLICABLE (backend-only patch).

Enterprise review: Backend/Data reviewed units, alias priority and unavailable
states; Security reviewed no new I/O/secrets/authorization changes; QA reviewed
regression-first examples, generated inputs and serialization. DevOps gates
remain unchanged. This self-review is not independent GitHub approval.

Raw logs are retained in `/private/tmp/cypher65-stabilize-20261027-4NywAr/`.
Final commit/check results are recorded in the campaign checkpoint and PR;
earlier commands must not be attributed to a later changed source revision.

## Primary-source research (consulted 2026-10-27)

| Source / applicable version | Concrete implication |
| --- | --- |
| [Python math.isfinite, 3.14](https://docs.python.org/3.14/library/math.html#math.isfinite) | Validate conversion and scaled output, not just input syntax. Local runtime is 3.14.6; this API also exists in CI's 3.13. |
| [Python JSON, 3.13](https://docs.python.org/3.13/library/json.html#infinite-and-nan-number-values) | Default encoder permits nonstandard numbers. Regression tests use strict serialization, not its permissive default. |
| [RFC 8259 section 6](https://www.rfc-editor.org/rfc/rfc8259#section-6) | Infinity/NaN are not JSON numbers; unavailable is null. |

## Next actions

Publish the scoped PR, inspect exact-head CI, preserve any independent failure,
then continue the separately tracked rental test-clock defect. #659/PR #715
still needs the provider-owned API schema; this patch does not close #659.
