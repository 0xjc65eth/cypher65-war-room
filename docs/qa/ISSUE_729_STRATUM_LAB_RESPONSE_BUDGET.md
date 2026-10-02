# Issue #729 — Stratum V2 lab response budget

Issue: [#729](https://github.com/0xjc65eth/cypher65-war-room/issues/729).
Date: 2026-10-02. Base: `4e2cc2e5827cfa19e16e78f56c229138557a0742`.
Final test source validated: `61c7f3b5840b82e1a3c0da4c454e43f5db0d9a77`.
This subsequent checkpoint is documentation-only, not a new measured source.

## Original failure and limits

Root's full regression on `65af4126a5f1c02d13b80031e5f19093ba76aa97`
reported **4083 passed, two failed, three skipped, 556 warnings**, exit 1,
244.31 seconds and 85.59% aggregate coverage. Its CLI output remains in Codex
execution session 76906; no shell log is claimed. The retained JUnit has
4088 tests, two failures and 244.120 seconds.

One failure was
`test_virtual_lab_failures_are_bounded_and_sanitized[wrong_type-4096-unsupported_message]`:
the expected `unsupported_message` was instead `timeout`. The other failure
was the monkeypatch-target guard, handled separately; this Issue does not
claim to resolve that failure or make the original full run green.

**Fact:** the original adapter and Fleet classification cases used the same
50 ms socket timeout as the intentional silence case. The synthetic lab uses
a separate handler thread. **Hypothesis:** handler scheduling or response
arrival beyond 50 ms could explain the mismatch, but the original cause was
not instrumented and remains unproven. Five isolated passes do not establish
absence of a load-sensitive failure, nor does a later green full suite prove
the original cause. The failing test's JUnit duration of
0.616 seconds includes fixture cleanup and is not a probe latency measurement.

## Scoped correction

- Non-silent exact classification cases in the adapter and Fleet suites use
  an explicit **1.0 second test-only per-socket-operation response budget**,
  not a whole-probe wall-clock cap. Intentional silence still uses **0.05
  seconds** per socket operation and must return exactly `timeout`.
- The local fixture accepts a finite response delay from 0 to 0.5 seconds;
  invalid/boolean/nonfinite values, including enormous positive/negative
  integers, fail before server creation. Range validation precedes float
  conversion to avoid `OverflowError`. Silence does not take this response delay.
- New cases delay a valid success frame and a valid unsupported-message frame
  by 100 ms, then require their exact protocol/capability/failure outcomes and
  one request. Real `perf_counter` elapsed time is measured around the probe
  inside the fixture context, excluding shutdown/join, and must include the
  configured delay. No clock is mocked and no latency SLO is introduced.
- Existing error sanitization remains required. No retry, skip, production
  adapter, destination policy, operational timeout or dependency changes.

All network I/O is synthetic `127.0.0.1` loopback through the existing redirect
socket fixture. The pinned public-shaped address is not contacted. This is
local contract/reliability evidence, not real pool, Noise, hardware, credential
or production integration acceptance.

## Regression-first and focused verification

At the base above plus the retained `regression-first.patch`, the new delayed
cases used the historical 50 ms budget and **both failed with `timeout`**:
two failed, 17 deselected, exit 1, 1.46 seconds. This demonstrates the synthetic
failure mechanism, not the unobserved cause of the earlier full-suite failure.

On initial frozen source `b78a1b50557a663f7f11f4073b9f6b6f71d48737`, adapter
plus Fleet V2 suites passed **42 tests**, exit 0, 6.80 seconds. After fixture
validation hardening, final frozen source `61c7f3b` passed **44 tests**, no
failures or skips, exit 0, 7.60 seconds. The named adapter + lab line-coverage
scope passed the unchanged 80% threshold at **88.93%** (lab 96.15%, unchanged
production adapter 85.87%). This focused scope is not the repository-wide gate.

Local command (configured Python 3.13.13 / pytest 9.1.1, `.env` disabled):

```bash
env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin PYTHON_DOTENV_DISABLED=1 \
  /private/tmp/cypher65-runtime599/bin/python -m pytest \
  tests/test_stratum_v2_adapter.py tests/test_fleet_stratum_v2_pipeline.py \
  -q --tb=short \
  --junitxml=/private/tmp/cypher65-729-response-budget.k4b7Kq/final-focused.xml \
  --cov=tests.virtual_pool.stratum_v2_lab --cov=services.pool_intelligence.stratum_v2 \
  --cov-report=term-missing \
  --cov-report=xml:/private/tmp/cypher65-729-response-budget.k4b7Kq/final-focused-coverage.xml \
  --cov-fail-under=80
```

Black on all three changed test files, explicit fatal Flake8 (`F821,F541,E9`),
Bandit medium/high, monkeypatch-target guard, diff and commitlint passed.
Initial Black checking identified new test-line wrapping; formatting corrected
it before the frozen source run. The patch changes only tests and this document;
production files remain byte-identical to the base. No full suite, benchmark,
application server, GitHub write, push, merge or deploy was run during local
preparation. Independent review and root's later full regression/exact-head CI
are still required; this checkpoint is not GitHub approval.

## Retained local artifacts

These artifacts are out of tree, not uploaded CI reports. The original JUnit
and coverage paths are respectively `/private/tmp/cypher65-607-root-full-tests.xml`
and `/private/tmp/cypher65-607-root-full-coverage.xml`. New files below are in
`/private/tmp/cypher65-729-response-budget.k4b7Kq/`.

| Artifact | SHA256 |
| --- | --- |
| Original full JUnit | `d7bae4659a1f5a48f5819ac5e531efc6e76e2c6b5350b726dceb4ba06527199f` |
| Original full coverage | `1eb94548d571d21f5630d1b66d8cd32d2dd371f66113c61eba12d546f108d867` |
| `regression-first.patch` | `fddfa729423638e286e5047d364fc8d0f81710323ca7899571e4faec8ae43d2e` |
| `regression-first.log` | `43838bd8f9c628ae2d94b181e2ff798274281f9a53dfa37330ca17c5f1080068` |
| `regression-first.xml` | `cb2e0b5aaba51826e0b399bad4be64b89eab027d53dc233027723cba299971b0` |
| `frozen-focused.log` | `b7d5cf4d7fdc7e9cec27993282fb3479c1e46f9f10b1d1be8daa4f25ad16948d` |
| `frozen-focused.xml` | `9b9faac830da5b1171f09cd639241658ddabe0868a730742de2ff966ad43e03c` |
| `frozen-focused-coverage.xml` | `0fbcf92fac3b6dd2e7e300cdd9b2e309a184aa06502030ac73a341da933bb7c9` |
| `final-focused.log` | `09068c0b9b13dd0bf3e33183c991839200acc5f756d041206c5884b188503a7d` |
| `final-focused.xml` | `e350bc8074034fd7e36d26cbf3c3ebb1adbce6948072a27800514cae74494baa` |
| `final-focused-coverage.xml` | `a16fbdd3b940c56407ae737dab64203000d5542120d3e6240607dd515ca5061c` |
