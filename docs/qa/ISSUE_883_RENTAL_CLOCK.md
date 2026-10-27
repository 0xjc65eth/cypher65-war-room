# Rental evidence clock stabilization — Issue #883

Base: `adbfcd7d120487c2b80558fc7e3599fc820034f5`.
Branch: `fix/883-rental-evidence-clock`, independent of pool PR #882.

## Root cause and baseline

The sample-coverage test constructed a second sample at `created_at + 1.002s`
without advancing collector time. The real collector deliberately rejects
timestamps more than one second in the future. Test outcome depended on a few
milliseconds of runner overhead, not on the coverage semantics under test.

Initial campaign full run: 5,148 passed / 1 failed / 4 skipped, 86.38% coverage;
standalone rerun passed. On the unchanged master base, freezing process time
to 1000.0 deterministically reproduces the missing observation: expected end
1001.002, actual end 1000.002. This baseline is retained in
`/private/tmp/cypher65-stabilize-20261027-4NywAr/rental-clock-red-base.log`.

## Correction and acceptance

Only the affected test owns a module-local clock and advances it alongside
the synthetic collection times, matching other tests in this file. All original
coverage/zero/missing/unconfigured assertions remain. No sleeps, wider timeout,
production-code edits or collector guard changes.

Added boundary regressions prove exactly +1.000s is tolerated and +1.001s is
rejected without creating evidence. Existing real SQLite fixtures remain.

Validation commands (Python 3.14.6 locally; CI Python 3.13):

```bash
python -m pytest tests/test_rental_evidence.py -q
python scripts/check-monkeypatch-targets.py
git diff --check
```

The deterministic proof is also repeated after the correction with global
time frozen, so success cannot depend on real execution delay. Final tested
SHA, full-suite evidence and exact-head CI are recorded in the PR/campaign
checkpoint. A failing initial run is not relabeled green.

Enterprise review: QA verified identical assertions and explicit sample clocks;
Backend/Security verified production future-skew and stale guards unchanged.
Frontend/motion/native/hardware: NOT APPLICABLE. Self-review is not formal
independent GitHub approval. No merge, deploy or real upstream call authorized.
