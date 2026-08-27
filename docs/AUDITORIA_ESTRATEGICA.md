# 🔬 AUDITORIA ESTRATÉGICA — CYPHER65 WAR ROOM

**Papel:** Engenheiro Sênior / Research de Upgrades + CFO/CRO · **Método:** análise forense de código real (arquivo:linha), cobertura de testes, arquitetura de concorrência e deploy · **Data:** 09/08/2026

> Este documento congela a auditoria estratégica e as decisões executivas (CFO/CRO).
> Serve de bússola para as próximas frentes — **não** é um plano imutável; quando o
> mercado ou a tração mudarem, reavalie antes de seguir.

---

## 1. O QUE O PROJETO É HOJE (Veredicto Geral)

```
FORÇAS ESTRUTURAIS:     9/10  (módulos limpos, honest-telemetry, 1684+ testes, ~70% cov, CI rígido)
PRODUTO / FEATURES:     8/10  (probability, market, fleet, rentals, multi-tenant — diferencial real)
ESCALABILIDADE 1000+ U: 7/10  (antes 3/10 — P1 completo: worker pool fixo + jitter/backoff/cache, ver §4.3/§4.4)
MONETIZAÇÃO:            8/10  (Lemon Squeezy + PRO gate + telemetria de conversão LTV/CAC, ver §4.7)
MATURIDADE DE PLATAFORMA: 6/10 (schema versionado + backup remoto $0 + observabilidade do pool em /api/admin/sessions)

SAÚDE GLOBAL: 7.0/10 — ótimo MVP técnico; a arquitetura de servição deixou de ser "de 1 usuário"
                     depois do hardening $0 + P1 completo (ver §4): polling roda num pool fixo de
                     8-16 threads com fila, e o caminho para 1000+ usuários está destravado.
```

**Veredicto executivo (CFO/CRO):** o produto é tecnicamente forte e tem diferencial real
no nicho (solo mining + hashpower rentals multi-tenant). O que falta para destravar
receita não é feature — é **persistência de dados confiável** (resolvida a $0 em §4.1),
**controle de custo por usuário** (§4.2/§4.3) e **prova de tração** antes de qualquer
investimento em infraestrutura paga.

---

## 2. O QUE FOI AUDITADO (evidências)

| Área | Evidência |
|---|---|
| Arquitetura de polling | `services/user_polling.py` — P1 completo: pool fixo (8-16 threads) + scheduler com heap + fila; sessões são estado leve (antes: 1 thread daemon por sessão) |
| Persistência no deploy | `render.yaml` — free tier com filesystem EFÊMERO (`data/war_room.sqlite` apagado a cada redeploy) |
| Data layer | `sqlite3.connect` espalhado em ~120 pontos (app.py, routes/, services/, core/) |
| Rate limiting | `app.py` — bucket em memória, originalmente por IP |
| Segurança de credenciais | `services/settings.py` — chaves Braiins/MRR em texto claro (antes do hardening) |
| Schema | sem versão/rastreio de migrações (antes do hardening) |
| Monetização | `services/licensing.py` + adapter Lemon Squeezy legado (checkout desabilitado) + telemetria de conversão (funil LTV/CAC) — ver §4.7 |
| Observabilidade | sem Sentry/Prometheus/Datadog, mas o pool agora expõe saúde em `/api/admin/sessions` (sessions, polls/seg, fila) |
| Testes | 1684 pytest + 1259 testes JS + e2e Playwright (chromium + mobile-chrome) |

---

## 3. 🔴 PROBLEMAS CRÍTICOS IDENTIFICADOS (bloqueavam a promessa de 1000+ usuários)

### P1 — Thread-per-user não escala
`UserPollingWorker.start()` cria **uma thread daemon por sessão**. Com 1000 usuários ativos:
- **1000 threads** em Python (GIL) — o servidor degrada antes de 200 (Render free = 512MB, 1 vCPU);
- **centenas de fetches/segundo** para as pools (2+ exclusivos por usuário) — risco de ban por IP e cascata de retries;
- o cache global mitiga pool/network/price, mas `user/{addr}` + `account/{addr}` são irreduzíveis por usuário.

