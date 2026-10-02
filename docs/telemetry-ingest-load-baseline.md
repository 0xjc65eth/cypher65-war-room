# LOAD-002 telemetry-ingest baseline

## Status and scope

This is a diagnostic harness for Issue #607, not a performance acceptance test. It sends 10,000 synthetic submissions per repeat through Flask's in-process test client, the real agent telemetry blueprint/handler, the real `DeviceRegistry`, and a temporary SQLite database. External sockets and the hardware connector are guarded. It does not model a network server, production WSGI workers, Render, a physical ASIC, or customer traffic. Process RSS is not measured.

The workload is 8,000 first submissions, 1,800 exact same-tenant replays (18%), 100 changed-payload conflicts (1%), and 100 identical key/sample probes under a second tenant (1%). It uses 50 serialized per-device streams with one client per worker. To test tenant isolation, each of the 50 documentation-only IPs has one synthetic device row in each of two tenants: 50 primary stream devices and 100 tenant-scoped device rows total. The harness queue is capped at two waiting submissions per stream; this is a harness constraint, not an observed production or WSGI backlog.

The database pragmas match `services.bootstrap.get_db`: WAL, `synchronous=NORMAL`, and a 3,000 ms busy timeout. Per-request latency is measured around `test_client.post` with `perf_counter_ns` and includes in-process dispatch, route/registry work, and SQLite; it excludes network transport. The report separately records producer admission delay, admitted-queue wait, active handler count, queued count, and admitted outstanding count. Percentiles use nearest-rank, in milliseconds.

Sample timestamps are synthetic epoch seconds derived from the current clock. Sequence 158 is intentionally received with an older sample timestamp, while sequence 159 remains newest. Assertions independently compare SQLite row-id receive order with sample-time chart order; they do not assume those orderings are interchangeable.

## Resumo executivo (pt-BR)

Foram concluídas três medições locais, sequenciais e independentes, cada uma com 10.000 submissões, 50 fluxos de devices e SQLite real. Todas reconciliaram 8.100 eventos persistidos, 1.800 replays idempotentes e 100 conflitos 409, sem tentativas de transporte externo. A latência p95 do `test_client.post` variou de 585,312 a 612,461 ms; o p99, de 929,030 a 1.034,274 ms. Esses números descrevem somente este harness in-process, com fila fechada e limitada pelo próprio teste: não medem WSGI, rede, Render, ASIC físico, memória nem capacidade de produção. Como não há SLO aprovado nem topologia representativa, a #607 continua aberta e a aceitação de desempenho continua bloqueada.

## Baseline evidence (English)

Three separate fresh Python processes ran `--runs 1 --max-wall-seconds 300` sequentially; each artifact therefore has `run_index=0`, and this was not one `--runs 3` process. No coverage, profiler, mocked route/database behavior, or code changes were present during measurement. Source commit: `b87acd15b92f8ad5aef66cc9b47ec41fc66329a7`; harness SHA-256: `b5b02da3f4b7854015d0b40ad4cf87c76bd4695c9726830fa1c8d9730999621a`. The measured pre-report version of this document had SHA-256 `d4266afc31bb56409b2c3d2d145c555fbc30994ce7b43f57c2e0e345dd918b5d`. This document/evidence commit is later than the measured source and was not measured; the three artifacts preserve their original source-input hashes and `git_dirty=false` provenance.

| Run | Full artifact (SHA-256) | Worker invocation UTC start → artifact finish | Measured workload (s) | Completed/s | `test_client.post` p50 / p95 / p99 (ms) | Offer→completion p95 / p99 (ms) |
| --- | --- | --- | ---: | ---: | --- | --- |
| 1 | [run-1.json](evidence/telemetry-ingest-607/run-1.json) · `084e43f758da3c71703c0b95306c3f0343c3497700febd2920aff1c08b1e8555` | 20:42:43.964982 → 20:43:52.775416 | 61.324858 | 163.066 | 62.612541 / 612.460917 / 1,034.274417 | 829.322250 / 1,240.512500 |
| 2 | [run-2.json](evidence/telemetry-ingest-607/run-2.json) · `b9ef59339dee7a037c7d0dad794d520a4bf0cf1639ffc6e3f9e184980c3c1d73` | 20:44:24.492461 → 20:45:32.669033 | 60.983490 | 163.979 | 61.679209 / 585.311625 / 929.029792 | 759.775458 / 1,123.714459 |
| 3 | [run-3.json](evidence/telemetry-ingest-607/run-3.json) · `5bd1ae75bc3f0ed4911b3b48466c97cb778e24a0cc7df6f8b0e62835363aea09` | 20:45:59.759160 → 20:47:06.416960 | 59.525601 | 167.995 | 57.064750 / 597.839708 / 1,019.550250 | 827.513042 / 1,252.133958 |

The UTC interval is the worker invocation start through artifact finish. It includes worker startup/setup and post-workload reconciliation and provenance hashing; the measured workload duration is narrower, from the first offered submission through the last completion. Those setup and reporting steps account for the roughly seven-second difference and are not included in request-latency samples.

All three completed `PASS` for harness integrity, with 10,000 submitted/admitted/sent/completed each: 8,000 tenant-A first submissions, 1,800 exact same-tenant replays, 100 changed-payload conflicts (409), and 100 same-IP/key probes accepted under tenant B. Persistence reconciled to 8,100 rows (8,000 tenant A + 100 tenant B); replay/conflict responses did not add rows. Every integrity invariant passed, `external_transport_attempts=0`, and the final tracked source tree was clean at the recorded commit.

