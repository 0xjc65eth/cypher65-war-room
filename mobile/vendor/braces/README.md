# Maintained braces depth-guard backport

Issue: [#737](https://github.com/0xjc65eth/cypher65-war-room/issues/737).
Internal version: `3.0.4-cypher65.1`, **not an official upstream release**.
The name remains `braces`; the original MIT license is included.

## Provenance and scope

This source is based on official `3.0.3` release commit
`74b2db2938fad48a2ea54a9c8bf27a37a62c350d`, with depth guards informed by
[upstream PR #72](https://github.com/micromatch/braces/pull/72).
The advisory is [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm).
Upstream has not released an official fix at preparation time. Do not treat
a higher internal version number or a clean audit as proof of code safety.

Parsing counts both brace and parenthesis containers. Compile, expand and
stringify also check caller-supplied AST depth, so a caller cannot evade the
parser guard by providing an AST. The default hard cap is 100 nested containers;
larger configured limits cannot raise it. Finite `maxDepth` values are floored
and clamped to 0..100, consistently across parser and walkers. Non-finite or
non-numeric values fall back to 100. In particular, `1.5` means one level,
not two. Excessive parsed input throws `SyntaxError`; excessive AST traversal
throws `RangeError` with an explicit depth-limit message, not stack exhaustion.

```js
const braces = require('braces');
braces.expand('src/{app,lib}/*.js'); // ['src/app/*.js', 'src/lib/*.js']
braces.parse('{{a,b},c}', { maxDepth: 1.5 }); // throws at depth 2
```

The published release's quote parsing, malformed-input behavior and stringify
parent handling are retained. Changes unrelated to the depth guard in the
unreleased upstream HEAD/fork are not incorporated. Expansion cardinality,
arbitrary AST width and user-supplied object getters/parent graphs are not
claimed to be generally hardened by this depth-only patch.

## Packaging and gates

The reviewed source is packed as a local tarball by `npm pack`; the mobile
root uses an override pointing to that tarball. No registry publication or
separate GitHub repository is needed. Commit the source, tarball, LICENSE,
NOTICE and lockfile together. The lockfile pins archive integrity; the CI
security checker compares installed runtime files with this source and tests
controlled rejection plus ordinary compatibility. The unchanged full
`npm audit --audit-level=high` gate remains mandatory, with no advisory filters.

Before release: reproduce the unpatched failure in an isolated subprocess;
run the published release suite unchanged against this source; test direct
ASTs, boundaries, mixed/escaped/malformed patterns and normal consumer globs;
then clean `npm ci`, `npm ls --all`, node-forge/braces security checks, Expo
doctor, lint, typecheck, Jest and iOS/Android/web exports. Current-head remote
CI and independent GitHub approval are still required. No test fixture is
evidence of a signed iOS application, physical ASIC or deployed service.

Retire this override only after an official compatible upstream release has
the actual depth fix, equivalent regressions pass and a reviewed Issue/PR
updates the lockfile. Do not silently replace it with a floating tag or version.
