# Energy Advisor — explicit, read-only energy scenarios

Issue: #837. Research/implementation checkpoint: 2026-10-23.

## Resumo executivo

O Energy Advisor compara cenários de energia com tarifa confirmada pelo operador, moeda, horizonte, limites e perfis revisados. Exibe a potência reportada pelo firmware com origem e validade, não presume leitura de tomada nem promete economia ou lucro. Toda alteração das premissas invalida a comparação anterior; mudanças de modelo, firmware, versão ou capacidades invalidam a revisão dos perfis. Nenhum equipamento recebe comandos.

Esta entrega não conecta MQTT/Home Assistant: solar permanece **não configurado**, sem desconto estimado. A integração real exige ponte local autenticada e evidência de origem/replay; não foi substituída por fixtures. A Issue permanece aberta até os gates e critérios restantes serem cumpridos.

## Baseline and read-only audit

1. **Verdict:** the existing fleet supplies tenant-scoped local metadata and telemetry, but there was no dedicated tariff/profile energy comparison contract or screen on master `9d4123e`.
2. **Evidence/limits:** `axe_fleet/axeos_contract.py` maps firmware power; this is not a wall meter. Registry telemetry timestamps and its measurement validity rules are inspected, not hardware-certified. Existing Auto-Pilot/control surfaces remain unchanged.
3. **Findings:** shared tenant injection alone does not fail closed on explicitly invalid credentials in local/open mode; existing SW caches same-origin GETs. New private routes add explicit credential validation and cache fences. Latest history needs deterministic ordering and a compound index rather than a tenant-wide scan.
4. **Metrics:** firmware W/H/s and observation time; manual currency/kWh and confirmation validity; modelled kWh/cost over 1–24 constant hours. No hashrate output, profitability, lifetime, thermal safety, PSU loss, cooling consumption or efficiency is inferred for a hypothetical profile.
5. **Command security:** no command, dry-run, relay, frequency, voltage, pool, payout or provider operation exists in this feature. No connector credentials are requested or returned.
6. **Validation:** real SQLite/Flask contracts and actual production JS imports; browser presentation fixtures plus an unintercepted local service-worker/Cache API probe. Hardware/broker proof is not provided.
7. **Missing evidence:** production index-build latency; real local solar agent, broker identity, reconnect/high-water replay and physical measurements; exact-head CI and GitHub approval.
8. **Release requirements:** retain draft until CI/review gates pass. Do not interpret local tests as merge, deploy or physical validation.

The mining-review skill's read-only diagnostic phase ended before the separately authorized implementation. Enterprise review and motion principles guide the implementation/release evidence; no new paid observability stack is adopted.

## Arena: proposal and independent challenge

| Problem / proposal | Alternative and objection | Evidence and decision |
| --- | --- | --- |
| Explicit manual tariff with its own validity | Reuse legacy default tariffs; objection: less typing | No operator price is established by a default. Require value/currency/validity; zero is accepted only as explicitly entered. |
| Compare operator-defined profiles | Ship invented Eco/Turbo presets or scale frequency linearly | No validated preset catalogue found. Exact model/firmware/version/capability match plus explicit review; no hardware safety inference. |
| Show eligible candidates without ranking | Recommend the lowest price as universally best | Hashrate trade-off is unknown. Preserve input order; no winning profile or performance ranking. |
| Keep solar unavailable until a local bridge exists | Fetch the user's LAN from Render or accept browser live sensor claims | Cloud cannot assume LAN access; retained/old MQTT states can look current. No broker/network ingest or arbitrary URL input added. |
| Bounded indexed local history | LIMIT 1 over existing tenant-only index | Independent challenge found scan/sort risk; add idempotent compound index and verify real initialization/EXPLAIN. |
| Session/selection-bound result | Keep old comparison while inputs change | Reviewer found approval surviving firmware change and Add Profile failing to invalidate pending results. Fingerprint-bound review and request generation fences implemented and regression-tested. |
| Visible monetary resolution | Round tiny positive costs to displayed zero | Independent reviewer identified false-free-energy presentation. Explicit sub-resolution flags and lower-bound display preserve positive-versus-zero semantics. |

## Advisor priority

