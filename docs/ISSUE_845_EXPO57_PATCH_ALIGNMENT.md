# Issue #845 — Expo 57 patch alignment checkpoint

## Scope and decision

Base: master `9d4123e`. Branch: `fix/845-expo57-gates`. Draft only; no merge,
deploy, native signing or device operations. The live Expo compatibility map
reported six mismatched direct dependencies. Align only those six patches and
their required resolution closure; do not suppress Doctor or audit findings.

| Direct package | Before | Reviewed patch |
| --- | --- | --- |
| @expo/metro-runtime | 57.0.16 | 57.0.17 |
| expo | 57.0.27 | 57.0.31 |
| expo-constants | 57.0.21 | 57.0.22 |
| expo-notifications | 57.0.22 | 57.0.23 |
| expo-splash-screen | 57.0.9 | 57.0.10 |
| jest-expo | 57.0.5 | 57.0.6 |

The lock updates 19 installed package versions (six direct, 13 transitive) and
removes the now-unused root uuid package. xcode 4 is required by the new
@expo/config-plugins range, not a discretionary major update. A structural
comparison found **949 unchanged entries byte-equivalent as JSON values**, with
zero metadata drift among unchanged package versions. React/React DOM/renderer
19.2.3, Babel 7, Stryker core/runner 9.6.1, the Forge HTTPS commit and vendored
braces provenance remain intact. Four opportunistic dependency upgrades were
reverted before validation.

## Actual validation, 2026-10-21

Logs: `/private/tmp/cypher65-expo57-845.Dmx9ya/`.

| Check | Result / evidence |
| --- | --- |
| Baseline Expo install check | FAIL: six mismatches |
| New runtime/lock contract on baseline | RED, preserved in toolchain-red-runtime.log |
| Clean normal npm ci | PASS: 910 packages, 50s; npm-ci-aligned.log |
| npm ls --all | PASS; npm-ls-aligned.log |
| Existing Forge and braces exploit/provenance gates | PASS; braces 10/10 |
| Online CI=1 expo install --check | PASS; install-check-online.log |
| Online Expo Doctor | PASS: 21/21; doctor-aligned.log |
| Jest with original timeout/config | PASS: 119 tests, 16 suites, 16.032s |
| Strict Biome and TypeScript | PASS, no source exclusions |
| iOS/Android/web exports | PASS; build-aligned.log |
| npm audit --audit-level=high | FAIL: follow-redirects HIGH, 22 moderate; isolated fix is PR #848 / #844 |
| Native simulator/device auth, signing, hardware, production | NOT RUN |
| Exact-head CI and independent GitHub approval | Required, not inferred from local results |

An initial sandbox install check reported offline mode. It is **not** used as
online compatibility evidence; the explicit online run and Doctor above replace
that limited observation. npm prints a git-dependency integrity warning; the
existing Forge runtime/commit gate separately passed. No credentials were used.

The unchanged AI operator test timed out in the baseline full suite (110 pass,
one fail) but passed alone before these updates (5/5, 1.077s). The corrected full
suite passed. This does not isolate or certify the cause of that intermittent
timeout. Do not increase its timeout, weaken assertions or claim it was fixed.

## Reproduction

```sh
cd mobile
npm ci
npm ls --all
npm run test:security-node-forge
npm run test:security-braces
CI=1 npx expo install --check
npm run doctor
npm audit --audit-level=high
npm test -- --runInBand
npm run typecheck
npm run lint
npm run build
```

Audit failure on this isolated branch is expected until the independently
reviewed #844 dependency fix is composed. No workflow gate was changed. This is
dependency/test-contract work with no added application business logic; no
application coverage improvement is claimed.

## Evidence hashes (SHA-256)

```text
71d38eb84b1b560bebe9ecd9021296d4aba3ecad88106e54dfa8341fb7dad8c2  npm-ci-aligned.log
7f0ec03013d71bc250cc258ef8a907af9fbf5493fdab2024b0be93268ac153d1  doctor-aligned.log
5f2445aa6845c35bdf9dbbc8bc2adfbacbffc3917cefe026de02731a36224616  jest-aligned.log
593e542be0fc7d24319794d0f2c086a74b05eb40210f3318c282c4b3c7945064  build-aligned.log
cd9dd064c64b972200fdc311678c1e4135647863307439d03667b854a9e1f017  audit-aligned.log
```
