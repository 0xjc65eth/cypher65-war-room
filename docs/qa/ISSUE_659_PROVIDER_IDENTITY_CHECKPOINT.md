# Issue #659 — BTC PoW Lab identity checkpoint

Updated: 2026-10-03. PR: [#715](https://github.com/0xjc65eth/cypher65-war-room/pull/715).
Original implementation and validation base: `c597304efb867716c0b8cf45ec72d1de8a98dc53`.
Latest base synchronized locally: `60eda10d3c9fbd6373029e73750bff41bdd1b3ad`.

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

After external #730, master `cd4925df6079faa6b493a7590f1bf518e241ca9e` was
integrated normally as `3865a74acd9ae50c1ab1b7510fbb7f7671951712`. Incoming
changes add the separate #607 diagnostic CLI, its test helper and documentation;
they do not change pool/provider or other production runtime files compared
with pre-integration `d6957a4867d91eff87a05ae49e20c44964ff52e2`. On the merged
revision, JS core (**1565 assertions**), bundle drift, syntax and the
monkeypatch-target guard passed. No full suite, E2E, server or benchmark was
rerun for this bounded synchronization. The earlier 629-test and 16-E2E
records remain tied to their original sources, not this new integration.

Following externally merged #731, an ordinary local merge of master
`39fa95b5833ea0f61c8f578df1cabb388d8a61e4` produced
`49ab5a61cf87ca0f4c31f6490b55192cdc43a8e3`. Incoming changes comprise only
the three #729 fixture/test files and its QA checkpoint. All production files,
including pool/provider inputs, remain byte-identical to pre-integration
`542b6e4ea2ce4d2c3e16a95ea5dedaba24523062`. JS core (**1565 assertions**),
bundle drift, syntax and monkeypatch-target guard passed on that merged source.
No full suite, E2E, application server or benchmark was rerun here; the earlier
629-test and 16-E2E runs retain their actual source revisions. This synchronizes
the feature branch only, not an agent-performed protected-branch merge or approval.

The preceding light artifacts remain local, out of tree and not uploaded, in
`/private/tmp/cypher65-715-39fa-integration.JFITFy/`. The subsequent checkpoint
edit changes documentation only; it is not a new measured production source.

| Artifact | SHA256 |
| --- | --- |
| `bundle-drift.log` | `a96b5918454bd04b48a3526ce8cf0ce44431a81fe21af34c8ae06db728efe65b` |
| `js-core.log` | `14ca31c7f5dfd3e5489f65e9b3f2d4ed0d66a3b51abeab4d586f51583b82b8ab` |
| `js-syntax.log` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `monkeypatch-guard.log` | `b9f3743163a0fc72822b7bb4f8501cfbc9f575dd84b972dfd21e084dc3606196` |

## Current-base full validation — 2026-10-03

An ordinary merge of master `60eda10d3c9fbd6373029e73750bff41bdd1b3ad`
produced frozen source `2fc47706ec9e438ed397060c1883b812059028d0`, tree
`d6ddd2df3971c19310162fca15c694234388b68c`. This preserves the externally
merged cloud seed, trusted telemetry batching, dashboard/snapshot freshness,
comparability and profitability-oracle changes. The diff against this base
still contains the nine original #659 paths; no provider API was enabled.

Validation on that exact frozen source:

- Full Python suite: **4149 passed, 3 skipped, 573 warnings**, 281.43 seconds;
  **85.61%** total line coverage across the CI application scopes, with the
  unchanged 80% gate. Two collection skips are Render blueprint tests because
  this existing runtime lacks `yaml`; the third explicitly requires real
  private-Gist credentials. No credential was supplied. Warnings and skips
  remain disclosed, not characterized as tested integrations.
- JS core: **1590 passed**. Bundle drift checks all 17 source fragments;
  JavaScript syntax and orphan-monkeypatch guard passed.
- CI-equivalent production Black, Flake8 and Bandit medium/high gates passed;
  Black left 105 files unchanged. Bandit emitted benign `nosec` warnings.
  Diff and commitlint passed. An initial non-login commitlint capture failed
  with exit 127 because Node was absent from that shell's PATH; rerunning with
  the existing Node 22.22.0 binary passed, without installing dependencies.
- Affected Playwright: **8 desktop + 8 mobile passed**, including normal and
  reduced-motion provider cases. Each viewport ran against a fresh scratch
  server with the real application/source, no background workers and outbound
  transport denied. Synthetic pool reports exercise the renderer contract,
  not the provider API, real mining results or physical ASIC compatibility.
- The first combined Playwright run had **15 passes and 1 failure**: the
  final mobile page received HTTP 429 at `/`, with `Too Many Requests` in the
  recorded page snapshot, before `#app-shell` could load. Its logs, screenshot,
  video and trace are retained in `ui-first-test-results/`. Restarting the
  disposable server separately for each viewport isolated accumulated
  rate-limit state. No application limit, assertion, timeout or test source
  was weakened. The original failed run is not relabeled green.

All three owned QA servers were stopped. Each shutdown recorded
`OUTBOUND_ATTEMPTS []`. The harness only substitutes unrelated market/subnet
consumers and does not validate production, customer-LAN or live pool access.
This later checkpoint edit is documentation-only; these test counts belong
to source `2fc4770`, not to an untested final documentation commit or remote CI.
Independent source review found no actionable P0/P1/P2 findings, including
the interaction with the current snapshot/dashboard freshness consumers;
that is not independent GitHub approval.

Artifacts remain local, not uploaded, under
`/private/tmp/cypher65-715-current-validation.1VE090/`:

| Artifact | SHA256 |
| --- | --- |
| `full-tests.xml` | `00fc1ba9030027892c010b3ef90d7738a7eee391233bd318855d5d9d6a38d69d` |
| `full-coverage.xml` | `68d9f5aa9c5791f06fd51978463a262d26dfb4ab1316f7b9dd676d20bde04d8f` |
| `js-core.log` | `133e84b29ca68891d7e0d98466833bf3a52cd9aebc95941ce4692e05a3217d89` |
| `ui-tests.log` (first, failed) | `5a7db1cc193da97dc808f91c68466c9386f214dac39189bf24d77ab025afd50b` |
| `ui-server.log` (first) | `7f77c1e2d49ea49cc229282d10f0050bf23bd23da57a7b1d1a83292d5e35873e` |
| `ui-desktop-tests.log` | `90495aa533134195fb1e552c5180cd38177efbb3be50f572d25b1efe2285854e` |
| `ui-server-desktop.log` | `c90c9d03f76c85c288cbe837d93d58e2f251d4e2ddbd7249b4bb65d6eedb2e50` |
| `ui-mobile-tests.log` | `004725d36dc320751fc41791938b61b66e5505032f23c642098a808ae6f41228` |
| `ui-server-mobile.log` | `977469033ad9f7172cd1de756a08e1eeedb07a77b654ac6065f68c76e0c7df5b` |

Static-gate logs remain under `/private/tmp/cypher65-715-*.log`; they are
separate from the full-suite and viewport artifacts above.

## Release gates

Independent technical review is not GitHub approval. Require all protected
checks green on the exact published head, current base, resolved review
threads, and an independent GitHub approval before squash merge. PR #723
addressed the historical #710 dependency issue, not the new unpatched
`braces` advisory tracked by #737. The old eight-green CI result on `7e0abf4`
against `39fa95b` cannot satisfy current-head/current-base gates. Local Python,
JS and UI success does not override a failing mobile security audit. Do not
bypass any gate. Issue #659 remains open until its API acceptance criteria
are implemented from verified evidence. No root protected merge or deploy
was performed.
