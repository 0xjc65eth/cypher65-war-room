# Issue #741 — bounded lender-identity test oracle

## Scope and provenance

Issue #741 was created before implementation. This is a test-oracle repair,
not a change to profitability formulas, recommendations, inputs or prices.
The original property compared separately rounded money fields with a fixed
absolute tolerance that was smaller than one representable float step at
large magnitudes. The supplied deterministic example fails that oracle on
the unchanged master-equivalent baseline.

| Checkpoint | Actual source revision | Result |
| --- | --- | --- |
| Explicit-example red | `b2682a2fe25c379b487c802f44ef570bf1c20117` | One intended property failure |
| Focused green | `96e6daa1e2a76d8c8e17fd241522ff9b18be4a18` | 25 tests passed |
| Root full, original base39fa | `96e6daa1e2a76d8c8e17fd241522ff9b18be4a18` | 4097 passed, 3 skipped; 85.59% coverage; exit 0 |
| Root full, refreshed base402f | `59a8ae6913398830b7ea5023d617cc8e40390cbe` | 4125 passed, 3 skipped; 85.60% coverage; exit 0 |

The refreshed source incorporates externally merged #740, #744 and #743.
Root did not perform those protected merges. Relative to master
`402f57da689378bd5c0b52bc4fc1e4a942bdae2a`, the implementation delta is only
`tests/test_numeric_properties.py`. Documentation commits must not be
relabeled as source revisions on which the local runs actually executed.

## Oracle contract

The explicit example uses `ths=75`, `rate=78187493531`, `mining=1.416015625`
and `price=0.375`, with zero power cost. Comparing raw-then-rounded and
independently-rounded paths differs by `0.00048828125` (one ULP), exceeding
the old `0.0002` bound. This demonstrates an oracle false negative, not a
financial formula defect or a proof that every formula is correct.

The repair keeps `rel_tol=0`. Its absolute envelope is the larger of
`2e-4` (four half-quantum decimal rounding contributions) and two ULPs at
the largest compared money magnitude. The property domain, 150 generated
examples, finite/JSON invariants and existing assertions remain intact.
Negative controls reject a one-cent error at ordinary and approximately
2.2-trillion-dollar scales. This is not a universal cent-precision claim:
at extreme magnitudes, a cent may not be representable by a binary float.
The envelope includes the compared result; independent review found no
material false acceptance, while noting operands-only scaling could make
the oracle more independent. No relative percentage tolerance was added.

Production `helpers.py` SHA256 remains
`9a556e7f3ffcecc56d14f53f87b95810900ae322e1d0b7a66d9fed03c59fb4a8`.
Test file SHA256 at the green checkpoints is
`596e1135c8918c481fc71f41d956faa597de80b06459a8858384d97c6311cf2e`.

## Retained evidence

All paths below are local artifacts, not downloadable CI artifacts.

| Artifact | SHA256 |
| --- | --- |
| `/private/tmp/cypher65-741-red.xml` | `72093983654e3fb32371febe51cde3af528d13a6d7024ef9d8c3e5e45fe293cf` |
| `/private/tmp/cypher65-741-focused-final.xml` | `d6a0adde5ec859c34d08b56610fc7991172fbc3a2578fcc290a473b690bf7bce` |
| `/private/tmp/cypher65-741-root-validation.SXHLVp/full-tests.xml` | `3c310781a28a5e49193d2e1fadb3b77776f3977728c46a65c09a4ba0241dfd62` |
| `/private/tmp/cypher65-741-root-validation.SXHLVp/full-coverage.xml` | `7bc4165049c7f66e85b1987d22a97f3771a13ea1ac1c0d3b3ded688ecc1397a1` |
| `/private/tmp/cypher65-741-root-validation.SXHLVp/full-tests.log` | `eb6379e37ef2eeafd4256c0360a3759f835548d653a2cd2cd09232b864b0d210` |
| `/private/tmp/cypher65-741-root-validation.SXHLVp/current-base-tests.xml` | `28363508fac8b77552dd1464b84eea3ecde581cb37b35475ba072b61014e9fc1` |
| `/private/tmp/cypher65-741-root-validation.SXHLVp/current-base-coverage.xml` | `3e5fea34db7a84e9ff7314dc444a13a9f88700663c9d1f167e3ee4449651fcb7` |
| `/private/tmp/cypher65-741-root-validation.SXHLVp/current-base-tests.log` | `728f8896f329b55d9e8d3ba961b766fce420f08c11e3e1d99d8a9c04f22078ad` |
| `/private/tmp/cypher65-741-root-validation.SXHLVp/js-core.log` | `71796bd873c0013a279b05cb3626592ba4dc73be399580d7dc9fc1ea03d23c06` |
| `/private/tmp/cypher65-741-root-validation.SXHLVp/black-baseline.log` and `black-candidate.log` | Both `f8e5515ea893aa51f7fd1a3c28c73d3499a93499d8652f3400f27a66bfdbb552` |

Refreshed full JUnit totals 4128 cases, zero failures/errors and three skips:
the two existing Render blueprint collection skips and the real private-Gist
integration requiring explicit credentials. No new skip was introduced.
These credentials-dependent checks are not reported as exercised. The full
run retains 573 warnings and took 229.70 seconds.

Root full runs use the existing Python 3.13 runtime, a clean environment
with installed Node in PATH and `PYTHON_DOTENV_DISABLED=1`. Test-local
listener permissions were explicitly approved; no provider, production
account, hardware command, payment or deployment is exercised.

```bash
env -i PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin \
  PYTHON_DOTENV_DISABLED=1 /private/tmp/cypher65-runtime599/bin/python \
  -m pytest tests/ -q --tb=short --disable-warnings \
  --junitxml=/private/tmp/cypher65-741-root-validation.SXHLVp/current-base-tests.xml \
  --cov=app --cov=helpers --cov=axe_fleet --cov=services --cov=core \
  --cov=routes.admin_routes --cov-report=term-missing \
  --cov-report=xml:/private/tmp/cypher65-741-root-validation.SXHLVp/current-base-coverage.xml \
  --cov-fail-under=80
```

## Review, quality and remaining gates

Independent SecurityOps/Architect review of source96e6 found no P0/P1/P2.
This is technical review, not an independent GitHub approval. Root checked
the refreshed base and confirmed the same test-only delta. JS core 1560,
17-fragment drift, JS syntax, orphan-patch guard, fatal Flake8 and diff
checks passed on refreshed source59a8. Black, Flake8 and Bandit also passed
the exact production-path scopes configured in CI. Black --check of the entire legacy
test file fails both on unchanged base39fa and on the candidate; baseline
and candidate outputs are retained. No unrelated whole-file formatting,
skip, failing-test filter, audit suppression or dependency downgrade was
used to manufacture a green gate.

The mobile security gate remains a separate Issue #737: the current
GitHub-reviewed braces advisory lists affected versions through 3.0.3 and
no patched release: https://github.com/advisories/GHSA-vfj7-8cjw-p6xm.
PR #743's externally updated final head `fe63deceb1f70c9afcb540a7e7bc04eb62428d0f`
was merged by `0xjc65eth` despite its recorded mobile check failure; root
does not describe that state as all-CI-green or infer how approval rules
were satisfied. Exact-head CI and independent approval remain required
for this new PR. No root merge, deploy or governance bypass is authorized
by this checkpoint.
