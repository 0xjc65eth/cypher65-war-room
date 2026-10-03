# Issue #750 — Console observation fidelity

Date: 2026-10-03. Base: `47b84464251691bf18b0bebdc35f72f3f7b29685`.
This follows the externally merged #747, not its author branch. The original
user checkout remains untouched; implementation uses an isolated Issue branch.

## Executive summary

O detalhe não permanece aberto com estado aparentemente atual quando a entidade
desaparece da resposta atualizada. Temperaturas Celsius válidas entre -40 e 150
continuam observáveis, inclusive negativas. Hashrate, potência e contadores
mantêm a validação não negativa. Não houve comando físico ou acesso a pool real.

## Implementation

- `consoleNumber` supports explicit inclusive field bounds; unsigned callers
  retain the zero minimum. The temperature caller alone uses the backend's
  `axe_fleet/models.py` Celsius contract, [-40, 150]. Non-finite values, booleans,
  empty strings and container values remain unavailable.
- A selected ID absent from current console rows closes the native dialog.
  The existing close handler restores focus to a surviving entity or search.
  API failures still retain qualified last observations; existing tests verify
  that independent behavior. No command dispatch or security flag changed.
- Generated `static/app.js` was rebuilt from the source fragments.

## Regression-first evidence

Before the source fix, eight browser cases failed: two defects × desktop/mobile
× normal/reduced motion. Screenshots and traces show the removed entity's open
online-looking detail and signed Celsius rendered unavailable. The added core
assertions failed four times: -40, numeric/string -5, and out-of-range 151.
The pre-existing 14 browser cases passed on the integrated base.

After the fix, the unchanged expanded browser file passed **24 cases**;
JS core passed **1,649 assertions**. This includes 40 repeated keyboard detail
open/close cycles, pointer entry's computed 160ms timing, instant keyboard and
reduced motion, focus fallback, and absence of Fleet mutation requests in the
removal scenarios. These are synthetic observation tests, not hardware results.

The full frontend pipeline passed on a fresh isolated server, with the original
application rate limits and check sources unchanged. The first combined run
failed axe (proxy score 88; only h1/p/html reported). That reduced-document
failure is preserved, not relabeled green; accumulated rate limiting is a
plausible cause, not a demonstrated root cause. A standalone unchanged axe
retry and the complete fresh-server retry passed with zero violations and
100/100 proxy scores in both viewports. No threshold or production source
change was used between these retries.

The first full Python attempt stopped during collection because the original
Python 3.14 runtime lacks Hypothesis. The existing Python 3.13.13 test runtime
contains Hypothesis 6.168.1; no dependency was installed or original environment
modified. Its full-suite retry uses the actual CI coverage scopes and the
unchanged 80% gate: **4,141 passed, 3 skipped, 573 warnings**, **85.96%** coverage
in 375 seconds. Two collection skips concern Render blueprint tests because
this runtime lacks YAML; the third requires real private-Gist credentials.
No credential was supplied. These skips are not tested integrations. Both
owned application servers were stopped and recorded `OUTBOUND_ATTEMPTS []`.

## Local source and artifacts

Artifacts remain local, not uploaded, under
`/private/tmp/cypher65-747-current-qa.uWMJpP/`.

| Source / artifact | SHA-256 |
| --- | --- |
| `static/src/39b-dashboard.js` | `5629b5887ccf77d2c935ec375623e4f5593a0f26711f80cb59662bd8fea5d0c7` |
| `static/app.js` | `410fa4583d73098a8042b61283e0f5ca91e413099b66a19a8da2255f744f119a` |
| `tests/test_app_js_core.js` | `eabbaf32ef90c73f7ec7d2822987dec9bc4ae614c89f077a97410c21aa042b29` |
| `tests/e2e/terminal-console.spec.js` | `28d5591c9b5ce2e6c8767e46acd209f7eba9e28644aa92810831adc3658b6aa4` |
| `red.log` (eight expected failures) | `b34ab43e782f3548191dcf3d7d12dea229fffb157f76f7248a83f541d59f1825` |
| `red-core.log` | `4096db3fc0ab4ecae8820e962f1301c9241c3aae72dd27d931b6eb9545a678d1` |
| `green.log` | `ca30a29ab7ceeafeb9255c68443f91b25ecaddbbc2e9e975830e1e389d5a724c` |
| `green-core.log` | `a98da66a5a6e09d4cdeb457014caa6d67cd4ae4523581adae2fad998262d913c` |
| `frontend.log` (first failure) | `0477e50ee9a70baeeed36b1b715812ab46594f3e5b3542a93d0058c3ed4e85ef` |
| `frontend-retry.log` | `ba7e358710b8202b1183fc7feba7441526bc30863908bb67b8d49ee4b3c022eb` |
| `pytest.log` (collection failure) | `402548ae4aaf4995fb795746ab3fcd44bd8b5f2282c7653aab77cddcc847cb5b` |
| `pytest-retry.log` | `25f5f944d8bcc8df4bd99af6983f8027219e9ec313e6af1d10ae686926abc1ae` |
| `coverage-retry.xml` | `e6318622cbd6afbaad60a764439c4e34529f15bd2e7b210b70e2091b8f71c858` |
| `frontend-server.log` | `224742562eb0bd29e75f797856fc49f70e564707d32f8c90a945febdb65e9528` |

## Review and release boundary

Enterprise source review checked field bounds, DOM escaping, missing-row focus,
source-failure behavior, generated-bundle identity and command isolation.
The confirmed motion weighting is Emil primary, Jakub secondary, Jhey selective;
no CSS, entry/exit duration or reduced-motion rule changed. A local HTML motion
report was rendered offline in both themes at 1440/390px, without overflow and
with final-state reduced-motion fallback. It remains outside the scoped commit.

Subagents hit quota limits, so no new independent team approval is claimed for
this fix. Require exact-head remote CI, resolved threads and independent GitHub
approval before squash merge. Local QA does not certify production or deployment.
