# Issue #841 — Block Probability Lab numerical evidence

Date: 2026-10-21. Baseline: `9d4123e0e18aaef06c3b3aaf7fb7e71ea30249d2`.
Issue: <https://github.com/0xjc65eth/cypher65-war-room/issues/841>.

## Proven problem and bounded decision

The fixed 10% target applied two different inversions: first a per-second
binomial expression, then a division by `window / 600`. It did not invert the
forward Poisson model. For a 600-second window, it returned approximately
`0.000175585` of network hashrate. The same forward model yields approximately
`0.00017557` probability, not the advertised `0.10` probability.

The correct inversion for this model is:

```text
lambda = (user_hashrate_Hs / network_hashrate_Hs) * (window_s / 600)
P(at least one) = -expm1(-lambda)
required_ratio = -log1p(-target_probability) * 600 / window_s
```

For a 600-second window and a 10% target, `required_ratio` is approximately
`0.1053605156578263`. Feeding that ratio back into the forward model returns
10%. A target of 100% has no finite solution and is rejected, not advertised
as attainable.

Decision: reuse the existing target solver, preserve public identifiers, and
make status fields explicit. Use `expm1`/`log1p` for small probabilities. Keep
unrepresentable intervals/ratios unknown and unrepresentable event counts
`NO_DATA`; never report an overflow as a successful zero probability. Reject
boolean, non-finite and unconvertible numeric inputs. Preserve representable
event counts when an intermediate ratio overflows or underflows by using a
logarithmic fallback.

Alternative considered: replace the entire probability stack or adopt a new
numerical dependency. Rejected for this milestone: the defect is local, the
stdlib is sufficient, and changing unrelated models would enlarge risk.

Main objection: a mathematically valid required ratio can exceed one for a
short window. This is a fixed-input scenario, not evidence of physically
available capacity, feasibility, profitability, or authorization to purchase
hashrate. No execution paths were added.

## Scope and compatibility

- Changed only `services/block_probability_lab.py`, focused tests, and this
  document. No routes, source integrations, UI, dependencies, settings,
  wallets, hardware, purchases, or production databases were changed.
- The model is the existing Bitcoin-oriented 600-second constant-rate
  Poisson approximation. No claim is made for another network, a changing
  difficulty, or future market conditions. `D * 2^32` is a conventional work
  approximation; consensus evaluates the actual target threshold.
- Invalid windows no longer silently become successful 600/86400-second
  defaults. Valid callers retain their existing values and identifiers.
- Additive status fields distinguish `SOLVED`, `NO_DATA`,
  `INSUFFICIENT_INPUTS`, `INVALID_TARGET`, and `SOLVER_FAILED`.
- `share_of_network_required_str` retains its identifier but now displays a
  dimensionless multiplier (`0.105361×`), never H/s. A search of repository
  UI consumers found no current consumer of this field or the fixed-target
  route. Unknown external consumers must respect status and nullable values;
  an unavailable result must not be treated as a solved zero.
- `/api/block-probability-lab/target-solver` still lacks network inputs and
  returns `INSUFFICIENT_INPUTS`. This patch deliberately does not invent a
  network sample or enable that unfinished route.
- Legacy models in `services/probability.py`, `helpers.py`, and
  `solo_mining.py` remain outside this patch; the application has not been
  claimed to have one unified probability implementation.
- Best-share outputs remain historical descriptions, not progress or a
  change in the next-hash odds. Numeric ratios that cannot be represented
  are unavailable, not Infinity.
- Generic timestamp/schema validation and rental currency/unit/retention
  contracts remain separate
  findings. This is not a universal input-schema or product-certification
  claim. At the initial checkpoint only the `P(X >= 1)` tail was in scope;
  the bounded pure count-tail follow-up below adds multi-count validation
  without introducing a new HTTP or UI contract.

## Evidence and validation

Local checkout: `/private/tmp/cypher65-issue841.HHRgS4/repo`.
Branch: `fix/841-block-lab-probability`.
Runtime: existing Python 3.14.6 environment; no dependency installation.
All tests use pure functions, temporary test storage, or an isolated Flask
blueprint. No provider/account/hardware interaction establishes support.

| Gate | Observed result |
| --- | --- |
| Baseline existing math/market/rental tests | PASS: 356 tests, 3.88 seconds |
| First strict regression run before implementation | Expected RED: 35 failed, 16 passed, 0.34 seconds |
| Secondary extreme-value regression run before follow-up fix | Expected RED: 6 failed, 54 passed, 0.13 seconds |
| Focused module, evidence, and hermetic HTTP tests | PASS: 251 tests, 3.73 seconds |
| Scoped module coverage with `--cov-fail-under=80` | PASS: 95.65%, 230 statements, 10 missed |
| Final expanded regression suites with coverage | PASS: 585 tests, 66 warnings, 4.47 seconds; scoped coverage 95.65% |
| Flake8 changed production module | PASS |
| Black changed module and both test files | PASS |
| `git diff --check` | PASS |
| Bandit | NOT RUN: selected runtime has no `bandit` module; nothing installed |
| Full repository suite, global coverage, JS/E2E, exact-head CI | NOT RUN for this local checkpoint |
| Independent approval, merge, deploy | NOT PERFORMED; no authorization inferred |

Local logs outside the patch: `red-strict-tails.log`,
`red-secondary-extremes.log`, `green-api-coverage.log`,
`red-ratio-unit.log`, `regression-expanded.log`,
`final-regression-coverage.log`, and `coverage.xml` under
`/private/tmp/cypher65-issue841.HHRgS4/`.

