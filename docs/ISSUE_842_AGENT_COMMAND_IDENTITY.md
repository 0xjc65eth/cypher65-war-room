# Issue #842 — Agent identity and at-most-once delivery checkpoint

Date: 2026-10-21. Base: `9d4123e0e18aaef06c3b3aaf7fb7e71ea30249d2`.
Branch: `security/842-agent-command-identity`.
Issue: <https://github.com/0xjc65eth/cypher65-war-room/issues/842>.

## Proven risks and bounded changes

Previously an overdue pulled command could be returned again after60seconds.
The agent would dispatch it again even if the first effect happened and only
the ACK was lost. ACK idempotency did not make a hardware effect idempotent.
The physical envelope also carried only a locator, while the agent selected
the protocol from a cached IP occupant. DHCP reuse between pull and execution
was not covered by the otherwise existing identity/authorization protections.
These are conditional source-confirmed risks, not observed hardware incidents.

The patch keeps authorization, confirmation and the default physical-operation
policy. It adds:

- Pull protocol negotiation: only integer `command_protocol:1` consumers receive
  physical commands. Legacy consumers can still receive read-only probes.
- Envelope binding to the registry's canonical MAC and discovered protocol.
  A new local read-only identity probe precedes dispatch. Missing/mismatched
  identity, protocol or unsupported parameters prevents the mutable transport.
- The server includes the original UTC expiry. The agent captures one wall/
  monotonic clock pair before the pull and retains it for the whole batch.
  Expiry is checked before and after identity probing: network delay, earlier
  commands, and clock rollback during the batch cannot renew later intents.
  Server/agent clock synchronization at receipt remains an operational premise.
- Unknown device types remain telemetry-only. Protocol metadata is not flattened
  into a boolean command capability or rendered as an action.
- Atomic physical delivery is pending-only. An overdue pulled physical delivery
  becomes `unknown`, never silently requeued. Read-only probes retain retry.
  A late same-tenant ACK can update the observed acknowledgement without causing
  another dispatch; it is still not evidence of physical effect.

Alternative: a durable agent-side execution journal. The conservative server
policy is smaller and persists across both server and agent restarts. Its
trade-off is deliberate: a crash before dispatch can lose execution. The result
must remain unknown and require investigation/new explicit intent, not an
automatic replay. MAC matching is operational identity evidence, not
cryptographic attestation, and cannot eliminate every read/write race on an
unauthenticated firmware API.

## Rollout and rollback boundaries (not executed)

Keep physical commands disabled during upgrade. Upgrade backend and agent,
then refresh explicit registration to populate verified protocol metadata.
An old agent cannot use the new physical path; a new agent rejects the legacy
identity-less envelope. Do not re-enable commands just because telemetry works.
Existing Braiins/cgminer discovery lacks a MAC contract, so those paths correctly
remain blocked unless a separately verified identity is available. Fixture
dispatch success does not announce physical compatibility.

If rolling back, keep physical commands disabled. Do not reset unknown/pulled
rows to pending or replay historical operator intents. No schema migration,
production rollout or hardware action was performed by this checkpoint.

## Observed validation and limits

Python3.14.6; temporary SQLite, synthetic identities, mocked transports and
explicit loopback-only HTTP/TCP firmware servers. No pool/provider account,
real ASIC, credential, network scan or hardware dry-run was used.

| Check | Result |
| --- | --- |
| Regression-first identity/replay cases | Expected RED:29 failed before patch |
| Initial compatibility run | FAIL:13 tests +12 fixture errors; retained in compatibility-first.log |
| Root targeted source/contracts | PASS:166 tests |
| Root protocol/integration first loopback run | FAIL:1 test/35 pass; legacy pause fixture omitted the required envelope |
| Initial expanded related tests | PASS:304 tests; ResourceWarnings retained |
| Execution-expiry regression before follow-up | Expected RED:5 fail/29 pass; batch/oversized-expiry follow-up2 fail/34 pass |
| Final expanded related tests | PASS:311 tests,10.29 seconds; ResourceWarnings retained |
| Coverage of all three complete modules | FAIL:57.40%, below the unchanged80% requirement |
| Changed executable-line diagnostic |67/70=95.71%; not a replacement for the full coverage gate |
| Black / Flake8 / diff whitespace | PASS at root checkpoint; repeat on final reviewed tree |
| Generated JS drift / JS core | PASS; 1,694 JS assertions |
| Full repository suite/global coverage, web E2E | NOT RUN for this checkpoint |
| Physical matrix / human commands / native devices | NOT RUN; #386 remains externally gated |
| GitHub independent approval / merge / deploy | NOT PERFORMED |

