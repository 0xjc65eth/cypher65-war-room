# Fleet Summary Scale Diagnostic — Issue #606

## Resumo executivo (PT-BR)

Este trabalho prepara um diagnóstico local e reproduzível do resumo Fleet com
100 e 500 dispositivos sintéticos gerenciados por agente. Exercita o registry
SQLite, a rota, a autenticação JWT e o isolamento por tenant reais, sem mineradores,
credenciais operacionais ou chamadas externas. Os resultados e opções de limites
abaixo são evidência para decisão, não um SLO aprovado. A aceitação `LOAD-001` e
a Issue #606 continuam bloqueadas até a aprovação explícita dos limites e do
ambiente de execução.

Foram preservadas três matrizes completas: o pior p95 foi 282,093 ms para 100
dispositivos e 1.126,159 ms para 500. Uma leitura de 500 dispositivos chegou a
5.180,054 ms; não foi descartada. Essa variabilidade impede extrapolar um SLO
de produção a partir deste ambiente local. As alocações Python e o pico RSS do processo
foram medidos separadamente e não representam memória total da frota.

## Status and scope

This is authorized diagnostic preparation, not implementation of the original
performance acceptance gate. No production source behavior, dependency, default
CI performance gate, operational device, or external system is changed.

The measured path is the production `axe_fleet.routes.fleet_summary` blueprint at
`GET /api/axe-fleet/summary`, authenticated with a transient synthetic viewer JWT
through the real tenant and RBAC decorators. A separate synthetic tenant holds one
200 TH/s sentinel; neither that device nor its sample may enter the measured
tenant's summary. An anonymous non-localhost client must receive HTTP 403.

The harness does not import `app.py` or start bootstrap/background workers. It
uses an in-process Flask test client, not a TCP server. Full-app middleware,
network/TLS, distributed contention, rate limiting, hardware polling, customer
LANs, providers, Render, and concurrent traffic are outside this measurement.

## Reproduction

Use the project's existing Python environment with its runtime dependencies. No
benchmark-specific dependency is required. Run each complete matrix sequentially
and avoid overlapping CPU/DB-intensive jobs. Choose a new output path per run;
the CLI refuses to overwrite evidence.

```bash
python scripts/measure_fleet_scale.py \
  --devices 100 500 --modes fresh stale mixed \
  --warmups 3 --samples 25 --memory-samples 3 \
  --output /absolute/new/path/run-1.json
```

Repeat the same command twice with new output names. `--warmups` accepts 0–20;
`--samples` 1–100; `--memory-samples` 1–10. The public CLI permits only 100/500
devices. Internal tiny workloads exist solely for fast diagnostic-contract tests.
Each case runs in a sequential disposable subprocess with its own discarded
temporary SQLite file. Credentials are generated per worker, inherited operational
environment variables are excluded, and `.env` loading is disabled.

## Workloads and invariants

| Mode | Registered devices | Current ONLINE | STALE | IDLE (measured zero) | OFFLINE (missing) | Current hash sum |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 100 fresh | 100 | 100 | 0 | 0 | 0 | 10,000 TH/s |
| 100 stale | 100 | 0 | 100 | 0 | 0 | 0 TH/s |
| 100 mixed | 100 | 25 | 25 | 25 | 25 | 2,500 TH/s |
| 500 fresh | 500 | 500 | 0 | 0 | 0 | 50,000 TH/s |
| 500 stale | 500 | 0 | 500 | 0 | 0 | 0 TH/s |
| 500 mixed | 500 | 125 | 125 | 125 | 125 | 12,500 TH/s |

Actual registration and validated ingestion methods seed one 100 TH/s sample per
fresh/stale device, zero per IDLE device, and no sample per missing device. Stale
samples are older than the current 900-second freshness horizon by 3,600 seconds;
their stored registry status deliberately remains ONLINE so the summary must
reconcile freshness rather than trust that cached status. Stale current hash is
zero and last-known hash remains 100 TH/s. Missing hash stays unavailable, not a
measured zero. The current summary's `offline` aggregate includes IDLE; this report
does not redefine that production schema.

