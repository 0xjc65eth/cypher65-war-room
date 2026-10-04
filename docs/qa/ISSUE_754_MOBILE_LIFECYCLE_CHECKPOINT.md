# Issue #754 — foreground-only mobile observation polling

Reviewed: 2026-10-04. Parent: #399, GATE-067 foundations, **not native
certification**. Implementation branch: `fix/754-mobile-foreground-polling`.
Initial baseline: `5f9d5e3809088aded3fdbed77c2df7eef71bd718`.

## Proven defect and scope

The previous `useBatteryMode` scheduled unconditional intervals and never
observed React Native AppState. Added regression tests failed before the fix:
11 failed / 5 passed (16 cases), including background/inactive/unknown/null
startup, no foreground catch-up, overlapping scheduled reads, and missing
listener disposal. The failure log is retained, including the deliberately
reproduced uncaught callback rejection/throw.

The replacement uses the existing React Native AppState API, not a background
service. Only `active` permits automatic reads. A non-active → active transition
requests one immediate catch-up; duplicate active notifications do not duplicate
reads. Missed background intervals are not replayed. A pending scheduled read
coalesces foreground catch-up to one subsequent invocation while still active.
Callback replacement and 60s/15s battery-mode changes re-arm a single timer.
Manual-only mode never starts a timer or foreground refresh.

`schedule` and `cleanup` retain stable identities, so `useSnapshot` does not
repeat its mount refresh when the battery mode changes. Explicit cleanup
discards scheduling and queued catch-up; the listener remains owned by the hook
until unmount, when it is removed and late events/completions cannot dispatch.
Callbacks own user-visible errors; failure does not poison later scheduling.