Observed queue maxima were identical in every run: 100 queued waiting requests of the harness's configured 100 total slots, 50 active handlers, and 150 admitted outstanding requests. These values are the hardwired closed-loop harness limits (two waiting requests per stream plus one active per stream), not observed production backlog, a capacity estimate, or an approved backlog budget. Admission backpressure is part of this workload; completed/s is not an open-loop offered-arrival rate. The maximum across repeats of per-request p95 / p99 was 612.460917 / 1,034.274417 ms overall. The slowest operation-kind p95 / p99 observed were unique 522.420667 / 924.641834 ms, replay 863.523000 / 1,449.088750 ms, conflict 689.440250 / 909.588250 ms, and tenant probe 207.588959 / 595.049584 ms.

All four global raw timing arrays contain 10,000 full-precision integer nanosecond samples per run. The operation-kind payload retains all four phases for each operation: 8,000 unique, 1,800 replay, 100 conflict, and 100 tenant-probe samples per phase. An independent check recomputed all published summaries from these raw arrays using nearest-rank `sorted[ceil(p*n)-1]`, verified all samples finite/nonnegative, and confirmed the saved JSON is byte-identical to its full stdout capture; stderr was empty. Artifact SHA-256 values above match the original JSONs retained at `/private/tmp/cypher65-607-b87-baseline-run{1,2,3}.json`. The initial measurement did not modify or regenerate any timing data.

The host was Python 3.13.13, Darwin 25.5 arm64, SQLite 3.53.4, with 8 reported logical CPUs. The three runs did not overlap one another or another heavy benchmark; light repository work was active on the shared host, so this was not an isolated/dedicated performance runner and host scheduling/thermal variance remains uncontrolled. No process RSS was measured. The harness is Flask `test_client` → the real telemetry blueprint/handler → `DeviceRegistry` → isolated SQLite (WAL, `synchronous=NORMAL`, 3,000 ms busy timeout); it is not a network/production WSGI test and includes no Render, ASIC, provider, or customer traffic.

For future repeats, use one new invocation and one unique, non-existing output path per repeat; do not overwrite evidence or use coverage instrumentation as timing evidence:

```bash
for run in 1 2 3; do
  python scripts/measure_telemetry_ingest.py --runs 1 --max-wall-seconds 300 \
    --output "artifacts/telemetry-ingest-607/run-${run}.json"
done
```

The default artifact filename includes the first 12 characters of the harness SHA-256, not a Git revision. A completed worker report includes the actual commit and source-input hashes, UTC timestamps, runtime/SQLite/platform details, each repeat's integrity checks, latency percentiles, throughput, queue/active bounds, and exact request/persistence reconciliation. Full-precision timing samples are retained as compact, independently parseable JSON integer arrays inside the report. A successful integrity result does not mean latency or capacity passed an SLO.

`--max-wall-seconds` bounds worker execution; after that expires, the supervisor sends TERM to the isolated worker process group, waits at most one second, sends KILL, and uses the remaining two seconds of the three-second cleanup grace to reap it (or returns an explicit reap failure). Thus the worker execution plus cleanup allowance is at most `--max-wall-seconds + 3` seconds, recorded as `worker_wall_cap_with_cleanup_seconds` on supervisor failures. The parent performs no Git subprocess calls: the default artifact name uses the harness SHA-256, not a purported commit. On supervisor failure, schema version 2 records `source_commit: unavailable_after_supervisor_failure` and explicitly unknown Git dirty/status fields (`null`), never a clean result, while retaining direct source-file hashes. The failure artifact separately discloses that parent-side hashing, JSON serialization, and atomic writing happen after worker cleanup and are outside the worker cap; these synchronous local filesystem operations have no claimed hard wall-clock bound. Existing artifact paths are never replaced.

The fast named coverage check exercises a parameterized four-device/136-submission real route-and-SQLite burst, two-device admitted-work drain and already-expired-deadline cleanup, and a real hung-child termination path. It is contract/lifecycle coverage, not baseline timing evidence:

```bash
python -m coverage erase
python -m coverage run --include='scripts/measure_telemetry_ingest.py' \
  -m pytest tests/test_measure_telemetry_ingest_helpers.py -q
python -m coverage report -m
```

Coverage-instrumented execution must never be used as performance timing evidence.

## SLO decision and remaining acceptance

Approved latency, memory, and backlog SLO values are absent. Numerical targets must be selected by the product/service owner against a declared deployment topology, client population, telemetry mix, retention/database size, and resource envelope; this local baseline cannot supply those missing production assumptions. Any proposed targets are therefore unapproved and must remain outside the default performance gate until an owner records and approves the workload and thresholds.

Two unapproved latency decision options for the owner, using only the observed worst repeat, are:

1. A local diagnostic envelope with `T95 = W95` and `T99 = W99`, where `W95 = 612.460917 ms` and `W99 = 1,034.274417 ms` are the worst observed run-level `test_client.post` percentiles. These are measured reference values, not a production SLO or a gate.
2. A margin-based candidate with `T95 = α95 × W95` and `T99 = α99 × W99`, where owners choose and document `α95`/`α99` only after agreeing on representative deployment topology and load. No multiplier is approved by this report.

Neither option supplies a memory target or production backlog budget; the queue counts above are harness caps and must not be promoted into product SLOs.

For eventual acceptance, the owner must approve (1) p50/p95/p99 and error-rate budgets, (2) memory scope and limit, (3) queue/backlog and recovery limits, and (4) a representative deployed topology and repeat protocol. Then run reproducible diagnostics on that topology, review variance and resource saturation, add a separately approved CI or release gate, and retain an exact-head artifact. Until then, LOAD-002 performance acceptance remains blocked even if helper tests or a local diagnostic are successful.
