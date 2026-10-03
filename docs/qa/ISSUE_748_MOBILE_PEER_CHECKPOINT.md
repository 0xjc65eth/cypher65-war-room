# Issue #748 — Mobile `test-renderer` peer alignment

## Change

The mobile tree uses React 19.2.3. `@testing-library/react-native@14.0.1` declares `test-renderer@^1.0.0` as a peer. The previously selected `test-renderer@1.3.0` brought `react-reconciler@0.34.0`, whose React peer is `^19.3.0`; this does not include the app's React 19.2.3 and caused `npm ls --all` to report an invalid peer tree.

This change pins the direct peer anchor to exact `test-renderer@1.2.0`. Its registry metadata declares `react-reconciler~0.33.0` and React peer `^19.0.0`. `react-reconciler@0.33.0` declares React peer `^19.2.0`, which includes 19.2.3. No override is used for React or the reconciler. The package-lock delta changes only the root dev dependency and the affected renderer/reconciler entries; unrelated packages and their lock metadata are preserved.

The mobile CI job runs blocking `npm ls --all` immediately after `npm ci`, so invalid or missing peer dependencies fail before later checks.

Official registry metadata captured by the parent task:

- `test-renderer@1.2.0` integrity: `sha512-JYiEGbgBGtmHAWX8Kf99gGRL1HtjcRVHLrmJNTZL4vFs9XrnWcuL45Iszw/pO4094+JR7havSrN+ds6YTOpSQA==`.
- `react-reconciler@0.33.0` integrity: `sha512-KetWRytFv1epdpJc3J4G75I4WrplZE5jOL7Yq0p34+OVOKF4Se7WrdIdVC45XsSSmUTlht2FM/fM1FZb1mfQeA==`.
- The raw registry metadata is retained at `/private/tmp/cypher65-737-upstream-tests.72v3Wb/test-renderer-1.2-metadata.json` and `/private/tmp/cypher65-737-upstream-tests.72v3Wb/react-reconciler-0.33-metadata.json`.

## Validation checkpoint

Executed on Node.js 22.22.0 with npm 10.9.2, from a clean mobile install in the isolated Issue #748 worktree, on 2026-10-03:

| Check | Result |
|---|---|
| `npm ci` | PASS — 962 packages added; npm emitted its existing git-dependency integrity warning for node-forge. |
| `npm ls --all` | PASS — exit 0; no invalid or unmet required peer dependencies. Optional platform packages remain optional. |
| `npm ls test-renderer react-reconciler react --depth=2` | PASS — `test-renderer@1.2.0` → `react-reconciler@0.33.0` → React 19.2.3. |
| `npm run test:security-node-forge` | PASS — pinned ASN.1 exploit rejected and valid RSA compatibility passed. |
| `npm run doctor` | PASS — Expo Doctor 21/21. |
| `npm run lint` | PASS — Biome checked 30 files. |
| `npm run typecheck` | PASS — `tsc --noEmit`. |
| `npm test -- --ci` | PASS — 16 suites, 91 tests. |
| `npm run build` | PASS — iOS, Android, and web exports. |
| `npm audit --audit-level=high` | BLOCKED BY #737 — audit still reports the high-severity `braces` stack-exhaustion advisory (GHSA-vfj7-8cjw-p6xm). This is an active, executable security fix tracked in #737, not an external dependency blocker; #748 neither suppresses nor resolves it. |
| `npm run lint:knip` | Advisory failure — existing unused `react-test-renderer`, undeclared `node-forge` reference in the security checker, and three exported types; CI marks this step `continue-on-error`. |
| `git diff --check` | PASS at checkpoint. |

The audit's exit 1 is intentionally retained; do not describe the complete mobile CI as green until #737's reviewed patch is integrated and the audit passes on the exact resulting head. No application source, React, Expo, or Stryker version was changed for #748.

## Retained command logs

Full command output is outside the checkout at `/private/tmp/cypher65-issue748-evidence-20261003/`. SHA-256 values are recorded here so the results can be checked without adding generated logs to the source tree.

| Log | SHA-256 |
|---|---|
| `npm-ci.log` | `d6d365265298e3d6e4bbce44daba2400862db407f930a90440b88a3ba602f648` |
| `npm-ls-all.log` | `b6d1a804c1d0ff34bc99146525358f98e1e5707d0a177ed68f7ec8602288b303` |
| `node-forge-check.log` | `20cfa0996cc5e5f24a27ec079bb1cbae0a86f14ff3d6fde5b7b917baf64bc3e5` |
| `expo-doctor.log` | `7f0ec03013d71bc250cc258ef8a907af9fbf5493fdab2024b0be93268ac153d1` |
| `biome-lint.log` | `2becd080541a79f49a1a8ebac28613820ed5505bf6039ef4b8013d2fa21ae636` |
| `typecheck.log` | `c714b26fb9614d20d049a0117ecd01f35cc487ef1bfb2db75f774fcc546deb9e` |
| `jest.log` | `aca0601e73255080893a567724f17a00bda44664f86b03c2de254f199357a195` |
| `mobile-build.log` | `5c75bb37a3ed0aab71e29b22217bb9cfe9523a483cef9e082d0911db2d985c78` |
| `npm-audit.log` | `d3d0c9041476866aaedf5e1673dc42fc5b69e801f0a248689fa7cd75d3e8133e` |
| `knip.log` | `7350d32c2584d4cf9a4e0d05dc14184dcf8c78263623e750b520b196c3228bfe` |

The clean install log includes npm's existing warning that the lock resolves the node-forge Git dependency over SSH and that npm skips its integrity check. This inherited transport detail was not changed by #748.

## Reproduction

From `mobile/`, use Node.js 22 and npm 10.9.2:

```sh
npm ci
npm ls --all
npm ls test-renderer react-reconciler react --depth=2
```

Then run the existing mobile checks as listed in `.github/workflows/ci.yml`. The validation worktree is `/private/tmp/cypher65-issue748.KHqCLF`, branch `fix/748-mobile-test-renderer-peer`, based on `60eda10d3c9fbd6373029e73750bff41bdd1b3ad` before this change. Root is expected to integrate this child fix with reviewed #737 work before final joint validation.
