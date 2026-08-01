# 🚀 CYPHER65 War Room — Free Production Hosting

> **TL;DR** — This app is a *stateful* Flask service (background polling threads,
> SQLite file persistence, SSE streaming). **Serverless platforms (Vercel, Render
> free, Railway, Netlify) are NOT compatible** — their filesystem is read-only/ephemeral
> and they kill background processes. The only genuinely-free, always-on host that
> fits is an **Oracle Cloud Free Tier ARM VPS**. This guide walks through it in ~20
> minutes, and the repo already ships `Dockerfile`, `docker-compose.yml`, `install.sh`
> and a validated CI pipeline.

---

## 1. Why not Vercel? (production review verdict)

| Requirement | Vercel (serverless) | Oracle Free VPS |
|---|---|---|
| Persistent filesystem (SQLite `data/war_room.sqlite`) | ❌ read-only/ephemeral | ✅ dedicated disk |
| Background threads (polling, warmup, donation watcher) | ❌ never start | ✅ run 24/7 |
| SSE streaming (long-lived responses) | ❌ 10s/60s timeout | ✅ unlimited |
| Always-on / no cold sleep | ⚠️ cold starts, sleeps | ✅ always on |
| Free forever | — | ✅ Always Free tier |

**Vercel verdict: NO-GO for the current architecture.** Moving would require a full
rewrite (stateless + external DB + queue workers) — the wrong trade for a self-hosted
mining dashboard. Oracle Cloud's Always Free ARM VM gives you 4 OCPU / 24 GB RAM /
200 GB disk for **$0/month, indefinitely**.

---

## 2. Step 1 — Create the Oracle Cloud Free VM

1. Go to <https://signup.cloud.oracle.com/> and create an account (a real credit card
   is required for identity verification, but **Always Free resources never charge**).
2. After the account is active: **Compute → Instances → Create instance**.
3. Choose:
   - **Image**: `Canonical Ubuntu 24.04` (aarch64)
   - **Shape**: `VM.Standard.A1.Flex` (Always Free eligible)
   - **OCPU**: `4` / **Memory**: `24 GB` (max free config — more than enough)
   - **Boot volume**: 200 GB (Always Free max)
4. **Add SSH key** — generate a keypair locally and paste the public key:
   ```bash
   ssh-keygen -t ed25519 -C "cypher65-deploy" -f ~/.ssh/cypher65
   ```
5. Create the instance. Note the public IP shown in the console.

> ⚠️ **Free-tier cost guard**: Oracle bills you if you exceed Always Free limits.
> Always choose the `A1.Flex` shape, keep 4 OCPU/24GB, and stop the instance when not
> in use. Set up a **budget alert** (Billing → Budgets, $1) to be safe.

### Open the port in the security list

In the instance details → **Virtual cloud networks → Security list → Add ingress rule**:
- Source CIDR: `0.0.0.0/0`
- IP protocol: `TCP`
- Destination port: `8765`

---

## 3. Step 2 — First SSH login

```bash
ssh -i ~/.ssh/cypher65 ubuntu@<PUBLIC_IP>
```

Then install Docker + Compose (single command, official script):

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-compose-plugin
sudo usermod -aG docker ubuntu   # log out & back in for this to take effect
```

---

## 4. Step 3 — Deploy the app

```bash
# clone
git clone https://github.com/<your-user>/cypher65-war-room.git
cd cypher65-war-room

# env (NO DEBUG_MOCK — honest telemetry premise)
cp .env.example .env
#  ─ edit .env ─
#  SECRET_KEY=<long-random-string>      (generate: openssl rand -hex 32)
#  PORT=8765
#  # Optional, for API-key auth + multi-tenant:
#  API_KEY=your-operator-key
#  TENANT_API_KEYS={"acme":"key-acme-1"}
#  # Optional monitoring:
#  SENTRY_DSN=https://....ingest.sentry.io/....
#  # Optional CORS for the React Native mobile app:
#  CORS_ORIGINS=https://your-domain

# build + start (image is arm64-native, uses docker compose v2)
docker compose up -d --build

# verify
curl -s http://localhost:8765/api/healthz   # → healthy
docker compose logs -f                      # watch boot: polling threads + warmup
```

The repo's `install.sh` automates this interactively (asks for Tailscale auth key,
subnet, DB choice) — run `./install.sh` if you prefer the guided path.

---

## 5. Optional — Tailscale for private access (recommended)

Never expose the dashboard to the public internet unless you configure API-key auth.
The recommended pattern is **Tailscale** — the dashboard lives on your private
overlay network:

```bash
curl -fsSL https://tailscale.com/install.sh | sudo sh
sudo tailscale up --ssh   # authenticate with your Tailscale account
```

Now the app is reachable only from your devices at `http://<tailscale-ip>:8765`.
See `docs/REMOTE_ACCESS_TUTORIAL.md` for the full guide with limitations.

---

## 6. Keep it healthy

- **Restart policy**: `docker-compose.yml` sets `restart: unless-stopped` — the app
  comes back after reboots and crashes.
- **Backups** (the whole state is one SQLite file):
  ```bash
  # daily cron: copy the DB + WAL off-box
  0 3 * * * cp /home/ubuntu/cypher65-war-room/data/war_room.sqlite /home/ubuntu/backups/war_room.$(date +\%F).sqlite
  ```
- **Updates**:
  ```bash
  cd ~/cypher65-war-room && git pull && docker compose up -d --build
  ```
- **CI is already wired**: `.github/workflows/ci.yml` (lint + 850+ pytest + 800+ JS
  core) and `execution-pipeline.yml` (validate → build image → integration → deploy
  hook) run on every push; `soak-weekly.yml` runs the long-duration soak suite.

---

## 7. Cost summary

| Item | Cost |
|---|---|
| Oracle ARM VM (4 OCPU / 24 GB / 200 GB) | **$0.00** always free |
| Domain (optional) | ~$10/yr or use Tailscale magic DNS |
| Sentry free tier (optional) | **$0.00** |
| Total | **$0/month** |

> The only thing that would ever cost money is exceeding Always Free limits — keep
> the shape at A1.Flex 4/24 and you're permanently free.

---

## 8. If you outgrow free tier

When this stops being enough, the **same Docker image** deploys unchanged to a
$4–6/mo VPS (Hetzner, DigitalOcean, Oracle paid shapes). The compose file, env vars
and healthcheck are identical — scale up, don't rewrite.
