# CYPHER65 · PARASITE POOL · WAR ROOM

A real-time dashboard that surfaces every publicly visible signal from your `cypher65`
worker and the [Parasite Pool](https://parasite.space). Designed for rented hashrate.
Dark, cyberpunk, glassy, Matrix-themed. Python backend + lightweight HTML/CSS/JS
frontend — runs locally on your Mac.

## What you get

- 🛰 **Worker hero panel** — live hashrate, best difficulty, last share age, uptime for `cypher65`
- 🌊 **Pool context** — pool hashrate, worker/user counts, highest diff ever, last block, work-since-last-block progress bar with milestone markers
- 📈 **Three live charts** — your hashrate history, pool hashrate, network difficulty (15m / 1h / 6h / 24h / 7d / all)
- 🏆 **Leaderboard** — top 30 miners with your row highlighted in gold
- 🎯 **High-diff events** — recent pool-wide high-difficulty events; toggle to "mine only"
- ⚡ **Live alert feed** — `stale_submission`, `hashrate_drop`, `new_high_diff`, `new_block`, `worker_offline`
- 💸 **Your account** — Lightning address, total difficulty, blocks found, leaderboard ranks
- 🌐 **Network context** — block height, network difficulty, network hashrate, BTC/USD, BTC/BRL
- 🧮 **Estimated luck math** — share-of-pool, fair diff since block, expected share difficulty, expected time to find a block at your rented hashrate
- 🕶 **Aesthetic extras** — Matrix rain canvas scanlines, CRT scanlines, ASCII logo, vitals pill, micro-stats ticker, blomberg-style glass panels

## Quick start

```bash
cd ~/cypher65-war-room
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open: <http://localhost:8765>

## Configuring a different worker / address

Override with env vars:

```bash
BTC_ADDRESS=bc1qyour… WORKER_NAME=yourrig python app.py
```

Or edit the defaults near the top of `app.py`.

## Data sources

- `https://parasite.space/api/*` — pool stats, user, account, leaderboard, highest-diff
- `https://mempool.space/api/*` — block height, network difficulty
- `https://api.coingecko.com/api/v3/*` — BTC/USD, BTC/BRL

## Where data is stored

Everything is persisted to a local SQLite at `data/war_room.sqlite`. Snapshots, alerts,
and high-diff events are kept 30 days. Delete the file to reset.

## What you CANNOT see

The pool only exposes aggregates. **Per-share and per-job logs are server-side
operator data**. To get those you'd need to:

- Run your own stratum proxy (e.g. intercept `mining.notify` + `mining.submit` traffic),
- Or run modified firmware on physical hardware that logs jobs.

This dashboard ships the maximum signal available without that infrastructure.

## Files

- `app.py` — Flask backend, polling loop, SQLite persistence, anomaly detection
- `templates/dashboard.html` — single-page dashboard markup
- `static/style.css` — cyberpunk visual layer (matrix rain, scanlines, glassmorphic panels)
- `static/app.js` — DOM updates, charts, terminal log feed, polling

## Keyboard

- `R` — refresh now
- click on the LN address row to copy
