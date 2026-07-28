# CYPHER65 WAR ROOM — COMPLETE LAYOUT DOCUMENT

> **Generated:** 2026-07-28
> **Files:** `templates/dashboard.html` (1,552 lines), `static/style.css` (2,985 lines), `static/app.js` (2,158 lines)

---

## 1. APP SHELL — LAYOUT CONTAINERS

### `div.app-layout` (#app-layout)
- **Type:** Flex container (`display: flex`)
- **Purpose:** Wraps Sidebar + Main Content
- **Children:** `aside.sidebar`, `div.app-main`

### `div.app-main` (#app-main)
- **Type:** Flex column (`flex: 1; display: flex; flex-direction: column`)
- **Purpose:** Contains topbar, status bar, and command center grid

---

## 2. BACKGROUND LAYER

### `canvas#matrix-canvas`
- **CSS:** `position: fixed; inset: 0; z-index: 0; opacity: 0.025`
- **Purpose:** Matrix rain animation canvas (JS-controlled)

### `div.scanlines`
- **CSS:** `position: fixed; inset: 0; z-index: 1; pointer-events: none`
- **Purpose:** CRT scanline overlay effect

### `div.vignette`
- **CSS:** `position: fixed; inset: 0; z-index: 2; pointer-events: none`
- **Purpose:** Dark vignette at top edges

### `body::after` (noise texture)
- **CSS:** `position: fixed; inset: 0; z-index: 1000; opacity: 0.035`
- **Purpose:** Subtle noise texture overlay (SVG data-URI fractal noise)

---

## 3. SIDEBAR (`aside.sidebar` #sidebar)

| Section | ID/Class | Description |
|---------|----------|-------------|
| Brand | `.sidebar__brand` | CYPHER65 logo + title |
| Logo | `.sidebar__logo` | "65" in orange gradient box |
| Title | `.sidebar__title` | "CYPHER65" |
| Navigation | `nav.sidebar__nav` #sidebar-nav | 7 nav items |
| Nav Item | `.sidebar__item.active` #hero-worker | ⌘ Command |
| Nav Item | `.sidebar__item` #axe-fleet-panel | ⚙ Fleet |
| Nav Item | `.sidebar__item` #block-hunt-panel | ◈ Block Hunt |
| Nav Item | `.sidebar__item` #market-panel | ⟐ Market |
| Nav Item | `.sidebar__item` #ai-operator-panel | ◆ AI |
| Nav Item | `.sidebar__item` #alerts-panel | ⚠ Alerts |
| Nav Item | `.sidebar__item` #profit-panel | Ξ P&L |
| Footer | `.sidebar__footer` | Status LED + collapse toggle |
| Status | `.sidebar__status` #sidebar-status | LED + "INIT" text |
| Toggle | `button.sidebar__toggle` #sidebar-toggle | Collapse ◀ |

**CSS Details:**
- Width: 180px (collapsed: 48px)
- Height: 100vh, sticky
- Background: `var(--bg-surface)`
- Active item: left orange indicator dot (3px × 16px)
- Breakpoint: `<1100px` → fixed overlay, hamburger visible

### Sidebar Backdrop
- `div.sidebar-backdrop` #sidebar-backdrop
- **CSS:** `position: fixed; inset: 0; z-index: 299`
- **Purpose:** Mobile overlay backdrop (click to close)

---

## 4. TOPBAR (`header.topbar`)

| Element | ID | Description |
|---------|-----|-------------|
| Hamburger | `button.topbar__hamburger` #sidebar-hamburger | Mobile menu toggle (hidden on desktop) |
| Brand | `div.brand` | MISSION CONTROL title + wallet address |
| Brand Meta | `div.brand__meta` | Hidden wrapper (brand is now in sidebar) |
| Brand Title | `.brand__title` | "MISSION CONTROL" |
| Brand Sub | `.brand__sub` #topbar-address | Wallet + worker name |
| Status Pill | `div.pill.pill--status` #status-pill | LED + ONLINE/OFFLINE |
| Clock | `div.pill.pill--clock` #clock | Current time HH:MM:SS |
| Next Poll | `div.pill` | Pulse dot + next poll countdown |
| Refresh | `button.btn--mini` #refresh-now | ⟳ (Keyboard: R) |
| Wallet | `button.btn--mini` #open-wallet | ⟐ (Keyboard: W) |
| Settings | `button.btn--mini` #open-settings | ⚙ (Keyboard: S) |
| Alerts | `button.btn--mini` #open-alert-center | 🚨 (Keyboard: A) |
| Exports | `button.btn--mini` #open-exports | ↓ |
| Sound | `button.btn--mini` #toggle-sound | 🔇 (Keyboard: N) |