P2 differentiation after #836 Mini War Room and #838 Thermal Timeline implementation/QA. This branch starts from master, not an unapproved stacked merge. Their releases and composition remain separately gated. This feature's privacy/math correctness takes precedence over adding live integrations or execution.

## API and data flow

```text
tenant-scoped axe_devices + newest axe_telemetry
  -> strict bounded evidence snapshot
operator tariff + review-bound hypothetical profiles + constraints
  -> Decimal calculation and explicit match/block reasons
  -> private response -> ephemeral browser comparison
  X no persistence of operator inputs / no command dispatch
```

- `GET /energy-advisor`: static authenticated-consumer shell, no injected private telemetry.
- `GET /api/energy-advisor/devices`: at most 100 public device identities and `truncated`.
- `GET /api/energy-advisor/snapshot?device_id=...`: owned, non-tombstoned device; newest `(ts DESC, id DESC)` row only. Payload/capabilities limited to 64 KiB at SQL selection; no older-valid fallback hiding an invalid/latest heartbeat or future sample.
- `POST /api/energy-advisor/evaluate`: computational-only, viewer access, no writes. Strict JSON <=16 KiB; duplicate keys, unknown fields, numeric strings, bool-as-number, nonfinite values, unsupported currency, out-of-range values and >8 profiles rejected. Browser UI limits profiles to three.

### Evaluation request (synthetic contract example)

```json
{
  "device_id": "owned-device-id",
  "hours": 6,
  "tariff": {
    "value": 0.3, "currency": "EUR", "source": "operator",
    "observed_at": 2000000000, "valid_until": 2000003600
  },
  "constraints": {"max_power_watts": 150, "max_cost": 1},
  "profiles": [{
    "id": "operator-profile", "name": "Reviewed scenario",
    "model": "Gamma", "firmware": "AxeOS", "firmware_version": "2.9",
    "expected_power_watts": 100, "required_capabilities": ["telemetry"],
    "approved": true
  }]
}
```

No input is a firmware instruction. `approved` records only the operator's review of this request; it is not durable approval, authentication, certification or permission to execute anything. The browser binds it to device ID/model/firmware/version/capability fingerprint, clears it when profile inputs change, and clears it on device/session changes.

### Evidence and freshness

The response contains schema version, server `generated_at`, allowlisted public device metadata, and telemetry `{state, source, observed_at, age_seconds, stale_after_s:900, power_watts, hashrate_hs, temperature_c}`. States distinguish `empty`, `unknown`, `offline`, `stale`, `current`. Only valid newest measured hashrate and power with age **<900 seconds** and canonical ONLINE/HASHING/IDLE state qualify. Zero is real; missing power is never zero. Paused/invalid telemetry markers do not qualify.

Tariff freshness is independent: `observed_at <= now < valid_until`. The response includes the explicit tariff and `tariff_state`. A fresh device cannot revive an expired tariff, nor vice versa. No solar observation exists: `{state:"not_configured",source:"local_agent",observed_at:null,age_seconds:null,power_watts:null}`. Browser solar/telemetry claims are not accepted by the evaluator.

### Computation and output

`energy_kwh = power_watts / 1000 * hours`; `cost = energy_kwh * tariff` using Decimal from validated numeric inputs. Constraints compare unrounded Decimal values. Six-place `half_up` wire amounts explicitly declare `resolution`; separate `energy_below_resolution` and `cost_below_resolution` preserve positive values rounded below wire precision. UI shows a `<` threshold rather than free energy. Explicit zero tariff or zero measured power remains zero.

`baseline.state` is `available|blocked`. Each profile has `eligible` and reason codes for stale/invalid evidence, tariff validity, operator review, identity/capability mismatch and power/cost limits. `suggestion.type = review_candidates`, `profile_id = null`; eligible IDs remain in operator input order. Eligibility means **only that these declared criteria matched**.

`expires_at` is the earlier of the telemetry and tariff deadlines. UI clears results on expiry, session/offline/navigation changes, edits/add/remove/device selection, and ignores delayed bodies after invalidation. Requests coalesce to latest intent, deadline includes JSON body (8 seconds); GET retries once after 1-second backoff. POST computations are not replayed automatically; the operator may explicitly compare again.

### Privacy / operations

