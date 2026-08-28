# CYPHER65 War Room — Mobile App

React Native 0.86 + Expo SDK 57 mobile command center for the CYPHER65 War Room.

Requirements: Node.js 22.13 or newer, iOS 16.4+, Android 7+ and Android SDK 36.

## Quick Start

```bash
cd mobile
npm ci
npx expo start
```

Run on iOS or Android with an SDK 57 development build. Expo Go is useful for
early development, but production validation must use a development/native build.

## Environment

Update `app.json` → `extra.apiBaseUrl` and `extra.apiBaseUrlDev` to point to your Flask backend.

## Features

- **Command**: global operation status and recent alerts.
- **Fleet**: device list, status filters, device detail, and remote commands.
- **Block**: network statistics, per-window probability estimates and a model
  mean interval (not a countdown, prediction or guarantee).
- **Market**: hashrate market offers and opportunity comparison.
- **AI**: chat interface for the CYPHER65 AI Operator.

## Backend endpoints used

See `docs/MOBILE_ARCHITECTURE.md` for the full endpoint mapping.

## Tests

```bash
npm test
npm run lint
npm run typecheck
npm run doctor
npm audit --audit-level=high
npm run build
```

`npm run build` exports independent iOS, Android and web bundles. The repository
uses Expo Continuous Native Generation, so `ios/` and `android/` are generated
artifacts rather than committed source directories. The custom notification sound
reference was removed because the referenced file did not exist; notifications use
the platform default sound until a reviewed audio asset is added.
