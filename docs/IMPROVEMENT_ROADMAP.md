# 🛣️ CYPHER65 WAR ROOM — IMPROVEMENT ROADMAP (CPO/CFO)

**Owner:** CPO (Product & Strategy) with CFO mandate · **Status:** Active
**Baseline date:** Aug 2026 · **Ground rule:** every shipped item below is anchored
in real code + hermetic tests; planned items are labeled as estimates.

> North star: take the platform from *monitoring dashboard* to *autonomous
> mining operation system* — the only upgrade that changes positioning (and
> therefore pricing power).

---

## 1. Executive Summary

The platform's structural strength is **data clarity at low cost-to-serve**
(cached single poll, gzip, SQLite on a $5 VPS serving ~200 users). Its two
weaknesses are **cross-tab journey fluidity** and **undeveloped monetization**.
This roadmap executes the value funnel first (monitor → predict → decide →
buy), then the Big Bet.

**Global Health Index: ~71/100** — composite of the 4 lens averages from the
Global Baseline Matrix (A 6.7 · B 7.9 · C 8.1 · D 5.5 → mean 7.05/10).

**Already shipped (this roadmap's executed work):**
- ✅ **P0-1** Live Mining → Probability funnel
- ✅ **P0-2** Hash Market Decision Matrix
- ✅ **P0-3** Command Center widget (3 contextual action cards)
- ✅ **R1** Revenue activation (Lemon Squeezy + dynamic PRO keys + upgrade modal)
- ✅ **Quick wins** gzip compression + Block Hunt background pause
- ✅ **Ops/security (CFO sweep):** standalone worker entrypoint
  (`services/workers.py` — destrava gunicorn/multi-processo), blacklist JWT
  persistida em SQLite via `REVOKED_TOKENS_DB=1`, `requirements-dev.txt`,
  `dependabot.yml`, `.pre-commit-config.yaml` (hygiene-only),
  `CHANGELOG.md`, `CONTRIBUTING.md`
- ✅ **Multi-tenant fleet isolation (audit de escopo):** snapshot `axe_fleet`
  filtrado por tenant (fail-closed), rotas `remote/*` + leituras do fleet com
  `@require_tenant`/`@role_required("viewer")`, SSRF do `diagnose` fechado,
  `test-devices` scoped, power-cycle por tenant — 13 testes de regressão

**The Big Bet:** 🛸 **Auto-Pilot** — merge Live Mining + Probability + Automations
(§5).

---

## 2. Global Baseline Matrix (11 tabs × 4 lenses)

| # | Módulo | A: Journey (1-10) | B: Data Clarity (1-10) | C: Cost-to-Serve (1-10) | D: Monetization (1-10) |
|---|--------|:---:|:---:|:---:|:---:|
| 1 | Dashboard | 8 | 9 | 8 | 3 |
| 2 | Wallet | 7 | 9 | 9 | 5 |
| 3 | Fleet | 7 | 8 | 7 | 6 |
| 4 | Live Mining | 8 | 9 | 8 | 4 |
| 5 | Probability | 6 | 7 | 8 | **9** (Monte Carlo gated) |
| 6 | Hash Market | 7 | 8 | 7 | **9** (LEASE + highlights) |
| 7 | Alerts | 7 | 8 | 8 | 5 |
| 8 | Automations | 5 | 6 | 8 | **8** |
| 9 | Docs | 8 | 9 | 9 | 2 |
| 10 | Learning | 6 | 8 | 9 | 5 |
| 11 | Support | 5 | 6 | 8 | 4 |
| | **MÉDIA** | **6.7** | **7.9** | **8.1** | **5.5** |

**CFO read:** force in clear data (B) and low cost-to-serve (C); the two
investment targets are cross-tab journey (A) and monetization (D).

---

## 3. Executed Work (P0s + Quick Wins)

### 3.1 ✅ CFO Quick Wins

| Item | Verdict on the improvement doc | Action |
|---|---|---|
| 1. Cache Mempool/CoinGecko | Already existed (`latest_snapshot` + `btc_price_cache` TTL) | Archived |
| 2. Parallelize fetches | Already done (`ThreadPoolExecutor(max_workers=8)`) | Archived |
| 3. Pause animations on hidden tab | Matrix paused; **Block Hunt ran at 60fps** | ✅ Fixed |
| 4. Rate-limiter "sledgehammer clear" | Already fixed (prune-by-expiry) | Archived |
| 5. WebSocket/SSE "5s polling" | Polling is 15s, served from cache | Archived |
| 6. SECRET_KEY + Gunicorn | Already mitigated (render.yaml forbids gunicorn) | Archived |
| 7. **gzip/brotli** | Did not exist — the only real quick win | ✅ Implemented |
| 8. SQLite → Postgres | Keep SQLite at current scale | Archived |
| 9. Split app.py + Alembic | Partially modularized (blueprints + services/) | Later |

**Shipped:** `flask-compress==1.24` (`app.py`, `requirements.txt`) — all JSON/HTML
responses gzip-encoded; Block Hunt rAF loop skips `update/draw` while the tab is
hidden (`static/app.js`). Regression test: `test_gzip_compression_enabled`
(`tests/test_anti_mock.py`).

### 3.2 ✅ P0-1 — Live Mining → Probability funnel

**Why first:** the product's central value loop (monitor → predict → decide),
zero new external dependencies, unlocks the monetization funnel (Monte Carlo is
already PRO-gated).

| Layer | Change |
|---|---|
| Backend | `/api/chart-data?chart=share_dist` now returns `target_diff` (network difficulty) + `target_bucket` (clamped histogram bucket); `null` when unavailable / on `cum_p` — never fabricates data (`app.py`) |
| Frontend | Solid purple overlay of the network target on the share-difficulty histogram + `target <diff>` badge (`badge--purple`) + **`⚡ P(block)` CTA** that navigates to Probability (solo-stats) — operator sees in <5s how far shares are from block difficulty (`static/app.js`, `templates/dashboard.html`, `static/style.css`) |
| Tests | `tests/test_share_dist_target.py` — 6 hermetic: target present, clamp below→0, clamp above→last bucket, no network→null, `cum_p` no target, empty session |

### 3.3 ✅ P0-2 — Hash Market Decision Matrix

**Why second:** decision support on the buy side — solo vs pool vs lease with a
unified break-even, one-click CTA to the best offer.

| Layer | Change |
|---|---|
| Backend | `build_decision_matrix(...)` — pure aggregation of the 3 modes into `best_option` + recommendation + break-even; `_num()` guards NaN/inf, deterministic tie-break, honest solo fallback (`helpers.py`); attached to the snapshot's `profitability` block (`app.py:3469`) — zero new external calls |
| Frontend | New **Decision Matrix** panel in the Hash Market module: 3 cards (pool/solo/lease), best-mode badge, break-even, recommendation + `→ offers` CTA (`templates/dashboard.html`, `static/app.js`, `static/style.css`) |
| Tests | `tests/test_decision_matrix.py` — 9 hermetic: best option per mode, no-data fallback, negative-as-numeric, deterministic tie-break |

### 3.4 ✅ R1 — Revenue activation (Lemon Squeezy + dynamic PRO keys)

**Provider decision (CFO):** **Lemon Squeezy** over Stripe — Merchant of Record
(no US entity needed; global tax/VAT handled by the provider), native license-key
email delivery, 5% + $0.50 per sale (vs Stripe 2.9%+$0.30 plus tax-nexus and
licensing-infra cost, or Gumroad 10%).

| Layer | Change |
|---|---|
| Core | `services/licensing.py` — `generate_license_key()` (`C65-XXXX-XXXX-XXXX-XXXX`, copy-safe alphabet), `pro_licenses` DB table (self-healing), `issue_license()` / `revoke_license()`, `_key_valid` now honors static env keys **and** DB keys (non-revoked, non-expired). Gate activates on `PRO_LICENSE_KEYS` \| `LEMON_SQUEEZY_API_KEY` \| `PRO_KEYS_DB=1`. **Off-by-default preserved.** |
| Payments | `services/payments.py` (new) — `create_checkout()` (POST /v1/checkouts), `verify_webhook_signature()` (HMAC-SHA256 over raw body vs `x-signature`, constant-time), `handle_webhook()` (`order_created` → issue). Zero new dependencies (`requests` already present). |
| Routes | `POST /api/upgrade/checkout` (503 unconfigured) · `POST /api/payments/webhook` (403 bad signature; issues key on valid order) · `POST /api/admin/licenses` (localhost or `X-API-Key`; manual/community keys) · `/api/license-status` now reports `payments` (`app.py`) |
| Frontend | Upgrade modal replaces `window.prompt`: **Buy PRO** (opens LS checkout, price driven from server payload) + redeem-key input; UPGRADE badge opens the modal (`templates/dashboard.html`, `static/app.js`, `static/style.css`) |
| Tests | `tests/test_license_keys.py` — 24 hermetic: key format/safety, issue→valid, expiry (months=0), lifetime (None), revoke, unknown-key, gate activation, signature forge rejection, webhook E2E, checkout 503/URL, admin 403/200 |

**Activation checklist (operator):** set `LEMON_SQUEEZY_API_KEY`,
`LEMON_SQUEEZY_WEBHOOK_SECRET`, `LEMON_SQUEEZY_STORE_ID`,
`LEMON_SQUEEZY_VARIANT_ID`; point the LS webhook at
`https://<host>/api/payments/webhook`. LS emails the key to the buyer; the
webhook keeps the gate in sync. (Full docs in `README.md` §R1 + licensing.py
docstring.)

**Validation status:** 960/960 pytest · 844 JS core tests · `py_compile` +
`node --check` OK · code-reviewed without blockers. (Last full-suite run;
the two final polish edits were behavior-preserving and re-validated via the
44 licensing tests + 844 JS.)

---

### 3.5 ✅ P0-3 — Command Center widget (3 contextual actions)

**Why next:** the roadmap's own priority queue (#1) — it kills the cross-tab
journey gap (A-lens = 6.7) at its root by surfacing the ONE action to take
right now as a decision card, not a raw metric. This is the advisory
read-only precursor to the Auto-Pilot Big Bet: it proves the
"trigger → action card → navigate" loop before any autonomous execution.

| Layer | Change |
|---|---|
| Backend | `helpers.build_command_center(snapshot)` — pure aggregation (no network/DB, never raises) of up to **3** cards, severity-ranked crit > gold > warn > info: `worker_offline` (crit, gated on `ts > 0` so a cold boot with no wallet never false-fires), `fleet_attention` (OFFLINE/WARNING devices), legacy `proximity_streak` (mudança retrospectiva da dificuldade dos shares, nunca odds futuras) / `proximity_milestone` (razão histórica best-share/alvo ≥1%), `capital_lease` (Decision Matrix best=lease), `negative_operation` (pool net < 0), `affiliate_buy` (operator-configured affiliate link). Each card carries `target`/`panel`/`url` for one-click navigation |
| Snapshot | `api_snapshot` injects `resp["command_center"]` computed from `resp` **after** `attach_affiliate` (regression-tested: the affiliate card must see the real resolved link, not a dead `latest_snapshot`) |
| Frontend | New **Command Center** panel at the top of the dashboard grid: card grid with severity accent bars, status badge (0 actions = "All systems nominal"), click navigates via `activateModule(target)` + scrolls to the target panel, or opens the affiliate buy URL in a new tab (`templates/dashboard.html`, `static/app.js`, `static/style.css`) |
| Tests | `tests/test_command_center.py` — 27 hermetic + integration: every rule, severity ranking, max-3 cap, cold-boot vs real-offline gate, snapshot injection, affiliate card sees the real URL |

**Design guardrail:** advisory-only (read-only) by design — Auto-Pilot's
*autonomous execution* stays gated for a later phase; Command Center only
navigates and opens links, it never issues device commands.

---

## 4. Stage 4 — Global Investment Portfolio (planned)

Classification: **Quick Wins** (M1-2, <40 dev-hrs) · **Strategic Overhauls**
(M3-4, backend/API/schema) · **Moonshots** (M5-6, AI/predictive/new revenue).
Cost figures are **estimates** from the CPO/CFO analysis, not quotes.

| Improvement Cluster | Class | Dev Cost (est.) | Projected Monthly Value | Payback |
| :--- | :--- | :--- | :--- | :--- |
| ✅ P0-1 + P0-2 + P0-3 (Live→Prob funnel + Decision Matrix + Command Center) | Quick Win | ~$4.2k | Unlocks the monetization funnel; −10% lost navigation | 2–4 mo |
| ✅ R1 revenue (LS + keys + modal) | Quick Win | ~$2.0k | Direct MRR (PRO $9/mo, per BUSINESS_PLAN) | <1 mo |
| ✅ P0-3 Command Center widget (3 contextual actions) | Quick Win | ~$1.5k | +8% session time; −10% lost navigation | Shipped |
| Wallet QR + checksum highlight + wallet health | Quick Win | ~$1.2k | −15% wrong-address support tickets | 2–3 mo |
| Support triage → auto-FAQ loop into Learning | Strategic | ~$2.0k | −30% recurring support volume (the Hidden Tax) | 3–4 mo |
| Live Mining → Block Model real-time feed (shorter feed loop) | Strategic | ~$3.0k | Fresher source windows and clearer uncertainty → PRO stickiness | 4–6 mo |
| 🛸 **Auto-Pilot** (Live+Prob+Automations merge) | Moonshot | ~$12k | Repositioning + premium tier (positioning change) | 12+ mo |
| AI Operator premium tier (per-query or PRO add-on) | Moonshot | ~$4k | New revenue stream (upsell PRO → $29/mo PREMIUM) | 6–9 mo |

**Avoid list (negative NPV):** SQLite → Postgres at current scale; heavy Alembic
migration while the schema is stable; white-label before the first paying users.

---

## 5. 🛸 The Big Bet — Auto-Pilot

**The one architectural change with the highest global impact.**

> Merge **Live Mining** (real-time telemetry) + **Block Model** (statistical scenarios, not forecasts) +
> **Automations** (trigger → action) into a single **Auto-Pilot command center**:
> when hashrate drops below its 7-day peak or the historical best-share ratio crosses a
> threshold, Auto-Pilot surfaces *the one action to take right now* (reset
> device, switch pool, buy lease) as a decision card — not a raw metric.

**Why it wins:**
- Kills the cross-tab journey gap (A-lens = 6.7) at its root.
- Sits directly on top of P0-1/P0-2 (target overlay + decision matrix) — those
  were deliberately the enabling steps.
- Automations already has `trigger → action` semantics
  (`core/alerts/automation_engine.py`); the work is unification, not invention.

**Dependencies:** P0-1 ✅ · P0-2 ✅ · P0-3 ✅ (Command Center proves the trigger→card→navigate loop) · R1 gate ✅ (Monte Carlo already PRO).
**Funding:** phased — a read-only "advisory" mode first (M3-4), autonomous
execution (M5-6) behind the PRO gate.

---

## 6. The Hidden Tax

**Docs/Learning are static + Support has no triage** — the recurring-support loop
drains dev time (~15–30% of estimated volume). Every manually-answered ticket
that could have been a FAQ is invisible cost. First mitigation: the Support →
Learning auto-FAQ loop in the Stage 4 portfolio.

---

## 7. 12-Month Forecast (if executed)

| Metric | Today | +12 months |
| :--- | :---: | :---: |
| Retention (M1) | ~35% | ~52% |
| MAU | 1–5 | 20–50 |
| NPS | ~20 | ~45 |

---

## 8. Priority Queue (next)

1. ✅ **P0-3 — Command Center** dashboard widget (Quick Win, M1-2) — **shipped**
2. ✅ **P0-4 — Wallet QR + checksum + health** (Quick Win, M1-2) — **shipped**
   - QR code puro JS (v1-10, ECC L/M/Q/H) no modal CONNECT WALLET + endereço
     com checksum destacado + health strip honesto (6 checks) + check-digits
     na status bar. Zero dependência externa — o endereço nunca sai do browser.
   - Cobertura E2E: `tests/e2e/wallet-identity.spec.js` (connect real via UI
     → QR viewBox + checksum split + COPY + health + status bar; idempotente
     e com cleanup do DB — roda no `run-e2e.sh` nos 2 projetos).
3. **P1 — Auto-Pilot advisory mode** (phased start of the Big Bet)
4. **P1 — Support → Learning FAQ loop** (kills the Hidden Tax)

---

## 9. References

- Code: `app.py` · `helpers.py` · `services/licensing.py` · `services/payments.py`
  · `static/app.js` · `static/style.css` · `templates/dashboard.html`
- Tests: `tests/test_share_dist_target.py` · `tests/test_decision_matrix.py` ·
  `tests/test_command_center.py` · `tests/test_license_keys.py` · `tests/test_licensing.py`
- Docs: `BUSINESS_PLAN.md` (tiers/pricing/unit economics) · `README.md` §R1
- Status: working tree carries P0-1/P0-2/R1 (uncommitted as of this doc)