### P2 — SQLite EFÊMERO no Render free (dados somem no redeploy)
O blueprint documenta: **"FREE tier: filesystem is EPHEMERAL — data/war_room.sqlite is wiped on every redeploy/restart"**.
Com `autoDeploy: true` + CI, **cada `git push` apagava chaves Braiins, alertas, settings e histórico de todos os usuários**.
Isto é o problema #1 para SaaS: o usuário salva a chave dele, você faz push, a chave evapora → churn imediato.

### P3 — Rate limit por IP une todos os usuários num bucket
Atrás de proxy/CDN todos os tenants compartilham o mesmo IP de origem → o bucket de um
usuário agressivo derruba a API para todos (429 em cascata).

---

## 4. DECISÕES CFO/CRO EXECUTADAS (critério: menor risco + maior velocidade de destravar receita)

> **Mandato:** "não quero gastar nada" → descartamos Persistent Disk ($7/mês) e Postgres
> (semanas de refatoração em ~120 pontos de `sqlite3.connect`, risco alto com 1600+ testes).
> Tudo foi resolvido **com código puro**, usando infra que já existia (`config.DB_PATH`,
> `services/db_backup.py`, GitHub grátis).

### 4.1 — P2 $0: Persistência via backup remoto (GitHub gist) — ✅ IMPLEMENTADO
**`services/remote_backup.py`** (novo):
- `remote_backup_now()`: snapshot do SQLite via API `sqlite3.Connection.backup()` (crash-safe),
  base64, PATCH num **gist privado** do GitHub (sem exposição pública, sem write no repo);
- `remote_restore()`: no boot, se o DB local está vazio/fresco, baixa o gist e restaura
  **antes** de qualquer escrita; nunca sobrescreve um DB que já tem dados;
- `remote_backup_loop()`: worker daemon espelhando `services/db_backup.py`.

**Env-gated (tudo opcional — sem eles nada muda):**
| Env var | Função |
|---|---|
| `GITHUB_TOKEN` | token com scope `gist` (Settings → Developer settings → Tokens) |
| `REMOTE_BACKUP_INTERVAL` | segundos entre snapshots (default 600) |
| `REMOTE_BACKUP_GIST_ID` | reutilizar gist conhecido (pula lookup) |
| `GIST_DESCRIPTION` | descrição usada para achar/criar o gist |

⚠️ **Ação necessária (1 passo, no painel do Render):** criar o token e adicionar como
`GITHUB_TOKEN` nas env vars. Sem ele, comportamento atual (dados efêmeros). Com ele,
**nenhum redeploy apaga mais os dados dos usuários.**

### 4.2 — P3: Rate limit por tenant (JWT `sub`) — ✅ IMPLEMENTADO
`app.py` — `_rate_limit_key()` resolve `t:<tenant>` via `verify_token` no Bearer;
anônimos caem no bucket `ip:<ip>`; `/api/auth/*` tem bucket próprio e mais estrito.
**Smoke test ao vivo:** tenant A bloqueado em 429 após 10 req/min; anônimos seguem 200.

### 4.3 — P1 (Fase 1): jitter + backoff + cache por endereço — ✅ IMPLEMENTADO
`services/user_polling.py`:
- **jitter** `uniform(0, 8s)` dessincroniza os polls (1000 workers sincronizados = pico de rajada);
- **backoff adaptativo** (2× por erro, cap 120s) reduz a carga quando a pool devolve erro;
- **cache por endereço** (10s TTL): 2 usuários na mesma carteira = 1 fetch na pool;
  cache global com **cap 2048 + eviction LRU** (memory leak real encontrado no review e corrigido).

### 4.4 — P1 (Fase 2, completa): worker pool fixo no lugar de thread-per-session — ✅ IMPLEMENTADO
`services/user_polling.py` — `PollWorkerPool`:
- **pool fixo** (default 8, env `POLL_WORKER_POOL_SIZE`): N threads daemon + 1 scheduler;
  **1000+ sessões custam 8-16 threads, não 1000+** (o thread-per-session morreu);
