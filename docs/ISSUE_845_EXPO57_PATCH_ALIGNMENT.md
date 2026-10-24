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

## Follow-up — 2026-10-23, post-merge dependency composition

This follow-up starts from master `02901d7c095e378ec0b2daab005d127cc9be00e1`.
Earlier checkpoints above remain historical; they do not describe the composed
tree. This is a **partial repair, Refs #845, not Closes #845**. Exact-head remote
CI and independent approval remain separate gates; no merge/deploy is performed.

### Reproduced dependency failures and minimal repair

- A normal isolated `npm ci` installed the baseline, but `npm ls --all` failed:
  React19.2.3 did not satisfy React DOM19.2.8 / renderer19.2.9 peers.
- Both selected Jest suites failed before collecting any tests because the
  composed manifest omitted `expo-crypto`, although owner-bound offline storage
  imports it and `jest.setup.js` mocks its real SHA-256 contract.
- The online official Expo compatibility check required notifications~57.0.24
  and React DOM19.2.3. The bundled Expo57.0.31 file still listed notifications
  .23; the CLI explicitly prefers the remote SDK matrix for emergency patches.
- Restore Expo-compatible `expo-crypto~57.0.4`, update notifications to~57.0.24,
  and align DOM/renderer to React19.2.3. Lock/installed-version tests cover the
  restored module and all three React packages.
- A later unchanged Forge guard exposed a baseline lock transport regression:
  its resolved URL used SSH, whereas the reviewed manifest/guard require HTTPS.
  Restore HTTPS with the **same full commit and SRI**. Do not weaken that guard.

Only the three direct existing package versions above change; expo-crypto is
added. The redundant nested jest-expo renderer/react-is entries are deduplicated.
Npm also reclassifies unchanged devOptional entries as dev; no version changes
are hidden in that metadata churn. Preserve existing Biome Linux libc metadata,
Babel7, both Stryker9.6.1 pins, the Forge commit/SRI, vendored braces, and
follow-redirects1.16.1. No audit-fix, legacy-peer flag, SDK exclusion, timeout
increase, source exclusion or workflow weakening is used.

### AI stall: falsified experiment, still unresolved

The actual unchanged `AiOperatorScreen`/RNTL event path was exercised. A cold
`--no-cache` run reproduced the first test timeout: **1FAIL/4PASS**, first test
7553ms versus the unchanged5000ms budget; a cached full suite passed. Temporary
phase instrumentation in another cold run measured render3656ms, text change
at3677ms, press at3683ms, and answer assertion at3685ms. The backend fixture was
already resolved: that observation locates the expensive portion before request
completion, but does **not** establish one universal root cause.

RN exports lazy component getters. Materializing real constructors before tests
initially reduced a cold first case to796ms; another repetition passed at420ms.
However, the next cold repetition still failed two cases at6950ms/5242ms.
Consequently the hypothesis that constructor preloading alone stabilizes this
test was **falsified**. A fake-timer diagnostic passed once but had no sufficient
causal red/green proof; it is not shipped. A pending-native-handler diagnostic
also remains outside the patch because that cold repeat failed it.

Final source retains the original AI screen, tests, real timers, Jest preset and
5000ms timeout unchanged. No fake answer, warmed render, mocked native list or
cache-dependent green run is presented as a completed stall fix. Continue with
monotonic phase/promise/native-layout investigation and cold/order/load controls;
keep #845 open until that first acceptance criterion is actually satisfied.

### Validation boundaries

Normal clean install/tree, online Doctor21/21, online Expo compatibility, audit
zero vulnerabilities, full mobile Jest, strict lint/TypeScript, all three security
guards, and iOS/Android/web exports were observed on October23 after dependency
repair. A final repeat with the unchanged AI tests passed200tests/25suites in
3.808s. An intermediate201-test run included a subsequently removed diagnostic,
not an extra shipped test. Native auth/Keychain/device/signing evidence is
**NOT RUN**; no application business logic or new coverage result is claimed.

On October24, the resumed full Jest repeat passed200tests/25suites in23.701s;
Doctor21/21 and online Expo compatibility passed again. **The current audit
gate FAILS:3HIGH/1MODERATE**, unlike the historical zero result. The updated
official [Zod advisory GHSA-mrhx-c7xc-m3w5](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5)
marks versions<4.6.6 affected and4.6.6 patched. Existing pinned Zod entries are
unchanged by this patch. `@expo/cli57.0.32` requires Zod^3.25.76, while mutation
server tooling requires^4.1.12; a blind global4.6.6 override crosses the CLI's
major-version contract. Npm's proposed force-fix downgrades Expo to54.0.38.
Neither workaround is applied. Track/review that security repair separately;
do not label this branch all-green or ready to merge. Fast-uri remains the
reported moderate finding. Audit evidence is `resume-audit.log`.

Integration inspection against master633b0d1202f6d83e7dd8e5d98398be5750c65893
found only the separate Block Lab numeric patch since02901d7: no mobile or CI
workflow overlap. That source comparison is not a composed CI run or approval.

Evidence is outside Git at `/private/tmp/cypher65-mobile845.AfUtAQ/`, including
baseline/green install logs, `cold-ai.log`, `ai-phase-diagnostic.log`,
`preloaded-cold-ai.log`, both `cold-final-*.log`, and the discarded fake-timer
diagnostic. Keep failed evidence instead of silently replacing it with green.
