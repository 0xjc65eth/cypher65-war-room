# C65-01–05: dashboard telemetry contract (Issue #732)

Base: master 39fa95b5833ea0f61c8f578df1cabb388d8a61e4. Production observed 03/10/2026 Europe/Brussels without login: difficulty 132.76 TH/s, height 958527 with age 20717d, pool 323 PH/s with fixed 161.6 subtitle, NETWORK 323000000000000000, topbar INIT with absent metrics.

Cause confirmed locally: DashboardCore ran after renderNetwork/renderHostCore and overwrote units/entity. The pool field lastBlockTime carries a legacy height; it was rendered and stored as a Unix timestamp. Topbar IDs had no snapshot writer except HR/temp. Pool workers and registered ASICs have distinct scopes.

Fix: retain canonical network/pool renderers, normalize height/timestamp separately (seconds or milliseconds, Bitcoin-era timestamps only), clear absent block data, populate snapshot topbar with explicit pool-worker/BTC-USD labels and stale/unknown states, replace literal subtitle. Both polling paths use the same Python contract for new persisted rows. Existing historical rows are intentionally not migrated; raw exports containing old rows need provenance review before analytical use.

Evidence: new Playwright regression failed before with 132.76 TH/s in chromium and mobile-chrome, passed after. Fixture tests block service workers because their fetches bypass page.route. 61 focused Python tests passed; full CI coverage scope: 4118 passed, 1 skipped, 85.50% (555 existing/dependency warnings, not suppressed). Frontend combined pipeline passed including visual audit, axe-core, guards and unit tests. Further topbar invalid/stale assertions were added after review.

Self-review (not independent GitHub approval): Frontend/Data — canonical DOM ownership, null/zero/legacy behavior; Security — textContent only for new writes, no credential or permission change; Backend — no schema or historical mutation; QA — real source loaded by JS tests, full rendering checked in browser. No new animation; polling updates remain immediate. Existing reduced-motion policy retained. Rollback: revert this PR via a reviewed PR. Merge/deploy require user authorization and independent approval; hardware/production after-change validation not performed.