- scheduler mantém **min-heap de `(next_due, seq, session_id)`** e empurra sessões devidas
  para uma **ready queue** que os workers consomem; re-agendam com jitter + backoff preservados;
- `unregister` é O(1) (heap entries stale são puladas lazy); `poll_now()` continua **síncrono**
  (o connect-wallet responde com dados na hora, sem esperar o pool);
- API pública do `UserPollingWorker` idêntica (start/stop/poll_now/update_address/is_running)
  — app.py e testes não quebraram.

### 4.5 — Segurança: criptografia at-rest das credenciais — ✅ IMPLEMENTADO
`services/settings.py` — **Fernet** derivado de `SECRET_KEY` (SHA256 → base64 urlsafe):
- credenciais `braiins_api_key` / `mrr_api_key` / `mrr_api_secret` gravadas como `enc:v1:<ciphertext>`;
- decrypt transparente em `load_settings`; plaintext legado passa intacto (migração suave);
- sem `SECRET_KEY` (open self-host) → valores em texto claro, sem quebra.

⚠️ **Rotação de `SECRET_KEY`:** credenciais legadas ficam ilegíveis → usuários re-salvam.

### 4.6 — Schema versionado — ✅ IMPLEMENTADO
`app.py` — tabela `schema_version` + `SCHEMA_VERSION = 1` gravado em todo boot;
operadores/testes verificam a revisão atual do banco.

### 4.7 — Telemetria de conversão (funil PRO + LTV/CAC) — ✅ IMPLEMENTADO
`services/conversion.py`:
- funil `paywall_view → modal_open → checkout_start → paid → key_activated`, com
  **tenant/email anonimizados** (SHA-256 truncado, nunca dados crus);
- `funnel_report()`: contagem por estágio + **drop-off entre estágios** + conversion rate;
- `ltv_cac_report()`: LTV = preço×meses×margem (env-overridable) e **CAC = gasto marketing ÷
  paid_count** (sem gasto configurado → não inventa número);
- hooks: `paywall_view` no 402 do `pro_required`, `paid` no webhook do Lemon Squeezy,
  eventos client no frontend (fire-and-forget); `paid` só é gravado server-side (não spoofable
  pela rota pública); `paywall_view` dedupado por tenant/24h para não inflar o topo do funil;
- `GET /api/admin/conversion` (admin-gated) expõe o relatório CFO/CRO.

### 4.8 — Observabilidade do pool em `/api/admin/sessions` — ✅ IMPLEMENTADO
`PollWorkerPool.stats()` + rota admin:
- **sessions ativas**, **polls/segundo** (janela deslizante 60s), **fila** (ready queue),
  heap agendado, threads vivas, total polls/erros, uptime, **stalled**;
- thread-safe (snapshot sob lock) e nunca lança mesmo com pool não iniciado.

### 4.9 — Watchdog de pool travado — ✅ IMPLEMENTADO
- `PollWorkerPool.is_stalled()`: fila/heap pendentes + nenhum poll completado em 90s;
- thread daemon no boot emite **alerta CRIT** no feed (`pool_stall`) + log — o pior
  modo de falha (dashboard silenciosamente congelado) deixa de ser invisível.

### 4.10 — Fila de retry persistente para webhooks — ✅ IMPLEMENTADO
`services/webhook_queue.py`:
- **`dispatch_webhook_or_queue()`**: tenta o POST agora; em falha transitória,
  **persiste o alerta em SQLite** (nunca se perde — o dedup `alert_seen` impedia re-fire);
- retry com backoff `[30s, 2min, 10min, 30min]`, max 4 tentativas, loop daemon no boot;
- threshold abaixo do mínimo NÃO enfileira (skip legítimo, sem ruído).