**CSS:**
- Sticky, z-index: 100
- Blur glass background
- Border-bottom: 1px subtle
- Min-height: 44px

---

## 5. STATUS BAR (`div.status-bar` #status-bar)

5 horizontal blocks in a flex row with `border-top: 2px solid` accent colors:

| Block | ID | Accent | Fields |
|-------|-----|--------|--------|
| SYSTEM | #sb-system | BTC Orange | LED (#sb-led), Status (#sb-status), Workers (#sb-workers) |
| MINING | #sb-mining | Green | Hashrate (#sb-hashrate), Best Diff (#sb-bestdiff), Last Share (#sb-lastshare) |
| POOL | #sb-pool | Blue | Pool HR (#sb-pool-hr), Workers (#sb-pool-workers), Block (#sb-pool-block) |
| NETWORK | #sb-network | Purple | Net Diff (#sb-net-diff), BTC Price (#sb-net-price), Height (#sb-net-height) |
| FLEET | #sb-fleet | Teal | Online (#sb-fleet-online), Total (#sb-fleet-total), Fleet HR (#sb-fleet-hr) |

**CSS:**
- Flex row, scrollable on mobile
- Each block: `backdrop-filter: blur(12px); border-top: 2px solid [accent]`
- Mobile: horizontal snap scroll at 480px

---

## 6. COMMAND CENTER GRID (`main.grid`)

**Grid:** 12 columns, gap `clamp(12px, 1.5vw, 18px)`, max-width 1680px

### 6.1 — HOST CORE / WORKER (#hero-worker)
- **Class:** `panel panel--hero panel--biolume`
- **Span:** 12 columns
- **Organic nodes:** 2 (bottom:4px left:20% tendril, top:4px right:30% organic)

**Sub-components:**

#### Host Core Section (`.host-core`)
| Element | ID | Description |
|---------|-----|-------------|
| Title | `.host-core__title` | "CENTRAL NERVOUS SYSTEM · REAL-TIME COLONY STATUS" (gradient text) |
| Badges | `.host-core__badge` #hc-hr-badge | Current hashrate |
| Badges | `.host-core__badge` #hc-net-badge | Network difficulty |
| Stat 1 | #hc-colony-hr | Colony hashrate (worker / network) |
| Stat 2 | #hc-best-diff | Best difficulty |
| Stat 3 | #hc-network | Block height |
| Stat 4 | #hc-fleet-health | Fleet health (online/total + %) |
| Stat 5 | #hc-block-prob | Block probability |
| Stat 6 | #hc-alerts | Alert count or "nominal" |

**CSS:** Radial gradient background, animated shimmer border (biolume-organic-btc gradient, 4s animation)

#### Hero Metrics Grid (`.hero-grid` — 4 columns)
| Metric | ID | Label | Left Border Color |
|--------|-----|-------|-------------------|
| Metric 1 | #m-hashrate | HASHRATE | BTC Orange |
| Metric 2 | #m-bestdiff | BEST DIFFICULTY | Green |
| Metric 3 | #m-lastshare | LAST SHARE | Blue |
| Metric 4 | #m-state | STATE | Purple |

Each metric has `.metric__label`, `.metric__value`, `.metric__sub`.

#### Extra Metrics (`.hero-extra` — 4 columns)
| Cell | ID | Label |
|------|-----|-------|
| Cell 1 | #m-share-pct | SHARE-OF-POOL |
| Cell 2 | #m-fair-diff | FAIR DIFF SINCE BLOCK |
| Cell 3 | #m-expected-share | EXPECTED SHARE DIFF |
| Cell 4 | #m-expected-block | EXPECTED TIME / BLOCK |

#### Header Elements
| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "◈ HOST CORE // WORKER_NAME" |
| Badge | #worker-rank-badge | RANK ? |
| Badge | #worker-uptime-badge | UP — |

---

### 6.2 — HASH PROXIMITY METER (#proximity-panel)
- **Class:** `panel panel--proximity panel--biolume`
- **Span:** 12 columns
- **Organic nodes:** 2 (top:4px left:15% lg tendril, bottom:4px right:25% spore)

**Sub-components:**

| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "⌖ HASH PROXIMITY METER · QUANTUM-LOCK ASSESSMENT" |
| Badge | #prox-pct-badge | % of network |
| Badge | #prox-alltime-badge | Peak difficulty |
| Badge | #prox-streak-badge | Hot streak indicator |
| SVG Arc | `svg.prox-svg` | Semi-circle gauge (r=90) |
| Arc Fill | #prox-arc | Progress arc with gradient |
| Tip Dot | #prox-tip | Pulsing indicator dot on arc |
| Center % | #prox-hero-pct | Proximity percentage |
| Center Sub | #prox-hero-sub | "of network challenge" |
| Center Best | #prox-hero-best | "best [value]" |
| Stat | #prox-chance | CHANCE / SHARE |
| Stat | #prox-time | EXPECTED TIME / BLOCK |
| Stat | #prox-time-sub | Blocks per year |
| Stat | #prox-distance | DISTANCE FACTOR |
| Stat | #prox-trend | TREND · 1H |
| Sparkline | `canvas#prox-sparkline` | LAST 24H best difficulty sparkline |
| Ladder | #prox-ladder-row | Milestone dots (% of network) |
| Footnote | #prox-footnote | Proximity explanation |

#### Live Hash Calculator (`.prox-live-calc` #prox-live-calc)
| Element | ID | Purpose |
|---------|-----|---------|
| Title | `.prox-live-calc__title` | "⚡ LIVE HASH CALCULATOR · PER-SHARE BREAKDOWN" |
| Last Hash Time | #lc-time-big | Timestamp of last share |
| Session Count | #lc-session-share-count | Session share # |
| Share Diff | #lc-share-diff | Current vardiff target |
| Hashes Attempted | #lc-hashes | share_diff × 2³² |
| Time Observed | #lc-time-obs | share_ts − prev_ts |
| P(Block) | #lc-p-block | share_diff ÷ network_diff |
| Instant HR | #lc-inst-hr | hashes_attempted ÷ time_observed |
| Session Shares | #lc-session-shares | since process start |
| Avg Share Diff | #lc-avg-share-diff | over last 20 shares |
| Cumulative P | #lc-cum-p | 1 − (1 − p)^session_shares |
| Expected Blocks | #lc-expected-blocks | N · p (linear) |
| Ticker List | #lc-ticker-list | Recent shares ticker |

---

### 6.3 — POOL OVERVIEW (#pool-overview)
- **Class:** `panel`
- **Span:** 6 columns

| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "# POOL CONTEXT" |
| Badge | #pool-uptime | Uptime |
| Stat | #p-hashrate | POOL HASHRATE |
| Stat | #p-workers | WORKERS / USERS |
| Stat | #p-high-diff | HIGHEST DIFF |
| Stat | #p-last-block | LAST BLOCK # |
| Stat | #p-last-block-time | Time since last block |
| Progress | #p-work-num | Work since last block number |
| Progress | #p-work-fill | Progress bar fill (%) |
| Progress | #p-expected-blocks | Expected blocks |

---

### 6.4 — ACCOUNT (#account-panel)
- **Class:** `panel`
- **Span:** 3 columns

| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "§ ACCOUNT" |
| Badge | #acct-blocks-badge | Block count |
| Row | #acct-ln | LN ADDRESS (copyable) |
| Row | #acct-total-diff | TOTAL DIFFICULTY |
| Row | #acct-highest-block | HIGHEST BLOCK |
| Row | #acct-combined | LEADERBOARD COMBINED |
| Row | #acct-diff-rank | DIFF RANK |
| Row | #acct-loyalty-rank | LOYALTY RANK |

---

### 6.5 — NETWORK (#network-panel)
- **Class:** `panel`
- **Span:** 3 columns

| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "⌬ NETWORK · MEMPOOL" |
| Badge | #net-status | Fetch status |
| Stat | #n-height | HEIGHT |
| Stat | #n-diff | NETWORK DIFF |
| Stat | #n-hashrate | NETWORK HASHRATE |
| Stat | #n-btc-usd | BTC USD |
| Stat | #n-btc-brl | BTC BRL |
| Stat | #n-btc-eur | BTC EUR |
| Stat | #n-btc-gbp | BTC GBP |

---

### 6.6 — HALVING COUNTDOWN (#halving-panel)
- **Class:** `panel`
- **Span:** 4 columns

| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "⚒ HALVING COUNTDOWN" |
| Badge | #halving-epoch-badge | Current epoch |
| Stat | #h-blocks | BLOCKS REMAINING |
| Stat | #h-days | DAYS REMAINING |
| Stat | #h-cur-reward | CURRENT REWARD |
| Stat | #h-next-reward | NEXT REWARD |
| Stat | #h-next-height | NEXT @ HEIGHT |

