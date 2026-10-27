# Issue #859 — compatible transitive security updates (partial)

Date: 2026-10-25. Base: `e616a0169659a8f5c8c70c5f13e67f300b86075c`.
Issue: <https://github.com/0xjc65eth/cypher65-war-room/issues/859>.
Branch: `security/859-compatible-transitive-fixes`.

## Decision and remaining blocker

This is a **partial remediation**, not completion of #859 or permission to merge.
The actual npm audit remains nonzero with **3 HIGH / 0 MODERATE / 0 CRITICAL**:
root Zod v3 plus the propagated Expo CLI and Expo findings. A draft PR must use
`Refs #859`, not `Closes #859`. The high/critical-zero gate is unchanged.

The source-backed compatible changes are only:

| Locked node | Before | After | Existing consumer contract |
| --- | --- | --- | --- |
| `knip/node_modules/zod` | 4.4.3 | 4.6.7 | Knip 6.39.0 requires `^4.4.3` |
| `mutation-server-protocol/node_modules/zod` | 4.4.3 | 4.6.7 | Protocol 0.4.1 requires `^4.1.12` |
| `fast-uri` | 3.1.8 | 3.1.9 | AJV 8.18.0 requires `^3.0.1` |

Expo 57.0.31, CLI 57.0.32 and root Zod 3.25.76 are preserved. So are all other
package nodes, Babel 7, Stryker 9.6.1, the full-SHA Forge pin, vendored braces,
follow-redirects 1.16.1 and existing quality/security gates. No manifest override,
force downgrade, advisory exclusion, SDK upgrade or global major override exists.

## Current official sources

Consulted 2026-10-25, registry snapshots at 11:14–11:17 UTC. Registry metadata is
time-sensitive; refresh it before resuming rather than treating this as a future
release promise.

