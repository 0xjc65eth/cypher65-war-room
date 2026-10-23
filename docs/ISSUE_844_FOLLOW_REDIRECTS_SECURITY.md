# Issue #844 — follow-redirects credential isolation

Date: 2026-10-21. Base: `9d4123e0e18aaef06c3b3aaf7fb7e71ea30249d2`.
Issue: <https://github.com/0xjc65eth/cypher65-war-room/issues/844>.

**Resumo executivo:** a versão oficial 1.16.1 elimina os dois advisories HIGH
identificados na dependência mobile. Dez regressões passam sem rede ou segredos.
Os 22 avisos moderados e o gate Expo SDK preexistente permanecem visíveis;
esta entrega não autoriza merge nem deploy.

## Evidence and decision

The installed transitive path was `axios@1.20.0 → follow-redirects@1.16.0`.
The two GitHub-reviewed HIGH advisories list affected versions `>=1.16.0 <1.16.1`
and the patched version `1.16.1`:

- [GHSA-q3jh-wrc6-jgq8](https://github.com/advisories/GHSA-q3jh-wrc6-jgq8):
  array-form headers bypass credential removal on a cross-origin redirect.
- [GHSA-8r9p-f939-6h3c](https://github.com/advisories/GHSA-8r9p-f939-6h3c):
  regex metacharacters in declared sensitive-header names bypass literal matching.

Both advisories were published October 1 and updated October 20, 2026; accessed
October 21, 2026. The [official npm metadata](https://registry.npmjs.org/follow-redirects/1.16.1)
was checked using `npm view follow-redirects@1.16.1 version dist --json` against
`https://registry.npmjs.org`. The official tarball was inspected read-only.

Decision: pin the upstream release with an exact mobile override. Only the
follow-redirects lock entry's version, resolution and integrity change. Its SRI is
`sha512-FNvFGzoMLWmE6Yj9spb/zjd7yiNCHiAW9/Tg9CXrQ8wuu32HtlJOwWO11OJafl5FfY3DxTdQ0vj42zU1kvv5jg==`.
No other dependency was updated or vendored; no `audit fix --force` was used.
The node-forge HTTPS/full-SHA pin, braces archive, Babel 7, Stryker 9.6.1 and
Expo 57 entries remain unchanged. CI runs the new regression command alongside
the existing forge/braces gates without weakening those gates.

## Reproduction and regression boundary

`mobile/scripts/check-follow-redirects-fix.test.cjs` exercises the actual installed
library's exported `wrap()` API with deterministic in-memory HTTP/HTTPS protocols.
It does not replace the library's redirect state machine or header filtering.
There are no sockets, DNS lookups, account credentials or real providers. Header
values are conspicuously synthetic fixtures and `.invalid` hosts never resolve.

The ten cases cover the reviewed manifest/lock/runtime provenance; object/array
built-in credentials; same-origin compatibility; literal `^`/`|` custom names and
a normal-name control; HTTPS downgrade; and POST-to-GET content-header cleanup.
The vulnerable baseline produced **4 PASS / 6 FAIL**, including both advisory
behaviors. The patched package produced **10 PASS / 0 FAIL**. These are contract
regressions, not evidence of a production incident or proof that React Native's
shipping adapter uses Node's HTTP implementation.

## Validation

Runtime: Node `22.22.0`, npm `10.9.4`, macOS; independent disposable checkout.

| Check | Result |
| --- | --- |
| Clean `npm ci --ignore-scripts --no-audit --no-fund` | PASS; 911 packages |
| Clean normal `npm ci --no-audit --no-fund` | PASS; exit 0; 911 packages, 42 s |
| `npm ls --all --json` | PASS, exit 0; platform-optional packages are not errors |
| `npm run test:security-follow-redirects` | PASS; 10/10, ~90 ms |
| `npm run test:security-node-forge` | PASS; forgery rejected, valid RSA retained |
| `npm run test:security-braces` | PASS; provenance gate and 10/10 self-tests |
| `npm run lint` / `npm run typecheck` | PASS; 30 files linted; no TS errors |
| `npm test -- --ci` | PASS; 16 suites / 111 tests, 6.705 s |
| `CI=1 EXPO_NO_TELEMETRY=1 npm run build` | PASS; iOS, Android, web exports only |
| `npm audit --json` | 23 findings before → 22 moderate after; HIGH 1 → 0, CRITICAL 0 |
| `npm audit --audit-level=high --json` | PASS; exit 0; 22 moderate remain |
| `npm run doctor` | FAIL; 20/21 checks, six existing Expo patch mismatches |
| Lockfile scope / `node --check` / CI YAML parse / `git diff --check` | PASS |
| Exact-head remote CI / independent review / native-device E2E | NOT RUN |

The Expo mismatch versions are unchanged from the base: metro-runtime `57.0.16`,
Expo `57.0.27`, constants `57.0.21`, notifications `57.0.22`, splash `57.0.9`,
and jest-expo `57.0.5`. The current doctor expects `.17`, `.31`, `.22`, `.23`,
`.10`, and `.6`, respectively. Do not hide this failure or conflate it with the
redirect fix. No app business logic was added and no coverage gate was waived.

## Handoff

Local evidence directory: `/private/tmp/cypher65-follow-redirects-844.UEfuGo/`.
It contains red/green logs, baseline/fixed audit JSON, npm-ci logs, dependency
tree, forge/braces, lint/typecheck/Jest, doctor and export results. Source changes
are limited to the mobile manifest/lock, original security tests, the CI step and
this checkpoint. No commit, push, merge, deployment or physical operation has
been performed. Prepare a draft PR only after independent review; retain the
Expo gate as a visible blocker for merge.