Independent cross-review found the original per-command deadline could renew a
later batch command after clock rollback. The pre-pull clock pair and two-command
regression address that objection; a final read-only cross-review found no new
P0/P1 in this delta. The new monotonic dependency also exposed six old test clock
fixtures lacking that stdlib method; those fixtures now provide it explicitly.
No runtime fallback to a non-monotonic clock was introduced to silence tests.

The initial sandbox denied binding even `127.0.0.1`; it did not prove a source
defect. The repeat explicitly allowed only virtual-device local servers. Tests
were not rewritten to bypass identity checks; nominal fixtures now provide the
new envelope, while MAC-less cgminer discovery is expected to fail closed.
Formatting-only changes must remain separate from logic when reviewing.

## Exact reproduction and resume

Checkout: `/private/tmp/cypher65-agent-842.9zteQt/repo`.
Evidence: sibling `red.log`, `compatibility-first.log`,
`root-loopback-validation.log`, `root-final-validation.log`,
`root-coverage-gate.log`, and `coverage.json`.

```bash
/Users/juliocesar/cypher65-war-room/venv/bin/python -m pytest \
  tests/test_agent_protocol.py tests/integration/test_agent_fleet_pipeline.py \
  tests/test_agent_command_identity.py tests/test_agent_command_safety.py \
  tests/test_agent_api.py tests/test_scan_protocol_evidence.py \
  tests/test_device_identity_atomic.py tests/test_fleet_identity_recovery.py \
  tests/test_agent_identity_evidence.py tests/test_command_confirmation.py \
  tests/test_command_reconciliation.py \
  --cov=agent.agent --cov=axe_fleet.registry --cov=axe_fleet.routes \
  --cov-report=term --cov-fail-under=80 -q --disable-warnings
```

This command currently fails coverage despite311passing tests. Do not present
the earlier coverage-collection-only run with threshold0as a passing80% gate.
The full-module denominator includes extensive unrelated routes; retain that
distinction and run the complete required CI rather than lowering thresholds.

Next: complete independent cross-review, publish draft only, run exact-head CI
and full coverage, address findings, obtain GitHub approval, then separately
plan authorized physical validation. No issue closure or operational enablement.

## Exact-head CI follow-up (63c7449, then local correction)

The published draft PR #849 did not pass its first full CI. Two independent
Python jobs reported six failures (4489 passed, three skipped): five old clock
fixtures in discovery/main-loop tests lacked monotonic, and an aggregate contract
detected pause/resume/configure advertised for Bitaxe type without AxeOS firmware
evidence. The static gate also rejected registry formatting. These are actual
failures, not attributed to the environment or hidden behind the targeted suite.

Follow-up restores the conservative firmware prerequisite for optional AxeOS
capabilities and adds four explicit regressions. The five nominal clock cases
now supply real monotonic alongside their fake sleep; no runtime clock fallback
or assertion weakening was introduced. Focused rerun: **63 PASS**, 3.81s.
The exact CI formatter Black25.1.0 (Python3.13) passes all107 configured files;
the earlier local Black26.5.1 was not the same formatter. Flake8 and monkeypatch
target guard pass. CI gates/configuration were not changed.

A broader diagnostic including the separately excluded singular agent directory
also reports existing B310 on agent/agent.py urlopen. This is not new dispatch
code and is not claimed fixed; the exact configured CI scan remains the release
gate. Full-suite collection initially failed because local Hypothesis was absent.
An initial temporary CPython3.13 wheel could not load under3.14; the matching
CPython3.14 dependency was installed in /private/tmp only, not the user's venv.
The complete rerun is recorded separately; do not treat a collection error as PASS.

Final local follow-up: **4498 PASS /4 SKIPPED**, 644 warnings,206.91s.
The unchanged CI denominator (app/helpers/axe_fleet/services/core/admin_routes)
reached **85.71%**, passing the explicit80% gate. This does not erase the earlier
57.40% diagnostic across three complete modules or certify excluded code/native
effects. Logs: full-followup-ci-final.log and coverage-followup-ci-final.xml.
The exact configured Bandit scan also passed. Publish the follow-up and wait for
new exact-head remote CI; this local pass is not independent GitHub approval.
