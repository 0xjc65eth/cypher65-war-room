# Portfolio — Julio Cesar (0xjc65 / @0xcypher65)

> **For:** Full Stack Solana Developer @ Hedge Your Fun (Superteam Earn)

---

## Live Projects

### 1. CYPHER V3 — AI Agent Orchestration Platform
- **URL:** https://cypherordifuture.xyz
- **Stack:** Next.js 15, TypeScript, React 19, Tailwind CSS, Vercel
- **What it proves:** Full-stack Next.js architecture, zero TypeScript errors, real-time streaming, environment-based secret management, modular skill system (21 skill files)
- **Relevant to:** Frontend architecture, real-time data, secret management, API routes

### 2. polybotcypher — Polymarket CLOB Trading Bot
- **Repo:** Private (access available upon request)
- **Stack:** Python, `py_clob_client`, LMSR pricing, Kelly Criterion
- **What it proves:** Deep Polymarket CLOB API expertise (indexSets, proxy wallets, redemption flow, tick-size rounding), automated market making, position sizing
- **Relevant to:** Item #1 in scope — Polymarket API integration

### 3. cypher65 War Room — Bitcoin Mining Monitor
- **Repo:** This repository (`cypher65-war-room`)
- **Stack:** Python, Flask, SQLite, REST APIs, SSE, parallel API fan-out
- **What it proves:** Real-time monitoring infrastructure, P&L calculation engine, anomaly detection, data persistence, webhook alerting
- **Relevant to:** Items #3, #4, #7 — data persistence, P&L tracking, API hardening

---

## Proof-of-Capability Prototype (planned — 72h build target)

### Hedge Your Fun — Full Stack Prototype
- **Repo:** `hedge-proto/` (this repository)
- **Planned Stack:** Next.js 15, TypeScript, Drizzle ORM, PostgreSQL, Solana web3.js, Privy, Polymarket CLOB API, Kalshi API
- **Features (72h target):**
  1. `/api/markets` — real Polymarket + Kalshi market data (no mocks)
  2. Privy embedded wallet connection + SOL/USDC balance display
  3. SSE-powered P&L endpoint (replaces polling)
  4. PostgreSQL persistence layer with Drizzle ORM
  5. Rate limiting + retry middleware on all external API calls

---

## Skill Modules — CYPHER V3 Framework (existing, documented)

The CYPHER V3 agent framework already includes these documented skill files demonstrating domain expertise. Each is a reusable, self-contained specification for an AI agent to perform a specific domain task:

| Skill | Domain |
|---|---|
| `skill-polymarket-clob.md` | CLOB order book, indexSets, redeem, proxy patching |
| `skill-solana-web3.md` | RPC connection, SPL Token, commitment levels |
| `skill-privy-embedded-wallet.md` | Auth flow, embedded wallet creation, delegated signing |
| `skill-kalshi-api.md` | RSA-SHA256 auth, order book, CFTC settlement differences |
| `skill-nextjs-serverless-hardening.md` | Rate limiting, retry/backoff, error boundaries, secret rotation |
| `skill-realtime-pnl.md` | SSE/WebSocket for real-time data, polling elimination |

*Note: the Pol-Kalshi, Privy, and hardening skill files are designed but not yet implemented in the CYPHER V3 skill library. Solana, Polymarket, and real-time P&L modules exist today.*

---

## Design Philosophy

1. **Non-custodial by default.** Backend never touches private keys. All signing is client-side.
2. **Zero hardcoded secrets.** `.env.local` + `.gitignore` from commit zero. Credential rotation is a first-class concern.
3. **Ship real data, not mocks.** Every integration hits the live API. If it can't, the README explains exactly why and how to enable it.
4. **Readable READMEs.** Evaluators spend 5 minutes on your repo. The README should tell the whole story.
