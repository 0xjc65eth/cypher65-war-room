<div align="center">

# ⚡ CYPHER65 · WAR ROOM

**Real-time Bitcoin mining operations dashboard** — fleet telemetry, live probability engine,
solo/pool/rental/lease profitability, hashrate market intelligence, alerts & automation.

`Python · Flask · SQLite · Vanilla JS · React Native`

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](requirements.txt)
[![Tests](https://img.shields.io/badge/tests-800%2B%20pytest%20%2B%20JS%20core%20%2B%20E2E-brightgreen.svg)](tests/)

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
| **Probability Engine** | P(block)/share, expected block time, cumulative P progression, hash-proximity ladder, quantum-lock health score |
| **Profitability** | POOL / SOLO / RENTAL / LEASE scenarios with break-even, fiat conversion (USD/BRL/EUR/GBP), variance-aware math |
| **AXE Fleet Command** | ASIC registry with chip/VR temperature, 1h hashrate, efficiency (J/TH), power (W), latency/ping advice, remote commands |
| **Hash Market** | Braiins / NiceHash / KissMyHash / Parasite rental offers, BTC + USD per TH/day, provider filters, warm background cache |
| **Alerts & Automations** | Rule engine with cooldowns, history, tenant-scoped persistence |
| **AI Operator** | Natural-language assistant over fleet, probability, market and metrics |
| **Multi-tenant** | JWT auth with tenant isolation for fleet, alerts and automations |
| **Learning & Support** | Bitcoin whitepaper, free book library, cypherpunk support panel (BTC / Lightning / hashrate donations) |
| **Mobile companion** | React Native app in [`mobile/`](mobile/) for on-the-go monitoring |

## 🏗 Architecture

```
┌─ app.py                 Flask app — REST API, SSE stream, background poll workers
├─ core/                  Device registry, alert & automation engines, safety, diagnostics
├─ axe_fleet/             ASIC fleet registry, connector, remote onboarding (Tailscale)
├─ services/              Polling, per-user snapshots, hashrate market, probability, tenant, auth, push
├─ routes/                API blueprints (dashboard, alerts, settings, device control, solo mining, export)
├─ static/ + templates/   Dashboard UI (templates/dashboard.html, static/app.js, static/style.css)
├─ mobile/                React Native companion app
├─ tests/                 800+ pytest, JS core tests, Playwright E2E suite
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
# Python unit + integration (800+ tests)
python -m pytest tests/ --cov=app --cov=helpers --cov=axe_fleet --cov=services --cov=core --cov-fail-under=45

# JS core tests (rendering helpers, probability math, terminal)
node --test tests/test_app_js_core.js

# Playwright E2E (spawns its own server on a free port, RATE_LIMIT_PER_MINUTE=1000)
npm install
npm run test:e2e
```

The CI workflow (`.github/workflows/ci.yml`) gates merges on all suites plus a **45% coverage floor**.

## 📚 Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system design & data flow
- [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) — persistence model
- [`docs/SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md) — security review
- [`docs/DESIGN_SYSTEM_V2.md`](docs/DESIGN_SYSTEM_V2.md) — UI design system
- [`docs/REMOTE_ACCESS_TUTORIAL.md`](docs/REMOTE_ACCESS_TUTORIAL.md) — Tailscale remote access
- [`docs/AUDITORIA_PROD_READINESS.md`](docs/AUDITORIA_PROD_READINESS.md) — production-readiness audit
- [`docs/`](docs/) — full index (mobile, milestones, audits)

## 🛡 Honest Telemetry

- External APIs (pool, mempool, CoinGecko) are polled in the background; failures never fabricate data.
- Stale responses are served from the last **real** cached value with a `stale` badge in the UI.
- `/api/v1/status` reports integration health (`online` / `stale` / `offline`).

## 📄 License

[MIT](LICENSE) © 2026 [0xjc65eth](https://github.com/0xjc65eth)

---

Built for the cypherpunks. Don't trust — verify. ⛏
