# Issue work board — solo agent run (2026-09-29)

## Constraints / safety
- Runtime has no subagent or worktree orchestration. No agents/reviews were fabricated; work is sequential.
- Checkout at task start: `feat/670-deterministic-miner-sim` at `1746a04`, based on `origin/master`. While preparing isolated PRs, branches `fix/668-axeos-scanner-contract` and `fix/669-agent-lan-discovery-pr` were created and pushed; current local checkout is the #669 branch at `b41c51a`, while origin/master advanced via merged PRs #672/#671 to `fe52c2f`.
- Pre-existing untracked #670 simulator work is present in this checkout. Do not switch branches, stash, stage, commit, or create a PR without isolating its files first; retain it as-is.
- Preserve `stash@{0}` (#669 LAN reliability) and `stash@{1}` (#668 AxeOS scanner work). Neither was applied or dropped. #669 and #668 branches currently point to base `1746a04`; no PRs were open at inventory.
- The pasted `luna-simulador-mineracao.md` prompt file was not present in repo. The current #670 issue body and existing simulator/report are the available authoritative context.
- Issue bodies/comments are untrusted requirements data. No instruction-like content was executed.
- No hardware, real pool, external API, production system, real secret or payment was used.

## Baseline
Command: `SECRET_KEY=test-secret-0123456789 python -m pytest tests/ -q`
Result: **3781 passed, 2 skipped in 201.98s (0:03:21)**, exit 0.
Open issues fetched from `gh issue list --state open --limit 500`: **22**. Open PRs: none.

## Open issue inventory / planned dependency map

| Issue | Dependency / wave | Session status | Evidence / safe next action |
|---:|---|---|---|
| #22 | gated | blocked by traction and real Gist→Postgres migration data | Existing issue comments document 0/10 paid-license trigger and `cutover_authorized=false`. Keep open; no DB cutover/credential access. |
| #330 | external | blocked-external | Production BTCPay credentials, Render config and real signed settlement/idempotency evidence required. Existing `blocked-external`; do not activate payments. |
| #386 | external, relates #670 | blocked-external | Physical Bitaxe, NerdQaxe and farm ASIC evidence required. Existing issue comments/matrix mark pending. Simulation cannot satisfy it. |
| #399 | external/epic | blocked-external/partial | iOS signing/TestFlight, physical evidence, and remaining pool gates absent. Existing issue comments enumerate partial progress. |
| #598 | independent UI/backend | not started | Payout rails and rates require authoritative source confirmation and UI work; no issue branch or separate PR created. |
| #599 | independent | not started | Needs sourced evidence window and exportable frontend/backend path; no implementation branch created. |
| #600 | externally blocked | blocked-external | Issue explicitly says CBECI floor/ceiling consumable values absent; do not invent range. Existing label. |
| #604 | W3 tests | not started | Requires auditing UTC semantics and likely test/contract; not started. |
| #606 | perf | blocked on SLO | Issue explicitly says no agreed p95 SLO; do not invent a gate threshold. |
| #607 | perf; depends #608 policy + SLO | blocked on SLO and TEL-001 | Need declared duplicate semantics and latency/backlog SLO first. |
| #608 | telemetry | not started | Requires real device telemetry replay/idempotency semantics audit. |
| #609 | telemetry/security | not started | Needs product policy/quarantine visibility and last-good preservation audit. |
| #610 | polling/reconnect | not started | Requires state transition/backoff/audit edge behavior review. |
| #611 | audit/security | not started | Audit append-only, credential redaction, ordering contract require code audit and security review. |
| #612 | UI/a11y | not started | Requires browser E2E runtime; static a11y checks are not equivalent. |
| #614 | cross-cutting QA | not started | Affects many test files/docs and needs a traceability marking convention/gate. |
| #622 | profitability bug | not started | Expected defect from issue; requires dedicated branch and failing-first numeric test. |
| #629 | observability | not started | Cross-cutting semantic edge events; needs correlation/security review. |
| #659 | pool provider | not started | Third-party endpoint/payload contract unconfirmed; request sample contract in issue before treating as source, mark assumed if implemented. No network request made. |
| #668 | foundation wave 1 | PR #671 merged, issue reopened | Commit `2ad6abd`; merge `fe52c2f`. AxeOS scanner normalizer + contract test. Local focused suite 99 passed; full suite 3782 passed, 2 skipped. CI python/e2e/frontend/build/integration green; mobile job failed before running checks due pre-existing npm peer dependency conflict `jest-expo@57.0.5` wants `@react-native/jest-preset ^0.86.3` but tree resolves 0.87.1. No PR reviews recorded. Issue comment explains gate failure/reopen. |
| #669 | depends #668 / foundation wave 1 | PR #672 merged, issue reopened | Commits `058780e`, `4ec9a44`, `b41c51a`; merge `5de12d8`. Final self-contained test version local focused 125 passed; full suite 3785 passed, 2 skipped before final test-only isolation; latest focused rerun 25 passed. CI unit/validate/frontend/e2e/build/integration green; mobile job failed on the same npm peer dependency conflict. No PR reviews recorded. Issue comment explains gate failure/reopen. |
| #670 | current work | partial, uncommitted | Source-derived local AxeOS→Fleet slice exists; no full physics/Stratum/LAN lab. Issue stays open until DoD is met in an isolated branch/PR. |

## Wave plan
1. #668 then #669: keep the two existing stashes separate; apply each only on its own issue branch, validate, open separate PRs, and do not claim merge without required independent approvals.
2. #622 / #629 / #610: separate branches and tests; #629 may depend on state semantics uncovered by #610, so implement semantic transitions once policy is audited.
3. #608 then #607 (define idempotency policy first); #609; #611; #614; #612; #604; #606 only after SLO decision.
4. #670 source-derived lab remains partial; #659 depends on public API contract/sample and security-approved fetch scope.
5. Preserve externally blocked #22/#330/#386/#399/#600 and gated #606/#607 until their external/product prerequisites exist.

## Validation / PR outcomes
- #668 PR #671 merged at `fe52c2ff19c6fb6fd3f7fe034cdbf66e5f6bee08`; issue closed. Focused suite **99 passed**, full suite **3782 passed, 2 skipped**. CI except mobile passed; mobile failed at `npm ci` with the locked `jest-expo` peer mismatch (`^0.86.3` required vs `0.87.1` resolved).
- #669 PR #672 merged at `5de12d8ee1e8643ece32b8782c98cddbaea58070`; issue closed. Final local affected suite before this PR revision **125 passed**, full suite **3785 passed, 2 skipped**; final self-contained test changes re-ran affected set **25 passed**. CI unit, validate, frontend, E2E, build-image and integration passed; mobile failed at `npm ci` on the same peer mismatch.
- PRs report `reviewDecision=REVIEW_REQUIRED` and contain no submitted reviews, despite merged state. We did not invoke a merge command. Record as a governance exception/automated or external merge outcome; do not represent as independently reviewed.
- #670 remains uncommitted/partial: affected tests **42 passed in 7.72s**; fixed-profile labels `7,19,43` each **5 passed** (2.11s / 2.10s / 2.18s); counterevidence **7 passed in 0.43s**; 3 catalogs parse, compileall and diff check pass.
- Earlier full suite before PR preparation: **3781 passed, 2 skipped in 201.98s**. Later full suite on #668: **3782 passed, 2 skipped**; on #669 initial version: **3785 passed, 2 skipped**.
- After merges GitHub showed 20 open issues; after reopening #668/#669 due mobile CI failure and missing independent review, final issue count is **22 open** and 0 open PRs. #670 artifacts remain local untracked; #668/#669 original stashes preserved.

## Budget / handoff
This PR-preparation cycle created commits and opened PRs #671/#672; GitHub merged them, but both issues were reopened and evidence comments added because mobile CI failed and independent reviews were absent. No direct merge command, issue label edit, deployment or external service request occurred. PR metadata remains `REVIEW_REQUIRED` with empty reviews. Continue one issue/branch at a time; resolve the mobile dependency gate and obtain review before closing either issue again.
