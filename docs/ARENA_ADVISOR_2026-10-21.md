# CYPHER65 /arena /advisor — 2026-10-21 checkpoint

## Resumo executivo

O cadastro manual e a identidade canônica já existem: não há evidência para
reescrevê-los. As prioridades comprovadas são isolamento de sessões mobile,
correção do alvo de probabilidade e despacho seguro de comandos. Três agentes
reais fizeram propostas independentes e contestação com o agente raiz; depois
atingiram o limite de uso. O root conferiu os artefatos e continuou as validações.
Nenhuma aprovação GitHub foi simulada. Não houve merge, deploy, compra,
pagamento ou operação em ASIC real. O roadmap não está concluído.

## Baseline and capability map

Repository: `0xjc65eth/cypher65-war-room`, live master `9d4123e`.
Main user checkout: `fix/798-console-ids-chart-init`, `ec3bdf6`, five modified
tracked files plus `docs/PR1-PR7-SERIES.md`; preserved without edits or staging.
Initial live inventory: 13 open issues and 9 PRs; PR #715 already covers partial
BTC PoW Lab recognition. Do not duplicate that work. New findings are #841–#845.
Stack: Flask/SQLite, generated vanilla-JS bundle, React Native/Expo57; not Next.js.

| Capability | Evidence/classification | Remaining boundary |
| --- | --- | --- |
| Tenant+MAC identity, aliases, tombstones, DHCP reconciliation | Verified with SQLite fixtures; `axe_fleet/registry.py` | Not physical attestation; IP/wallet/name alone are insufficient |
| Manual fleet registration and cloud/local-agent split | Implemented; UI `49-axe-fleet.js`, routes onboarding/probe | Hosted cloud cannot scan customer LAN; require local outbound agent |
| AxeOS telemetry normalization | Partial integration; source adapters and pinned contract tests | Actual hardware/firmware matrix remains #386 |
| Braiins/cgminer discovery-to-registration | Partial: parser returns no MAC, registration correctly refuses it | Obtain verified stable identity; do not relax fail-closed MAC validation |
| Fleet freshness/units | Trusted latest telemetry and stale states exist | Preserve H/s, W, degrees C, timestamp/window/source; no missing-as-zero |
| Mobile session boundary | Broken baseline; implemented in #835 branch | Exact-head CI, independent review, native fault/E2E evidence |
| Block Lab fixed10% target | Wrong baseline; corrected in draft PR #846 | Constant600s Bitcoin model; not all models or multi-count tails |
| Block Lab target-solver endpoint | Partial/unavailable: no live network inputs | Keep INSUFFICIENT_INPUTS; do not invent a source |
| Agent commands | Existing policy/auth/confirmation gates; #842 hardening | Lost ACK and IP-reuse risks; MAC check is not cryptographic identity |
| Rentals/market economics | Partial; mixed-currency/unknown-unit defects #843 | Quote defaults are not executable all-in offers or profit |
| Payout net rail, cost bands, BTC activation | Input/operator-blocked #598/#600/#330 | Do not infer payout rail, tariff or production credentials |
| Mini/thermal/energy views | #836 partial; #838/#837 not implemented | Preserve sequence after P1s; no restricted third-party code copied |

Data flow: firmware/pool/network/provider -> collector/adapter -> normalized,
tenant-scoped SQLite/cache -> Flask API -> web/mobile -> server-authorized
confirmation -> queued dispatch -> ACK -> independent observed reconciliation.
Pool workers do not prove physical temperature, energy or ASIC health. ACK is
not a verified physical effect; best share is historical, not progress.

## Arena proposals and adversarial decisions

| Perspective/issue | Proven problem and proposal | Alternative / principal objection | Decision |
| --- | --- | --- | --- |
| D + C, #835 | A callbacks/cache/native writes can cross B; immutable session leases and keyed subtree | Logout-only clearing misses async work; rekey loses login feedback | Implement; shared non-sensitive progress/notice fixes the objection |
| B, #841 | 600s10% inverse yields about0.01756% forward probability; use one consistent Poisson inverse | Rewrite all math/use dependency adds unnecessary risk; ratio may exceed feasible capacity | Local stdlib fix with round-trip/extreme tests, scenario labeling |
| A + C + D, #842 | Lost ACK can replay effects; cached IP does not verify present target | Durable local journal vs server at-most-once; conservative delivery may lose an action before execution | Never blindly replay physical delivery; unknown + reconciliation, fresh MAC/protocol guard |
| B, #843 | MRR paid values may be treated BTC regardless of currency; raw unknown scale treated TH/s | FX conversion requires source/time; invented conversion is unsafe | Separate tracked P1; fail closed rather than fabricate economics |
| E + A | Manual registration already exists; firmware compatibility is overstated by fixtures | Broad new UI/adapters would duplicate code and conceal evidence gaps | Reuse existing flows, make partial support explicit, prioritize exceptions/freshness |