Every request hard-fails malformed/count/hash/source/tenant/status/age results,
including Boolean or nonfinite numeric fields, unexpected agent latency probes,
duplicate identities, and lost latest-sample provenance. Ages are checked against
real request begin/end wall-clock timestamps. A logical SQLite dump hash must be
identical before and after requests. HTTP, DNS and socket connection/sendto
transport boundaries use fail-closed guards (the only measured-path mocks), and
a valid result requires zero attempted calls.
Fast tests also exercise replayed identical keys, conflicting altered payloads,
equal/late timestamps, cleanup, transport violations, and CLI failure modes.

## Measurement method

Latency uses the unmocked monotonic `time.perf_counter_ns`. Each sample includes
the buffered authenticated GET, SQLite registry reads and JSON serialization,
but excludes JSON decoding, invariant checking, and response cleanup. Warm-ups
are excluded. Raw milliseconds are retained. Percentiles use nearest rank,
`sorted[ceil(q*N)-1]`, without interpolation; at N=25, p99 equals the maximum.
This is sequential warm-cache latency, not throughput, concurrency, or an
independent hardware-mining benchmark. The implementation currently performs a
per-device latest-telemetry read after the batch registry read; this diagnostic
does not optimize or replace it.

After latency, separate requests run under `tracemalloc`. These include Python
JSON decoding and invariant checks and exclude fixture setup and SQLite/C memory.
The reported incremental peaks are Python-tracked allocations, not process RSS.
Their durations are intentionally discarded. `resource.getrusage(RUSAGE_SELF)`
reports worker-process lifetime peak RSS at capture, including imports, fixture
setup and both phases; macOS reports native bytes, Linux KiB converted to bytes.
It is neither current RSS nor total fleet memory. These two memory metrics must
not be added together. Disposable worker processes prevent earlier workloads
from contaminating each case's RSS high-water.

## Recorded environment, provenance and results

Measured source HEAD: `ed14e1865c4a87778dbb45feaff81dbd4e6c11c2`, based on
production revision `c597304efb867716c0b8cf45ec72d1de8a98dc53`. All three matrices
record `working_tree_dirty: false` and identical harness/production file hashes.
This is a frozen revision baseline, not a claim about a later GitHub/deployed
HEAD. The later documentation/evidence commit changes no measured input; the
JSON `source.git_head` remains the authoritative measured revision.

The original two unpublished commit messages failed the repository's 100-character
body/footer line-length gate. They were wrapped before publication, never by
changing source or raw measurements. The replacement source commit is
`d3953652c2b1fbcc0d7926512e96f442b702712b`; its tree is exactly the original
`a06e6684c05f42fbfcc082b4d8a8501e8a046b4a`. It was **not** the HEAD measured in
these artifacts. The original commit payload is retained in
[measured-source-commit.txt](evidence/fleet-scale-606/measured-source-commit.txt),
and the local pre-rewrite documentation/source history is backed up at
`refs/codex/checkpoints/606-before-commitlint`. No remote branch, tag or force-push
was used. Verify the original measured object without changing the evidence:

```bash
git hash-object -t commit docs/evidence/fleet-scale-606/measured-source-commit.txt
# ed14e1865c4a87778dbb45feaff81dbd4e6c11c2
```

Harness SHA256:
`1dfcf351d57a110070e75d1dda631c3a4769847570ff64964249ace683564a00`.
Each JSON also hashes `axe_fleet/registry.py`, `axe_fleet/routes.py`,
`axe_fleet/models.py`, `core/models/device.py`, `services/tenant.py`, and
`services/auth.py`. Those hashes were checked against the checkout after all
measurements. The per-case fixture dump SHA256 is expected to vary because
registration and observation timestamps are real.

