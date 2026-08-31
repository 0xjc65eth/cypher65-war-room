# CYPHER65 War Room — Mobile Architecture

> **Milestone 8, Task 1 — Stack & Architecture Decision**

## 1. Decision: React Native + Expo

| Concern | Why React Native + Expo |
|---|---|
| **Single codebase for iOS + Android** | One TypeScript/React codebase, shared with existing web mental model. |
| **Faster iteration / lower cost** | Expo Go for instant preview, EAS Build for production binaries. |
| **Push Notifications (APNs + FCM)** | `expo-notifications` abstracts APNs/FCM; can also be swapped for OneSignal later. |
| **Biometrics** | `expo-local-authentication` provides Face ID / Touch ID / Android Biometrics. |
| **OTA Updates** | EAS Update allows urgent UI-only fixes without app-store release cycles. |
| **Web parity** | Reuse logic, types, and helper modules with the existing web dashboard. |

### Alternative considered

- **Flutter**: Strong, but adds a second language (Dart) and a separate widget model. The team already owns React for the web dashboard.
- **PWA-only**: Cheaper, but limited offline background execution, biometric UX, and push reliability on iOS. Rejected for a true "command center" experience.

**Decision**: React Native (managed with Expo SDK) is the primary mobile stack.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Mobile App (RN + Expo)                 │
│  ┌───────── ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌────────│
│  │ Command │ │ Fleet   │ │ Block   │ │ Market  │ │  AI    ││
│  │ (home)  │ │         │ │         │ │         │ │        ││
│  └────────┘ └────┬────┘ └────┬────┘ └────┬────┘ └───┬────┘│
│       └──────────────────────┬───────────────────────────┘  │
│                        React Navigation                    │
│                    Zustand / TanStack Query                 │
│                            │                               │
│                    API Client (fetch/axios)                 │
└────────────────────────────┬──────────────────────────────┘
                             │ REST + WebSocket (future)
┌────────────────────────────▼──────────────────────────────┐
│              CYPHER65 Flask Backend                        │
│   /api/snapshot  /api/devices  /api/block-hunt  etc.       │
│   Web Push (VAPID) → FCM / APNs via Expo push tokens        │
└────────────────────────────────────────────────────────────
```

### Folder layout

```
mobile/
├── App.tsx                         # Entry + navigation container
├── app.config.js / package.json      # Expo environment/native config
├── src/
│   ├── api/                         # REST client + endpoints map
│   ├── components/                  # shared UI primitives
│   ├── screens/                     # one folder per bottom tab
│   ├── hooks/                       # data, polling, notifications
│   ├── store/                       # Zustand slices
│   ├── services/
│   │   ├── push.ts                  # register + handle push tokens
│   │   ├── biometrics.ts            # unlock + confirm critical actions
│   │   └── offline.ts               # cache + sync strategy
│   └── types/                       # shared TypeScript interfaces
└── tests/
```

---

## 3. Navigation (Bottom Tabs)

| Tab | Screen | Purpose |
|---|---|---|
| **Command** | `CommandScreen` | Global operation status, alerts, quick actions, top-level dashboard. |
| **Fleet** | `FleetScreen` | List miners, filter by status, drill into a device. |
| **Block** | `BlockHuntScreen` | Per-window probability model, network stats and best-share history; no countdown/progress semantics. |
| **Market** | `MarketScreen` | Hashrate market offers, opportunity comparison. |
| **AI** | `AiOperatorScreen` | Chat with the CYPHER65 AI Operator. |

Tech: **React Navigation v6** (`@react-navigation/bottom-tabs`) with a custom dark theme matching the web dashboard.

---
## 4. Backend Communication

### 4.1 REST API endpoints consumed by the mobile app

| Feature | Endpoint | Notes |
|---|---|---|
| Command Center | `GET /api/snapshot` | Full dashboard state; poll every 15–60 s depending on battery mode. |
| Alerts | `GET /api/alerts` | Pull recent alerts; primary updates come via push. |
| Fleet list | `GET /api/devices` | Returns `devices[]` + `summary{}`. |
| Fleet summary | `GET /api/fleet/summary` | Total, status counts, total hashrate. |
| Device detail | `GET /api/devices/<uuid>` | Telemetry, capabilities, diagnostics. |
| Device refresh | `POST /api/devices/<uuid>/refresh` | Fetch fresh telemetry. |
| Device commands | `POST /api/devices/<uuid>/command` | Execute supported commands; requires biometric confirmation for risky ones. |
| Command history | `GET /api/devices/<uuid>/commands` | Audit trail. |
| Diagnostics | `GET /api/devices/<uuid>/diagnostics` | Health/issue list. |
| Maintenance | `GET/POST /api/devices/<uuid>/maintenance` | Record service notes. |
| Timeline | `GET /api/devices/<uuid>/timeline` | Combined event history. |
| Block Hunt | `GET /api/block-hunt` | Network stats + probabilities. |
| Best Diff History | `GET /api/best-diff-history` | Global best-diff history. |
| Market | `GET /api/hashrate-market` | Live offers. |
| Market compare | `GET /api/opportunities/compare` | Side-by-side offer comparison. |
| Market history | `GET /api/hashrate-market/history` | Price history. |
| AI chat | `POST /api/ai/chat` *(planned)* | Natural-language operator. |

### 4.2 Polling vs Push strategy

- **Primary update mechanism**: Push notifications for CRIT/WARN/GOLD events.
- **Background refresh**: Periodic `/api/snapshot` poll with frequency controlled by battery mode (see §7).
- **Foreground refresh**: Manual pull-to-refresh + automatic low-frequency polling.

---

## 5. Push Notifications

### 5.1 Native push channel

- Use **Expo Notifications** (`expo-notifications`) to:
  - Request notification permissions.
  - Obtain the device `pushToken` (APNs for iOS, FCM for Android).
  - Handle foreground/background/launch notifications.
- Mobile app registers its token with the backend:
  - `POST /api/push/register` *(to be implemented)* with `{ token: string, platform: 'ios'|'android', categories: string[] }`.

### 5.2 Backend push delivery

- The existing `services/push_notifier.py` currently sends **Web Push** via VAPID to browser subscriptions.
- For the mobile app, the backend will also support **Expo Push API** or direct FCM/APNs.
- Recommended path (Phase 1):
  1. Send mobile push via **Expo Push Service** using the token from `expo-notifications`.
  2. Keep VAPID/Web Push for the existing web dashboard.
- Alert categories: `temperature`, `hashrate_drop`, `worker_offline`, `device_offline`, `best_diff_bump`, `new_block`.

### 5.3 Per-category subscription

Stored in backend per device token and exposed as:

```ts
interface PushPreferences {
  token: string;
  categories: {
    temperature: boolean;
    hashrate_drop: boolean;
    worker_offline: boolean;
    device_offline: boolean;
    best_diff_bump: boolean;
    new_block: boolean;
  };
}
```

---

## 6. Security & Authentication

| Layer | Approach |
|---|---|
| **Token auth** | Login returns a short-lived JWT. Stored in encrypted storage (`expo-secure-store`). |
| **Biometric gate** | `expo-local-authentication` required for app unlock and critical actions (restart, identify, wallet change). |
| **Certificate pinning** *(future)* | Pin the backend certificate or use a trusted CA. |
| **Remote logout** | Backend invalidates token; app detects `401` and wipes local secure storage. |

### Critical-action flow

```
User taps high-risk command
        ↓
