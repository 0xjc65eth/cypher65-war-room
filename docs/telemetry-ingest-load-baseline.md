# LOAD-002 telemetry-ingest baseline

## Status and scope

This is a diagnostic harness for Issue #607, not a performance acceptance test. It sends 10,000 synthetic submissions per repeat through Flask's in-process test client, the real agent telemetry blueprint/handler, the real `DeviceRegistry`, and a temporary SQLite database. External sockets and the hardware connector are guarded. It does not model a network server, production WSGI workers, Render, a physical ASIC, or customer traffic. Process RSS is not measured.

The workload is 8,000 first submissions, 1,800 exact same-tenant replays (18%), 100 changed-payload conflicts (1%), and 100 identical key/sample probes under a second tenant (1%). It uses 50 serialized per-device streams with one client per worker. To test tenant isolation, each of the 50 documentation-only IPs has one synthetic device row in each of two tenants: 50 primary stream devices and 100 tenant-scoped device rows total. The harness queue is capped at two waiting submissions per stream; this is a harness constraint, not an observed production or WSGI backlog.

The database pragmas match `services.bootstrap.get_db`: WAL, `synchronous=NORMAL`, and a 3,000 ms busy timeout. Per-request latency is measured around `test_client.post` with `perf_counter_ns` and includes in-process dispatch, route/registry work, and SQLite; it excludes network transport. The report separately records producer admission delay, admitted-queue wait, active handler count, queued count, and admitted outstanding count. Percentiles use nearest-rank, in milliseconds.

Sample timestamps are synthetic epoch seconds derived from the current clock. Sequence 158 is intentionally received with an older sample timestamp, while sequence 159 remains newest. Assertions independently compare SQLite row-id receive order with sample-time chart order; they do not assume those orderings are interchangeable.

## Baseline evidence

No 10,000-submission measurement has yet been run for this change. The first and subsequent repeated measurements must be made in a quiet, non-overlapping window with the #606 fleet-scale diagnostic. Store the complete JSON artifact from the command-line output and include its SHA-256 in review notes; refuse to overwrite an existing artifact. Do not use measurements made with coverage instrumentation as timing evidence.

Suggested command (explicit diagnostic invocation only):

```bash
python scripts/measure_telemetry_ingest.py --runs 3 \
  --output artifacts/load-002-baseline-c597304.json
```

The resulting report includes commit and harness hashes, UTC timestamps, runtime/SQLite/platform details, each repeat's integrity checks, latency percentiles, throughput, queue/active bounds, and the exact request/persistence reconciliation. A successful integrity result does not mean latency or capacity passed an SLO.

The fast named coverage check exercises a parameterized two-device/20-submission real route-and-SQLite run plus admitted-work drain and already-expired-deadline cleanup. It is contract/lifecycle coverage, not baseline timing evidence:

```bash
python -m coverage erase
python -m coverage run --include='scripts/measure_telemetry_ingest.py' \
  -m pytest tests/test_measure_telemetry_ingest_helpers.py -q
python -m coverage report -m
```

Coverage-instrumented execution must never be used as performance timing evidence.

## SLO decision and remaining acceptance

Approved latency, memory, and backlog SLO values are absent. Numerical targets must be selected by the product/service owner against a declared deployment topology, client population, telemetry mix, retention/database size, and resource envelope; this local baseline cannot supply those missing production assumptions. Any proposed targets are therefore unapproved and must remain outside the default performance gate until an owner records and approves the workload and thresholds.

For eventual acceptance, the owner must approve (1) p50/p95/p99 and error-rate budgets, (2) memory scope and limit, (3) queue/backlog and recovery limits, and (4) a representative deployed topology and repeat protocol. Then run reproducible diagnostics on that topology, review variance and resource saturation, add a separately approved CI or release gate, and retain an exact-head artifact. Until then, LOAD-002 performance acceptance remains blocked even if helper tests or a local diagnostic are successful.
