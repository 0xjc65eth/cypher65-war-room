# CYPHER65 — Mobile Strategy

**Date:** 2026-07-28  
**Scope:** MILESTONE 10 — Tarefa 4 (Definir Estratégia Mobile)

---

## Executive Summary

| Option | Recommendation | Phase |
|---|---|---|
| **PWA** | Adopt immediately | Short-term |
| **Flutter** | Adopt for a native app | Long-term |
| React Native | Not recommended at this stage | — |

---

## Evaluation Matrix

| Criteria | PWA | React Native | Flutter |
|---|---|---|---|
| **Time to market** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| **Cost / maintenance** | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ |
| **UX / performance** | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Push notifications** | Limited on iOS | Good | Good |
| **Background tasks** | Limited | Good | Excellent |
| **Offline support** | Good | Good | Good |
| **Code reuse with web** | Maximum | Medium | Low-medium |
| **Battery efficiency** | Medium | Medium | Good |
| **Charting performance** | Good | Good | Excellent |

---

## Recommendation

### Phase 1 — PWA now

The dashboard already has the core PWA assets (`manifest.json`, `service worker`, responsive CSS). The fastest path to a usable mobile experience is to:

1. Fix the service worker scope warning.
2. Generate PNG icon set from the existing SVG logos.
3. Add splash screens and an `apple-touch-icon`.
4. Ship the PWA.

**Why:** Zero extra dependencies, same codebase, installable from the browser, and good enough for most monitoring tasks.

### Phase 2 — Native app with Flutter

When the product needs:

- Reliable push notifications on iOS
- Background sync for fleet telemetry
- Biometric authentication
- Smoother 60fps charts and animations
- App Store presence

**Flutter** is preferred over React Native because:

- The UI is data-dense (gauges, charts, real-time meters); Flutter's rendering engine delivers more consistent 60fps performance.
- Single codebase for iOS and Android.
- Strong out-of-the-box support for animations and custom painters (useful for the best-share ratio and network gauges).
- Dart's null-safety reduces runtime errors for a finance/mining app.

---

## Push Notifications & Background Tasks

| Approach | PWA | Flutter |
|---|---|---|
| Push service | Web Push / FCM | FCM / APNs |
| Background sync | Service Worker (Android only, partial iOS) | Background fetch / isolate |
| Critical alerts | Unreliable on iOS PWA | Reliable via native push |
| Battery impact | Medium | Lower |

**iOS PWA caveat:** even with `apple-mobile-web-app-capable`, iOS limits background execution and Web Push on home-screen PWAs. Critical alerts may not arrive reliably unless the user keeps the app in the foreground. This is the strongest argument for a native app when iOS push is required.

**Conclusion:** Use PWA push for Android and non-critical alerts; move to Flutter when iOS reliability is required.

---

## Migration Path

```
Now        →  PWA (manifest + SW + icons)
3-6 months  →  Flutter MVP with fleet + alerts
6-12 months →  Feature parity (commands, market, settings)
```

## Generated Assets

`static/generate_icons.py` produces all PWA/native icon assets:

- `static/icon-*.png` — standard PWA icon set (16×16 to 512×512)
- `static/maskable-icon-512x512.png` — Android adaptive/maskable icon
- `static/apple-touch-icon.png` — iOS home-screen icon
- `static/favicon.ico` — multi-resolution favicon
- `static/splash-*.png` — iOS startup images; `splash-1024x1024.png` is also kept as a source asset for Flutter/React Native splash-screen generators.


---

## Risks

- **PWA on iOS:** Apple limits background sync and push; users may need to open the app to refresh alerts.
- **Flutter cost:** Requires learning Dart/Flutter or hiring dedicated mobile engineers.
- **Feature drift:** Maintaining two UIs (web + native) can diverge. Keep shared API contracts strict.
