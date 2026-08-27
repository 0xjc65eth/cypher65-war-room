# CYPHER65 War Room — Mobile App

React Native + Expo mobile command center for the CYPHER65 War Room.

## Quick Start

```bash
cd mobile
npm install
npx expo start
```

Run on iOS or Android with Expo Go, or use `npx expo run:ios` / `npx expo run:android`.

## Environment

Update `app.json` → `extra.apiBaseUrl` and `extra.apiBaseUrlDev` to point to your Flask backend.

## Features

- **Command**: global operation status and recent alerts.
- **Fleet**: device list, status filters, device detail, and remote commands.
- **Block**: network stats, per-window probability estimates, and a model mean interval (not a countdown or prediction).
- **Market**: hashrate market offers and opportunity comparison.
- **AI**: chat interface for the CYPHER65 AI Operator.

## Backend endpoints used

See `docs/MOBILE_ARCHITECTURE.md` for the full endpoint mapping.

## Tests

```bash
npm test
npm run typecheck
```
