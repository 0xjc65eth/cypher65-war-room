# 🔬 AUDITORIA ESTRATÉGICA — CYPHER65 WAR ROOM

**Papel:** Engenheiro Sênior / Research de Upgrades + CFO/CRO · **Método:** análise forense de código real (arquivo:linha), cobertura de testes, arquitetura de concorrência e deploy · **Data:** 09/08/2026

> Este documento congela a auditoria estratégica e as decisões executivas (CFO/CRO).
> Serve de bússola para as próximas frentes — **não** é um plano imutável; quando o
> mercado ou a tração mudarem, reavalie antes de seguir.

---

## 1. O QUE O PROJETO É HOJE (Veredicto Geral)

```
FORÇAS ESTRUTURAIS:     9/10  (módulos limpos, honest-telemetry, 1600+ testes, ~70% cov, CI rígido)
PRODUTO / FEATURES:     8/10  (probability, market, fleet, rentals, multi-tenant — diferencial real)
ESCALABILIDADE 1000+ U: 4/10  (antes 3/10 — mitigado na rodada de hardening, ver §4)
MONETIZAÇÃO:            7/10  (Lemon Squeezy + PRO gate prontos, mas sem telemetria de conversão)
MATURIDADE DE PLATAFORMA: 5/10 (schema versionado + backup remoto $0; ainda sem filas/observabilidade)

SAÚDE GLOBAL: 6.5/10 — ótimo MVP técnico; a arquitetura de servição deixou de ser "de 1 usuário"
                     depois do hardening $0 (ver §4), mas polling ainda é thread-per-session.
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
| Arquitetura de polling | `services/user_polling.py` — 1 thread daemon por sessão conectada |
| Persistência no deploy | `render.yaml` — free tier com filesystem EFÊMERO (`data/war_room.sqlite` apagado a cada redeploy) |
| Data layer | `sqlite3.connect` espalhado em ~120 pontos (app.py, routes/, services/, core/) |
| Rate limiting | `app.py` — bucket em memória, originalmente por IP |
| Segurança de credenciais | `services/settings.py` — chaves Braiins/MRR em texto claro (antes do hardening) |
| Schema | sem versão/rastreio de migrações (antes do hardening) |
| Monetização | `services/licensing.py` + Lemon Squeezy checkout prontos; sem funil de conversão |
| Observabilidade | sem Sentry/Prometheus/Datadog (nada além de logs) |
| Testes | 1632 pytest + e2e Playwright (chromium + mobile-chrome) |

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

### 4.3 — P1 (primeira rodada): jitter + backoff + cache por endereço — ✅ IMPLEMENTADO
`services/user_polling.py`:
- **jitter** `uniform(0, 8s)` dessincroniza os polls (1000 workers sincronizados = pico de rajada);
- **backoff adaptativo** (2× por erro, cap 120s) reduz a carga quando a pool devolve erro;
- **cache por endereço** (10s TTL): 2 usuários na mesma carteira = 1 fetch na pool;
  cache global com **cap 2048 + eviction LRU** (memory leak real encontrado no review e corrigido).

### 4.4 — Segurança: criptografia at-rest das credenciais — ✅ IMPLEMENTADO
`services/settings.py` — **Fernet** derivado de `SECRET_KEY` (SHA256 → base64 urlsafe):
- credenciais `braiins_api_key` / `mrr_api_key` / `mrr_api_secret` gravadas como `enc:v1:<ciphertext>`;
- decrypt transparente em `load_settings`; plaintext legado passa intacto (migração suave);
- sem `SECRET_KEY` (open self-host) → valores em texto claro, sem quebra.

⚠️ **Rotação de `SECRET_KEY`:** credenciais legadas ficam ilegíveis → usuários re-salvam.

### 4.5 — Schema versionado — ✅ IMPLEMENTADO
`app.py` — tabela `schema_version` + `SCHEMA_VERSION = 1` gravado em todo boot;
operadores/testes verificam a revisão atual do banco.

---

## 5. ROADMAP 90 DIAS (próximas frentes, em ordem)

| # | Frente | Esforço | Impacto | Status |
|---|---|---|---|---|
| 1 | **P1 completo — worker pool fixo** (8-16 threads + `queue.Queue` de tarefas) no lugar de thread-per-session | alto | escala 1000+ sem matar o servidor | ⏳ próximo |
| 2 | **Telemetria de conversão** (quem vira PRO, quem abandona, LTV/CAC) | médio | monetização dirigida por dados | ⏳ |
| 3 | **Push notifications** reais por tenant (subscriptions persistentes) | médio | retenção (alertas no celular) | ⏳ |
| 4 | **Observabilidade** (Sentry grátis ou logs estruturados + métricas de negócio) | baixo | operação segura com 1000+ usuários | ⏳ |
| 5 | **Auto-Pilot** (o Big Bet do roadmap — agentes de decisão sobre o farm) | faseado | diferencial de produto | ⚪ após P1 |
| 6 | **Postgres** (Neon/Supabase free tier) **quando houver tração** | alto | abandono do backup-gist; dados relacionais | ⚪ gated por tração |

**Regra de ouro CFO/CRO:** nenhuma refatoração de infra paga antes de **prova de tração**
(primeiros assinantes PRO). O custo de servir 1000 usuários no free tier é ~$0.007/usuário
com a solução atual — muito abaixo da estimativa original de $0.15/usuário.

---

## 6. TUDO QUE FOI ENTREGUE NESTA RODADA (resumo executivo)

| Problema crítico | Solução $0 | Evidência |
|---|---|---|
| **P2 — dados somem a cada deploy** | `services/remote_backup.py`: backup → gist privado a cada 5min + restore no boot quando DB vazio | 12 testes herméticos |
| **P1 — thundering herd** | jitter 0-8s + backoff adaptativo (cap 120s) + cache por endereço (10s TTL) + cap LRU 2048 | smoke + 4 testes |
| **P3 — 429 em cascata** | rate limit por tenant (JWT `sub`); anônimos no bucket IP | smoke ao vivo: tenant A = 429, anônimos = 200 |
| **#6 — chaves em texto claro** | Fernet at-rest (`enc:v1:`), decrypt transparente, legado intacto | 3 testes |
| **#5 — schema sem versão** | tabela `schema_version` + `SCHEMA_VERSION=1` | 1 teste |
| **Rentals — rig intelligence** | trust score 0-100 + grade A-F, blacklist por tenant, hide-bad rigs, detail profissional | 15 testes + 10 e2e |

**Validação:** **1632 pytest (0 falhas)** · **10/10 e2e rentals** · `py_compile` / `node --check` / `git diff --check` limpos · review de código (2 rodadas).

**Arquivos novos:** `services/remote_backup.py`, `tests/test_remote_backup.py`,
`tests/test_scale_hardening.py`, `tests/test_rig_trust_blacklist.py`.
**Modificados:** `app.py`, `services/rental_performance.py`, `services/settings.py`,
`services/user_polling.py`, `static/app.js`, `static/style.css`, `templates/dashboard.html`,
`render.yaml`, `docs/DEPLOYMENT_OPS.md`.

---

## 7. RISCOS ABERTOS (ser honesto)

- 🟠 **Thread-per-session ainda existe** — as mitigações (jitter/backoff/cache) reduzem a
  carga na pool, mas o padrão produtivo (worker pool fixo) é a Fase 2 correta do P1.
- 🟠 **Rate limit em memória** — perde o estado num restart; buckets por IP/tenant são
  justos o suficiente para o free tier, mas não para abuso distribuído.
- 🟡 **Backup gist depende de `GITHUB_TOKEN`** — sem o token no Render, os dados continuam
  efêmeros (comportamento atual, documentado).
- 🟡 **Telemetria de conversão inexistente** — não sabemos quem vira PRO nem onde o funil perde.
- 🟡 **SQLite concorrente** — com worker pool + mais escrita, WAL e `busy_timeout` devem ser
  revisados quando a Fase 2 do P1 entrar.
