# CYPHER65 — Beta Tester Recruitment Templates

**Version:** 1.0
**Date:** 2026-08-24
**Goal:** Recruit 10 beta testers (Solo Miners + Small Farms + Rental Ops)

---

## Target Platforms

| Platform | Audience | Tone | Length |
|---|---|---|---|
| Reddit r/BitcoinMining | Solo miners, small farms | Technical, honest | Long-form (500-800 words) |
| Telegram SHA-256 groups | Active miners | Concise, direct | Short (150-250 words) |
| Braiins Discord | Pool users, rental ops | Peer-to-peer, practical | Medium (200-400 words) |
| Twitter/X | Mining community | Hook + thread | Thread (5-7 tweets) |

---

## Template 1: Reddit r/BitcoinMining

```
Title: [Beta] Self-hosted mining dashboard — fleet telemetry, probability engine, hash market comparison (free PRO keys)

---

Hey everyone,

I've been building a self-hosted command center for Bitcoin SHA-256 mining operations and I'm looking for 10 beta testers to stress-test it before a wider release.

**What it does:**

- **Fleet telemetry** — real-time hashrate, temperature, fan speed, efficiency (J/TH), uptime for every ASIC (Antminer, Bitaxe, NerdQaxe, etc.)
- **Probability engine** — P(block)/share based on your actual hashrate and current difficulty (not a calculator, Poisson-based with variance)
- **Hash market comparison** — live prices from Braiins, NiceHash, MRR, and Parasite side by side
- **Rental P/L tracking** — cost vs. market per contract, worst-rig leaderboard, arbitrage alerts
- **Auto-Pilot** — alert when a miner goes offline, restart rules (with consent, safety checks)
- **Profitability** — pool/solo/rental/lease break-even with real electricity costs

**What it's NOT:**

- Not a pool dashboard (it reads from pools, doesn't replace them)
- Not a firmware (no OTA updates)
- Not cloud-hosted (runs on your machine, your data stays local)

**Tech stack:** Python/Flask, SQLite, vanilla JS, React Native companion app. 2,600+ tests.

**What I need from beta testers:**

1. Run it locally (`git clone` + `./run.sh`)
2. Connect your pool (BTC address + worker name)
3. Use it for 2+ weeks
4. Tell me what's broken, what's confusing, what's missing

**What you get:**

- 30-day free PRO access (Probability Engine, Hash Market, Rentals Hub, Auto-Pilot advisory)
- Direct input on the roadmap
- Your name in the credits (if you want)

**Who I'm looking for:**

- Solo miners with 1-5 ASICs (Bitaxe, Antminer, NerdQaxe)
- Small farms (5-20 rigs) tired of spreadsheets
- Rental operators comparing Braiins vs MRR vs NiceHash

**To join:** Comment below or DM me with:
- Your setup (number of ASICs, models, pool)
- Which ICP you identify with (Solo / Farm / Rental)
- Your email (for the trial key)

I'll send you a PRO trial key and a quick-start guide. First 10 get in.

GitHub: https://github.com/0xjc65eth/cypher65-war-room

**Disclaimer:** This is beta software. Probability estimates are statistical, not predictions. Auto-Pilot executes real commands on real hardware — you consent before anything runs. Your data never leaves your machine.
```

### Reddit posting tips

- **Best time:** Tuesday-Thursday, 14:00-18:00 UTC (peak mining discussion)
- **Flair:** Use "Discussion" or "Tool" if available
- **Engagement:** Reply to every comment within 1 hour
- **Cross-post:** r/Bitcoin, r/BitcoinMining, r/Bitcoinmining (check rules first)
- **Don't:** Spam, post daily, use clickbait titles

---

## Template 2: Telegram (SHA-256 Mining Groups)

```
🔧 Looking for 10 beta testers — self-hosted mining dashboard

I built a command center for SHA-256 miners. It runs locally, reads from your pool, and shows:

• Fleet telemetry (hashrate, temp, efficiency per rig)
• P(block) based on YOUR hashrate + current difficulty
• Hash market prices (Braiins/NiceHash/MRR) side by side
• Rental P/L per contract
• Alert when a miner goes offline

What it's NOT: not a pool, not firmware, not cloud.

Tech: Python/Flask, 2,600+ tests, MIT license.

🎁 Free 30-day PRO for first 10 testers.

Who I need:
→ Solo miners (1-5 ASICs)
→ Small farms (5-20 rigs)
→ Rental operators

To join: DM me with your setup + email.
```

### Telegram posting tips

- **Groups to target:** Bitcoin mining groups, ASIC mining groups, solo mining groups
- **Tone:** Concise, no walls of text
- **Don't:** Post in groups with >10k members without checking rules
- **Do:** Share a screenshot of the dashboard if possible

---

## Template 3: Braiins Discord

```
Hey everyone 👋

I've been building a self-hosted mining dashboard that pulls data from Braiins (and other pools) to give a unified view of your operation. Looking for a few testers.

**What it does:**
- Fleet telemetry across all your rigs (not just what the pool shows)
- Live hash market comparison (Braiins vs NiceHash vs MRR)
- Rental P/L tracking with arbitrage alerts
- Probability engine (P(block)/share based on your real hashrate)
- Auto-Pilot alerts (miner offline, overheating)

**What it doesn't do:**
- Replace your pool dashboard (complements it)
- Run firmware updates
- Store your data in the cloud (self-hosted)

**What I need:** 10 people to run it for 2+ weeks and tell me what's broken.

**What you get:** Free 30-day PRO access (all features).

**Who's ideal:**
- Running 1-20 ASICs
- Using Braiins + at least one other pool (for market comparison)
- Tired of checking 3 different dashboards

DM me if interested. First 10 get a trial key.
```

