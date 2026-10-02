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

No required audit gate, approval or CI check was bypassed. No direct push to
`master`, merge or deployment occurred at this checkpoint.
