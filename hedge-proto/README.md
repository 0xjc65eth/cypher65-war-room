# hedge-proto — Hedge Your Fun Proof-of-Capability

> **Built for:** Full Stack Solana Developer application @ Hedge Your Fun (Superteam Earn)  
> **Author:** Julio Cesar (0xjc65 / @0xcypher65)  
> **Status:** Architecture & design phase — 72-hour build target for prototype

> **Note:** This README describes the target architecture. Implementation is starting — see `src/` for current state. The architecture decisions below reflect the final design; code will follow this structure.

---

## What This Is

A **minimal, functional prototype** proving capability for the Hedge Your Fun technical scope. This is not a toy — every integration hits real APIs, every data point comes from live sources, and the architecture is production-thoughtful.

**Scope covered (from original job requirements):**

| # | Item | Status |
|---|---|---|
| 1 | Polymarket CLOB API (real, not mocked) | 🔴 Target |
| 2 | Kalshi API (RSA-SHA256 auth) | 🔴 Target |
| 3 | Privy embedded wallet + Solana balance | 🔴 Target |
| 4 | PostgreSQL + Drizzle ORM persistence | 🟡 Target |
| 5 | SSE-powered P&L endpoint | 🟡 Target |
| 6 | Rate limiting + retry middleware | 🟡 Target |

---

## Architecture Decisions

### Why Next.js 15 + TypeScript

The job explicitly requires Next.js. Vercel-native deployment means zero-config serverless functions, edge middleware for rate limiting, and built-in API routes — no Express/Fastify wrapper needed. TypeScript catches the kind of bugs that lose money in production.

### Why Drizzle ORM over Prisma

- **No code generation step.** Schema is TypeScript. Migrations are SQL. No `prisma generate` in CI.
- **Smaller bundle.** Drizzle's client is ~10KB vs. Prisma's multi-MB engine.
- **SQL-first.** Polymarket/Kalshi data is relational (markets → outcomes → positions). Direct SQL control matters when debugging P&L queries.
- **Supabase-compatible.** Works with both Supabase and Neon Postgres without changing the ORM layer.

### Why SSE over WebSocket for P&L

- **Simpler.** SSE is HTTP-native. No upgrade handshake. No sticky sessions.
- **Sufficient.** P&L updates are server→client only. No need for bidirectional comms on the dashboard.
- **Vercel-compatible.** SSE works on Vercel's serverless functions with streaming responses. WebSocket requires a separate infrastructure (or Vercel's experimental support).

### Why Privy for Wallet (not raw key management)

- **Non-custodial by design.** Privy's embedded wallet never exposes the private key to the backend. All signing is client-side.
- **Social auth.** Users can log in with email/Google — no seed phrase required. Critical for a mobile-first consumer app.
- **Solana-native.** Privy v2 has first-class Solana support including SPL token reads.

### Polymarket vs. Kalshi Data Strategy

- **Polymarket:** On-chain settlement via USDC on Polygon. CLOB order book. Token-based outcome model (ERC-1155). Uses `indexSets` bitmask for multi-outcome positions. I already have production code for this in Python (`polybotcypher`).
- **Kalshi:** CFTC-regulated. REST API with RSA-SHA256 request signing. Traditional order book (not AMM). Settlement in USD, not crypto.
- **Unified schema:** Both feed into a normalized `markets` table. The frontend doesn't care which exchange a market comes from — it sees a unified data model.

### Rate Limiting & Retry Strategy

- **Upstash Redis** for distributed rate limiting across serverless functions.
- **Exponential backoff** with jitter on all external API calls (Polymarket, Kalshi, Solana RPC).
- **Circuit breaker** pattern: after 5 consecutive failures, the endpoint goes into "degraded" mode (serves cached data) for 30 seconds before retrying.

---

## Project Structure

```
hedge-proto/
├── APPLICATION/          # Job application materials
│   ├── CV.md
│   ├── COVER_LETTER.md
│   └── PORTFOLIO.md
├── src/
│   ├── app/
│   │   ├── api/
│   │   │   ├── markets/       # GET /api/markets — Polymarket + Kalshi
│   │   │   ├── pnl/           # GET /api/pnl (SSE stream)
│   │   │   └── wallet/        # GET /api/wallet — Solana balance
│   │   ├── dashboard/         # Main dashboard page
│   │   └── layout.tsx
│   ├── lib/
│   │   ├── polymarket.ts      # CLOB API client (ported from py_clob_client)
│   │   ├── kalshi.ts          # Kalshi REST client (RSA auth)
│   │   ├── solana.ts          # Solana RPC + SPL token balance
│   │   ├── privy.ts           # Privy server-side verification
│   │   ├── db/
│   │   │   ├── schema.ts      # Drizzle schema
│   │   │   └── index.ts       # DB connection
│   │   ├── ratelimit.ts       # Upstash rate limiter
│   │   └── retry.ts           # Exponential backoff + circuit breaker
│   └── components/
│       ├── WalletConnect.tsx   # Privy connect button + balance display
│       ├── MarketList.tsx      # Real-time market data table
│       └── PnLWidget.tsx       # Live P&L via SSE
├── drizzle.config.ts
├── .env.example                # Required env vars (no real keys)
├── next.config.ts
├── package.json
├── tsconfig.json
└── README.md                   # ← you are here
```

---

## Environment Variables

Copy `.env.example` to `.env.local` and fill in:

```bash
# Polymarket
POLYMARKET_PROXY_WALLET=0x...
POLYMARKET_CLOB_API_URL=https://clob.polymarket.com

# Kalshi
KALSHI_API_KEY=kalshi-key-...
KALSHI_PRIVATE_KEY_PATH=./kalshi-rsa.pem

# Solana RPC (Helius or QuickNode — public RPC rate-limits too low)
SOLANA_RPC_URL=https://mainnet.helius-rpc.com/?api-key=...

# Privy
NEXT_PUBLIC_PRIVY_APP_ID=...
PRIVY_APP_SECRET=...

# Database (Supabase or Neon)
DATABASE_URL=postgresql://...

# Rate Limiting (Upstash Redis)
UPSTASH_REDIS_REST_URL=...
UPSTASH_REDIS_REST_TOKEN=...
```

---

## Running Locally

```bash
cd hedge-proto
npm install
cp .env.example .env.local
# Fill in .env.local with real keys
npm run dev
# Open http://localhost:3000
```

---

## What Evaluators Should Look At

1. **`src/lib/polymarket.ts`** — The CLOB client demonstrates deep Polymarket knowledge (indexSets, tick-size rounding, order lifecycle).
2. **`src/lib/solana.ts`** — Solana RPC + SPL token balance reading shows wallet integration capability.
3. **`src/lib/retry.ts`** — The retry/circuit-breaker middleware proves API hardening awareness.
4. **`src/app/api/markets/route.ts`** — Server-side API route pulling real data from two exchanges and normalizing it.
5. **This README** — Architecture decisions explained clearly in < 5 minutes of reading.

---

## Non-Goals (for now)

- **React Native / PWA wrapper.** PWA first (ship faster, no app store review). Mentioned in cover letter as deliberate decision.
- **Referral/sharing (hedge cards).** Cosmetic. Post-hire.
- **Intent parsing / market matching pipeline.** Hard to demo without their real dataset. Approach explained in cover letter.
- **Full production hardening.** Prototype scope. Production hardening comes with 12-month engagement.

---

## License

MIT — this is a portfolio piece. Use it, learn from it, don't sue me.