Environment: macOS 26.5, arm64, eight reported logical CPUs; Python 3.13.13,
SQLite 3.53.4, Flask 3.1.3. The configured interpreter was
`/private/tmp/cypher65-runtime599/bin/python`. Every case has three discarded
warm-ups, 25 latency samples and three separate allocation samples. There are
18 cases and 450 retained latency samples in total. Runs were sequential; the
agent team reserved exclusive measurement windows, but host scheduling, thermal
state, CPU frequency and other desktop activity were not controlled or recorded.

| Run | UTC start–end (2026-10-02) | Raw artifact | SHA256 |
| --- | --- | --- | --- |
| 1 | 18:36:02.261832–18:36:43.131305 | [run-1.json](evidence/fleet-scale-606/run-1.json) | `67079e5d2bb4ee8685f87ae105bb44a024ba789fda89fb68b1113049af581fc6` |
| 2 | 18:36:54.326081–18:37:35.542881 | [run-2.json](evidence/fleet-scale-606/run-2.json) | `8d3602583720b2612b3f895f30b8933cab3eb641913dd79c85242ba2af026745` |
| 3 | 19:25:46.391693–19:27:01.765626 | [run-3.json](evidence/fleet-scale-606/run-3.json) | `ec20ee8f10d65224deb8924e0cedf777f41e7ea584478edbc892ad804afa6b66` |

The normal account-usage interruption between runs 2 and 3 was preserved; no
finished run was restarted. After authorized resumption, only the remaining
third matrix ran. All outputs exited zero on safety/data invariants, not on a
latency budget. Repository copies are byte-identical to the original out-of-tree
JSON artifacts. Raw percentile values were independently recomputed and matched
all reported statistics. No samples, outliers or workloads were discarded.

The following ranges describe separate per-run statistics, not percentiles
pooled across runs. Latency is milliseconds; memory is MiB (1,048,576 bytes).
Python peak means the maximum incremental tracked peak among the nine separate
allocation samples for each workload. RSS is each worker's lifetime high-water.

| Workload | p50 range (ms) | p95: run 1 / 2 / 3 (ms) | p99 range (ms) | Python incremental peak max (MiB) | Worker peak RSS range (MiB) |
| --- | ---: | --- | ---: | ---: | ---: |
| 100 fresh | 44.936–78.957 | 58.601 / 65.589 / 183.592 | 64.759–390.219 | 0.737 | 53.797–57.125 |
| 100 stale | 45.767–96.847 | 73.529 / 49.612 / 282.093 | 54.545–359.165 | 0.733 | 53.125–57.125 |
| 100 mixed | 48.417–98.811 | 71.475 / 71.328 / 143.449 | 72.826–351.618 | 0.703 | 56.906–57.406 |
| 500 fresh | 251.641–407.413 | 334.447 / 345.729 / 1126.159 | 370.331–5180.054 | 3.624 | 55.203–55.438 |
| 500 stale | 259.934–404.364 | 411.401 / 382.965 / 604.172 | 448.542–975.819 | 3.605 | 55.219–55.484 |
| 500 mixed | 251.068–398.055 | 378.130 / 271.361 / 601.407 | 303.341–941.252 | 3.461 | 55.188–55.656 |

The maximum incremental tracked allocation is 3,800,338 bytes; the maximum
worker RSS high-water is 60,194,816 bytes. The latter is not monotonic across
100/500-device workers and cannot be used as a per-device memory coefficient.
All 18 cases reconciled current/stale/missing/zero counts, tenant sample
provenance and hash sums, denied anonymous access, preserved logical storage,
and recorded zero attempted outbound transports.

Run 3's 500-fresh p99/max of 5,180.054 ms and p95 of 1,126.159 ms are materially
higher than runs 1/2, despite identical source hashes. This is observed
variability, not proof of a production regression, host contention or thermal
throttling. A controlled target-runner experiment is needed to explain it.
With N=25, p99 is only the largest sample, not a stable tail estimate.

## Unapproved SLO options

These are decision proposals only: neither is approved, enforced by the CLI,
or represented as a passing acceptance test. They apply only to the measured
in-process agent-managed workload and must be re-baselined on a named controlled
runner before adoption. They are not end-user/network latency commitments.

