<div align="center">

# ⚡ CYPHER65™ · WAR ROOM

**Real-time Bitcoin mining operations dashboard** — fleet telemetry, block-statistics models,
solo/pool/rental/lease economic scenarios, hashrate market intelligence, alerts & automation.

`Python · Flask · SQLite · Vanilla JS · React Native`

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](requirements.txt)
[![Tests](https://img.shields.io/badge/tests-2651%20pytest%20%2B%201401%20JS%20core%20%2B%20E2E-brightgreen.svg)](tests/)
[![Codecov](https://codecov.io/gh/0xjc65eth/cypher65-war-room/branch/master/graph/badge.svg)](https://app.codecov.io/gh/0xjc65eth/cypher65-war-room)

</div>

---

CYPHER65 War Room is a self-hosted command center for Bitcoin miners. It turns raw pool
telemetry, ASIC fleet state and network data into actionable decisions — with an
honest-telemetry principle: **no mock data, no fabricated prices**. When an external source
fails, the UI shows a stale/offline badge with the last real cached value, never an invented number.

## ✨ Features

| Module | What it does |
|---|---|
| **Live Mining** | Share timeline, worker/pool hashrate, best-difficulty tracking, network difficulty, event stream + live terminal |
| **Block Statistics** | Per-window P(≥1) estimates, model mean interval, session-work probability estimate and best-share/target ratio. These are not countdowns, progress or predictions. |
| **Scenario Economics** | POOL / SOLO / RENTAL / LEASE constant-input scenarios, modeled cost threshold and fiat conversion (USD/BRL/EUR/GBP); no profit promise. |
| **AXE Fleet Command** | ASIC registry with chip/VR temperature, 1h hashrate, efficiency (J/TH), power (W), latency/ping advice, remote commands |
| **Hash Market** | Braiins / NiceHash / MRR / Parasite rental offers, BTC + USD per TH/day, provider filters, warm background cache |
| **Rentals Hub** | MRR + Braiins rentals, per-rental P/L (historical network HR), cost vs market, worst-rig leaderboard, concentration risk, arbitrage window + overpay alerts, ⚡ one-click Braiins spot buy with balance guard, portfolio time series |
| **Auto-Pilot** | Automation rules with fail-closed arming, per-tenant action budget (rate limit), deadlock prevention, SafetyEngine-validated execution |
| **Alerts & Automations** | Rule engine with cooldowns, history, tenant-scoped persistence; Discord/Telegram webhooks |
| **AI Operator** | Natural-language assistant over fleet, probability, market and metrics (DeepSeek/OpenAI, SSE streaming) |
| **Multi-tenant** | JWT auth with tenant isolation for fleet, alerts, rentals, settings and exports (1000+ tenants) |
| **Learning & Support** | Bitcoin whitepaper, free book library, cypherpunk support panel (BTC / Lightning / hashrate donations) |
| **Mobile companion** | React Native app in [`mobile/`](mobile/) — Command, Fleet, Block, Market, **Rentals**, AI |

## 🏗 Architecture

```
┌─ app.py                 Flask app — REST API, SSE stream, background poll workers
├─ core/                  Device registry, alert & automation engines, safety, diagnostics
├─ axe_fleet/             ASIC fleet registry, connector, remote onboarding (Tailscale)
├─ services/              Polling, per-user snapshots, hashrate market, probability, tenant, auth, push
├─ routes/                API blueprints (dashboard, alerts, settings, device control, solo mining, export)
├─ static/ + templates/   Dashboard UI (templates/dashboard.html, static/app.js, static/style.css)
├─ mobile/                React Native companion app
├─ tests/                 2650+ pytest, JS core tests, Playwright E2E suite
└─ docs/                  Architecture, data model, audits, design system, mobile strategy
```

## 🚀 Quick Start

```bash
git clone https://github.com/0xjc65eth/cypher65-war-room.git
cd cypher65-war-room

cp .env.example .env        # set BTC_ADDRESS + WORKER_NAME
./run.sh                    # creates a venv, installs deps and starts the server
```

Open **http://localhost:8765** in your browser.

### Manual setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

### Local demo data

Set `DEBUG_MOCK=1` to seed demo devices for development. In production (default) seeding is
disabled and any leftover demo rows are purged — the dashboard only ever shows real devices.

## ⚙️ Configuration

All settings are environment variables (see [`.env.example`](.env.example)):

| Variable | Default | Purpose |
|---|---|---|
| `BTC_ADDRESS` | — | Wallet address to monitor |
| `WORKER_NAME` | — | Worker label on the pool |
| `PORT` | `8765` | HTTP port |
| `POLL_INTERVAL` | `15` | Pool polling interval (seconds) |
| `RATE_LIMIT_PER_MINUTE` | `300` | API rate limit |
| `SECRET_KEY` | random | Session signing (rotate for persistence) |
| `API_KEY` | — | Static HTTP basic auth |
| `TENANT_API_KEYS` | — | JSON `{tenant: api_key}` map → multi-tenant JWT auth |
| `DEBUG_MOCK` | `0` | `1` enables demo seeding (dev only) |
| `CERT_FILE` / `KEY_FILE` | — | Optional TLS termination |

## 🧪 Testing

```bash
# Python unit + integration (2650+ tests)
python -m pytest tests/ --cov=app --cov=helpers --cov=axe_fleet --cov=services --cov=core --cov-fail-under=65

# JS core tests (rendering helpers, probability math, terminal)
node --test tests/test_app_js_core.js

# Playwright E2E (spawns its own server on a free port, RATE_LIMIT_PER_MINUTE=1000)
npm install
npm run test:e2e
```

The CI workflow (`.github/workflows/ci.yml`) gates merges on all suites plus a **65% coverage floor** (matching `codecov.yml` and the local `--cov-fail-under=65`).

## 📚 Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system design & data flow
- [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) — persistence model
- [`docs/DEPLOYMENT_OPS.md`](docs/DEPLOYMENT_OPS.md) — deploy & operations guide
- [`docs/DESIGN_SYSTEM_V2.md`](docs/DESIGN_SYSTEM_V2.md) — UI design system
- [`docs/REMOTE_ACCESS_TUTORIAL.md`](docs/REMOTE_ACCESS_TUTORIAL.md) — Tailscale remote access
- [`docs/WALLET_POOL_SETUP.md`](docs/WALLET_POOL_SETUP.md) — wallet & pool configuration guide
- [`docs/archive/`](docs/archive/) — consolidated historical audits (stale, kept for reference)
- [`docs/`](docs/) — full index (mobile, milestones, audits)
- [`docs/TRADEMARK_POLICY.md`](docs/TRADEMARK_POLICY.md) — brand protection: registration strategy, costs & enforcement
- [`TRADEMARKS.md`](TRADEMARKS.md) — public trademark usage guidelines

## 🛡 Honest Telemetry

- External APIs (pool, mempool, CoinGecko) are polled in the background; failures never fabricate data.
- Stale responses are served from the last **real** cached value with a `stale` badge in the UI.
- `/api/v1/status` reports integration health (`online` / `stale` / `offline`).
- Probability uses current worker/network snapshots and the window shown in the UI. The model assumes independent hashes and constant hashrate/difficulty within that window. A statistical mean is not a deadline; historical shares and round work do not improve the next-hash odds.
- Economic values use the latest available price plus configured fees/costs. They are constant-input scenarios in the displayed units and window, not profit, ROI or break-even guarantees.

## ⚡ Licensing and checkout (off-by-default)

> **Current public deployment (Aug 2026):** checkout is not operational
> (`payments: null`, `btcpay: false`, `webln: false`). The UI offers beta/trial
> access or activation of an existing operator-issued key; it does not show a
> purchase action. Prices below are product hypotheses, not an available sale.

The PRO gate (`Monte Carlo scenarios`, `best-share ratio history`, `30d history`,
`webhooks`) is a no-op until the operator activates it. These explicit controls
flip the gate ON; BTCPay/WebLN do so only when checkout and fulfillment are
complete:

| Env var | Purpose |
| --- | --- |
| `PRO_LICENSE_KEYS` | Static comma-separated keys (manual mode) |
| `PRO_KEYS_DB=1` | Dynamic keys issued manually via `POST /api/admin/licenses` |

The Lemon Squeezy adapter is **legacy and intentionally unavailable for new
checkout**, even if all variables below exist. Its authenticated webhook and
dedup ledger remain for historical orders, but the generated CYPHER65 key has
no authenticated delivery channel back to the checkout browser. Until that
channel is implemented and tested, these variables do not activate the gate or
a purchase CTA:

- `LEMON_SQUEEZY_API_KEY` — private API credential
- `LEMON_SQUEEZY_WEBHOOK_SECRET` — verifies `x-signature` on `/api/payments/webhook`
- `LEMON_SQUEEZY_STORE_ID` / `LEMON_SQUEEZY_VARIANT_ID` — checkout creation

The old webhook can issue a `C65-XXXX-XXXX-XXXX-XXXX` key idempotently, but it
does not expose that key in its HTTP response and must not be treated as a
customer-delivery mechanism. Manual/beta keys use `POST /api/admin/licenses`
with `X-API-Key` (or localhost) and are activated through `X-License-Key`.

## ⚡ R2 — Bitcoin channel (off-by-default)

The upgrade modal can accept **Bitcoin** only after the channel is released.
The production decision is **BTCPay Server**: it creates a unique invoice,
supports on-chain + Lightning through the store, and signs settlement
webhooks. The legacy `LN_INVOICE_ENDPOINT` adapter is not a public commercial
fallback in this beta. BTCPay stays off until it is fully configured and a
real settlement, duplicate webhook and license activation have been
reconciled. Before that, checkout returns
`503` with `payment_state: "checkout_unavailable"`; the tab and every purchase
CTA remain hidden:

| Env var | Purpose |
| --- | --- |
| `BTCPAY_URL` / `BTCPAY_API_KEY` / `BTCPAY_STORE_ID` | BTCPay Greenfield API (invoice creation + polling) |
| `BTCPAY_WEBHOOK_SECRET` | Required HMAC-SHA256 secret verifying `BTCPay-Sig` on the settlement webhook |
| `BTCPAY_RECONCILIATION_VERIFIED` | Release gate; keep `0` until the real end-to-end runbook passes, then set `1` |
| `PAYMENT_BTC_ADDRESS` | Operator revenue/reference address, separate from `BTC_ADDRESS`; BTCPay invoices settle to the wallet configured in the BTCPay store |
| `LN_INVOICE_ENDPOINT` | Legacy internal adapter; does not enable public checkout in the beta |

Flow after release: **Buy PRO → Bitcoin** → BTCPay invoice (QR / copy /
countdown) → signed settlement webhook → a `C65-XXXX-…` key is issued and
honored immediately via the existing `X-License-Key` header. Self-custody:
0% processor fee, no KYC — tax obligations stay with the operator.

Payment fulfillment is server-authoritative: signed webhooks/preimage proofs
are accepted only for locally-created orders/invoices, replays are deduplicated,
and paid licenses are issued idempotently. Payment webhooks never return the
license key and the license database does not retain buyer email for new paid
licenses. BTCPay status polling also requires the opaque token returned only to
the browser that created the checkout; an invoice ID alone cannot retrieve a key.

Production setup, least-privilege API scopes, webhook registration, smoke
test and rollback: [Deploy & Operations — Canal Bitcoin em produção](docs/DEPLOYMENT_OPS.md#-canal-bitcoin-em-produção--btcpay-server).

## Beta safety gates

- Physical commands are read-only by default. Real execution requires
  `dry_run:false`, an exact one-time human confirmation bound to tenant,
  device, command and parameters, a bounded adapter timeout and audit logging.
- Browser settings and configuration exports never return stored provider
  credentials. Encrypted remote backups require a dedicated stable Fernet key;
  plaintext legacy Gists are rejected.
- Named tenants receive only their own fleet/session data plus public network
  context. Legacy operator-global history and wallet views fail closed.
- MRR and Braiins diagnostics are read-only and return structured status
  without echoing credentials. Provider acceptance still must be verified with
  the operator's real account.
- Public hardware release remains blocked until the evidence in
  [Physical validation matrix](docs/PHYSICAL_VALIDATION_MATRIX.md) records 200
  dry-runs and 50 controlled human commands across Bitaxe, NerdQaxe and one
  farm ASIC family.
- Payments remain unavailable until a real BTCPay settlement, signed webhook,
  duplicate delivery and license activation are reconciled end to end. Provider
  credentials alone do not enable checkout.

## 📄 License

[MIT](LICENSE) © 2026 [0xjc65eth](https://github.com/0xjc65eth)

**CYPHER65**, **CYPHER65 WAR ROOM** and the ⚡ logo are trademarks of 0xjc65eth — the MIT license covers the code only. See [TRADEMARKS.md](TRADEMARKS.md) for usage guidelines.

---

Built for the cypherpunks. Don't trust — verify. ⛏