Biometric prompt (Face ID / Fingerprint)
        ↓
POST /api/devices/<uuid>/command
        ↓
Backend validates token + SafetyEngine
        ↓
Command executed + audit logged
```

---

## 7. Battery & Data Optimization

| Mode | Snapshot Poll | Push | Behavior |
|---|---|---|---|
| **Max Battery** | On open only | Enabled | No background polling; manual refresh. |
| **Balanced** *(default)* | Every 60 s in foreground | Enabled | Stop polling in background; rely on push. |
| **Real-time** | Every 15 s in foreground | Enabled | Higher data/battery use. |

### Offline support

- Cache the latest `/api/snapshot` and fleet list in AsyncStorage.
- Show stale data with an explicit "last updated" timestamp.
- Queue non-urgent actions (e.g., maintenance notes) and retry when online.

---

## 8. AI Operator Mobile

- Reuse the planned `/api/ai/chat` endpoint.
- Keep conversation context: current fleet status, recent alerts, telemetry.
- UI: chat bubble list + suggested quick commands.

---

## 9. Technology Summary

| Concern | Tech |
|---|---|
| Framework | React Native + Expo SDK |
| Language | TypeScript |
| Navigation | React Navigation (bottom tabs) |
| State | Zustand + TanStack Query |
| HTTP | `axios` or native `fetch` with retry interceptor |
| Charts | `react-native-chart-kit` or `victory-native` |
| Push | `expo-notifications` + Expo Push Service |
| Biometrics | `expo-local-authentication` |
| Secure storage | `expo-secure-store` |
| Offline cache | AsyncStorage + TanStack Query cache |
| Build / OTA | EAS Build + EAS Update |

---

## 10. Open Decisions / Next Steps

1. Confirm whether the AI chat endpoint should be a new `/api/ai/chat` route or an extension of the existing CLI/agent tool chain.
2. Decide whether to keep VAPID web push only or unify all push delivery under Expo Push Service.
3. Define the exact authentication flow (login + token refresh) before implementing Task 10.
