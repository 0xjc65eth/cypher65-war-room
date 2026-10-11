# Issue #822 — restore settings fixture configuration

Base `a121276f00c20feff5a9f06d3854eda911b35dcf`, 2026-10-11. Scope: test fixture only; production authentication and access guards remain unchanged.

The settings fixture left `JWT_SECRET_KEY` in Flask configuration after its client closed. Later export tests mint tokens outside an app context using the environment secret; verification prefers the retained configuration secret and classifies those tokens as anonymous. The intended tenant guards were therefore never reached.

## Red → green evidence

On an isolated, unmodified master checkout, `test_tenant_settings.py` followed by `test_export_tenant_isolation.py`: **7 FAIL / 20 PASS**. Auth followed by export without settings: **33 PASS**. The larger related selection during #821 also recorded **7 FAIL / 159 PASS**; it is not labeled green.

`rclient` now uses pytest's `monkeypatch.setitem` for TESTING and JWT_SECRET_KEY. The Flask client context closes before monkeypatch teardown restores each prior value or prior absence. `_token` still signs real JWTs in the real application context. No test assertion was changed.

- Same settings → export ordering: **27 PASS**, 1.41 s.
- Related 11-file selection: **165 PASS**, 37.58 s. Its count is one less than the #821 selection because this independent branch retains the single original snapshot case.
- /advisor independently reran the ordered pair: **27 PASS**; recommended this bounded test-only repair.
- /devil exercised the real unwrapped fixture and real MonkeyPatch in nine combinations: JWT key absent/None/prior × TESTING absent/False/True. Signing/verification passed during the yield; complete configuration was restored after client teardown and undo. Independent ordered run **27 PASS**; no CRITICAL/HIGH/MEDIUM residual demonstrated in this delta.
- `git diff --check`: **PASS**. Technical review does not constitute GitHub approval.

Logs: `/tmp/c65-821-baseline-settings-order.log`, `/tmp/c65-821-baseline-order.log`, `/tmp/c65-821-contracts.log`, `/tmp/c65-822-order.log`, `/tmp/c65-822-contracts.log`. These are temporary local logs, not remote artifacts.

Full CI of the published head remains authoritative. This separate branch inherits the mobile pins tracked in #819/PR820 and the clock-sensitive assertion tracked in #821; success in a later composed validation does not imply either dependency is already merged. No merge, deploy, manual Issue closure, secrets or physical operations were performed.

## Reconciled publication — Issue #825

PR824 was integrated externally by0xjc65eth at2026-10-11T16:02:40Z, squash5f6b0e5d98995100bc902f3ec788304ba87c6437. The merge occurred while E2E was still running. By the16:04UTC checkpoint, external head4296178b6fe62cee6c1235dc45e721f5fed1cc21 independently completed all eight required checks and Codecov SUCCESS. Reviews were empty in the snapshot. Completed CI is not classified as GitHub approval or deployment; no agent merge/deploy/manual Issue closure was performed.