- [Reviewed Zod advisory GHSA-mrhx-c7xc-m3w5](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5)
  identifies versions below 4.6.6 and names 4.6.6 as patched. The
  [upstream fix](https://github.com/colinhacks/zod/commit/a0ebf970f2d752e5f58527cd2942ff48be4f46bd)
  introduces early upper-size rejection in **v4** array/set/map interpreters and
  compiled validation. It is not a universal bound on unconstrained validation.
- [Official Zod registry](https://registry.npmjs.org/zod) lists latest stable
  v3 as **3.25.76**, latest v4 as **4.6.7**. No compatible published v3 fixed
  version was found in that snapshot.
- [Official CLI registry](https://registry.npmjs.org/%40expo%2fcli) lists SDK57
  CLI **57.0.32** and latest **58.1.15**; **both** declare Zod `^3.25.76`.
  [Expo metadata](https://registry.npmjs.org/expo) lists SDK57 **57.0.31** using
  CLI `^57.0.32`. An arbitrary CLI58 upgrade neither satisfies that contract nor
  removes this v3 requirement.
- [Upstream v3 issue #6653](https://github.com/colinhacks/zod/issues/6653) remains
  open. The maintainer stated that new v3 versions are no longer published;
  later discussion notes that the v3 entry point bundled inside v4 is unchanged.
  Those comments are not a fixed release or an approved CYPHER65 exception.
- [fast-uri v3.1.9 security release](https://github.com/fastify/fast-uri/releases/tag/v3.1.9)
  addresses four normalization/host/scheme advisories without requiring major 4.
  [The reviewed scheme advisory](https://github.com/advisories/GHSA-w74x-v6f9-j3xg)
  names 3.1.9 as a patched v3 release; the other three are
  [relative references](https://github.com/advisories/GHSA-xhq7-xmqj-769h),
  [host canonicalization](https://github.com/advisories/GHSA-wjr9-j795-jxcr) and
  [suffix schemes](https://github.com/advisories/GHSA-333x-w4r6-6crp).
  [Official fast-uri metadata](https://registry.npmjs.org/fast-uri/3.1.9)
  confirms version, registry archive and SHA-512 integrity.

## Implementation and bounded regression contract

`npm update zod fast-uri --package-lock-only --ignore-scripts --no-audit`
generated the three allowed resolutions. npm also rewrote unrelated
dev/devOptional/libc metadata and Forge's resolution representation. A mechanical
whitelist projection retained only the npm-generated version/resolved/integrity
fields for the three target nodes, preserving every other lock entry byte-for-byte
after JSON serialization. Final lock diff is 9 added and 9 removed lines.
Normal clean `npm ci` validates that narrow lock. Nothing is manually relabeled as
a fixed Zod-v3 version.

The new standalone CI step exercises the actual installed libraries with a
128 MiB heap ceiling and **256-element** synthetic inputs, never a million-element
or OOM attempt. Both nested v4 consumers reject oversized `.max(2)` arrays/sets/maps
before element callbacks and emit one size issue. Async rejection and normal
good/bad controls remain covered. The actual Expo CLI plugin schemas and mutation
protocol schemas also retain supported valid/invalid structures. URI regressions
cover each advisory class without resolving hosts or executing schemes.

A separate bounded diagnostic preserves the unresolved evidence: root v3 and the
`zod/v3` entry point inside patched v4 each visit 256 elements and emit 257 issues
for the constrained synthetic fixture. Therefore a v4-package/v3-entry alias is
not a genuine remediation, even if version-only scanning would appear cleaner.

The app's first-party `src/` and `App.tsx` have no direct Zod/fast-uri imports in
this source inspection. Identified paths concern development/build tooling and
schema processing. That does **not** establish absence of a reachable attack or
certify a production/mobile binary. No production exploit is claimed or attempted.

## Evidence and gates

Evidence directory: `/private/tmp/cypher65-859-readonly.nFOcbL/`.
Runtime: existing Node 22.22.0 / npm 10.9.4; clean isolated install. Empty distinct
user/global npm configs and a task-specific cache avoid reading user credentials.

| Check | Observed result |
| --- | --- |
| Current base lock audit | FAIL as expected: 3 HIGH, 1 MODERATE, 0 CRITICAL (`audit-master-current.json`) |
| Partial lock audit | **Still FAIL:** 3 HIGH, 0 MODERATE, 0 CRITICAL; only root v3/Expo chain remains (`audit-partial.json`) |
| Vulnerable-library comparison | Expected RED: 12 failed / 2 passed, using existing Zod4.4.3 and fast-uri3.1.7 libraries; the latter is not represented as the base's locked3.1.8 (`regression-red-existing-libraries.log`) |
| Final bounded installed-library/consumer regressions | PASS: 16 tests (`regression-final-16.log`) |
| Normal clean npm ci | PASS: 911 packages (`npm-ci.log`), no install flags suppressing scripts/peer checks |
| npm ls --all | PASS: no problems (`npm-ls.json`) |
| Expo Doctor | PASS: 21/21 (`doctor.log`) |
| Existing Forge / braces / follow-redirects protection | PASS: Forge exploit+valid-RSA control; braces10/10; redirects10/10 |
| Strict lint / TypeScript | PASS: 34 files / no TS errors (`lint.log`, `typecheck.log`) |
| Full mobile Jest | PASS: 25 suites, 200 tests, 11.359 s (`jest.log`) |
| iOS / Android / web Expo exports | PASS: all three (`exports.log`); not native signed builds/device tests |
| Knip advisory | FAIL: vendor unused files/devDependencies/types and existing unlisted Forge/redirect test imports; identical output on a clean base-source clone using the same Knip tree (`knip-baseline.log` vs `knip-final.log`); no gate weakened |
| Syntax / lock scope / whitespace | PASS |
| First-party changed production-function coverage | NOT APPLICABLE: no first-party production function changes; dependency behavior is covered above, not claimed as whole-upstream-library coverage |
| Exact-head remote CI / formal approval / merge / deploy | NOT PERFORMED; audit remains blocking |

Retained unsuccessful probes: registry version endpoints initially rejected the
abbreviated Accept header (406), then succeeded with JSON; npm rejected loading
`/dev/null` as both user and global config, so distinct empty configs were used.
The first Knip run also flagged a bare transitive test import; tests now address
the exact locked nested node without adding a direct dependency or suppression.
No result was rewritten as a full security pass.

## Next decision

Publish only a reviewed draft partial PR with `Refs #859` if authorized. Keep
#859 and the mobile security gate open. Supported completion requires an upstream
v3 fix/advisory correction or an Expo-supported migration to a patched API under
an explicit compatibility decision. A private backport, package alias or patched
fork would require separate authority, provenance/licensing and security evidence;
it would not automatically satisfy the current official audit range. Do not use
`npm audit fix --force`, which still proposes a breaking Expo54 downgrade.

Reproduce from `mobile/`:

```sh
npm ci --no-audit --no-fund
node --max-old-space-size=128 --test scripts/check-transitive-validation-fixes.test.cjs
npm ls --all
npm run doctor
npm audit --audit-level=high # Expected nonzero until the v3 blocker is resolved.
npm run test:security-node-forge
npm run test:security-braces
npm run test:security-follow-redirects
npm run lint && npm run typecheck && npm test -- --ci
CI=1 EXPO_NO_TELEMETRY=1 npm run build
```
