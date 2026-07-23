# Julio Cesar — Full Stack Solana Developer

> **Contact:** 0xjc65 / @0xcypher65  
> **Location:** Brazil (UTC-3)  
> **Portfolio:** https://cypherordifuture.xyz  
> **GitHub:** [github.com/0xjc65](https://github.com/0xjc65) *(request access for private repos)*

---

## Summary

Full-stack engineer with production experience across **Polymarket CLOB API**, **Next.js 15/TypeScript**, **Bitcoin mining infrastructure**, and **non-custodial financial integrations** (BTCPay Server, Ledger hardware wallets). Built and deployed a Polymarket trading bot (`polybotcypher`) that runs live against the CLOB order book with LMSR probability pricing and Kelly criterion position sizing. CYPHER V3, a Next.js 15 full-stack application with zero TypeScript errors, is live at cypherordifuture.xyz. Seeking to bring real prediction-market and Web3 infrastructure experience to Hedge Your Fun.

---

## Technical Skills

| Category | Stack |
|---|---|
| **Blockchain / Web3** | Solana web3.js, SPL Token, Polymarket CLOB API, Bitcoin RPC, BTCPay Server, Ledger HW |
| **Frontend** | Next.js 15, React 19, TypeScript, Tailwind CSS, Progressive Web Apps |
| **Backend** | Node.js, Python (Flask), REST APIs, Server-Sent Events, WebSocket |
| **Data** | PostgreSQL, SQLite, Drizzle ORM, Prisma, real-time polling pipelines |
| **Infrastructure** | Vercel, Docker, Linux systemd, nginx |
| **AI / Automation** | AI agent orchestration, social media automation (X/Twitter bot), intent parsing |
| **Financial** | Automated Market Makers (LMSR), Kelly Criterion, P&L tracking, prediction markets |

---

## Relevant Projects

### polybotcypher — Polymarket CLOB Trading Bot *(2025–present, Production)*
**Stack:** Python, `py_clob_client`, LMSR pricing, Kelly Criterion

- Built a fully autonomous trading bot operating on **Polymarket's CLOB order book**
- Implements **indexSets calculation** (multi-outcome token bundle logic — ridiculously tricky edge case in Polymarket's v2 API that most devs get wrong)
- **LMSR-based probability pricing** for market-making spreads
- **Kelly Criterion position sizing** with configurable risk fraction
- Handles proxy wallet patching, order redemption, and CLOB order lifecycle
- *Directly relevant to: Polymarket API integration (#1 in scope)*

### CYPHER V3 — AI Agent Orchestration Platform *(Q1 2026–present, Live)*
**Stack:** Next.js 15, TypeScript, React 19, Tailwind CSS  
**URL:** https://cypherordifuture.xyz

- Full-stack Next.js 15 application with **zero TypeScript errors** across the entire codebase
- Multi-agent orchestration system with chat interface, file management, and real-time streaming
- **21 modular skill files** for domain-specific agent behaviors (Solana, Polymarket, serverless hardening, etc.)
- Deployed on Vercel with environment-based secret management (zero hardcoded keys)
- Custom CSS design system with dark theme, responsive layout, and micro-interactions
- *Directly relevant to: Next.js/TS architecture, real-time data, secret management (#3, #4, #7 in scope)*

### cypher65 War Room — Bitcoin Mining Monitor *(2024–present, Production)*
**Stack:** Python, Flask, SQLite, REST APIs, real-time polling

- Real-time mining dashboard monitoring a Bitcoin miner on Parasite Pool
- **Parallel API fan-out** (8+ endpoints polled simultaneously, 15s intervals)
- **Anomaly detection**: stale shares, hashrate drops, pool block found, proximity to network difficulty
- P&L calculator: pool vs. solo vs. rental modes, multi-currency (USD/BRL/EUR/GBP)
- Webhook alerts to Discord/Telegram with severity-based routing
- Server-Sent Events for live timeline updates (eliminated polling for critical events)
- *Directly relevant to: real-time P&L, data persistence, alerting infrastructure (#3, #4, #7)*

### BTCPay Server + Ledger Hardware Integration *(2024)*
**Stack:** BTCPay Server API, Ledger HW wallet, Bitcoin

- Integrated BTCPay Server for non-custodial Bitcoin payment processing
- Hardware wallet workflow with Ledger for cold-storage operational security
- **Zero private key exposure** — all signing happens on-device
- *Directly relevant to: non-custodial architecture, Privy integration philosophy (#2 in scope)*

### X/Twitter Automation Bot *(2025)*
**Stack:** Node.js, Twitter API v2

- Automated content scheduling and engagement bot for X/Twitter
- Rate-limit-aware queue with exponential backoff
- Multi-account support with credential rotation
- *Directly relevant to: API rate limiting, retry strategies (#7 in scope)*

---

## Languages

- **Portuguese** — Native
- **English** — Professional working proficiency (reading/writing: fluent; speaking: intermediate)

---

## Availability

- Available to start upon selection (announcement: July 29, 2026)
- Committed to the full 12-month engagement
- Full-time availability (40+ hrs/week)
