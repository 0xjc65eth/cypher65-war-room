# Issue #607 — telemetry diagnostic and validation checkpoint

Date: 2026-10-02. This is a partial delivery, **Refs #607**, not LOAD-002
performance acceptance. [Baseline report](../telemetry-ingest-load-baseline.md).

## Evidence boundaries

Three separate fresh processes measured the clean source
`b87acd15b92f8ad5aef66cc9b47ec41fc66329a7`, sequentially, without coverage or
mocked handlers. Each submitted 10,000 synthetic events through the real
Flask agent blueprint and SQLite registry, reconciling 8,100 persisted rows,
1,800 identical same-tenant replays and 100 changed-payload conflicts. The
100 second-tenant probes prove the declared tenant-isolation invariant.
External transport attempts were zero. Full raw arrays, source hashes and
outliers are retained in the three byte-preserved JSON artifacts.

Independent root/reviewer reconciliation verified artifact/stdout identity,
all nine measured source hashes, counts, nearest-rank summaries and maxima:
120,000 global phase values and 120,000 classified values are duplicate
views of 30,000 submissions, not additional requests. No data was rewritten
after measurement. Harness SHA256:
`b5b02da3f4b7854015d0b40ad4cf87c76bd4695c9726830fa1c8d9730999621a`.

This is closed-loop in-process test-client evidence, not production WSGI,
network, Render, physical ASIC, provider or customer traffic. Queue100,
active50 and outstanding150 are harness caps, not production capacity.
RSS was not measured; host scheduling/thermal variation was uncontrolled.
Approved latency, memory, backlog and deployed-topology SLOs remain absent.
The default CI gate does not promote these diagnostic percentiles into SLOs.

## First full regression — failure retained

On `65af4126a5f1c02d13b80031e5f19093ba76aa97`, root's full Python suite
finished with **4,083 passed, 2 failed, 3 skipped, 556 warnings**, 244.31s,
and 85.59% coverage. Exit1 is retained, not relabeled green.

- The repository monkeypatch guard could not correctly identify the helper's
  locally returned `routes` alias. `a15e89e` made the canonical
  `axe_fleet.routes` import explicit, asserted module identity and exercised
  the patched connector to prove interception. The guard itself and its
  tests were not weakened; no orphan-patch exception was added.
- The unchanged Stratum V2 local `wrong_type` test expected
  `unsupported_message` but observed `timeout` under its 50ms socket budget.
  Adapter, test and lab were unchanged from the base. Five authorized isolated
  repetitions passed, but do not establish the original failure's cause.
  Scheduling/listener delay is a hypothesis. Test reliability is separately
  tracked in [#729](https://github.com/0xjc65eth/cypher65-war-room/issues/729),
  without changing the production adapter or claiming real-pool acceptance.

Original local artifacts, not uploaded:

- `/private/tmp/cypher65-607-root-full-tests.xml`, SHA256
  `d7bae4659a1f5a48f5819ac5e531efc6e76e2c6b5350b726dceb4ba06527199f`.
- `/private/tmp/cypher65-607-root-full-coverage.xml`, SHA256
  `1eb94548d571d21f5630d1b66d8cd32d2dd371f66113c61eba12d546f108d867`.

## Fixed and integrated source validation

After the alias correction, root helper/guard/traceability selection passed
22 tests in5.53s on `a15e89e`. Agent helper/traceability validation passed
12 tests with 438/542 statements covered in the named harness, **80.81%**,
meeting the unchanged 80% threshold. The timing-document clarification
distinguishes `_run` metadata markers from first-offer to last-completion;
the finish marker precedes artifact serialization/write, not completion of I/O.

Normal master integration at
`4e2cc2e5827cfa19e16e78f56c229138557a0742` produced frozen source
`02e8376f0a6123bda1e4e2eb07c4a57b6b0b94c3`. Incoming master changes were
Rentals documentation only. Harness and raw artifacts remain byte-identical
to their measured versions; the helper and later documentation are not
mislabeled as the originally measured source.

On this frozen source, root reran the **full** Python suite: **4,085 passed,
3 skipped, 556 warnings**, 241.11s, **85.59%** aggregate coverage and exit0.
`--disable-warnings` suppressed detailed warning output, not test collection
or failures. This success does not prove the cause of the earlier Stratum
timeout or close its reliability follow-up. The unchanged skipped cases and
warnings are disclosed, not repaired by this harness change.

Successful local rerun artifacts, not uploaded:

- `/private/tmp/cypher65-607-root-refreeze-full-tests.xml`, SHA256
  `1f21a9d870280dc3f47ce72df90c334e5f0eb31041005c9370bab81b0504bdec`.
- `/private/tmp/cypher65-607-root-refreeze-full-coverage.xml`, SHA256
  `a2083ce16944c3d0b3229f0313ca7d761a0a1a5bb6917b1259dd3379840b519a`.

Changed-test Black, fatal Flake8, Bandit medium/high, compilation,
monkeypatch-target guard, diff and conventional commit checks passed.
Independent bounded source/documentation review found no P0/P1/P2 on
`02e8376f`; this later checkpoint is documentation-only, not another measured
or full-regression source revision.

## Release and acceptance gates

Publication is not merge approval. All eight protected exact-head checks,
current base, resolved review threads and an independent GitHub approval are
required before squash merge. No bypass, direct-master push, physical command,
paid operation or production deployment was performed by root.
Issue #607 remains open until its owner records representative topology and
approves latency/error, memory and backlog/recovery budgets, then validates
them with appropriate reproducible deployed evidence.
