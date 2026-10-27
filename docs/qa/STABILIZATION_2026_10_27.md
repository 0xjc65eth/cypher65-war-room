# Stabilization campaign checkpoint — 2026-10-27

## Executive summary (Português)

Corrigidos e publicados: contrato numérico de pools, teste de relógio de Rentals
e isolamento/freshness do cache SQLite. O alinhamento React DOM/Expo restaura
a instalação mobile, mas não resolve as três HIGH restantes de Zod. Nenhum
merge/deploy foi executado por este agente; #882/#884 foram integrados por um
ator externo durante a campanha. As Issues sem aceite comprovado continuam
abertas. O checkout original, com alterações de dashboard, foi preservado.

## Authority, bases and evidence boundaries

Latest attached prompt authorizes isolated fixes/Issues/commits/PRs and forbids
merge, production deployment, payments, credential changes and miner commands.
No network scan or live pool query was made. Public GitHub/npm/documentation
reads are distinct from operational provider access.

Initial default branch: `adbfcd7d120487c2b80558fc7e3599fc820034f5`.
Externally advanced master observed later:
`0fa259eb5e333dc24f33df74fefb420c072b16a2` (#882 then #884).
External updates are preserved; an old green result is not approval or evidence
for a changed head. AGENTS/workflow/contribution/audit/architecture/data/test
instructions and all six actual CI workflows were inspected. Only root
AGENTS.md was found. Existing open Issues/comments and open/recent PRs were
read before creating new findings; all-state duplicate searches are recorded
in #881/#883/#885.

## Published lots and actual tested source

| Issue / PR / branch | Tested commit | Local evidence | Status |
| --- | --- | --- | --- |
| #881 / #882 / `fix/881-pool-numeric-contract` | `1a5cab725b3bf78c94f37ec4d8067e5bd3330300` | 5,157 Python PASS, 4 skips, 86.39%; scoped 164 PASS/94.98%; JS core 1,834 PASS | Fixed; externally merged as e241947, not by root |
| #883 / #884 / `fix/883-rental-evidence-clock` | `6ab73fefb381832e550626d7d193c9b4714588ab` | 5,090 Python PASS, 4 skips, 86.35%; scoped 32 PASS; frozen-clock 3 PASS | Fixed; externally integrated into master0fa259e; external branch update c52af76 was not the full-suite tested source |
| #885 / #886 / `fix/885-isolated-telemetry-cache` | `4a5f403ef84520dc7e7f84cd9399240ad3709654` | 5,098 Python PASS, 4 skips, 86.42%; scoped 17 PASS/83.66% | Fixed in PR; external head776286a revalidated with 208 composed tests /90.78% combined module coverage |
| #845 / `fix/845-sdk-react-dom-alignment` | Final SHA in PR/git history | Strict clean install PASS; full tree PASS; Expo Doctor21/21; lint/types; Jest25 suites/200 tests; security regressions | Partial; final post-install validation and exact-head CI recorded separately |

Do not sum full-suite counts into unique tests or infer production certification.
Local Python is3.14.6; CI uses3.13. Existing read-only venv supplies pytest9.1.1,
pytest-cov7.1.0; isolated Hypothesis6.168.0; CI static tools Black25.1.0 and
Bandit1.9.4. Four full-suite skips: two blueprint collections (PyYAML absent),
private-Gist credentials absent and Sentry SDK absent in that local venv.
Warnings include unclosed SQLite connections; they were not suppressed.

Full Python runs used scratch databases and an out-of-tree plugin denying
external DNS/sockets while allowing loopback simulators. No physical, payment,
installed-native or production-load success is claimed. Raw logs/XML live in
`/private/tmp/cypher65-stabilize-20261027-4NywAr/` and a durable artifact copy.

Preserved failures: #881 initial53FAIL/8PASS; initial full suite1 rental-clock
FAIL/5,148PASS; baseline frozen-clock reproduction1FAIL; cache baseline5FAIL;
an intermediate cache-init placement error; scoped cache coverage74.51% FAIL.
The first mobile install inherited the user's global `legacy-peer-deps=true`
and is not valid gate evidence. Explicit false reproduced ERESOLVE; subsequent
clean runs use `--legacy-peer-deps=false --force=false`. Global config was not
changed. An export accidentally overlapped a clean install and failed on a
removed dependency; it is invalid verification, not a product regression.
The final export must run after installation finishes, without that overlap.

## Actionable triage (ownership recommendations, not GitHub assignment)

| Issue(s) | Expected / observed / cause | Owner / priority | Acceptance / dependency / status |
| --- | --- | --- | --- |
| #859 | Zero HIGH vs fresh audit3HIGH: Zod<4.6.6 via Expo CLI; partial#872 did not complete acceptance | SecurityOps, FrontendGod / P1 | Reopened; compatible v3 remediation + bounded regression + zero-HIGH audit required; no global v4 override or Expo54 downgrade |
| #845 | Reproducible Expo tree vs react19.2.3 + DOM19.2.9 ERESOLVE in current master CI | FrontendGod / P1 | SDK57.0.31 expects both19.2.3; aligned partial fix. Security gate#859 remains separate; AI screen passed current full Jest but historic root cause not certified |
| #835/#842 | Session/physical-command boundaries already implemented; do not duplicate | SecurityOps, BackendCore / P1 | Hermetic suites pass in full run; exact composed release review/checks still required. Physical certification is separate#386 |
| #843/#841 | Currency/unit fail-closed and stable probability inversion/tails already merged | AlgoQuant, BackendCore / P1 | Current full regressions pass; no money/hashpower/profit guarantee or blanket Issue closure |
| #844 | Follow-redirects patched, credential stripping must remain | SecurityOps / P1 | Security regressions rerun; final mobile gate not green while#859 remains |
| #881/#883/#885 | Nonfinite/zero metrics; future-clock fixture race; shared/stale cache | BackendCore, QA / P1/P2 | Scoped fixes/evidence above, independent PRs; #885 still requires review/current-head checks |
| #836/#838 | Mini War Room/Thermal already implemented | FrontendGod / P2 | Preserve privacy/stale/source contracts; full JS/core regressions and remote browser CI, not OBS/native certification |
| #837 | Manual energy profile delivered; solar MQTT/HA contract/transport/replay incomplete | BackendCore, FeatureArchitect / P2 | Executable next lot: separate read-only schema/replay contract with synthetic sensors. Real broker/hardware remains external; no automatic profile approval |
| #659 / PR#715 | Host recognition is partial; public API schema/units/windows unknown | BackendCore / P2 | Provider-owned versioned docs/redacted fixtures; no guessed fields, API activation or duplicate identity work |
| #606/#607 | Diagnostic baselines already delivered; acceptance SLO absent; TEL-001 policy exists | Architect, BackendCore / P2 | Product/Ops-approved topology/latency/memory/backlog/repeat protocol; do not relabel baselines as SLO gates |
| #598 | Snapshot lacks reliable payout balance/current rail contract | BackendCore, AlgoQuant / P2 | Source-tagged balance+configured rail/rules or explicit changed acceptance; no marketplace balance reuse |
| #600 | Consumable applicable floor/ceiling source absent | AlgoQuant / P2 | Versioned source or operator inputs; no assumed tariff/CBECI number |
| #399/#386 | Native/signing and physical validation not certified | Architect, SecurityOps / P2 | Separate executable native gaps from signing/device/physical matrix; no simulated hardware PASS |
| #330 | Code/runbook exists, real payment settlement/activation absent | SecurityOps, Ops / P2 | Authorized operator secrets + masked checkout/settlement/idempotency evidence; forbidden in this campaign |
| #22 | Migration intentionally traction-gated | Architect / P3 | Approved traction + private-Gist/Postgres rehearsal; no unsolicited infrastructure migration |

## Technical research with concrete implementation consequences

Consulted2026-10-27; only primary evidence supports these conclusions.

| Source / version | Implication |
| --- | --- |
| [Python3.14 math.isfinite](https://docs.python.org/3.14/library/math.html#math.isfinite), [Python3.13 JSON](https://docs.python.org/3.13/library/json.html#infinite-and-nan-number-values), [RFC8259 §6](https://www.rfc-editor.org/rfc/rfc8259#section-6) | Validate conversion, scaling and aggregation; strict JSON/property regressions added in#881. |
| [OWASP API1:2023](https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/) | Device/session/object scope needs adversarial tests; cache isolation test is module-level, not proof of a live tenant exploit. |
| [OWASP SSRF cheat sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html) | Preserve DNS/redirect/destination validation; no generic LAN scan or operational connection used for this audit. |
| [SQLite WAL documentation](https://sqlite.org/wal.html) | WAL still permits SQLITE_BUSY; keep explicit contention/invariant testing. Existing3000ms busy timeout/NORMAL at services/bootstrap.py is not a production SLO; #606/#607 remain gated. |
| [Expo compatibility guidance](https://expo.dev/changelog/mitigating-critical-security-vulnerability-in-react-server-components), installed official expo57.0.31 `bundledNativeModules.json`, [npm metadata](https://registry.npmjs.org/expo/57.0.31) | Keep exact React/DOM/native-renderer matrix; restore DOM19.2.3 instead of forcing peers/upgrading React alone. |
| [React GHSA-xqc2-xf4c-x3h3](https://github.com/react/react/security/advisories/GHSA-xqc2-xf4c-x3h3), October14 advisory | Listed affected packages are react-server-dom-{parcel,turbopack,webpack}, not react-dom. No RSC package was downgraded; audit remains3HIGH Zod, not falsely zero. |
| [Zod advisory](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5), installed v3 consumer contract | v4.6.6 global override is not a proven v3-compatible fix. Reopen#859 and preserve the high/critical gate. |

## Review, release and next action

Enterprise self-review used workflow/security/quality/test/team references:
Backend/Data numeric/cache semantics; Security no auth weakening/new I/O;
QA real SQLite/serializer/property/clock evidence; Frontend existing motion
and source/bundle untouched; DevOps no CI gate changes; Product external gates
explicit. This is not formal independent GitHub approval.

No root merge, force push, deployment, payment, credential change or physical
command. Root PRs were created as drafts; external actors later changed state.
Recheck live head/base/reviews/threads/checks before any authorized release.

Next: compatible bounded Zod3 remediation under reopened#859, then fresh clean
install/tree/Doctor/audit/lint/TS/Jest/exports and exact-head CI. Independently,
prepare the original#837 read-only sensor contract in its own branch; preserve
provider/hardware/SLO/signing/payment/traction evidence gates above.
