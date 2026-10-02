# Issue #659 — BTC PoW Lab identity checkpoint

Date: 2026-10-02. PR: [#715](https://github.com/0xjc65eth/cypher65-war-room/pull/715).
Original implementation and validation base: `c597304efb867716c0b8cf45ec72d1de8a98dc53`.
Latest base synchronized locally: `4e2cc2e5827cfa19e16e78f56c229138557a0742`.

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

## Validation after external security/rental merges

Root normally integrated master `31d21e31adc4f8ad2eb4aaf0c5ee23b3f68de1fa`
into this isolated branch, producing `d640f880c74ec8336df405b3b80d96381961ea01`.
On that revision, the pool/Stratum/freshness-snapshot and rental-evidence
selection passed **629 tests**, with 22 SQLite resource warnings and **95.71%**
coverage of `services.pool_intelligence` (threshold 80%). JS core passed
**1565** assertions; generated-bundle drift, syntax, diff, commitlint, Black
on the four changed Python files, fatal Flake8 and Bandit medium/high passed.

The first identical Python attempt in the restricted sandbox produced
601 passes and 28 failures at synthetic loopback `socket.bind` (`EPERM`).
The authorized loopback rerun above passed; the first run is not called green.
An extra Black check on unchanged `tests/test_pool_detection.py` failed a
pre-existing formatting difference; that file has no diff against master and
was not reformatted as part of this provider change.

Local rerun artifacts, not uploaded:

- `/private/tmp/cypher65-659-postmerge-allowed-pytest.xml`, SHA-256
  `5546021df355622b2954f7ce01d905c3d2fdefaadbf56d46c9f11ea502dadcb9`.
- `/private/tmp/cypher65-659-postmerge-allowed-coverage.xml`, SHA-256
  `cea5cc1fddb7efaca06b1d8a90467423676565a8ebdf2c4e4b886325c49daaf6`.

Master `31e108a6d9ff1f57fdce9d9245954c9b2d0eb797` was subsequently integrated
normally, adding the already merged #725 audit fix without changing pool
production inputs, producing `1512c31003a6f271ebc2b6615c807db753f95eaf`.
On that source revision, affected Playwright passed **16 tests** in 1.3 minutes
across desktop/mobile and normal/reduced-motion modes; synthetic pool reports,
not real provider integration. The isolated E2E server was stopped afterward.
The strict frontend pipeline passed with 1565 JS assertions, zero console/page
errors or overflow, and one actually intercepted snapshot HTTP 500 with zero
remaining skeletons in each desktop/mobile viewport. Axe reported zero
violations and 100/100 proxy scores, with one mobile `incomplete` check retained.
The monkeypatch-target guard and nine snapshot-failure helper tests passed.
Pipeline output is retained at
`/private/tmp/cypher65-659-postmerge-frontend.log`; affected E2E HTML at this
worktree's `e2e-report/index.html`. The normal local boot may read public market
data; it is not production, customer-LAN or physical-ASIC evidence. Exact-head
remote CI and independent GitHub approval remain required before any merge.

After external #726 and #727 merges, master
`7c40f9d003aa4506eb261963fda93dd0cae4b02b` was integrated normally. The incoming
changes are the scoped Rentals toolbar and the separate #606 diagnostic; they
do not change the pool provider/resolver/statistics production inputs. The
merged-source bundle drift and JS core (1565 assertions) were rechecked. The
629-test and 16-E2E runs above retain their actual earlier source revisions;
they are not mislabeled as reruns on this later integration.

Master `4e2cc2e5827cfa19e16e78f56c229138557a0742` was then merged normally,
producing `76de9473d360cfdbf8b207a48c3d4e903b760023`. Incoming #728 changes only
`docs/RENTALS_TOOLBAR.md`; all tracked paths outside `docs/`, including provider
production inputs, are byte-identical to pre-integration head `48bb7d8`.
Bundle drift, JS core (**1565 assertions**) and JS syntax passed on that merged
revision. This checkpoint update is also documentation-only. No Python/E2E
suite or app server was rerun; the 629-test and 16-E2E records retain their
actual earlier source revisions and do not constitute current-head GitHub gates.

## Release gates

Independent technical review is not GitHub approval. Require all protected
checks green on the exact published head, current base, resolved review
threads, and an independent GitHub approval before squash merge. The mobile
dependency security mitigation from PR #723 is now in this base; the earlier
mobile failure does not describe the new head. Do not bypass any gate. Issue
#659 remains open until its API acceptance criteria
are implemented from verified evidence.
