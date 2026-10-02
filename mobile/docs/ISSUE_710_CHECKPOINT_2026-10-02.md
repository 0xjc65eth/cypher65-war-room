# Issue #710 candidate checkpoint — 2026-10-02

Status: local candidate only; **not security-approved, merged or deployed**.

- Branch: `fix/710-pin-forge-asn1-patch`.
- Base: `c597304efb867716c0b8cf45ec72d1de8a98dc53`.
- Checkout: `/private/tmp/cypher65-710-minlock-final-c597304`.
- Temporary upstream pin: `digitalbazaar/forge` commit
  `ceba34402e329f0365134f23fe19898756527d65` (upstream PR #1152).

See [`NODE_FORGE_ASN1_BACKPORT.md`](NODE_FORGE_ASN1_BACKPORT.md) for provenance,
the prerelease/advisory boundary and removal/rollback criteria. An audit-green
result by itself does not establish that the advisory is fixed.

## Candidate evidence

The real `security710_npm_mitigation` agent compared baseline `node-forge@1.4.0`
against the exact upstream snapshot: the upstream forged-signature vector was
accepted by the baseline and rejected by the candidate. Root reran
`npm run test:security-node-forge` successfully: exact pin/version checks,
forgery rejection, valid RSA/SHA-256 signature verification and modified-message
rejection. The gate is now included in the mobile CI job after `npm ci`.

Agent-reported completed candidate checks before its interruption:

- Minimal lockfile change preserving all unrelated entries; no whole-tree
  dependency regeneration.
- Clean-cache install with CI npm 10.9.2 and no SSH configuration/credentials;
  the immutable source archive was fetched over HTTPS.
- `npm audit`: zero reported vulnerabilities; dependency tree checks passed.
- Expo Doctor: 21/21; lint, TypeScript checking and iOS/Android/web exports passed.
- Baseline and candidate Jest: **15/16 suites, 90/91 tests passed**. Both failed
  the same `AiOperatorScreen` 5-second timeout. Full Jest is **not green**.

The agent was interrupted by the account usage limit while performing a new
final clean-install/audit/tree/Jest round after adding the durable regression
gate/documentation. That round is not claimed complete. The independent
`security710_upstream_patch_audit` agent was interrupted before a final #710
verdict; there is no independent sign-off for this candidate.

## Required before merge

1. Finish clean-install/audit/tree/regression/mobile checks on the final head.
2. Diagnose and track the demonstrated baseline Jest timeout; do not report the
   full suite green or remove/skip the failing test to get a green check.
3. Obtain independent review of the cryptographic change and its provenance.
   Recheck upstream PR/advisory status and the transitive Expo CLI use sites.
4. Publish a draft PR, run exact-head CI and obtain repository-required approval.
5. Revalidate merge rules and only then consider the authorized squash merge.

## Resumed final-head validation

The account usage query subsequently returned `ordinaryUsageAllowed: true`.
Work resumed through the same approved execution path, without a workaround.
The completed final round used commit
`dedc342256d7ad6782a39bfb15e446c11826a145` and **CI npm 10.9.2**:

| Check | Final result |
| --- | --- |
| Fresh-cache `npm ci`, SSH configuration disabled | Passed |
| `npm run test:security-node-forge` | Passed: forgery rejected; valid RSA verifies; tampering rejected |
| `npm audit --audit-level=high` | Passed, zero reported vulnerabilities |
| `npm ls node-forge --all`, test-renderer presence | Passed, one pinned forge version, no unrelated lockfile churn |
| Expo Doctor | 21/21 passed |
| Biome lint / TypeScript | Passed |
| Full Jest | **16/16 suites, 91/91 tests passed** |
| iOS / Android / web exports | Passed |

The earlier `AiOperatorScreen` timeout did not recur in two subsequent complete
suites or ten targeted repetitions. It remains historical intermittent evidence,
not a demonstrated product regression; the test was not changed, skipped or
weakened. Exact-head GitHub CI must still run and is not replaced by local results.

The clean HTTPS fetch of the full upstream SHA (cache miss) is recorded at line
1180 of
`/private/tmp/cypher65-710-final-ci-npm1092-cache/_logs/2026-10-02T16_33_34_500Z-debug-0.log`.
These logs are local temporary evidence, not uploaded Actions artifacts.

The independent Security reviewer technically approved the cryptographic patch
and immutable temporary pin, reporting no P0/P1 finding. The reviewer verified
the nested DigestAlgorithm child-count guard, upstream vector and transitive
Expo CLI/code-signing use sites; no direct application import was found. The
upstream PR remains open with no official patched release, so this approval is
for a temporary candidate backport, not a claim of maintainer release approval.
The reviewer did not independently repeat installation. This is engineering
sign-off, **not the required GitHub approval or merge authorization**.

No required audit gate, approval or CI check was bypassed. No direct push to
`master`, merge or deployment occurred at this checkpoint.
