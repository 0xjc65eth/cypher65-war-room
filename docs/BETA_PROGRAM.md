# CYPHER65 — Beta Program

**Version:** 1.0
**Date:** 2026-08-23

---

## Overview

The CYPHER65 War Room beta program gives early testers 30 days of free PRO access in exchange for feedback.

### What's included in PRO (beta)
- Probability Engine (Monte Carlo, proximity meter, 30d history)
- Webhooks (Discord/Telegram alert integration)
- Auto-Pilot (advisory + dry-run; autonomous requires separate consent)
- Hash Market (Braiins/NiceHash/MRR live prices)
- Rentals Hub (P/L tracking, arbitrage alerts, one-click Braiins buy)

### What's NOT included (enterprise features, future)
- Multi-tenant fleet management
- SSO/SAML authentication
- Custom alerting rules engine
- Priority support SLA

---

## How to get a trial key

### Option 1: Self-service (if server has admin API enabled)
```bash
# Issue a trial key (30 days)
curl -X POST http://localhost:8765/api/admin/licenses \
  -H "Content-Type: application/json" \
  -d '{"plan":"pro","months":1,"source":"beta-trial","email":"you@example.com"}'

# Response: {"ok":true,"license_key":"C65-XXXX-XXXX-XXXX-XXXX"}
```

### Option 2: Script (10 keys at once)
```bash
./scripts/issue-beta-trial.sh --count 10 --days 30
```

### Option 3: Request via GitHub
Open an issue with the label `beta-access` and include:
- Your BTC address or pool username
- Number of ASICs you operate
- Which ICP you identify with (Solo Miner / Small Farm / Rental Operator)

---

## How to activate PRO

### Method 1: Header (recommended for API access)
```bash
curl -H "X-License-Key: C65-XXXX-XXXX-XXXX-XXXX" http://localhost:8765/api/snapshot
```

### Method 2: URL parameter
```
http://localhost:8765/?license=C65-XXXX-XXXX-XXXX-XXXX
```

### Method 3: Settings modal (UI)
Open ⚙ Settings → paste the key in the License Key field.

---

## Beta Program Rules

1. **Duration**: 30 days from key issuance. Keys expire automatically.
2. **Feedback required**: Beta testers agree to provide at least 1 written feedback per week (bug report, feature request, or UX observation).
3. **No production SLA**: Beta deployments are not covered by any uptime guarantee. The operator is responsible for their own data.
4. **Auto-Pilot consent**: Autonomous execution requires separate opt-in via the EULA consent checkbox in the dashboard. The beta key does NOT auto-enable autonomous mode.
5. **Data ownership**: All telemetry and fleet data stays on the operator's self-hosted instance. CYPHER65 has zero access to user data.
6. ** termination**: Keys can be revoked at any time by the operator via `POST /api/admin/licenses` or by editing the database directly.

---

## EULA Summary (Auto-Pilot)

When activating Auto-Pilot (ARMED + AUTONOMO), the operator explicitly consents to:

- **Real commands on real hardware**: restart, pause, frequency changes on physical ASICs.
- **Operator responsibility**: all actions are logged in the audit trail, but the operator bears responsibility for operational outcomes.
- **No liability**: CYPHER65 is not responsible for lost shares, downtime, equipment damage, or financial losses resulting from Auto-Pilot actions.
- **Revocation**: the operator can disarm at any time to immediately stop all autonomous actions.
- **SafetyEngine**: all commands pass through SafetyEngine validation (temperature, hashrate, rate limits) before execution.

The full EULA is displayed in the Auto-Pilot arm/auto modal before consent is required.

---

## Feedback Channels

- **GitHub Issues**: `bug`, `improvement`, or `question` labels
- **Discord**: #beta-testers channel (if available)
- **Direct**: operator@cypher65.com (if configured)

---

## Metrics We Track (anonymized, self-hosted only)

- License activation events (source, plan, timestamp)
- Conversion funnel: paywall_view → modal_open → checkout_start → key_activated
- Auto-Pilot: arm events, autonomous executions, SafetyEngine blocks
- No telemetry is sent to external servers. All metrics are stored in the local SQLite database.

### Viewing the beta analytics dashboard

Open **Admin → Uso do Beta** from the War Room running on localhost. The panel
shows real events from the selected instance: boots, DAU/WAU, module usage,
time per module, and boot-to-navigation dropoff. It is loaded only when the
Admin module is opened.

Remote access requires the same operator API-key gate as the other
`/api/admin/*` endpoints. The raw report remains available for diagnostics:

```bash
curl -H "X-API-Key: $API_KEY" \
  "https://your-war-room.example/api/admin/analytics?days=30"
```

An empty panel means that the local instance has not recorded beta usage in
the selected period; the UI does not generate placeholder analytics.
