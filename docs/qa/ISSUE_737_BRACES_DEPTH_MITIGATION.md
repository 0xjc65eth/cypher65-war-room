# Issue 737 — braces depth-only mitigation evidence

Status: source/checker review and most consumer gates passed; dependency-tree
adoption blocked by linked sub-Issue 748; **not merge-approved**.
Issue: https://github.com/0xjc65eth/cypher65-war-room/issues/737
Owned branch: `security/737-braces-depth-mitigation`.
Base at preparation: `60eda10d3c9fbd6373029e73750bff41bdd1b3ad`.

## Security decision and provenance

The official `braces@3.0.3` release is affected by
[GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm).
The Issue permits an independently reviewed, tested vendored mitigation when
no compatible fixed release exists. This change does not create a remote fork,
publish to npm, suppress the advisory, rename the package or downgrade Expo.
It maintains the patched source and its immutable local archive in this repository.

Source baseline: official release commit
`74b2db2938fad48a2ea54a9c8bf27a37a62c350d` of
https://github.com/micromatch/braces (annotated tag `3.0.3`).
Depth-guard design reference: https://github.com/micromatch/braces/pull/72.
Internal version `3.0.4-cypher65.1` is explicitly **not** an official upstream
release; metadata, README and NOTICE preserve that distinction. `index.js` and
the MIT LICENSE remain byte-identical to the published baseline. The patch does
not include unrelated unreleased quote/comma/parser behavior changes.

The depth cap is 100 containers. Parser and AST walkers share finite-value
floor/clamp normalization; non-numeric/non-finite limits use the hard cap.
Parser excess throws a controlled SyntaxError, walker excess a controlled
RangeError. This is depth-only mitigation, not general protection against
expansion cardinality, AST width, getters or arbitrary parent graphs.

Archive `mobile/vendor/braces-3.0.4-cypher65.1.tgz`:

- SHA256: `1cc80791bc34d4a5b45ed71fc8a68074607a2640adcab6e770a8f17a8f36d19a`.
- SRI: `sha512-3xrpMNIIk+ilf5+8Ki0FSrlJqBDPoJ0D1Yfmhv5uG7BQFgaDPFMAYVD+jt1JQ+3TXgBloWG+3hjsiS4YCmuCZQ==`.
- 11 files, 9365 bytes packed / 29488 unpacked, no bundled dependencies.
- `npm pack --ignore-scripts` succeeded using an owned disposable cache.
  The first attempt failed with EPERM on the user's read-only npm cache;
  that failure was retained and no cache ownership or permissions were changed.

## Evidence completed before mobile installation

BackendCore reproduced the official baseline's compiler stack exhaustion at
depth 4000 in a subprocess limited to 4 seconds / 128 MB. This is not a
production exploitation claim. The patched code-only checker and shallow
baseline comparison passed. SecurityOps independently reviewed the minimal
source delta and found no P0/P1/P2 source blocker; this is not GitHub approval.

Root ran the **unmodified published release test files** against the reviewed
source. A disposable loader redirects baseline `index.js` / `lib/` resolutions
to `mobile/vendor/braces`; tests and assertions are not edited. The loader
rejects outbound Node transport APIs; local Bash fixtures still execute. This
is a test-process guard, not an OS-level network sandbox.

1. Published release suite: **764 passing**, 92.63% lines/statements,
   84.71% branches, 85.18% functions.
2. Same release suite plus 53 independently authored security boundary cases:
   **817 passing**, **93.93% lines/statements, 88.37% branches, 88.88% functions**.
   The c8 global gates for all four metrics were 80 and passed, including every
   vendored JavaScript file with `--all`; no source file was excluded.
   Tests cover brace/parenthesis depth 100/101, mixed nesting, configured
   fractional/zero/negative/oversized/non-finite/non-numeric limits, direct AST
   walker boundaries and child-node cycles with explicit error classes/messages.

QA runtime: Node 22.22.0, Mocha 11.8.0, c8 10.1.3, ansi-colors 3.2.4,
bash-path 2.0.1, fill-range 7.1.1, installed only in a disposable directory.
Its tooling install skipped lifecycle scripts and audit; **the mobile audit
gate is unchanged and must run without advisory exclusions**. An old glob
deprecation warning from QA tooling is retained, not a mobile runtime finding.

Local artifacts: `/private/tmp/cypher65-737-upstream-tests.72v3Wb/`.
These paths are local evidence, not portable CI artifacts. Preserve the frozen
baseline and loader to repeat the source-routing verification.

| Artifact | SHA256 |
| --- | --- |
| `install.log` | `9df87e8f0635ca02557b230c301df6bf86773e4c008db18d1e3ade3d5bd5cbeb` |
| `release-suite.log` | `66712793face9753b87de8cfc62b0a349c7f53de0da91a2dfb9d364b5051950c` |
| `release-suite-with-security.log` | `ae4439a97fc8c47f90f218d5a707a7a0b66cb7e2b3df5f673f236ef90927a54c` |
| `load-reviewed-source.cjs` | `d43177dfd7831029628320b6715b55094ac39d4dfff8cef459aaa1443033c190` |
| `security-boundaries.test.cjs` | `5735b4cf8ae3da30080a6d66d844057c21f4ce23bfce0774e8b808318db9c334` |
| `coverage-with-security/coverage-summary.json` | `5dae3cb5e86120ade7c831cedfb93de0e9a5b9f00652a642c96058b0fab2f9ab` |

Baseline reproduction log:
`/private/tmp/cypher65-737-red.z3ybvm/baseline-compile-stack.txt`, SHA256
`a0d0f4cd118fcef1b6833f9ac5b33ca6592768945ae06a5c41eb4b8f358826e2`.
The first reproduction lacked fill-range resolution; its setup failure is
retained separately, not counted as a successful vulnerability reproduction.

