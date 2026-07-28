# CYPHER65 — Current Mobile Limitations

**Date:** 2026-07-28  
**Scope:** MILESTONE 10 — Tarefa 6 (Documentar Limitações Atuais para Mobile)

---

## Known Limitations of the Web Dashboard on Mobile

### 1. Background Alerting

- The browser tab must remain active (or the PWA must be correctly installed on Android) for audio/visual alerts to fire.
- **iOS limitation:** Background browser tabs are suspended by the OS, so critical threshold alerts may be missed.

### 2. Battery Consumption

- Real-time DOM manipulation and 15-second multi-endpoint polling on the foreground tab drains battery faster than a native app.
- There is no background-throttle mode today.

### 3. Touch & Interaction

- Several UI elements rely on hover states (tooltips, panel glows, table row highlights) that require double-taps or are awkward on touchscreens.
- Some buttons and chips are small, even after the Tarefa 2 improvements.

### 4. Tables & Data Density

- Tables (leaderboard, events, fleet telemetry) are dense and require horizontal scrolling on small screens.
- Chart range selectors and terminal logs can feel cramped.

### 5. Offline Support

- The service worker caches static assets, but live data is not cached meaningfully.
- Offline mode is minimal: users see cached shell but no fresh metrics.

### 6. Push Notifications

- PWA push works reliably on Android but is limited on iOS.
- There is no granular per-category notification preferences UI yet.

### 7. Authentication

- Currently no authentication. A dedicated mobile app would need token + biometric auth for sensitive operations (e.g., remote restart).

---

## Features Better Suited for a Dedicated Mobile App

| Feature | Why a native app wins |
|---|---|
| **Reliable push alerts** | FCM / APNs work in background and on iOS |
| **Biometric lock** | Face ID / Touch ID for critical commands |
| **Battery modes** | Max Battery / Balanced / Real-time polling profiles |
| **Background sync** | Fetch telemetry even when app is closed |
| **Offline-first fleet view** | Cache device list and last telemetry locally |
| **Quick actions** | Home-screen widgets for fleet status |
| **AI Operator chat** | Microphone input, haptic feedback |

---

## What Works Well Today

- The dashboard is responsive down to 390px.
- Panels stack cleanly on mobile.
- The topbar now scrolls horizontally to avoid button overflow.
- Tables remain readable with horizontal scroll inside `.table-wrap`.

---

## Roadmap to Remove Limitations

1. **PWA improvements:** icons, splash screen, offline data cache, push categories.
2. **API optimization:** `/api/snapshot?lite=true`, paginated `/api/alerts`.
3. **Native app (Flutter):** Implement reliable push, background sync, battery modes, and biometric auth.