---

### 6.7 — MEMPOOL FEES (#fees-panel)
- **Class:** `panel`
- **Span:** 4 columns

| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "⛽ MEMPOOL FEE TIERS · SAT/VB" |
| Badge | #fees-status | Fee status |
| Fee | #fee-economy | ECONOMY sat/vB |
| Fee | #fee-hour | HOUR sat/vB |
| Fee | #fee-halfhour | HALF-HOUR sat/vB |
| Fee | #fee-fastest | FASTEST sat/vB (red accent) |
| Fee | #fee-minimum | MINIMUM sat/vB |

---

### 6.8 — PROFITABILITY (#profit-panel)
- **Class:** `panel panel--profit panel--biolume`
- **Span:** 12 columns
- **Organic node:** 1 (top:4px right:40% organic)

| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "Ξ PROFITABILITY · REAL-TIME" |
| Badge | #profit-share-badge | % of network |
| Badge | #profit-cost-badge | Cost per day |
| Mode Selector | `.profit-modes` | POOL / SOLO / RENTAL buttons |
| Stat | #p-btc-day | NET BTC / DAY |
| Stat | #p-fiat-day | FIAT / DAY |
| Stat | #p-fiat-day-week | ~ per week |
| Stat | #p-fiat-month | FIAT / MONTH |
| Stat | #p-breakeven | BREAK-EVEN |
| Solo extras | #solo-extra-stats | P(Block) today/year/5y, expected blocks/time |
| Fiat Row | #profit-fiat-row | USD / BRL / EUR / GBP per day |
| Footnote | #profit-footnote | Cost model note |

---

### 6.9 — NETWORK-SHARE GAUGE (#gauge-panel)
- **Class:** `panel`
- **Span:** 12 columns

| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "◉ NETWORK-SHARE GAUGE" |
| Badge | #gauge-label | Gauge label |
| Canvas | #gauge-worker-canvas | cypher65 vs NETWORK (semi-circle) |
| Canvas | #gauge-pool-canvas | POOL vs NETWORK |
| Canvas | #gauge-luck-canvas | POOL-LUCK · THIS ROUND |
| % | #gauge-worker-pct | Worker share % |
| % | #gauge-pool-pct | Pool share % |
| % | #gauge-luck-pct | Luck % |
| Chance | #gauge-worker-blockchance | 22-min block chance |

---

### 6.10 — MILESTONES (#milestones-panel)
- **Class:** `panel`
- **Span:** 4 columns

| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "★ ACHIEVEMENTS · MILESTONES" |
| Badge | #milestones-count | 0 unlocked |
| Strip | #badges-strip | Badge cards grid |

---

### 6.11 — LIVE MINING (#live-mining-panel)
- **Class:** `panel panel--live-mining`
- **Span:** 12 columns

| Element | ID | Description |
|---------|-----|-------------|
| Cyber Header | `.lm-cyber-header` | "◈ CYPHER // LIVE MINING" |
| Badge | #lm-status-badge | LIVE indicator |
| Badge | #lm-workers-badge | Worker count |
| Summary | #lm-summary-wallet | Wallet address |
| Summary | #lm-summary-pool | Pool name + connection dot |
| Summary | #lm-summary-workers | Worker count |
| Summary | #lm-summary-hr | Total hashrate |
| Summary | #lm-summary-best | Best difficulty |
| Stream | #hunt-stream-feed | CALC STREAM live feed |
| Canvas | #hunt-canvas | Hash Hunt visualization |
| Metrics | #hunt-metrics-hr | Instant hashrate |
| Metrics | #hunt-metrics-pblock | Cumulative P(Block) |
| Metrics | #hunt-metrics-expblocks | Expected blocks |
| Metrics | #hunt-metrics-bestdiff | Best difficulty |
| Shares | #hunt-shares-grid | Recent shares cards |
| Shares Count | #hunt-shares-count | Share count badge |
| Best Share | #lm-best-share | Best share card (hidden by default) |
| Event Log | #lm-event-log-terminal | Live mining events terminal |
| Footnote | `.lm-footnote` | Mining visualization explanation |

---

### 6.12 — CHARTS (4 panels)

