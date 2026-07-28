# CYPHER65 — Mobile API Reference

**Purpose:** This document lists the backend endpoints a mobile client (PWA or native) should consume, along with optimization notes and recommended request patterns.

**Last updated:** 2026-07-28

---

## Authentication & General Notes

- The CYPHER65 backend is a **stateless-ish** Flask application. Most endpoints are read-only `GET`s.
- For a mobile app, prefer a single lightweight entry point and cache aggressively to reduce battery use.
- All endpoints return JSON unless noted otherwise.
- Timestamps are Unix seconds unless otherwise specified.

---

## Priority Endpoints

### 1. Dashboard Snapshot

`GET /api/snapshot`

- **Use for:** Home screen / Command Center
- **Returns:** Full dashboard payload (worker, pool, network, BTC price, alerts, fleet, etc.)
- **Mobile note:** The response can be large. Consider adding a `?lite=true` query parameter in the future to strip heavy arrays (`leaderboard_table_top_30`, `highest_diffs`, `all_workers`).
- **Cache TTL:** 15 seconds (matches poll interval)

### 2. Alerts

`GET /api/alerts`

- **Use for:** Push-style alert list / Alert Center
- **Mobile note:** Always paginate: `?limit=20&severity=CRIT`. Never request unbounded history from mobile.
- **Related:**
  - `POST /api/alerts/acknowledge`
  - `GET /api/alerts/history`

### 3. Device Fleet

`GET /api/devices`

- **Use for:** Fleet list screen
- **Returns:** Devices with `current_telemetry`, `status`, `last_seen`, `ip`, etc.
- **Mobile note:** Heavy telemetry can be large. A future `?summary=true` flag should return only ID, name, status, and hashrate.

### 4. Fleet Summary

`GET /api/fleet/summary`

- **Use for:** Fleet health badge / quick dashboard overview
- **Returns:** Total devices, status counts, total hashrate, devices with recent telemetry
- **Lightweight:** Yes — ideal for mobile.

### 5. Device Detail

`GET /api/devices/<uuid>`

- **Use for:** Device detail screen
- **Returns:** Full device data + telemetry + capabilities

### 6. Device Refresh / Telemetry

`POST /api/devices/<uuid>/refresh`

- **Use for:** Pull-to-refresh on a device detail screen
- **Returns:** Updated device with latest telemetry

### 7. Device Command

`POST /api/devices/<uuid>/command`

- **Use for:** Remote actions (restart, identify)
- **Body:** `{"command": "restart", "parameters": {}}`
- **Safety:** All commands pass through `SafetyEngine`.

### 8. Automation Rules

- `GET /api/automation-rules`
- `POST /api/automation-rules`
- `PUT /api/automation-rules/<id>`
- `DELETE /api/automation-rules/<id>`

- **Use for:** Rule management screen
- **Mobile note:** Rule JSON can be edited, but complex conditions are better suited for the web admin.

### 9. Block Hunt

`GET /api/block-hunt`

- **Use for:** Block probability / network comparison screen
- **Returns:** Network hashrate, difficulty, height, user hashrate, best diff, probabilities

### 10. Hashrate Market / Opportunities

- `GET /api/hashrate-market`
- `GET /api/opportunities`
- `GET /api/opportunities/compare`

- **Use for:** Market intelligence tab
- **Mobile note:** Consider caching for 5 minutes; data rarely changes second-by-second.

---

## Recommended Mobile Optimizations

| Endpoint | Current state | Suggested improvement |
|---|---|---|
| `/api/snapshot` | Full payload | Add `?lite=true` returning only top-level metrics |
| `/api/devices` | Full telemetry | Add `?summary=true` for fleet list |
| `/api/alerts` | No pagination | Add `?page=&limit=` |
| `/api/alerts/history` | Time-bounded | Keep default window small (e.g., last 24h) |
| `/api/leaderboard` | Full top 30 | Add `?limit=` default to 10 on mobile |

---

## Connectivity & Error Handling

- Mobile networks are flaky. Use exponential backoff for retries.
- Cache the last successful `/api/snapshot` and `/api/fleet/summary` so the UI works offline briefly.
- Use `If-None-Match` / ETag where possible once the backend supports it.
- For time-sensitive commands, surface network failures clearly and allow retry.
