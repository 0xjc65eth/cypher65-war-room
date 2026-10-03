# Issue #735 — Fleet trusted telemetry batch

Issue: [#735](https://github.com/0xjc65eth/cypher65-war-room/issues/735).
Base: `39fa95b5833ea0f61c8f578df1cabb388d8a61e4`.
Date: 2026-10-03. Frozen implementation source:
`f1ec49981f0fbcbdea60182ac9386d1d249caf28`.
Verification status: **focused checks pass; full suite failed as recorded below**.

## Confirmed baseline and scope

Both `/api/axe-fleet/summary` and `/api/axe-fleet/health` request
`list_devices(tenant_id=..., with_telemetry=True)`. The registry already loads
the latest trusted measurement in a tenant-scoped batch. The old routes then
call `get_recent_telemetry` once per device: summary limits this read to one
row; health limits it to 50. These additional reads are redundant and use
`ts DESC` without the batch's explicit arrival tie-breaker.

Consequently, a newer empty heartbeat can hide the last measurement in
summary; more than 50 newer heartbeat rows can hide it in health. Equal sample
timestamps can also select a different payload. These are source findings;
the regression-first results below must establish the synthetic behavior.

## Required contract

The implementation reuses the attached `device['telemetry']` payload, without
a second per-device query or a fallback query when no measurement exists.
The registry remains responsible for selecting the largest sample timestamp,
with descending SQLite `rowid` as the arrival tie-breaker. Invalid JSON,
non-object payloads and payloads without a non-null `hashrate_hs` do not erase
the last measured sample. A literal zero is still a trusted measurement.

This does not introduce stronger numeric validation than the existing trust
predicate. Current/last-known H/s, timestamp, age, unavailable values, device
status policy, response schemas, supported-command arrays, tenant quarantine,
RBAC and the no-TCP guard for agent-managed devices must remain intact.
Ingestion ordering, idempotency and stale/future thresholds are out of scope.

## Evidence limits

Real SQLite statement counting establishes the number of telemetry reads,
not elapsed-time, memory or production capacity. The unchanged batch still
loads telemetry history for the tenant; constant query count is not constant
total query work. No benchmark outlier cause is claimed.

All new scenarios use synthetic devices in disposable local databases and
authenticated Flask requests. No ASIC, pool, wallet, production service,
payment or operator command is required. This task does not close #606/#607,
approve their SLOs, or establish real hardware integration.

## Validation ledger

Root froze the query-count regression on
`52fd0f32e6ff84e32f0465249e98492fd22cbc7b`, with production byte-identical to
the base. The targeted command ran 16 cases: **12 failed, four passed**, exit 1,
1.00 seconds. Both endpoints performed 2/101/501 telemetry SELECTs for
1/100/500 devices, for measured and missing-data fixtures alike. Empty fleets
performed one read. Requests succeeded, aggregates matched and the transport
guard recorded no attempts; the failures were the intended query bound.

Two preceding test harness runs failed because bulk device fixtures omitted
required IP/timestamp columns. They are retained as fixture errors, not as
demonstrations of the production defect. Their sources were `6af4fe89189035ed216af1bd595bf71e9415d9c6`
and `8f62c4cc40751df076f71aececf1d04db41edf45`; each had 12 failures and four
passes. No production changes were made between these runs.

Local root artifacts: `/private/tmp/cypher65-735-root-validation.ZGm16g/`.

| Artifact | SHA256 |
| --- | --- |
| `query-red.xml` (fixture error) | `a4748b9a7d9eb36bbf911234559bf12abf29672106b91882d9afc8c5279d46e6` |
| `query-regression-red.xml` (fixture error) | `07f5fc318c2a04889159ab18b7288bab4b55bfab88f3ddd186d51ef77af3570f` |
| `query-contract-red.xml` (intended regression) | `1b2c0c882329f5b8a2e771dc349dff50ae5a2bf801a783b49300648002a2c4f1` |

Command: clean environment (`env -i`, `PYTHON_DOTENV_DISABLED=1`), existing
Python 3.13 runtime, `python -m pytest tests/test_fleet_trusted_batch_queries.py
-q --tb=short --disable-warnings --junitxml=.../query-contract-red.xml`.
Full matching logs are retained alongside the JUnit reports.

## Frozen implementation verification

Root independently reran the two new contract modules, freshness tests and
the entire existing Axe routes integration module on `f1ec499`: **96 passed**,
1.06 seconds, exit 0. The backend agent also observed four targeted Agent API
regressions pass; those are agent tool-output results, not a separate retained
root JUnit. Independent SecurityOps/Architect review found no P0/P1/P2 code
finding. Earlier review gaps were fixed: standalone tie and late-arrival
checks precede heartbeat/noise tails; actual rejected agent input preserves
last-good measurements and quarantine advice; exact supported-command sets
and restored application test configuration are asserted.

Root full Python regression on this same source: **4113 passed, five failed,
three skipped, 573 warnings**, 199.98 seconds, exit 1. The unchanged production
coverage scope reached **85.60%** against the unchanged 80% gate. This run is
**not green**. Four failures were `FileNotFoundError: node` because root's
clean PATH omitted the installed Node directory. A separate approved rerun
with Node on PATH passed the complete harness/timezone modules: **20 passed**,
3.34 seconds. An intermediate default-sandbox rerun failed four local-bind
cases; that failure is retained, not hidden or counted as production evidence.

The fifth failure is the unchanged lender identity property in
`tests/test_numeric_properties.py`: the fixed absolute tolerance is smaller
than one ULP for a large synthetic input. The exact input reproduces on the
unchanged master-equivalent baseline, documented in separate [#741](https://github.com/0xjc65eth/cypher65-war-room/issues/741).
No financial helper or numeric property has been changed by #735. A successful
focused rerun does not relabel this full run as successful. The repository-wide
gate remains unresolved until this independent test-oracle issue is addressed.

Existing production Black, fatal-code Flake8 and medium/high Bandit CI scopes
passed locally, exit 0. The backend agent's broader advisory Flake8 scan also
reported pre-existing unused-import/line-length warnings; the actual blocking
CI selection is `.flake8`, not a claim of all-style-rule conformance.

FrontendGod ran fresh light checks on `f1ec499`: **1560 JS core checks**, 17
fragment drift gate, syntax, orphan patch guard, diff and five-commit commitlint
passed. Their initial non-login shell lacked Node (exit 127); retained logs and
successful existing-Node reruns are listed in
`/private/tmp/cypher65-735-light-f1ec499.6zFkXY/VALIDATION.md`, SHA256
`a91adc69e564857590de7c1d7e0e3a1d411b4b50b943b2dd2be3d65c2554b270`.
Static assets and templates are byte-identical to master; no UI code changed.

| Root artifact | SHA256 |
| --- | --- |
| `focused-f1ec.xml` | `e7a009e68bc7bab21623b36a2cabefaafd852747e0d2db71bb660d8a43af2fc5` |
| `full-tests.xml` (failed) | `6690553521550697c1b26f6e19346a247be5de729fcb5da89bc7e2190b74b28d` |
| `full-coverage.xml` | `3c97b7be0ede1fdfda502a35ac75790e892b7cb9faedc09d4d48e860f2ae9674` |
| `path-approved-rerun.xml` | `4b96f05cb874b97757439e280c189329848acd56a676f22710fb7abb4ea4f54d` |
| `black.log` | `159c67ada9d49c6ab3f1ac801fbedf684180960b0f914231510cd858721b95d6` |
| `bandit.log` | `0c7406409d88a5213524967dd1bebd92a8b8586794b9c2714c7ad7f034d067fc` |
| `flake8.log` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

## Local UI consumer smoke

On the same frozen implementation source, the existing
`operational-overview.spec.js` passed **six desktop/mobile tests**, 7.2 seconds,
exit 0. The app was imported without starting background workers; the server
used `127.0.0.1:8779` and a disposable database with dotenv disabled. Fleet
summary/health, registry, templates and JS were real. Unrelated market fetch,
opportunity scan and subnet suggestions were explicit empty QA fixtures.
The spec's critical/offline and 503 branches intercept responses as documented
in the existing spec; they do not establish hardware or provider behavior.
The outbound guard recorded **zero attempts** in this final scoped run. The
owned server was stopped and exited 0; no listener was left running.

Preparation failures were retained separately: first the guard blocked the
listener constructor's local getaddrinfo, so six browser cases could not
connect. An earlier listener-ready run passed six tests but its teardown guard
reported 14 blocked unrelated market/subnet transport attempts; it is **not**
a clean transport-guard pass. Another preparation attempt used a nonexistent
mock target and failed before serving. The final harness uses the actual app
opportunity scanner and only stubs dependencies outside the Fleet contract.
These are QA harness errors, not source fixes or permission bypasses.

Final local artifacts (same root artifact directory above):

- `ui-playwright-scoped.log`, SHA256
  `40e5f651ab6788f606247987feb655348681061e0452d7426cc4584290e1648f`.
- `ui-server-scoped.log`, SHA256
  `e16ebe06657f17c016f14fe88ee920bd45ad693208c4e8c9d2becb3e887184e7`.
- Temporary `serve_ui_contract.py`, SHA256
  `3b80bf89617621887ba0d9f18fb6c22fd04fa48919555f33cadeaee09f54f9a1`.

Pending: resolution of the independent #741 oracle and exact-head remote CI.
Merge requires the actual
independent GitHub approval and current-head CI; a subagent review is not that
approval. No merge or deploy has been performed by this task.