### Braiins Discord posting tips

- **Channel:** Check if there's a #tools, #mining-tools, or #self-hosted channel
- **Tone:** Peer-to-peer, not salesy
- **Don't:** Post in general chat if there's a dedicated channel
- **Do:** Mention Braiins integration specifically (they'll appreciate it)

---

## Template 4: Twitter/X Thread

```
Tweet 1 (Hook):
Building a self-hosted mining dashboard for SHA-256 miners.

Fleet telemetry, probability engine, hash market comparison, rental P/L.

Looking for 10 beta testers. Free PRO for 30 days.

Thread 🧵👇

---

Tweet 2 (Problem):
Solo miners check 3+ dashboards daily:
→ Pool dashboard for shares
→ Firmware UI for temp/hashrate
→ CoinWarz for profitability

None of them talk to each other. Spreadsheets fill the gap.

---

Tweet 3 (Solution):
CYPHER65 War Room — one dashboard, all your data.

• Fleet: hashrate, temp, efficiency per rig
• Market: Braiins vs NiceHash vs MRR live prices
• Rentals: P/L per contract, arbitrage alerts
• Probability: P(block) based on YOUR hashrate

---

Tweet 4 (Honesty):
What it's NOT:
❌ Not a pool
❌ Not firmware
❌ Not cloud-hosted (your data stays local)
❌ Not a prediction engine (it's Poisson statistics)

---

Tweet 5 (Tech):
Built with Python/Flask, SQLite, vanilla JS.
2,600+ tests. MIT license.
Runs on a Raspberry Pi.

GitHub: github.com/0xjc65eth/cypher65-war-room

---

Tweet 6 (CTA):
Looking for 10 beta testers:
→ Solo miners (1-5 ASICs)
→ Small farms (5-20 rigs)
→ Rental operators

Free 30-day PRO access.
DM me your setup + email.

---

Tweet 7 (Disclaimer):
Beta software. Probability = statistics, not prediction.
Auto-Pilot = real commands on real hardware (you consent first).
Your data never leaves your machine.
```

### Twitter posting tips

- **Time:** Post tweet 1 at 15:00 UTC (peak Bitcoin discussion)
- **Thread:** Space tweets 30-60 seconds apart
- **Engagement:** Reply to replies within 30 minutes
- **Don't:** Use hashtags beyond #Bitcoin #Mining
- **Do:** Pin tweet 1 to profile during beta period

---

## Template 5: Discord DM (personalized)

```
Hey [name],

Saw your post about [specific topic — e.g., "tracking rental ROI" / "monitoring Antminer temps" / "comparing Braiins vs MRR prices"].

I built a self-hosted tool that does exactly that. It pulls data from your pool, compares hash market prices, and tracks rental P/L per contract.

Looking for 10 testers — free PRO for 30 days.

Would you be interested in trying it? I can send you a trial key + quick-start guide.
```

### DM tips

- **Personalize:** Reference something specific they posted
- **Short:** Under 100 words
- **Don't:** DM more than 5 people per day (spam filter)
- **Do:** Follow up once after 3 days if no response

---

## Metrics to Track

| Metric | Target | How to Measure |
|---|---|---|
| Total reach | 500+ views | Reddit upvotes, Telegram views, Twitter impressions |
| DMs/Comments received | 20+ | Manual count |
| Trial keys issued | 10 | `scripts/issue-beta-trial.sh` + DB query |
| Keys activated | 8+ | `pro_licenses` table + `/api/v1/status` |
| Daily active users (DAU) | 5+ | Analytics self-hosted (TODO) |
| Feedback submitted | 10+ | GitHub Issues label `beta-feedback` |
| Trial→paid conversion | 2+ | Keys purchased after trial expires |

---

## Timeline

| Day | Action |
|---|---|
| **Day 1** | Post on Reddit + Telegram + Braiins Discord |
| **Day 2** | Post Twitter thread + DM 5 people |
| **Day 3-5** | Reply to all comments/DMs, issue keys |
| **Day 7** | Check activation rate, follow up with non-activated |
| **Day 14** | Mid-beta survey (3 questions) |
| **Day 21** | Reminder: trial expires in 7 days |
| **Day 30** | Trial expires → measure conversion |
| **Day 31** | Decide: launch public / pivot / close beta |

---

## Key Distribution

When someone joins, send them:

```
Hey [name],

Here's your CYPHER65 War Room PRO trial key:

Key: C65-XXXX-XXXX-XXXX-XXXX
Valid: 30 days from activation

Quick start:
1. git clone https://github.com/0xjc65eth/cypher65-war-room.git
2. cd cypher65-war-room && ./run.sh
3. Open http://localhost:8765
4. Go to ⚙ Settings → paste your key
5. Click CONNECT WALLET → enter your BTC address + worker name

What to try:
→ Fleet tab: see your rigs in real time
→ Market tab: compare hash prices across providers
→ Probability tab: see P(block) for your hashrate
→ Rentals tab: track your rental P/L (if applicable)

Feedback: Open a GitHub Issue (label: beta-feedback) or DM me.

Thanks for testing! 🙏
```
