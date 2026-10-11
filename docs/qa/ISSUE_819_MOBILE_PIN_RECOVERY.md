# Issue #819 — repair the two mobile pins changed by #782

Publication checkpoint: 2026-10-11 15:27 UTC. Base `a121276f00c20feff5a9f06d3854eda911b35dcf`. This unit repairs the shared base that blocks UI [PR #818](https://github.com/0xjc65eth/cypher65-war-room/pull/818); no UI code, guards, SDK or Zustand version changes.

## Demonstrated cause and bounded change

`git blame` and the diff of `3b9cb2d` identify PR #782 as the source of both changes. #781 changed Zustand and did not alter the Forge entry.

1. Master lockfile resolved `node-forge` through SSH, while the reviewed manifest override and security guard require HTTPS. The guard failed before the cryptographic vector on both PR818 heads (`755e806`, `503520a`). Restoring the lock URL retains commit `ceba34402e329f0365134f23fe19898756527d65`, version `1.4.1-0` and the integrity field. The guard and exploit/compatibility assertions remain unchanged.
2. After restoring Forge, the next mandatory check, Expo Doctor, failed **20/21**: SVG found `15.15.5`, expected `15.15.4`. Installed Expo `57.0.27` declares `15.15.4` in `bundledNativeModules.json`. Manifest/root-lock/SVG-lock entry now use that version, its npm-generated archive metadata and its `warn-once: 0.1.1` dependency (already present in the lock).

An npm lock regeneration also changed unrelated devOptional/libc metadata. That churn was removed before final clean validation: package keys and all other dependency versions/entries remain identical to the base. The package delta is two files, 8 added / 7 removed lines. No gate was relaxed and no package excluded from Doctor.

## Decision and independent review

Problem → both inherited pins block sequential mandatory steps. Alternatives → restore Forge alone and separately fix SVG, or restore both pins from the same #782 update in one bounded dependency unit. Risk → combining unrelated changes would expand review scope; restoring the SDK pin also gives up newer SVG patch behavior, and JS exports do not establish native runtime compatibility. Recommendation → the two-pin repair, because either isolated repair still leaves the mandatory mobile job blocked and both affect the same manifests/source update. Acceptance → clean tree, preserved security vector and Doctor21/21 plus lint/types/Jest/exports.

The Issue was explicitly updated before editing SVG. /advisor initially suggested a separate compatibility unit, then reviewed the expanded evidence and supported the bounded combined scope. /devil independently compared JSON structures: only the manifest SVG and three lock entries differ; all package keys, Forge SHA/version/integrity and remaining entries are preserved. Both independently ran Forge/braces checks or inspected the real SDK contract; no CRITICAL/HIGH/MEDIUM residual was demonstrated in this delta. These are technical reviews, not GitHub approval.

## Validation ledger

Local runtime: Node `22.22.0`, npm `10.9.4`; remote CI uses Node `22.13.0`, so local results do not stand in for exact-head remote checks.

- Clean `npm ci` and `npm ls --all`: **PASS**, exit 0; final scoped lock used for both.
- Existing Forge guard on the master lock: **FAIL**, exit 1, exact URL assertion reproduced in an isolated baseline fixture against the same installed dependency.
- Existing Forge guard on the restored lock: **PASS**, exploit rejected, valid RSA/SHA-256 accepted and tampered digest rejected.
- Braces provenance/depth guard + self-tests: **PASS**, 10 cases.
- Expo Doctor: **PASS**, **21/21** after the SVG pin; earlier 20/21 FAIL kept in the log.
- `npm audit --audit-level=high`: **PASS**; **22 moderate advisories remain**, no blanket claim of zero vulnerabilities.
- Biome: **PASS**, 30 files; TypeScript: **PASS**; Jest: **111 PASS / 16 suites**.
- JS exports iOS, Android and web: **PASS**, exit 0. Signing/archive/TestFlight, simulator/native build, hardware and production: **NOT RUN**.
- Diff/JSON scope: **PASS**. No additional test merely mirrors the URL edit; the unchanged existing guard provides the demonstrated red→green regression.
- Remote CI: **PENDING** at publication; the PR current exact-head checks are authoritative. Merge/deploy/manual Issue closure: **NOT RUN**.

npm warned that it skips integrity checking for the normalized Git dependency spec. Preserving the integrity metadata is not a claim that npm enforces Git archive integrity or that the effective fetch transport was observed. The full reviewed Git SHA and security regression remain the contract; this does not constitute a new broad upstream dependency security audit.

Logs: `/tmp/c65-819-forge-before.log`, `/tmp/c65-819-doctor.log` (FAIL), `/tmp/c65-819-npm-ci-scoped.log`, `/tmp/c65-819-npm-ls-final.log`, `/tmp/c65-819-forge-final.log`, `/tmp/c65-819-braces-final.log`, `/tmp/c65-819-doctor-final.log`, `/tmp/c65-819-audit-final.log`, `/tmp/c65-819-lint-final.log`, `/tmp/c65-819-typecheck-final.log`, `/tmp/c65-819-jest-final.log`, `/tmp/c65-819-build-final.log`. Temporary local logs are not remote artifacts.

CI evidence for inherited failure: [first Forge job](https://github.com/0xjc65eth/cypher65-war-room/actions/runs/38150517988/job/114502830961), [PR818 current code/doc head Forge job](https://github.com/0xjc65eth/cypher65-war-room/actions/runs/38150592298/job/114503052479).

## Reconciled remote evidence — Issue #825

PR820 was integrated externally by0xjc65eth at2026-10-11T15:49:54Z, squashf5dde52825dbc27891fcd2665a36a263201c4bb3. The external synchronized head30f3a80e7a60bbb6570e350a341441500881c964 passed all eight required checks and Codecov; reviews were empty in the snapshot, so approval/deploy is not inferred. The original a57af26 Unit Tests failure remains recorded and was traced to timestamp-substring comparison, fixed separately in PR823/Issue821.

Additional iOS gate: native generation/CocoaPods/build/install/launch/evidence upload SUCCESS on both originala57af26 (job114505462137,15:38:13UTC) and synchronized30f3a80 (job114508285831,15:57:14UTC). Original artifact11706747476 was downloaded and the login screenshot/app/build evidence inspected. Artifact names use the runner's synthetic merge-ref SHA; the associated workflow head was independently checked. This supplies native simulator evidence only; signing/archive/TestFlight/authenticated session/physical hardware/production remain NOT RUN. The earlier NOT RUN entry above describes local publication validation.