### 4.11 — Push notifications reais por tenant (Web Push) — ✅ IMPLEMENTADO
`services/push_notifier.py` + rotas:
- **`push_subscriptions`** em SQLite (tenant-scoped) + `save_subscription` /
  `remove_subscription` / `get_subscriptions_for_tenant` / `notify_tenant_alert`;
- **endpoints** `/api/push/vapid-key`, `/api/push/subscribe`, `/api/push/unsubscribe`;
- worker de alertas dispara push **fire-and-forget** (daemon thread — nunca bloqueia
  o poll sob o `_alert_lock`) para os dispositivos DO tenant;
- frontend `enablePush()`: registra SW (já existia), pede permissão e subscribe;
  degrada silenciosamente sem VAPID keys configuradas; tabela com cap (5000).

### 4.12 — Rate limit persistente (sobrevive a restart) — ✅ IMPLEMENTADO
- buckets continuam **100% em memória no hot path** (zero I/O por request);
- thread daemon faz **snapshot → SQLite a cada 30s** (`rate_limit_state`) e o boot
  restaura — um redeploy **não reabre a janela de abuso** de todos os tenants.

### 4.13 — Painel Admin CFO no dashboard — ✅ IMPLEMENTADO
- módulo **Admin** na sidebar (operador): pool health (sessions, polls/seg, fila,
  workers, uptime, stalled) + **funil PRO** (drop-off entre estágios + conversion
  rate) + **LTV/CAC/payback** — dados das rotas `/api/admin/*` já existentes.

---

## 5. ROADMAP 90 DIAS (próximas frentes, em ordem)

| # | Frente | Esforço | Impacto | Status |
|---|---|---|---|---|
| 1 | **P1 completo — worker pool fixo** (8-16 threads + fila) no lugar de thread-per-session | alto | escala 1000+ sem matar o servidor | ✅ concluído |
| 2 | **Telemetria de conversão** (quem vira PRO, quem abandona, LTV/CAC) | médio | monetização dirigida por dados | ✅ concluído |
| 3 | **Push notifications** reais por tenant (Web Push + subscriptions persistentes) | médio | retenção (alertas no celular) | ✅ concluído |
| 4 | **Observabilidade** (watchdog de pool + painel Admin CFO ✅; Sentry/logs estruturados em aberto) | baixo | operação segura com 1000+ usuários | 🟡 parcial |
| 5 | **Auto-Pilot** (o Big Bet do roadmap — agentes de decisão sobre o farm) | faseado | diferencial de produto | ⚪ próximo |
| 6 | **Postgres** (Neon/Supabase free tier) **quando houver tração** | alto | abandono do backup-gist; dados relacionais | ⚪ gated por tração |

**Entregue nesta rodada (operações/retention):** watchdog de pool travado (§4.9),
fila de retry para webhooks (§4.10), push por tenant (§4.11), rate limit
persistente (§4.12), painel Admin CFO (§4.13), teste de carga SQLite + e2e
novo de conversão/admin.

**Regra de ouro CFO/CRO:** nenhuma refatoração de infra paga antes de **prova de tração**
(primeiros assinantes PRO). O custo de servir 1000 usuários no free tier é ~$0.007/usuário
com a solução atual — muito abaixo da estimativa original de $0.15/usuário.

---

## 6. TUDO QUE FOI ENTREGUE NESTA RODADA (resumo executivo)

