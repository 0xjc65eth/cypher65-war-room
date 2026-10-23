# Issue #835 — Mobile session isolation checkpoint

Date: 2026-10-21. Base: `9d4123e0e18aaef06c3b3aaf7fb7e71ea30249d2`.
Branch: `security/835-mobile-session-isolation`.
Issue: <https://github.com/0xjc65eth/cypher65-war-room/issues/835>.

## Decision and acceptance

Private store values, global offline keys, and asynchronous callbacks were not
bound to the sending authentication session. A late request or cached snapshot
could survive a token transition. This patch binds work to an immutable
in-memory `(revision, token)` lease and clears private state synchronously.
Revision checks invalidate A -> logout -> A as well as A -> B.

- Native credential operations are serialized; bootstrap is single-flight.
  A stale write is compensated before a newer writer can persist credentials.
- Login/logout/biometric callbacks retain their originating identity. Local
  logout is immediate; remote revocation uses only the captured old credential.
- Login progress and generic native-deletion notices survive subtree rekeying.
  A late old failure cannot clear a newer login's progress or display its notice.
- Snapshot, fleet, command confirmation/history and reconciliation callbacks
  check identity before dispatch and after awaits, including errors/finally.
  Offline fallback is not allowed after HTTP 401/403.
- QueryClient and navigation/screen state live inside a revision-keyed boundary.
  Old query caches are cleared synchronously without waiting for cancellation.
- Offline records use SHA-256 namespaces scoped to environment/API/token, not
  raw credentials. Unknown legacy ownership is never adopted. Writes reject
  credential fields and raw active credentials. Same-owner relaunch/offline
  support remains; cached data is not represented as live hardware evidence.
- Push permission/token workflows retain the original session. Anonymous or
  superseded work cannot register under a later account.
- A retained native AI-submit handler cannot send account A's private prompt
  under account B's bearer. The screen and device-detail callbacks now retain
  the same originating scope; late UI/biometric continuations stay inactive.
- Old private UI is removed immediately, without a delayed fade. The bootstrap
  skeleton is static and readable without motion. This follows the confirmed
  Emil-first restraint/Jakub-secondary polish weighting, not decorative motion.

Alternative: clear the store only at logout. Rejected: it does not prevent late
callbacks, native writes, 401 handlers, cache reads or biometric prompts from
crossing identities. Independent challenge also found login-progress loss and
invisible deletion errors after rekey; those observations were addressed. A
subsequent challenge demonstrated the old AI handler's pre-dispatch leak with
the real screen/axios and a synthetic adapter; this was fixed before publication.

## Observed validation

Runtime: Node 22.22.0, locked Expo 57 dependency tree; fictitious accounts only.
No real credentials, provider requests, purchase or physical command was used.

