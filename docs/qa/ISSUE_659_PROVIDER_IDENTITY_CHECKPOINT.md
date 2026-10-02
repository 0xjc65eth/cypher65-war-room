# Issue #659 — BTC PoW Lab identity checkpoint

Date: 2026-10-02. PR: [#715](https://github.com/0xjc65eth/cypher65-war-room/pull/715).
Base synchronized locally: `c597304efb867716c0b8cf45ec72d1de8a98dc53`.

## Scope and evidence boundary

This is a partial implementation, **Refs #659**, not a closing implementation.
The exact domain and label-boundary subdomains are recognized. Lookalike
domains remain unknown. No BTC PoW Lab API URL or parser is configured, so the
provider is excluded from automatic stats probes and retains ASIC fallback.
This does not validate a live Stratum connection or a public miner API.

`has_stats_api` means a URL and parser are configured in this registry, not
that a public API exists or does not exist. A review found the old UI wording
"pool sem API pública" overstated that evidence. The panel now says
"API não integrada" alongside the actual source, `ASIC`; integrated API
failure remains a separate degraded state. No layout, CSS, animation, or
reduced-motion behavior changed. `static/app.js` was regenerated from source.

The [official dashboard](https://btcpowlab-pool.com/dashboard) documents a
human-facing interface, not a versioned per-address JSON contract. Research
did not locate a provider-owned versioned specification; that is not proof
that none exists. No real address, wallet, secret, or individual API endpoint
was queried. Before adding a normalizer, obtain an official schema or redacted
representative fixtures covering units/windows, timestamp timezone, worker
count semantics, null/missing values, and unknown addresses.

## Local validation

- Pool/Stratum domain suite: **549 passed**, 17 warnings, **95.71%** line
  coverage for `services.pool_intelligence`, gate `--cov-fail-under=80`.
  The warnings concern SQLite resource cleanup; they are not silently green
  fixes or physical-hardware acceptance evidence.
- An initial five-file selection passed 185 tests but failed the package-wide
  coverage gate at 55.54%. It omitted rollback, safety, and Stratum suites.
  The final run expanded tests across that same package scope; it did not
  lower the threshold or exclude modules to turn the gate green.
- JS core: **1549 passed**. Regression-first run failed exactly two wording
  assertions before the source fix, proving the tests detect the old behavior.
- Affected Playwright: **16 passed**, desktop/mobile, including BTC PoW Lab
  with normal and reduced motion. Real application bootstrap; synthetic pool
  reports. These are not live provider integration tests.
- `npm run check:frontend`: exit 0; generated-bundle, DOM, a11y, tokens,
  mobile-XSS, JS, visual/axe, and unit-mutation checks passed. Its legacy
  failed-fetch audit is addressed separately by PR #725; this run does not
  certify that inherited probe against service-worker interception.
- Black, fatal Flake8, Bandit medium/high gate, orphan-monkeypatch guard,
  JavaScript syntax, generated-bundle drift, and `git diff --check`: passed.

Local artifacts (not uploaded):

- `/private/tmp/cypher65-659-pool-coverage.xml`, SHA-256
  `862fea79942279ae598a2927e76a36eb417b563287c82cfed47c8e1b2f4cfe3a`.
- `/private/tmp/cypher65-659-pool-pytest.xml`, SHA-256
  `ca16955d39d88e426a2394eb151b1b5bd578188742ac7292b9ca4dcd23623058`.

## Release gates

Independent technical review is not GitHub approval. Require all protected
checks green on the exact published head, current base, resolved review
threads, and an independent GitHub approval before squash merge. The mobile
dependency security mitigation remains in PR #723; do not duplicate it here
or bypass its gate. Issue #659 remains open until its API acceptance criteria
are implemented from verified evidence.
