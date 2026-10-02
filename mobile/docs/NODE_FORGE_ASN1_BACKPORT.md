# Temporary node-forge ASN.1 signature-verification backport

## Scope and provenance

The mobile dependency tree temporarily pins `node-forge` to the full upstream commit
[`ceba34402e329f0365134f23fe19898756527d65`](https://github.com/digitalbazaar/forge/commit/ceba34402e329f0365134f23fe19898756527d65)
from [digitalbazaar/forge PR #1152](https://github.com/digitalbazaar/forge/pull/1152). The
override uses the HTTPS repository URL and a full commit SHA; it does not depend on an
SSH key or a moving branch/tag. npm reports the source snapshot as `1.4.1-0`, a prerelease
package version, not an upstream npm release. The lockfile also records the resolved
commit and archive integrity. The CI security regression script checks that provenance
has not drifted before testing the package.

The upstream PR adds a check that the RSA DigestInfo's nested ASN.1 digest-algorithm
sequence contains exactly the expected OID and optional NULL. Its regression vector is
adapted in `scripts/check-node-forge-fix.cjs` from `digitalbazaar/forge`'s
`tests/unit/rsa.js` in PR #1152. The upstream project declares `BSD-3-Clause OR GPL-2.0`.

## Reproduce the verification

From `mobile/`, use the repository's Node version and a clean dependency install:

```sh
npm ci
npm run test:security-node-forge
npm audit --audit-level=high
npm ls node-forge --all
```

CI performs the regression gate immediately after `npm ci` and before `npm audit`. A
fresh-cache installation was also checked with SSH configuration disabled; npm fetched
the pinned source archive over HTTPS. The audit result only means the current npm advisory
metadata no longer reports a high/critical finding for this dependency tree. It does not
prove the package secure, establish that upstream has released a fix, or replace code
review and the exploit/compatibility regression test.

## Advisory status and lifecycle

At the time this temporary backport was introduced, [GHSA-86w9-cpqp-85rv](https://github.com/advisories/GHSA-86w9-cpqp-85rv)
listed affected releases through `1.4.0` and no patched release, while upstream PR #1152
remained open. Recheck both upstream and the advisory before changing this override; the
prerelease version string alone is not evidence of a fix.

Remove the override and its lockfile change only after upstream publishes an official
fixed release and the advisory identifies it as patched (or after an equivalent reviewed
release is available). Then update the lockfile with the repository's pinned npm version
without unrelated dependency churn, and rerun the regression test, clean install, audit,
dependency-tree check, mobile tests, and builds. If upstream rejects or materially changes
the fix, or the backport causes a reproducible Expo/RSA compatibility regression, revert
only this override, lock entry, CI gate, and this document together; keep the dependency
audit/security gate blocking until an alternative mitigation is reviewed. Do not interpret
an audit-green result by itself as a security sign-off.