The final expanded run emitted database `ResourceWarning` messages while
coverage inspected modules. A subsequent same-command existing-suite comparison
passed on both baseline (507 tests, 114 warnings) and patch (507 tests, 113
warnings). Warning counts alone do not attribute every warning to its cause. Pure
Block Lab and isolated blueprint tests do not establish database lifecycle
correctness for the broader rental suites.

Focused coverage command:

```bash
/Users/juliocesar/cypher65-war-room/venv/bin/python -m pytest \
  tests/test_block_probability_lab_numeric.py \
  tests/test_block_probability_lab_routes_numeric.py \
  tests/test_block_probability_lab.py \
  tests/test_session_evidence.py tests/test_session_evidence_validity.py \
  --cov=services.block_probability_lab --cov-report=term-missing \
  --cov-fail-under=80 -q --disable-warnings
```

Root independent source review and a repeat of the focused command passed:
252 tests in 0.83 seconds, 95.65% scoped coverage, with Black, Flake8 and
`git diff --check` also passing. This is an internal independent review,
not a GitHub approval or release authorization. Broader audit evidence and
the unrelated mobile gates must remain explicit in the draft PR.

Next checkpoint: publish draft PR, required full-repository and exact-head CI
gates, and independent GitHub approval. No merge or deployment is part of this
milestone. At that checkpoint multi-count tails, generic metadata validation
and live input availability were not delivered. The follow-up below addresses
the first item only; generic metadata and live input availability are not
silently represented as delivered.

## Count-tail completion follow-up (2026-10-23)

Base: `02901d7c095e378ec0b2daab005d127cc9be00e1`. The inversion and
single-event input hardening above are already present on this base. The
remaining count-tail acceptance criterion is implemented as the pure typed
function `poisson_block_count_tail(mean, minimum_blocks)`, where `mean` is
the dimensionless expected event count, not H/s or seconds.

### Explicit new pure-function contract

- `mean`: finite nonnegative Python `int`/`float`, excluding booleans and
  numeric strings. `minimum_blocks`: integer from 0 through 10,000,
  excluding booleans. Zero mean is a valid mathematical distribution.
- The stable three-field result contains `minimum_blocks`,
  `probability_at_least` (a decimal probability or `None`), and `status`.
- `SOLVED` means a representable computed probability. Count zero is exactly
  1; positive count with zero mean is exactly 0. Binary64 rounding to 1 for
  large means is not certainty or an operational guarantee.
- `INVALID_INPUT` rejects invalid mean/count domains without coercion or
  nonfinite JSON. Invalid counts are returned as `None`, not echoed.
- `UNSUPPORTED_COUNT` rejects counts above 10,000, with no unbounded loop or
  oversized integer echoed. `UNDERFLOW` returns `None` when a mathematically
  positive tail rounds below binary64 range, never a solved zero.
- `NUMERIC_UNAVAILABLE` is the explicit defensive iteration-budget result;
  no partially summed probability is returned as solved.

The existing Block Lab forward model calls this primitive at count one and
retains its exact response keys, existing statuses and `expm1` result. No
`minimum_blocks` query parameter, new route, model default, dependency,
purchase or hardware path is added. `/target-solver` still has no network
inputs and accurately returns `INSUFFICIENT_INPUTS`; this does not claim that
route has become operational. Generic timestamp/schema validation remains
outside this mathematical follow-up.

### Numerical method and bounded work

For `lambda < k`, sum the upper tail directly, starting with a log-scaled
mass at `k`. The positive recurrence has decreasing ratios; a geometric
remainder bound controls termination at binary64 resolution. For
`lambda >= k`, sum the finite lower CDF backwards from `k-1` and complement
it. In that branch the requested upper tail is not tiny, avoiding catastrophic
subtraction. `lgamma` avoids factorial overflow; scaling the sum before the
final `exp` preserves representable subnormal tails even if the seed mass
would underflow. Count one uses `-expm1(-lambda)` directly.

Each call uses at most 10,000 recurrence terms; work never scales with the
mean. Inputs near `lambda=k=10,000`, finite mean `1e308`, representable
subnormal probabilities and explicit underflow are covered. No normal
approximation or new runtime dependency is introduced.

The test oracle independently sums the finite CDF from zero using Python
Decimal at 850-digit precision before taking the complement, rather than
mirroring production's log-scaled, mode-directed algorithm. Selected oracle
vectors use a relative tolerance of `5e-11`, including both sides of the
branch boundary; this is a test tolerance, not a universal accuracy warranty.
Additional regressions verify monotonicity, adjacent-tail probability mass,
strict input domains, bounded work, JSON safety, and unchanged forward keys.

### Follow-up evidence

Checkout: `/private/tmp/cypher65-841-complete.U5xDob/repo`.
Branch: `fix/841-multiblock-numerics-complete`. Existing Python 3.14.6
runtime, no dependency installation, no external or physical I/O.

- Baseline existing Block Lab tests: **PASS**, 101 tests, 0.49 seconds.
- Regression-first new count-tail tests: expected **RED**, 53 failures,
  0.28 seconds, before the primitive existed.
- First implementation: **PASS**, 53 tests, 1.01 seconds.
- Expanded coverage/static/review results are recorded in the adjacent
  handoff checkpoint and logs before publication. No remote CI or GitHub
  approval is implied by local tests. No merge/deploy is authorized.

## Primary references

Accessed 2026-10-21; documentation is not a live integration or physical
hardware test.

- [Python `math.expm1` and `math.log1p`](https://docs.python.org/3/library/math.html#math.expm1):
  stdlib functions avoiding loss of precision near zero. The documentation
  URL is mutable; the validation runtime above is recorded separately.
- [Bitcoin block header and target specification](https://developer.bitcoin.org/reference/block_chain.html):
  proof of work evaluates the header hash against the encoded target;
  this model does not replace consensus validation.