Top-five advisor queue, by risk rather than age: #835 (SecurityOps/FrontendGod),
#842 (SecurityOps/BackendCore/Architect), #844 (SecurityOps/FrontendGod), #841
(AlgoQuant/BackendCore), #843 (AlgoQuant/BackendCore). #845 is the cross-cutting
mobile gate repair. All have high-confidence source evidence, no recurring cost
added, medium implementation/review risk; hardware/provider access is not used
as a substitute for tests. #386/#399 remain physical/native evidence boundaries.

## Focused competitive matrix

Accessed 2026-10-21; documented capabilities are not tested integrations.

| Feature/reference | CYPHER65 gap | Decision/effort | Validation |
| --- | --- | --- | --- |
| [AxeOS OpenAPI, ESP-Miner v2.14.2](https://raw.githubusercontent.com/bitaxeorg/ESP-Miner/v2.14.2/main/http_server/openapi.yaml): GH/s, multiple windows, fan RPM vs percent | Physical version coverage, not missing parser | Reuse existing normalization; Low | Pinned fixtures then explicitly authorized hardware; GPLv3 code not copied |
| [Braiins Manager v2 documentation](https://manager.braiins.com/api/docs/v2/description/authentication): fleet API and async management | Manager-cloud integration not verified; not equivalent to local BOS REST | Assess read-only adapter; Medium | Root subsequently read the introduction through Exa; auth/pagination/rate/tenant contracts precede opt-in credential tests |
| [Braiins Hashpower API](https://hashpower.braiins.com/api/): configurable units/fees | Current quote defaults do not prove duration/capacity/all-in cost | Evidence envelope before ranking; Medium | Root subsequently read settings/fees through Exa; explicit unit/currency/fee/age and unknown states remain mandatory |
| [MRR API v2](https://www.miningrigrentals.com/apidocv2): currencies/scales and historical retention caveats | #843 normalization; pruned0% must not prove zero delivery | Correct contract before opportunity labels; Medium | Non-BTC/unknown-unit/retention fixtures, no purchases |

No feature-availability, benchmark superiority, license compatibility or physical
support is inferred merely from documentation. No paid service was provisioned.
Minimum competitive bar: honest freshness/units, coherent identity, safe commands,
auditable economics and recoverable offline/error states. Broader algorithms,
ML/AI automation and cross-chain expansion wait for these central contracts.

At most three actionable experiments, not achieved10x claims:

1. Model Guardrail (#841): automated forward/inverse/unit checks. Targets
   10x Efficiency + Zero Friction; measure model-review time and false-solved rate.
2. Quote Evidence Envelope (#843 follow-up): comparable currency, scale, fees,
   capacity, duration and age. Targets 10x Efficiency + Zero Friction; validate
   fewer manual conversions and zero unsupported opportunity classifications.
3. Exceptions-first Mini Monitor (#836): current/stale/unknown coverage without
   control surfaces. Targets Zero Friction + Visual Impact; test time-to-detect
   stale telemetry and small-screen/OBS legibility. No claimed measured uplift.

## Evidence and release checkpoint

- A/C baseline: 133 identity/discovery/command tests +29 capability/API tests
  passed with fixtures; general duplicate/manual-missing reports not reproduced.
- B baseline: 356 existing math/market/rental tests passed; #841 strict red35,
  final expanded585 pass, root focused252 pass, module coverage95.65%.
- #835: [session checkpoint](ISSUE_835_SESSION_ISOLATION.md):191 mobile tests,
  selected lines95.79%/branches81.02%, lint/TS/exports pass; doctor/audit fail.
- #842: 304 related tests pass. Coverage across the three entire large modules
  is57.25%: the80% gate FAILS. Changed executable lines54/56=96.43%, explicitly
  not a replacement for the full gate. Keep draft until wider CI/review passes.
- Draft #846 exact head `d8d5f18`: mobile CI failed at Expo compatibility;
  later audit/lint/TS/Jest/export steps skipped. Other checks were still running
  at observation; local green is not all-green CI.
- ResourceWarnings and the baseline AI-test timeout remain recorded, not hidden.
  Three agents hit account usage limits before final independent handoff; root
  review of their code is not an approval of root-authored #835 changes. After
  resumption, cross-review also reproduced the AI old-handler leak and the
  command batch-expiry clock rollback case; both received explicit regressions
  and fixes before draft publication. No staged agreement was substituted.

Next: publish remaining reviewed drafts, inspect exact-head CI, repair #844/#845
in separate branches, then #843 and physical/native evidence. Resume #836 ->
#838 -> #837 after P1 gates. Do not close issues, merge or deploy from this report.

## Research refresh — evidence-first API control planes

I used Exa to review 10 sources across 2 workstreams (Manager contracts and
Hashpower pricing), plus direct MRR documentation retrieval. This is the sum of
requested search results, not ten independent validations: Manager section URLs
repeat one reference, and the Academy HTML/Markdown variants are duplicates.
The unrelated third-party PyPI MCP wrapper was excluded as authority.

Key insight: an acknowledgement is a state transition, not proof of effect, and
a price is incomplete without its model/units/fee provenance. The official
[Manager v2 conventions](https://manager.braiins.com/api/docs/v2/description/conventions)
document permission-scoped keys, idempotent intents and asynchronous terminal
status polling. Quality: vendor-authored operational reference; authoritative
for documented behavior, not an independently tested integration. This supports
the #842 reconciliation boundary, not enabling physical controls.

The [Hashpower reference](https://hashpower.braiins.com/api/) requires interpreting
prices using settings and reading the caller-visible fee schedule. Quality:
official schema/reference, current retrieval; example responses are not real
account quotes. The [Academy API guide](https://academy.braiins.com/braiins-hashpower/api)
distinguishes read-only tokens and warns that the interactive console retains
authentication in browser storage. Quality: official integration guide, not
license/eligibility or execution certification. No token was entered.

The product implication is an inspectable evidence envelope before any ranking:
source, currency, scale, observation/window, fee and availability state. Reuse
the three experiments above; no fourth feature, invented10x result, purchased
service or live automation was introduced.

Resumo executivo: a vantagem prática vem de tornar explícito o que o sistema
sabe, não sabe e ainda precisa confirmar. As fontes sustentam contratos de
integração e testes; não comprovam suporte físico, oportunidade ou lucro.

## Follow-up — 2026-10-22 Europe/Brussels

Earlier paragraphs retain the initial checkpoint; the observations below are
the later state, not replacements for failed evidence.

- Draft PRs #846 (math), #847 (session), #848 (redirect security), #849
  (agent identity/replay) and #850 (Expo patch closure) were published/attached.
  Each still requires exact-head CI and independent GitHub approval.
- #847 clean normal npm ci in a fresh clone passed;191 tests/25suites, TypeScript,
  strict lint and Forge/braces passed again. Native Keychain/restart/signing
  evidence remains NOT RUN.
- #842 first remote CI failed6 Python cases plus formatting. Follow-up6aed088
  fixes missing clock fixtures and preserves firmware-dependent capabilities.
  Full local suite4498 PASS/4 SKIP,85.71% configured CI coverage; earlier57.40%
  selected-module coverage remains recorded as FAIL. New remote CI pending.
- #843 full local suite4504 PASS/4 SKIP,85.74% configured CI coverage; rental
  module87.8%. Synthetic currency browser10/10; independent Braiins compatibility
  challenge reproduced and fixed a shared-view regression. Publication and final
  browser evidence are tracked in its own checkpoint; do not claim all acceptance.
- #845 online Doctor21/21,119 tests, strict lint/TS and three exports PASS. Its
  isolated audit still fails the HIGH fixed separately in #848.
- Local composition ONLY of #847/#848/#850 (no PR/base merge or deploy) passed
  normal npm ci/tree, Forge/braces/redirect tests, online SDK check/Doctor21/21,
  high/critical audit gate (22moderates remain),199 tests, strict lint/TS and
  iOS/Android/web exports. The only manual composition conflict kept the six new
  SDK patches plus expo-crypto in manifest/lock. This is not exact-head PR CI.
  Evidence: /private/tmp/cypher65-mobile-composed.r8hTPa/validation.log;
  SHA256 c25c19a402717534710b73ad63328cf04a189d5662bbabb43f62d27ef55b171a.
- User checkout and partial #836 remain preserved. Research skills required
  primary-source qualification and deduplication; motion guidance required
  immediate privacy removal and no decorative animation for numeric fixes.
  No GitHub approval, issue closure, merge, deploy, account payment or ASIC
  command (including hardware dry-run) was performed.