## Consumer validation — completed results and explicit blocker

Runtime: Node 22.22.0 with disposable npm **10.9.2**. CI's Node version and
remote exact-head checks remain separate requirements. Clean consumer install
ran normal lifecycle scripts with an owned cache, not `--ignore-scripts`.

The final portable dependency contract is a direct dev dependency
`braces: file:vendor/braces-3.0.4-cypher65.1.tgz` plus `overrides.braces: $braces`.
The initial direct file override failed resolving relative to micromatch;
that failure is retained. A disposable fixture and clean full mobile install
proved the reference override and patched micromatch resolution. The final
lock delta is seven changed lines and preserves unrelated baseline entries.

| Gate | Actual result |
| --- | --- |
| Clean `npm ci` | PASS, 963 packages |
| `npm ls braces` | PASS, patched root and micromatch deduplication |
| `npm ls --all` | **FAIL, ELSPROBLEMS: pre-existing React peer mismatch** |
| Installed archive/source/license/provenance checker | PASS |
| Checker tamper self-tests | PASS, 10/10 |
| node-forge security regression | PASS |
| Unchanged full `npm audit --audit-level=high` | PASS, zero reported vulnerabilities |
| Expo doctor | PASS, 21/21 checks |
| Biome / TypeScript | PASS / PASS |
| Jest | PASS, 16 suites / 91 tests |
| iOS / Android / web exports | PASS / PASS / PASS |

The failing dependency tree is independently traced to existing
`test-renderer@1.3.0 -> react-reconciler@0.34.0 -> react@^19.3.0`, while the
application pins React 19.2.3. The relevant lock entries are identical to the
master baseline: the braces patch does not introduce this mismatch. Root
created [sub-Issue 748](https://github.com/0xjc65eth/cypher65-war-room/issues/748)
and verified its parent is Issue 737. Its implementation and validation remain
isolated on `fix/748-mobile-test-renderer-peer`; no peer check is suppressed,
no unsupported React upgrade or forced install is used. Adoption review is
withheld until a reviewed integration passes clean install, full tree and audit.

Final checker SHA256:
`c11ff5b981b9341ee4ca0b381024580117c4c654797fc85b4f51d319f33f7036`.
Self-test source SHA256:
`7de80abb68bbdd2f2059d04949f77642c5e53aff48108e8646bc8f86e107d415`.
SecurityOps independently cleared this exact source/checker version without
P0/P1/P2 findings; this is neither adoption sign-off nor GitHub approval.
The first tamper test run failed two diagnostic-message expectations; its red
log remains retained. The final checker passed all ten cases.

Consumer evidence directory: `/private/tmp/cypher65-737-red.z3ybvm/`.

| Artifact | SHA256 |
| --- | --- |
| `npm-ci-minimal-lock.log` | `5e9e0707f195c2aa3c2de445ee0864b47506c66e7503025677ca51c77c34b52d` |
| `npm-ls-braces-minimal.log` | `0c5d23f92493c8c9801bde935bf153feb40ebc95f048c39e47187615a03f5a02` |
| `npm-ls-minimal.log` (FAIL) | `a37285b11389ff9e776b7508228b9f90f447a1c68e1a266502af6204d3794d69` |
| `security-braces-final.log` | `2763a60cad9194af75d6552b38d5fedf36433776bdd56f0c175ca4f88d385113` |
| `security-node-forge.log` | `20cfa0996cc5e5f24a27ec079bb1cbae0a86f14ff3d6fde5b7b917baf64bc3e5` |
| `npm-audit-high.log` | `6d8c5c8f3d7684adb070417bd608d01ae90aa3dc26a65af03ffda4955f38d9a3` |
| `expo-doctor-network.log` | `7f0ec03013d71bc250cc258ef8a907af9fbf5493fdab2024b0be93268ac153d1` |
| `mobile-lint.log` | `3ccdb503f5626a3098ea47aed35a4afb539a6fc8bbf695feff5583495732e5d6` |
| `mobile-typecheck.log` | `c714b26fb9614d20d049a0117ecd01f35cc487ef1bfb2db75f774fcc546deb9e` |
| `mobile-jest.log` | `96a0a82140e154f42d08a936a3b23b57112a73f6a1b76ad2a42e605ade2afaee` |
| `export-ios.log` | `e59f10e584e1317e2467a56c50864dc9ba1e4197966b07cdefa741732dd7fd17` |
| `export-android.log` | `bc14dd635f2f65f561682f2b752645d583fed1018064d039a05270dbb59587b7` |
| `export-web.log` | `9a449306db52c796a32f69897c7069a0bad45d8c543464bcd8243c066a5058a8` |

## Required merge gates — pending

- Reviewed integration of sub-Issue 748 and clean integrated consumer gates.
- Conventional commit, normal Issue-branch push, linked PR, all required current-head
  checks against current master, resolved review threads and independent GitHub approval.

A clean version-range audit is a metadata gate, **not proof of a security fix**.
Keep the upstream advisory visible until official upstream remediation. Do not
claim signed-device, production-deploy or physical-hardware validation here.

## Ownership and adjacent work

Root owns the vendor/source/archive and this ledger. BackendCore owns mobile
manifest/lock/checker/CI insertion; SecurityOps independently reviews adoption.
The original dirty checkout is not edited or switched. Issue 746 is already
implemented in another user-owned chat (PR 747); do not duplicate its UI changes.
PR 715 currently has seven required green checks and the unchanged failing
mobile audit, so it is not eligible for merge until this dependency blocker and
its own refreshed exact-head/base gates and independent approval are satisfied.