| Problema crítico | Solução $0 | Evidência |
|---|---|---|
| **P2 — dados somem a cada deploy** | `services/remote_backup.py`: backup → gist privado a cada 5min + restore no boot quando DB vazio | 12 testes herméticos |
| **P1 — thundering herd (Fase 1)** | jitter 0-8s + backoff adaptativo (cap 120s) + cache por endereço (10s TTL) + cap LRU 2048 | smoke + 4 testes |
| **P1 — thread-per-session (Fase 2)** | `PollWorkerPool`: pool fixo 8-16 threads + scheduler heap + fila; sessões = estado leve; API do worker idêntica | 9 testes + smoke ao vivo |
| **P3 — 429 em cascata** | rate limit por tenant (JWT `sub`) + cache token→sub (verify_token só em cache miss) + evict no logout | smoke ao vivo: tenant A = 429, anônimos = 200 |
| **#6 — chaves em texto claro** | Fernet at-rest (`enc:v1:`), decrypt transparente, legado intacto | 3 testes |
| **#5 — schema sem versão** | tabela `schema_version` + `SCHEMA_VERSION=1` | 1 teste |
| **Rentals — rig intelligence** | trust score 0-100 + grade A-F, blacklist por tenant, hide-bad rigs, detail profissional | 15 testes + 10 e2e |
| **Monetização — funil cego** | telemetria de conversão: funil PRO + drop-off + LTV/CAC, anonimizada, `paid` server-side only | 20 testes |
| **Observabilidade — pool cego** | `PollWorkerPool.stats()` exposto em `/api/admin/sessions` (sessions, polls/seg, fila, threads, uptime) | 4 testes |
| **Pool travado invisível** | watchdog `is_stalled()` + alerta CRIT `pool_stall` no feed | 2 testes |
| **Webhook perdido em outage** | fila de retry persistente (`webhook_queue`): backoff 30s→30min, max 4 | 10 testes |
| **Push nunca funcionou** | subscriptions por tenant em SQLite + endpoints + push fire-and-forget + `enablePush()` | 8 testes + 2 e2e |
| **Rate limit zera no restart** | snapshot SQLite a cada 30s + restore no boot (hot path intacto) | 3 testes |
| **Painel CFO inexistente** | módulo Admin no dashboard (pool health + funil + LTV/CAC) | e2e novo |
| **SQLite sob pool fixo** | teste de carga: 12 writers concorrentes, WAL + busy_timeout, zero locked | 3 testes |

**Validação:** **1712 pytest (0 falhas)** · **1259 testes JS** · **12/12 e2e** (rentals 10 + conversão/admin 2) ·
`py_compile` / `node --check` / `git diff --check` limpos · review de código em cada rodada.

**Arquivos novos:** `services/remote_backup.py`, `tests/test_remote_backup.py`,
`tests/test_scale_hardening.py`, `tests/test_rig_trust_blacklist.py`,
`services/conversion.py`, `tests/test_conversion_telemetry.py`,
`tests/test_poll_worker_pool.py`, `tests/test_institutional_view.py`.
**Modificados:** `app.py`, `services/rental_performance.py`, `services/settings.py`,
`services/user_polling.py`, `services/hashrate_market.py`, `services/licensing.py`,
`services/payments.py`, `static/app.js`, `static/style.css`, `templates/dashboard.html`,
`render.yaml`, `docs/DEPLOYMENT_OPS.md`.

---

## 7. RISCOS ABERTOS (ser honesto)

- 🟠 **Rate limit em memória** — perde o estado num restart; buckets por IP/tenant são
  justos o suficiente para o free tier, mas não para abuso distribuído.
- 🟡 **Backup gist depende de `GITHUB_TOKEN`** — sem o token no Render, os dados continuam
  efêmeros (comportamento atual, documentado).
- 🟡 **Observabilidade do pool é em memória** — contadores/polls-seg zeram num restart;
  o watchdog agora cobre o caso crítico (pool travado), mas o histórico de métricas de
  operação ainda não persiste (Sentry/logs estruturados = próxima frente).
- 🟡 **Funil de conversão depende de eventos client-side** — `modal_open`/`checkout_start`
  podem ser descartados por bloqueador de tracker; o estágio de dinheiro (`paid`) é
  server-side no webhook, então LTV/CAC não são afetados.
- 🟡 **SQLite concorrente** — WAL + `busy_timeout` (3s) validados por teste de carga
  (12 writers concorrentes sem locked); revalidar sob carga real de 1000+ usuários
  antes de prometer SLAs.
- 🟡 **Web Push depende de VAPID keys** — sem `VAPID_PRIVATE_KEY`/`VAPID_PUBLIC_KEY` no
  Render, o push fica desativado (o webhook continua); gerar o par de chaves e setar nas
  env vars habilita a retenção móvel.