| Panel | ID | Class | Span |
|-------|-----|-------|------|
| Hashrate Chart | #chart-hashrate-panel | `panel panel--chart` | 4 |
| Pool Chart | #chart-pool-panel | `panel panel--chart` | 4 |
| Best Diff Chart | #chart-bestdiff-panel | `panel panel--chart` | 4 |
| Network Chart | #chart-net-panel | `panel panel--chart` | 12 |

**Canvas IDs:** `#chart-hashrate`, `#chart-pool`, `#chart-bestdiff`, `#chart-net`

Each has range selector chips (`.chart-range`):
- Hashrate: 15m / 1h / 6h / 24h / 7d / all
- Pool: 1h / 6h / 24h / 7d / all
- Best Diff: 1h / 6h / 24h / 7d / all
- Network: 24h / 7d / 30d / all

---

### 6.13 — HIGH-DIFF EVENTS (#events-panel)
- **Class:** `panel`
- **Span:** 4 columns

| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "⌖ RECENT HIGH-DIFF EVENTS · POOL WIDE" |
| Toggle All | #events-toggle-all | All events |
| Toggle Mine | #events-toggle-mine | Mine only |
| Table Body | #events-tbody | block, address, difficulty, time, claimed |

---

### 6.14 — SHARE TIMELINE (#timeline-panel)
- **Class:** `panel panel--timeline`
- **Span:** 8 columns

| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "▤ CYPHER65 · SHARE TIMELINE" |
| Badge | #timeline-shares-badge | Share count |
| Badge | #timeline-bumps-badge | Best-diff bumps |
| Badge | #timeline-rate-badge | Shares/hour rate |
| Stat | #t-stat-lastshare | LAST SHARE |
| Stat | #t-stat-1h | SHARES · 1H |
| Stat | #t-stat-24h | SHARES · 24H |
| Stat | #t-stat-bumps | BEST-DIFF BUMPS · 24H |
| Feed | #timeline-feed | Timeline event rows |

---

### 6.15 — LEADERBOARD (#leaderboard-panel)
- **Class:** `panel`
- **Span:** 8 columns

| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "⌬ POOL LEADERBOARD" |
| Badge | #leaderboard-total | Miner count |
| Table Body | #lb-tbody | #, address, diff rank, loyalty, score, blocks |

---

### 6.16 — LIVE LOG (#logs-panel)
- **Class:** `panel panel--logs`
- **Span:** 4 columns

| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "> LIVE LOG FEED" |
| Badge | #log-events-count | Event count |
| Button | #clear-logs | Clear button |
| Terminal | #terminal | Log lines container |

---

### 6.17 — ALERTS (#alerts-panel)
- **Class:** `panel panel--alerts`
- **Span:** 12 columns

| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "⚠ ALERTS" |
| Badge | #alerts-count-badge | Active count |
| List | #alerts-list | Alert items (severity-coded) |

Alert severity classes: `SEVERITY-INFO`, `SEVERITY-WARN`, `SEVERITY-CRIT`, `SEVERITY-SUCCESS`, `SEVERITY-GOLD`

---

### 6.18 — BLOCK HUNT (#block-hunt-panel)
- **Class:** `panel panel--block-hunt panel--biolume`
- **Span:** 12 columns
- **Organic node:** 1 (bottom:4px left:30% lg organic)

| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "◈ BLOCK HUNT · FIND YOUR BLOCK" |
| Badge | #bh-chance-badge | Chance % per share |
| Badge | #bh-difficulty-badge | Network difficulty |
| Card 1 | #bh-network-diff | NETWORK DIFFICULTY |
| Card 2 | #bh-best-diff | YOUR BEST DIFFICULTY |
| Card 3 | #bh-distance | DISTANCE TO BLOCK (× factor) |
| Card 4 | #bh-p-block | P(BLOCK) · THIS SHARE |
| Card 5 | #bh-expected-time | EXPECTED TIME TO BLOCK |
| Card 6 | #bh-cumulative-p | CUMULATIVE P(BLOCK) |

---

### 6.19 — MARKET (#market-panel)
- **Class:** `panel panel--market panel--biolume`
- **Span:** 12 columns
- **Organic node:** 1 (top:4px left:50% spore)

| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "⟐ HASHMARKET · OPPORTUNITIES" |
| Badge | #mkt-best-price-badge | Best price |
| Badge | #mkt-count-badge | Offer count |
| Grid | #mkt-grid | Offer cards (provider, price, HR, fee, duration) |
| Footnote | #mkt-footnote | Market disclaimer |

---

### 6.20 — AI OPERATOR (#ai-operator-panel)
- **Class:** `panel panel--ai-operator panel--biolume`
- **Span:** 12 columns
- **Organic node:** 1 (bottom:4px right:15% lg organic)

| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "◆ AI OPERATOR · OPERATIONAL INTELLIGENCE" |
| Badge | #ai-status-badge | ACTIVE |
| Button | #ai-clear | Clear chat |
| Messages | #ai-messages | Chat messages container |
| Input | #ai-input | Text input |
| Send | #ai-send | Send button (→) |
| Context | #ai-context | SYSTEM CONTEXT sidebar |
| Context | #ai-ctx-status | ONLINE/OFFLINE |
| Context | #ai-ctx-hr | Current hashrate |
| Context | #ai-ctx-best | Best difficulty |
| Context | #ai-ctx-net | Network difficulty |
| Context | #ai-ctx-fleet | Fleet device count |
| Context | #ai-ctx-pblock | Block probability |

---

### 6.21 — AXE FLEET (#axe-fleet-panel)
- **Class:** `panel panel--axe-fleet panel--biolume`
- **Span:** 12 columns
- **Organic nodes:** 2 (top:4px left:60% tendril, bottom:4px right:45% spore)

| Element | ID | Description |
|---------|-----|-------------|
| Eyebrow | `.panel__eyebrow` | "⚙ AXE FLEET COMMAND · AXEOS REMOTE CONTROL" |
| Badge | #axe-fleet-status-badge | INITIALIZING |
| Badge | #axe-fleet-count-badge | Device count |
| Button | #axe-fleet-add | + ADD device |
| Summary | #axe-summary-hr | TOTAL HASHRATE |
| Summary | #axe-summary-online | ONLINE count |
| Summary | #axe-summary-warning | WARNING count |
| Summary | #axe-summary-offline | OFFLINE count |
| Summary | #axe-summary-health | FLEET HEALTH % |
| Summary | #axe-summary-temp | AVG TEMP |
| Summary | #axe-summary-power | TOTAL POWER |
| Grid | #axe-grid | Device cards |
| Add Form | #axe-add-form | Add device form (IP, name) |
| Detail | #axe-detail | Device detail panel |
| Detail Title | #axe-detail-title | Device name |
| Detail Body | #axe-detail-body | Device metrics |
| Detail Close | #axe-detail-close | Close button |

---

## 7. MODALS

### 7.1 — Wallet Modal (#wallet-modal)
| Element | ID | Description |
|---------|-----|-------------|
| Modal | #wallet-modal | Modal overlay |
| Body | #wallet-body | Modal content |
| Current Address | #wallet-current-addr | Displayed current BTC address |
| Current Worker | #wallet-current-worker | Displayed current worker name |
| Address Input | #wallet-address-input | New address input |
| Worker Input | #wallet-worker-input | New worker name input |
| Save Button | #wallet-save | Save changes |
| Status | #wallet-status | Status message |

### 7.2 — Alert Center Modal (#alert-center-modal)
| Element | ID | Description |
|---------|-----|-------------|
| Modal | #alert-center-modal | Modal overlay |
| Body | #alert-center-body | Modal content |
| Status | #alert-center-status | Status message |
| Tabs | `.ac-tab` | Active / History / Rules tabs |
| Active List | #ac-active-list | Active alerts |
| History List | #ac-history-list | Alert history |
| Rules List | #ac-rules-list | Automation rules |
| Rule Form | #ac-rule-form | Rule creation form |
| Rule Name | #ac-rule-name | Rule name input |
| Rule Device | #ac-rule-device | Device selector |
| Rule Metric | #ac-rule-metric | Metric selector |
| Rule Op | #ac-rule-op | Operator selector |
| Rule Value | #ac-rule-value | Threshold value |
| Rule Action | #ac-rule-action | Action selector |
| Rule Save | #ac-rule-save | Save rule |
| Rule Cancel | #ac-rule-cancel | Cancel |

### 7.3 — Settings Modal (#settings-modal)
| Element | ID | Description |
|---------|-----|-------------|
| Modal | #settings-modal | Modal overlay |
| Body | #settings-body | Dynamic settings content |
| Status | #settings-status | Status message |

### 7.4 — Export Modal (#export-modal)
| Element | ID | Description |
|---------|-----|-------------|
| Modal | #export-modal | Modal overlay |

---

## 8. FOOTER

| Element | CSS Class | Description |
|---------|-----------|-------------|
| Footer | `.footer` | CYPHER65 branding |
| Signature | `.footer__sig` | "⚡ CYPHER65 // BITCOIN MINING INTELLIGENCE" |