| Check | Result |
| --- | --- |
| Initial partial-tree typecheck | FAIL: LoginScreen used removed `setToken` |
| Regression-first hook races | Expected RED: 21 failed before hook implementation |
| AI screen origin regression | Expected RED:3 fail/1 pass; after fix4/4 pass, no fixture error or timeout |
| Final complete mobile Jest | PASS:25 suites,191 tests,4.848 seconds |
| Selected business-module coverage | PASS: 95.79% lines, 91.29% statements, 94.33% functions, 81.02% branches; explicit 80% thresholds |
| Real QueryClient/subtree and push tests | PASS: 17 tests, default 5-second test timeout, clean process exit |
| Strict Biome / TypeScript | PASS |
| `npm ls --all` | PASS |
| node-forge / vendored braces provenance and regressions | PASS; braces 10 tests |
| iOS / Android / web Expo exports | PASS on final production source; not signed native applications |
| Mobile XSS / generated web bundle drift / JS core | PASS: zero XSS vectors; unchanged bundle; 1,694 JS assertions |
| Network-backed Expo Doctor | FAIL: 20/21; six baseline SDK patch mismatches (#845) |
| Network-backed npm audit | FAIL: 1 high follow-redirects advisory group, 22 moderate entries (#844) |
| Knip | Advisory findings retained; no exclusions added |
| Clean `npm ci`, native auth UI E2E, device Keychain/Keystore, signing | NOT RUN for this patch checkpoint |
| GitHub approval / merge / deployment | NOT PERFORMED |

Coverage scope is explicitly the session/offline/push services, auth/fleet/
snapshot/command/scope hooks, store and SessionBoundary, not all app UI or all
API functions. API request/401 tests execute the real interceptors separately.
The only lock change is Expo-compatible `expo-crypto`; every existing package
entry, including HTTPS Forge resolution and the braces mitigation, is preserved.

The unchanged AI-screen happy-path test timed out on a clean-source baseline
(4 pass/1 fail), and on the first full patch run (159 pass/1 fail). Later full
runs passed without changing that test or its timeout; one emitted a
VirtualizedList `act` warning. This is not a claim to have stabilized it (#845).
The new boundary test's intermediate timeout and GC cleanup were also retained;
the final default-timeout run exited cleanly without `--forceExit`.

## Residual security and release boundaries

- AsyncStorage observations are owner-bound, not encrypted or protected against
  device extraction. A token digest is not a server identity or authorization.
- Native deletion failure disables restoration in this process and produces an
  explicit notice. SecureStore deletion/restart under actual platform faults
  remains unverified; do not certify biometric-protected Keychain or a shared
  device handoff from Jest. See #399 and physical validation requirements.
- Cancellation/session change stops observation/publication. It cannot undo a
  command already delivered to a remote server or hardware. Backend authorization,
  confirmation, idempotency and reconciliation remain required.
- No retries of mutable commands, timeout exclusions, audit suppressions, Expo
  package exclusions or release-gate changes were introduced.

## Reproduction and exact resume point

Checkout: `/private/tmp/cypher65-mobile-session.I1sgJ9/repo`.
Evidence: sibling `log835/` and `coverage-final/`, outside the commit.
Baseline source: `/private/tmp/cypher65-arena-baseline.g7Iqry/repo` (its dependency
tree was reused read-only, not a clean-install certification).

```bash
cd mobile
npm run typecheck
npm run lint
npm test -- --runInBand --coverage \
  --collectCoverageFrom='src/services/{authSession,sessionLease,offline,push}.ts' \
  --collectCoverageFrom='src/hooks/use{Auth,Fleet,Snapshot,Commands,SessionScope}.ts' \
  --collectCoverageFrom='src/components/SessionBoundary.tsx' \
  --collectCoverageFrom='src/store/index.ts' \
  --coverageThreshold='{"global":{"lines":80,"statements":80,"functions":80,"branches":80}}'
npm run test:security-node-forge
npm run test:security-braces
npm run build
```

Checkpoint hashes (SHA-256):

- `log835/red-hook-races.log`: `d2b400078faef53e6e89219ddad85d81fdb11a79b10dbf37739ee3bbaed200bf`
- `log835/full-final.log`: `5ce7cab3df4899437a3caddd7e64dd79fc4cc47f1fc7f9736e4d2ed6fe5e9124`
- `log835/red-screen-races-final.log`: `9c30c147304b94eedb4379bd4478e01eedd7be6e505773ffcf6c194a88b9a42b`
- `log835/boundary-push-final-5s.log`: `47b3ccead44e602c90b154199ac77a089ae66092fae5c561236b4a12fa521e3e`

Next: draft PR, clean install and exact-head CI, resolve #844/#845 without
weakening gates, obtain an independent GitHub review, then native evidence.
Keep #835 open; no merge or deploy is authorized by this checkpoint.

## Primary references

Accessed 2026-10-21. Documentation is not evidence of native-device behavior.

- [TanStack QueryClient](https://tanstack.com/query/latest/docs/framework/react/reference/classes/QueryClient):
  cancellation and cache clearing are distinct operations; current docs, installed
  Query v5.104.0 behavior is additionally tested here.
- [Expo SecureStore documentation](https://docs.expo.dev/versions/v56.0.0/sdk/securestore/):
  native biometric behavior needs a real device. This adjacent-version reference
  is not an SDK57 certification; the v57 URL was inaccessible in this review.
