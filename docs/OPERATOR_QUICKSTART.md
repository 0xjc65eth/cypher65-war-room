# CYPHER65 War Room — 15-minute operator quickstart

This path starts a real, empty-by-default self-hosted instance. It does not seed
production devices, invent prices, enable physical commands, or expose checkout.

## Minute 0–3 — prepare the host

Use a machine with Git, Python 3.11+, and network access to the data sources and
miners you intend to observe.

```bash
git clone https://github.com/0xjc65eth/cypher65-war-room.git
cd cypher65-war-room
cp .env.example .env
```

Keep the instance on loopback for this first run. Remote access needs an
authenticated deployment and HTTPS termination.

## Minute 3–6 — identify the mining context

Edit `.env` and use your own values. These names come directly from
`.env.example`:

```dotenv
BTC_ADDRESS=bc1-your-address
WORKER_NAME=your-worker-name
PORT=8765
```

Generate and set a stable `SECRET_KEY` if sessions must survive a restart:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

For a read-only first run, leave these fail-closed defaults unchanged:

```dotenv
ENABLE_PHYSICAL_COMMANDS=false
ENABLE_AUTONOMOUS_COMMANDS=false
ENABLE_REAL_HASHRATE_PURCHASES=false
ENABLE_REAL_PAYMENTS=false
```

Do not set `DEBUG_MOCK=1`. That switch is only for an explicit local demo and
must not be used as production evidence.

## Minute 6–9 — start and verify

```bash
./run.sh
```

The launcher creates `.venv`, installs the pinned Python requirements, and starts
Flask. In a second terminal, verify readiness:

```bash
curl -fsS http://localhost:8765/api/healthz
```

Open [http://localhost:8765](http://localhost:8765). An empty or stale state is
valid until real sources answer. Do not replace it with sample numbers.

## Minute 9–12 — inspect before acting

1. **Overview:** read worker state, freshness, and warnings. It is a read-only
   decision surface.
2. **Live Mining:** inspect shares, worker/pool hashrate, best difficulty, and
   the event stream.
3. **Block Statistics:** read the displayed P(≥1) window and model mean interval.
   Neither value predicts when a block will arrive.
4. **AXE Fleet Command:** register or select the intended device and verify its
   identity, temperatures, J/TH, power, capabilities, and last observation.
5. **Hash Market:** compare provider, unit, source, freshness, and any estimate
   label. Missing data is unavailable, not a free or zero-price quote.
6. **Rentals Hub:** inspect P/L versus market, concentration, and overpay alerts.
   Do not initiate a buy during the walkthrough.

## Minute 12–15 — follow the safety handoff

Open **Auto-Pilot** and review a recommendation. The response contract for
Accept is intentionally read-only:

```json
{
  "advisory_only": true,
  "executed": false,
  "navigate_to": "fleet"
}
```

`navigate_to` may point to Fleet or Rentals. Acceptance records operator intent
in the audit trail; it does not execute the proposed action.

If you later choose a physical Fleet command, first run its dry-run. Real
dispatch remains unavailable until the deployment gate is enabled and the same
request includes `dry_run:false` plus a valid one-time human confirmation bound
to the tenant, device, command, and parameters.

Checkout remains unavailable until the BTCPay reconciliation runbook passes and
the release gate is explicitly enabled. `BTCPAY_RECONCILIATION_VERIFIED=1` is a
post-validation state, not a setup shortcut.

## Stop cleanly

In the terminal running `./run.sh`, press `Ctrl+C`. The operational store remains
on the self-hosted instance for the next start.

## First-run checks

- A source that cannot refresh shows stale/offline state and the last real cached
  value when one exists.
- A miner is not controllable merely because it appears in Fleet.
- A Block Statistics mean is not a countdown.
- Auto-Pilot Accept never executes a command, blacklist change, or purchase.
- Checkout configuration without reconciliation still returns
  `checkout_unavailable`.

Continue with the [operator flyover](OPERATOR_FLYOVER.md) and the
[runtime map](architecture/runtime-map.md).