| Option | Proposed p95, 100 devices | Proposed p95, 500 devices | Trade-off |
| --- | ---: | ---: | --- |
| A — tighter regression signal | 400 ms | 1,500 ms | 1.25× the worst observed per-run p95, rounded up to 100 ms; more sensitive to this host's variability |
| B — diagnostic headroom | 600 ms | 2,300 ms | 2× the worst observed per-run p95, rounded up to 100 ms; less sensitive, may tolerate an unacceptable interactive experience |

For either option, propose separate local workload budgets of 2 MiB tracked
incremental Python peak at 100 devices and 8 MiB at 500 (twice each load's
observed maximum, rounded up to a whole MiB). A distinct 128 MiB **worker-process
peak RSS** budget rounds twice the overall observed 57.406 MiB maximum up to a
64 MiB boundary. This is an instrumented diagnostic-worker budget, not a full
production Flask-worker memory SLO; application middleware/background workers
were excluded. Do not sum it with the Python allocation budget.

A proposed approval-validation schedule is manual/on-demand on a pinned runner,
then a dedicated non-parallel scheduled job if the owner approves it. Use at
least five repeated matrices, ten warm-ups and 100 samples per case to inspect
variability; concurrency remains one unless separately specified and measured.
This schedule is a proposal, not an added automation or default CI gate. The
current three-run evidence and N=25 p99 cannot support a p99 commitment. No
diagnostic duration becomes an acceptance threshold, and this work does not
close #606 or implement `LOAD-001`.

Approval requires a named owner, deployment environment, sample/concurrency
policy, latency percentile/budget, separate memory metric/budget, and scheduling
decision. The final acceptance test must then fail the approved budget and run
in its declared environment; this diagnostic and its helper coverage do not
fulfil that requirement.

## Validation and acceptance boundary

The 73 focused diagnostic-contract tests passed with 99.23% coverage of
`scripts.measure_fleet_scale`; this is named harness coverage, not overall
repository coverage. Root independently ran these plus 13 existing telemetry
idempotency/freshness tests: 86 passed. The final diagnostic-plus-traceability
run passed 74 tests with the same 99.23% named harness coverage.

The independent reviewer's first test attempt used a global Python interpreter
without Flask: 67 passed and six failed due to that missing runtime dependency.
That environmental failure is retained, not relabelled as a code pass. The
corrected run using the configured runtime passed all 73 focused tests. No
dependency was installed or measurement changed to obtain that result.

Root's CI-scope Python regression run completed with 4,028 passed, three skipped
and 551 warnings (227.97 seconds, exit zero). Its reported aggregate coverage was
85.58%; that XML includes the diagnostic harness, so it is not labelled as a
product-only coverage number here. The warnings are retained, not described as
a warning-free suite. Root's full-run artifacts are
`/private/tmp/cypher65-606-root-full-tests.xml` and
`/private/tmp/cypher65-606-root-full-coverage.xml`. This local regression result
does not substitute for exact-head GitHub CI/review approval.

Black, fatal Flake8 (`E9,F63,F7,F82`),
Bandit medium/high (`-ll`), monkeypatch-target checks and whitespace checks passed.
Low Bandit subprocess/test-assert findings are informational, not suppressed as
medium/high approvals. An independent frozen-source review found no actionable
P0/P1/P2 issues. None of this is exact-head GitHub CI approval or performance
acceptance; the repository's existing CI/review/coverage gates remain mandatory.

```bash
python -m pytest tests/test_fleet_scale_measurement.py -q \
  --cov=scripts.measure_fleet_scale --cov-report=term-missing --cov-fail-under=80
```

The tests deliberately have no `covers("LOAD-001")` marker. `docs/TEST_STRATEGY.md`
retains `LOAD-001` as blocked and records the separately authorized diagnostic
preparation. An approved SLO, target environment and acceptance/scheduling policy
are still required before the original Issue can be completed.