Explicit invalid/conflicting Bearer/API key fails closed even in local/open mode; resolved tenant must be nonempty. All new private responses/errors use `no-store, private`, `Pragma:no-cache`, `Vary:Authorization,Cookie,X-API-Key,*`. Vary star also prevents old service-worker cache admission. Updated SW excludes decoded/normalized private path aliases before network/cache fallback. No raw payload, IP, MAC, actor note, key or broker locator is exposed. Inputs are neither logged nor persisted by this feature.

Only additive DDL: `idx_axe_telemetry_tenant_device_ts(tenant_id,device_id,ts DESC,id DESC)` in registry initialization, compatible with the separate thermal reader's same-purpose guarded index. No destructive migration or schema-version rewrite. Index creation may lock/cost time on large production databases; production latency is **not measured**. Rolling back routes/UI does not require deleting telemetry or dropping this reusable index.

### UI / motion

Original responsive industrial dark layout with measured reference, explicit assumptions, per-profile criteria and no apply button. Native fields, visible focus, keyboard operation, reduced-motion, static loading skeleton, and 180 ms header orientation entry. Inputs, profile editing and cost refreshes are instant, without pulsing, bounce or decorative graph animations. No heavy chart library or new dependency.

## Primary-source research

Consulted 2026-10-23; documented behavior, not tested broker integration. No code/assets copied.

| Source / capability | CYPHER65 gap and decision | Effort / validation |
| --- | --- | --- |
| [Home Assistant MQTT Sensor](https://www.home-assistant.io/integrations/sensor.mqtt/): expiry/availability and retained message replay | A cached replay can revive an expired state. A future local bridge must retain original observation time, enforce bounded freshness, tenant/device/source identity and persistent replay ordering; receipt time alone cannot prove recency. | High; broker disconnect/restart/retained/out-of-order tests and real local evidence required. Not implemented here. |
| [Home Assistant sensor entity](https://contributors.home-assistant.io/core/entities/sensor/): distinct power and energy units; measurement versus totals | Preserve W versus kWh and measured baseline versus constant scenario. Do not subtract a nonexistent solar measurement or forecast. | Low for manual comparison, implemented/tested; real sensor adapter remains unverified. |

Innovation is the **evidence-first interaction**, not a claimed novel physical model: Zero Friction (one explicit comparison after entering assumptions) + Visual Impact (aligned baseline/candidate cards with visible blocking reasons). Decision-speed improvement is an unmeasured experiment target, not a 10x or competitive-superiority claim.

## Acceptance / release status

| Issue criterion | This delivery |
| --- | --- |
| Typed tenant-scoped manual tariff/profile contract and units/origin/validity | Implemented; Python validation, typed JSDoc production modules checked with TypeScript strict mode |
| Missing/invalid/nonfinite/stale/future/disconnected local evidence blocks | Implemented with SQLite regressions and UI lifecycle checks |
| Operator-defined compatible reviewed profiles; no profitability/overclock claim | Implemented, explainable/unranked candidates only |
| Read-only/no automatic hardware changes | Implemented; no execution path |
| Original responsive accessible source-tagged UI | Implemented; browser fixtures are clearly not physical proof |
| Optional local-agent MQTT/HA solar contract/transport and persistent replay behavior | **NOT IMPLEMENTED / NOT CONFIGURED**; requires separately validated local bridge, not cloud LAN requests or browser readings |
| Production migration latency, hardware/broker proof | **NOT RUN** |
| Exact-head CI, independent GitHub approval and release | Required; draft PR only, no merge/deploy or Issue closure |

Validation logs and final results belong to the delivery checkpoint/PR rather than a fabricated immutable claim in this working document. Retain the initial sandbox failures (`PermissionError` binding simulated localhost servers), corrected browser NOSCRIPT test-harness assertion, and final green repetitions separately. Do not weaken tests or treat environment failures as product bugs.

## Resume

Re-read live Issues/PRs and workflow; preserve the user's dirty console-recovery checkout. Revalidate exact head CI/review, including the existing mobile blockers #844/#845, without assuming this head has the same detailed failure cause. Review composition with #852/#853 before integration. Keep optional solar ingest and hardware execution disabled until their contracts and evidence exist.