---

## 9. DESIGN SYSTEM — CSS ARCHITECTURE

### CSS Variables (`:root`)
- **13** background/border/token variables
- **6** accent colors (btc, green, red, blue, purple, teal)
- **6** accent background variants (10% opacity)
- **6** bio-luminescent colors (biolume, organic, spore, tendril, colony)
- **5** glow shadows
- **5** organic gradients
- **5** border radii (xs, sm, md, lg, xl)
- **4** font families (mono, sans, display)
- **6** fluid font sizes (hero, h1, h2, body, mono, micro)
- **4** shadow levels (sm, md, lg, glow)
- **4** transition durations (fast 120ms, base 200ms, slow 400ms, glacial 800ms)

### Panel Variants (14 accent types)
| Variant | ::before Color | bio-luminescent |
|---------|----------------|-----------------|
| `panel--hero` | BTC Orange | ✅ |
| `panel--proximity` | Teal | ✅ |
| `panel--live-mining` | Blue | ❌ |
| `panel--profit` | Green | ✅ |
| `panel--timeline` | Blue | ❌ |
| `panel--logs` | Text Tertiary | ❌ |
| `panel--alerts` | Text Tertiary | ❌ |
| `panel--chart` | Purple | ❌ |
| `panel--block-hunt` | BTC Orange | ✅ |
| `panel--market` | Purple | ✅ |
| `panel--ai-operator` | Purple | ✅ |
| `panel--axe-fleet` | Teal | ✅ |
| `panel--biolume` | — (additional class) | ✅ |

### Animations (7 keyframe animations)
| Name | Duration | Purpose |
|------|----------|---------|
| `biolume-shimmer` | 4s ease-in-out | Host core gradient border shimmer |
| `node-breathe` | 3s ease-in-out | Organic node pulse |
| `panel-enter` | 0.4s ease-out | Panel entrance animation |
| `pulse` | 2s ease-out | Pulse dot animation |
| `prox-tip-pulse` | 2s ease-out | Proximity arc tip glow |
| `status-pulse` | 2s ease-in-out | Online LED breathing |
| `value-flash` | (inline) | Metric value change flash |

---

## 10. GRID COLUMN SPAN SUMMARY

| Panel | Desktop | <1400px | <768px |
|-------|---------|---------|--------|
| hero-worker | 12 | 12 | 12 |
| proximity-panel | 12 | 12 | 12 |
| live-mining-panel | 12 | 12 | 12 |
| profit-panel | 12 | 12 | 12 |
| pool-overview | 6 | 6 | 12 |
| account-panel | 3 | 6 | 12 |
| network-panel | 3 | 6 | 12 |
| gauge-panel | 12 | 12 | 12 |
| halving-panel | 4 | 6 | 12 |
| fees-panel | 4 | 6 | 12 |
| milestones-panel | 4 | 6 | 12 |
| chart-hashrate-panel | 4 | 6 | 12 |
| chart-pool-panel | 4 | 6 | 12 |
| chart-bestdiff-panel | 4 | 6 | 12 |
| chart-net-panel | 12 | 12 | 12 |
| timeline-panel | 8 | 6 | 12 |
| events-panel | 4 | 6 | 12 |
| leaderboard-panel | 8 | 6 | 12 |
| logs-panel | 4 | 6 | 12 |
| alerts-panel | 12 | 12 | 12 |
| block-hunt-panel | 12 | 12 | 12 |
| market-panel | 12 | 12 | 12 |
| ai-operator-panel | 12 | 12 | 12 |
| axe-fleet-panel | 12 | 12 | 12 |

---

## 11. SERVICE WORKER (`static/sw.js`)
- **Lines:** 117
- **Purpose:** PWA offline support / caching
- **Features:** Cache-first strategy for static assets

---

## 12. JAVASCRIPT ARCHITECTURE (`static/app.js`)
- **Lines:** 2,158
- **Functions:** 83
- **IIFE:** Wrapped in `(() => { 'use strict'; ... })()`
- **Poll Interval:** 15,000ms (configurable via `window.POLL_INTERVAL_MS`)