Source contract: [React Native AppState](https://reactnative.dev/docs/0.86/appstate)
and the installed React Native 0.86.3 implementation/type declaration. Runtime
startup state can be null even though the type declaration omits it, so null is
handled conservatively. Android notification-drawer blur without an AppState
change is not a background transition and is not claimed as covered here.

## Explicit boundaries

- Only scheduled callback invocations are single-flight. Manual `refresh()` and
  the initial mount refresh remain caller-owned; no claim of global request
  deduplication is made.
- Already-started reads are not transport-aborted by a lifecycle event. The
  existing axios timeout remains 15 seconds; neither timeout nor retry policies
  are changed. Snapshot cache/store completion is not blocked by this scheduler.
- This code dispatches no hardware command, introduces no secret, changes no
  API endpoint, enables no feature flag, and changes no dependency or lockfile.
- No layout, animation duration, CSS, or motion preference changes. Confirmed
  motion weighting remains Emil (speed/restraint), then Jakub (polish).
- JS event simulation does not certify OS suspension, termination/relaunch,
  native Keychain, installed-app networking, signing, archive or TestFlight.
  GATE-067 remains **FAIL** pending the complete native matrix.

## Local verification

Clean `npm ci --no-fund --no-audit` succeeded in this owned disposable worktree.
Host Node: 26.0.0; npm-script Node: 22.22.0 (verified with `npm exec -- node
--version`); dependency versions are exclusively the existing lockfile's.
`npm ls --all` succeeded. The npm advisory query reported 0 vulnerabilities.

| Check | Result |
|---|---|
| Full mobile Jest | Initial 16 suites / 107 tests PASS; strengthened final 16 suites / 111 tests PASS |
| Changed scheduler coverage | 100% statements, branches, functions and lines; not a claim of full-app coverage |
| TypeScript strict | PASS (`npm run typecheck`) |
| Biome | PASS (`npm run lint`, 30 files) |
| iOS, Android and Web exports | PASS; exports are not native install/launch evidence |
| Braces provenance/depth guard | PASS, including all 10 tamper regressions |
| Pinned node-forge exploit/valid RSA guard | PASS |
| JS core | 1649 assertions PASS on the initial baseline; integrated master `d2e0a57` FAIL (syntax regression from #755), tracked by #756 |
| Generated web bundle drift | PASS |
| Mobile XSS guard | PASS, 0 vectors |
| Whitespace diff | PASS |

Reproduction, from the worktree's `mobile/` directory:

```sh
npm ci --no-fund --no-audit
npm test -- --coverage --collectCoverageFrom=src/hooks/useBatteryMode.ts
npm run typecheck
npm run lint
npm run test:security-braces
npm run test:security-node-forge
npm run build
npm ls --all
npm audit
```

Targeted lifecycle tests include 22 scheduler cases and one actual
`useSnapshot`+scheduler integration case alongside the four existing snapshot
cases. Unmount with a pending read, late event disposal, cleanup of queued
catch-up, callback replacement, sustained background time, mode changes while
backgrounded, callback rejection/throw, and no overlapping scheduled reads are
explicitly asserted, not inferred from line coverage.

## Retained evidence

Local artifacts are outside the commit and contain no operational secrets:

| Artifact | SHA-256 |
|---|---|
| `/private/tmp/cypher65-754-red.log` | `ddd240e81d0b77afcad2f767d6a80a20f40418105c80a3cbda2a456494c2fc73` |
| `/private/tmp/cypher65-754-jest-final.log` | `0ae88b876883d26049c99902a7669035b55633ca277b51f5aefe15e8d3d935de` |
| `/private/tmp/cypher65-754-exports.log` | `fd32e22330a3028d0231beb3c06ecf165b3d6b46cf23f7f8ed216e5caa6ae26e` |
| `/private/tmp/cypher65-754-npm-ci.log` | `1eeea78d3ca3eabe484c1d1e05a64df81af608f6aa54dc9c4cd3076dfd615942` |
| `/private/tmp/cypher65-754-coverage/coverage-final.json` | `bff5d6605f8f82d705a251e5655092a4ee31ed42f786bc8987a6185b9521ef43` |

Frozen source SHA-256:

- `mobile/src/hooks/useBatteryMode.ts`:
  `5bff6e028283d6528af7e022f16c665c7b34eb25d830df2b1a78a6a2c558d524`
- Initial `mobile/tests/useBatteryMode.test.ts` (before timer-strengthening):
  `c2d75a9b4d092c3baeec38d22dcf77b10416e30f26eb2545a73c0c2df0bf6240`
- `mobile/tests/useSnapshot.test.ts`:
  `0d1b9f0772a6bd6970318de943bb2e2d9294460ac9977802d5cb5e72a57eef3c`

## Integrated-base and mutation verification

Ordinary integration of externally merged #753/#755 produced local source
`8d373cbafe0aabedbbdab7c325f2c37225320c9a` with base
`d2e0a572269827de326b7e41b8c524f80a558854`. Mobile runtime/dependency inputs
outside this Issue are byte-identical to the initial baseline. JS core and
`node --check` on both the dashboard fragment and generated app fail because
#755 introduced an incomplete duplicate function and unreachable old returns.
This is independently reproduced, **not relabeled green**. #756 is already being
implemented in the active task “Auditar e corrigir o CYPHER65”; no competing
implementation or edits to that task's worktree were made. This PR must remain
draft until its corrected base and exact-head CI can be revalidated.

Targeted Stryker verification of the scheduler produced 102 mutants:
81 killed, 2 timed out, 19 survived, 0 uncovered and 0 errors; reported score
**81.37%**. Timeouts count in Stryker's score and are disclosed, not called
explicitly killed. Approximately 28.43 tests ran per mutant. The repository's
breaking threshold of 40 was unchanged; no mutant exclusions were added.
Final timer tests track interval handles, so internal React async/act timers
cannot mask timer disposal. A queued tick after background, manual-mode change,
cleanup or unmount must not dispatch. These four added cases raise the full
Jest count to 111 without modifying production code.

Failures retained separately: initial sandbox socket `EPERM`; filtered Stryker
run with 23 dry-run tests but zero tests per mutant (invalid quality evidence);
valid initial score 61.76%; strengthening attempt incorrectly counted React's
internal timers; retained failed Stryker sandbox caused Jest Haste duplicate
module discovery. That **owned generated sandbox** was moved intact to
`/private/tmp/cypher65-754-failed-mutation-sandbox-8lE3H7` outside the Jest root,
not deleted; clean-root Jest passed afterward. One invocation from the root
directory failed before tests because that root has no `npm test` script.

Final scheduler test SHA-256:
`ea71a91c8622825e8e1b7dd85ce8f356fac20dd0d3155c0c49e67d26c9600e5f`.
Mutation JSON `/private/tmp/cypher65-754-mutation-strengthened.json`:
`b7e54eb64b1b7587d41a3193271a484d01381b1fea62b3b6a35df109215e850d`.
Mutation log `/private/tmp/cypher65-754-mutation-timers.log`:
`9a2fa0dd43eb879c02d48e793f9c551d359ac3c2b23313e1d0cfd1afb58fc7e8`.
Integrated JS failure `/private/tmp/cypher65-754-integrated-js-core.log`:
`c179437f6e050e484a6b82310791c855551f640e2737f6c3ee785d099c92ea3d`.
Final full Jest `/private/tmp/cypher65-754-jest-release.log`:
`134572c7070dd380f984207151fc41a811c283ccad5a867be0cf7bf85ce6aa44`.
Final coverage `/private/tmp/cypher65-754-final-coverage/coverage-final.json`:
`b997aae483728d744316d980afe7da6b0cd2cc5b8d4747b1f3ead0ec1b86a9c3`.

## Enterprise review and next gate

Frontend/QA: regression-first implementation; no UI/motion change. Security:
read-only observer, dependency provenance unchanged, no credential or physical
access. Observability: callback errors remain handled by the existing refresh
flow; no new logging of tokens or response payloads. DevOps: native inventory
is empty locally despite installed Xcode 26.6; no automatic SDK installation.
Product: no claim that an inactive terminal presents newly verified telemetry.

This is an author review using enterprise-code-review, **not independent
approval**. Required exact-head remote CI, resolved review threads, an
independent approval and current strict-base policy must all pass before normal
squash merge. No protected-branch bypass or direct deploy is authorized.
