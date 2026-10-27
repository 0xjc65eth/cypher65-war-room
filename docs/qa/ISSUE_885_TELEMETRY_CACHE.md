# Telemetry cache isolation — Issue #885

Base: `adbfcd7d120487c2b80558fc7e3599fc820034f5`.
Branch: `fix/885-isolated-telemetry-cache`; independent of #882/#884.

## Confirmed reproduction and bounded scope

Two DataManager objects on different temporary SQLite files, with identical
device/metric names, returned the first database's rows through class-level
caches. A successful write also left matching reads stale for the 300s TTL.
Colon-separated cache keys could alias different device/metric pairs.

Only tests currently consume these query methods; no production HTTP caller
was found. This is a proven module-level database boundary defect, **not** a
claim of a demonstrated live cross-tenant exploit. No tenant API/schema or
hardware path was changed.

## Correction

Keep the existing canonical DataManager and its lock. Caches are instance-owned
with tuple keys; lookup, SQLite read, cache publication and post-commit
invalidation share that lock. Successful writes invalidate all matching query
windows. Failed writes keep the last cached observation. Unrelated metrics
retain their cache. FIFO retention is capped at 256 queries per manager; this
is a cache policy, not an approved performance SLO. The 300s TTL remains.

Within-instance cached-object reuse is intentionally preserved. External writes
through another manager/process remain subject to TTL; no cross-process cache
coherence is claimed. SQL writes still report success only after commit;
InfluxDB remains optional and unchanged.

## Test evidence / enterprise review

- RED baseline: all five new isolation/freshness/concurrency/bound tests fail.
- First implementation run: FAIL, cache initialization accidentally attached to
  CircuitBreaker rather than DataManager; corrected before commit/publication.
- Second run: 12 assertions pass but module coverage 74.51% FAILS the unchanged
  80% threshold. Additional meaningful TTL, failed-write, wrapper, unrelated
  metric and existing circuit-cooldown regressions bring the scoped run to
  **17 passed / 83.66% module coverage**. No coverage exclusion was added.
- Concurrent regression reconciles 33 real SQLite rows after 32 writer/reader
  operations through eight threads. This is not the #607 10k-event load SLO.
- PASS: orphan-target guard, scoped Flake8/Bandit, diff check. Formatting uses
  CI's Black 25.1.0 (local default 26.5.1 would reformat an unrelated SQL string).

Backend reviewed locking and commit-before-invalidate; Security reviewed scope
and key boundaries; QA reviewed real SQLite, row counts and failure cases.
Self-review is not formal independent approval. UI/motion/physical/native
tests: NOT APPLICABLE. No external services, dependency installs or DB migration.

Final tested commit/full-suite/CI evidence lives in the PR/campaign checkpoint.
Raw logs: `/private/tmp/cypher65-stabilize-20261027-4NywAr/cache-*.log`.
No merge/deploy authorized.