### Key Render Functions (23 total)
| Function | Purpose |
|----------|---------|
| `renderStatusBar` | Updates status bar blocks |
| `renderHostCore` | Updates HOST CORE stats |
| `renderHero` | Updates hero metrics |
| `renderPool` | Updates pool overview |
| `renderNetwork` | Updates network stats |
| `renderAccount` | Updates account info |
| `renderBtcPrices` | Updates BTC fiat prices |
| `renderHalving` | Updates halving countdown |
| `renderMempoolFees` | Updates fee tiers |
| `renderProfitability` | Updates profit calculations |
| `renderProximity` | Updates proximity meter |
| `renderNetworkGauge` | Updates 3 gauges |
| `renderMilestones` | Updates badge cards |
| `renderAlerts` | Updates alert list |
| `renderEvents` | Updates events table |
| `renderLeaderboard` | Updates leaderboard |
| `renderTimelineFeed` | Updates timeline |
| `renderBlockHunt` | Updates block hunt panel |
| `renderMarket` | Updates market offers |
| `renderAiOperator` | Updates AI context + inits chat |
| `renderLiveMining` | Updates live mining panel |
| `_updateHashSearchState` | Updates hash search visualization |
| `_huntUpdateState` | Updates hunt state |

### Charts (Chart.js v4.4.1)
4 chart instances: `chart-hashrate`, `chart-pool`, `chart-bestdiff`, `chart-net`

### Animations
- Matrix rain (canvas-based, requestAnimationFrame)
- Proximity sparkline (canvas-based, custom drawing)
- 3 gauges (canvas-based, custom drawing)
- Count-up value transitions
- Skeleton loading overlays

---

## 13. DESIGN TOKENS — COLORS

| Token | Value | Usage |
|-------|-------|-------|
| `--accent-btc` | #F7931A | Bitcoin orange, primary accent |
| `--accent-green` | #10B981 | Success, healthy |
| `--accent-red` | #EF4444 | Critical, error |
| `--accent-blue` | #3B82F6 | Information |
| `--accent-purple` | #8B5CF6 | AI, charts |
| `--accent-teal` | #14B8A6 | Proximity, fleet |
| `--accent-biolume` | #00E5FF | Bio-luminescent cyan |
| `--accent-organic` | #A78BFA | Organic purple |
| `--accent-spore` | #F472B6 | Spore pink |
| `--accent-tendril` | #34D399 | Tendril green |
| `--accent-colony` | #FBBF24 | Colony yellow |
| `--bg-deep` | #0C0B0A | Deepest background |
| `--bg-base` | #141311 | Base background |
| `--bg-surface` | #1C1A18 | Surface/elevated panel |
| `--bg-elevated` | #24211D | Highest surface |
| `--text-primary` | #EDE8E3 | Primary text |
| `--text-secondary` | #9D968D | Secondary text |
| `--text-tertiary` | #5E5952 | Muted text |

---

## 14. COMPONENT — NEW BIO-LUMINESCENT SYSTEM

### Added in latest redesign:
| Component | Selector | Description |
|-----------|----------|-------------|
| Host Core | `.host-core` | Mission control hub with shimmer border |
| Shimmer Border | `.host-core::before` | Animated gradient top border (4s) |
| Organic Node | `.org-node` | Positioned dot at panel edges |
| Organic Dot | `.org-node__dot` | Pulsing colored circle (3s breathe) |
| Dot Variants | `.org-node__dot--lg`, `--organic`, `--spore`, `--tendril` | Size and color variants |
| Bio-luminescent | `.panel--biolume` | Teal border + soft glow |
| Panel Glow | `.panel::after` | Radial gradient overlay on hover |
| Colony Group | `.colony-group` | Fleet cell grouping with biolume left border |
| Status Pulse | `.led.is-online` | Breathing animation on online LEDs |

### Organic nodes deployed:
| Panel | Quantity | Types |
|-------|----------|-------|
| hero-worker | 2 | tendril, organic |
| proximity-panel | 2 | lg-tendril, spore |
| profit-panel | 1 | organic |
| block-hunt-panel | 1 | lg-organic |
| market-panel | 1 | spore |
| ai-operator-panel | 1 | lg-organic |
| axe-fleet-panel | 2 | tendril, spore |
| **Total** | **10** | |

---

## 15. FILE MANIFEST

| File | Lines | Purpose |
|------|-------|---------|
| `templates/dashboard.html` | 1,552 | Main dashboard template (Jinja2) |
| `static/style.css` | 2,985 | Complete design system |
| `static/app.js` | 2,158 | Client-side logic |
| `static/sw.js` | 117 | Service Worker (PWA) |
| `static/manifest.json` | — | PWA manifest |
| **Total** | **~6,812** | |

---

*End of layout document. 24 panels + 3 modals + sidebar + topbar + status bar + footer.*
