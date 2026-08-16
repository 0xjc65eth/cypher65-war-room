# ⚡ CYPHER65 War Room · Deploy & Operations

Guia de implantação **adaptado à realidade do projeto** (a stack enxuta que
realmente roda: Flask + SQLite + Tailscale opcional). Sem Kafka, ClickHouse,
InfluxDB obrigatório ou TimescaleDB — o sistema é self-contained e sobe com
um único comando.

> ⚠️ **Nota de honestidade**: um rascunho anterior propunha uma stack
> "cypher65-ultimate" com Kafka/ClickHouse/InfluxDB/TimescaleDB. Essa
> arquitetura referenciava módulos que não existem neste repositório
> (`run.py`, `core/axe_registry.py`, `routes/fleet.py`, `workers/`) e se
> contradizia ("sem libs externas" vs `influxdb_client`/`aiokafka`). Esta
> versão entrega o **mesmo valor operacional com a arquitetura real**:
> SQLite como fonte da verdade + mirror InfluxDB **opcional** + acesso
> remoto via Tailscale.

---

## 🚀 Instalação (1 comando)

No servidor Linux/Ubuntu **na mesma rede dos mineradores**:

```bash
curl -sSL https://raw.githubusercontent.com/0xjc65eth/cypher65-war-room/master/install.sh | bash
```

O script pergunta apenas 3 coisas:
1. **Tailscale Auth Key** (opcional — vazio = só local; cria em
   https://login.tailscale.com/admin/settings/keys)
2. **Sub-rede local** dos mineradores (ex: `192.168.1.0/24`)
3. **Rate limit** (default `300`)

Ele gera o `.env`, faz o build e sobe o stack. Ao final mostra a URL do
dashboard e, se você deu a chave Tailscale, a URL remota
`https://cypher65-<hostname>.ts.net`.

### Manual (equivalente)

```bash
cp .env.example .env      # edite BTC_ADDRESS + WORKER_NAME
docker compose up -d --build                 # só local
docker compose --profile tailscale up -d     # com acesso remoto
```

---

## 🏗 Componentes

| Arquivo | Função |
|---|---|
| `Dockerfile` | Imagem slim do app real (`python app.py`, porta **8765**, healthcheck `/api/healthz`) |
| `docker-compose.yml` | App + **sidecar Tailscale opcional** (profile `tailscale`, subnet router, `tailscale serve` em 443) |
| `install.sh` | Instalador interativo 1-comando (idempotente, preserva `.env`) |
| `core/data_layer.py` | Camada de dados **SQLite-first** + mirror InfluxDB **opcional** com circuit breaker e cache quente |
| `core/alerts/automation_engine.py` | Motor de automação com **deadlock prevention** (conflitos resolvidos por prioridade) |

### Por que sem InfluxDB/ClickHouse/Kafka?

- **SQLite (WAL)** já persiste tudo com zero infra — perfeito para 1 servidor
  e dezenas de miners.
- **InfluxDB é opcional** e ativado só se `INFLUXDB_URL` estiver definido **e**
  o pacote `influxdb_client` estiver instalado. Falha do mirror **nunca** derruba
  o app (circuit breaker abre após 3 falhas/60s e re-tenta em 5min).
- **ClickHouse/Kafka** são justificáveis a partir de ~1.000 miners; para a
  escala atual adicionam latência de deploy e superfície de falha sem ganho.

---

## ⚙ Multi-processo (gunicorn + workers) — opcional

O default é **single-process**: `python app.py` serve HTTP **e** roda os
workers de background (poll loop, hash-market warmup, donation watcher,
auto-backup) no mesmo processo. Isso funciona perfeitamente para
self-host/Tailscale/Render free tier.

Para uma topologia **multi-processo** (escala ou deploy em container com
`gunicorn`), o projeto agora oferece um entrypoint separado de workers:

```bash
# Processo 1 — HTTP (gunicorn):
gunicorn -k gevent -w 2 -b 0.0.0.0:8765 app:app

# Processo 2 — telemetria/workers (em outro container ou no mesmo host):
python -m services.workers
```

**Limitação honesta (SSE):** `/api/stream` (live-push) fan-out é
in-process. Na topologia de dois processos, o live-push só chega a quem
está conectado ao processo HTTP dono da conexão; o dashboard cobre com o
poll de 15s (cache) — suficiente para telemetria. Para live-push total
multi-worker seria preciso um pub/sub compartilhado (Redis) — não
implementado. Prefira `python app.py` quando live-push importar.

`render.yaml` documenta o mesmo: **nunca** rode `gunicorn app:app` sozinho
sem o processo de workers — o dashboard ficaria vazio para sempre.

## 💾 Persistência no Render — ZERO CUSTO (backup remoto via GitHub gist)

> **Decisão CFO/CRO (2026-08-09):** o projeto roda no **free tier ($0)** e a
> persistência é feita com **backup remoto automático** em um **gist privado
> do GitHub** (`services/remote_backup.py`). O free tier do Render apaga o
> SQLite a cada redeploy/restart — este mecanismo restaura os dados no boot
> seguinte, então **credenciais, settings, alertas e histórico por-usuário
> (multi-tenant) sobrevivem a deploys sem pagar nada.**

### Como funciona

- A cada `REMOTE_BACKUP_INTERVAL` (default 600s), o app faz um snapshot
  crash-safe do SQLite (`sqlite3.Connection.backup`) e envia base64 para um
  **gist PRIVADO** do GitHub (uma só instância do arquivo, sobrescrita).
- No boot, se o DB local está vazio (boot efêmero) e o gist tem snapshot,
  o app **restaura** o arquivo antes de qualquer escrita. Um DB que já tem
  dados de usuário **nunca é sobrescrito**.
- É env-gated: **sem `GITHUB_TOKEN`, nada acontece** (comportamento atual).

### Ativação (uma vez, $0)

> **Issue #14 (feito):** o blueprint (`render.yaml`) já provisiona as duas
> vars — `GITHUB_TOKEN` com `sync: false` (a chave é criada no deploy, o
> **valor nunca vai para o git** — só no dashboard) e
> `REMOTE_BACKUP_INTERVAL=300`. Depois de mergear o PR, o operador só
> precisa colar o PAT real no painel.

1. Crie um **Personal Access Token** do GitHub com scope `gist`:
   GitHub → Settings → Developer settings → Personal access tokens →
   **Generate new token (classic)** → marque `gist` → copie.
   (PAT fine-grained também funciona se tiver permissão de escrita em gists;
   o classic com scope `gist` é o caminho mais simples e suficiente.)
2. Render → Dashboard → o serviço → **Environment** → edite a var
   `GITHUB_TOKEN` (criada pelo blueprint com `sync: false`) e cole o token
   como secret. `REMOTE_BACKUP_INTERVAL` já vem com `300`.
3. **Redeploy** (ou Restart). Confira no log:
   `[remote_backup] snapshot pushed ... -> gist ...`
4. **Valide no shell do Render** (Render → o serviço → Shell):
   ```bash
   python scripts/verify_remote_backup.py             # probe read-only
   python scripts/verify_remote_backup.py --roundtrip # + teste de upload
   ```
   Saída esperada: `✔ verified — the gist is receiving backups...` (exit 0).
   O `--roundtrip` grava em um arquivo de verificação **separado**
   (`war_room.verify.sqlite.b64`) — nunca toca no snapshot real.
5. Teste o restore: conecte uma wallet/salve uma chave → force um redeploy →
   os dados **voltam** (o log mostra `[remote_backup] restored ... from gist`).

> 🔒 O gist é **privado** (só o seu token lê). A base64 não é criptografia —
> a proteção real das credenciais em repouso é o **Fernet** em
> `services/settings.py` (criptografa `braiins_api_key`/`mrr_*` quando
> `SECRET_KEY` está setada).

### Limites honestos

- **Única instância**: o backup pressupõe 1 serviço web. Com 2+ instâncias
  o restore poderia pisar em dados frescos — não rode replicação neste modo.
- **Tamanho**: limite de arquivo do gist (~100MB) — folga enorme para o
  SQLite real deste app (poucos MB). Se um dia exceder, aí sim migrar para
  Postgres (Supabase/Neon free tier — Gravity Index recommend).

### ⚠️ Rotação do `SECRET_KEY` e credenciais criptografadas

As credenciais (`braiins_api_key`, `mrr_api_key`, `mrr_api_secret`) são
armazenadas **criptografadas com Fernet derivado do `SECRET_KEY`**. Isso
significa:

- **Trocar o `SECRET_KEY` = credenciais legadas ficam ilegíveis.** O app
  degrada graciosamente (nunca quebra), mas os consumidores passariam a
  receber o ciphertext como se fosse a chave → auth das pools falha em
  silêncio. **Após rotacionar o `SECRET_KEY`, peça que cada usuário
  re-salve suas credenciais** (ou rode um script de re-criptografia).
- **Sem `SECRET_KEY`** (open self-host), os valores ficam em plaintext
  (comportamento legado, sem mudança).

---

## 🛰 Acesso Remoto (Tailscale)

O sidecar (`--profile tailscale`) transforma o servidor em **subnet router**:

- Anuncia a sub-rede local dos miners (`TS_ROUTES=192.168.1.0/24`), então o
  dashboard alcança `192.168.1.x` de qualquer lugar da tailnet.
- `tailscale serve --https=443` expõe o dashboard com **TLS automático** —
  sem abrir portas no roteador, sem port-forwarding, sem cert-manager.
- **O que o usuário consegue fazer remotamente**: ver dashboard, telemetria
  dos miners (hashrate, temp, eficiência), comandos de fleet, alertas.
- **Limitações honestas**:
  - O app expõe os miners **dentro da tailnet** — se você der acesso a
    terceiros, eles veem sua rede de mineração.
  - `tailscale serve` exige uma tailnet (plano gratuito suporta 3 usuários
    e até 100 dispositivos).
  - A sub-rede anunciada precisa de aprovação na admin console do Tailscale
    (subnet routes são review-required por padrão).

---

## 🔧 Configuração (`.env`)

| Variável | Default | Descrição |
|---|---|---|
| `BTC_ADDRESS` | — | Wallet a monitorar |
| `WORKER_NAME` | — | Worker no pool |
| `PORT` | `8765` | Porta HTTP |
| `RATE_LIMIT_PER_MINUTE` | `300` | Rate limit da API |
| `SECRET_KEY` | random | Assinatura de sessão |
| `API_KEY` / `TENANT_API_KEYS` | — | Auth básica / multi-tenant |
| `DEBUG_MOCK` | `0` | `1` apenas para demo local |
| `INFLUXDB_URL` / `TOKEN` / `ORG` / `BUCKET` | vazios | **Opção**: mirror de métricas |
| `CERT_FILE` / `KEY_FILE` | — | TLS opcional no app |
| `TAILSCALE_AUTH_KEY` / `LOCAL_SUBNET` | — | Usados pelo compose/install |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | — | **Web Push** (ver seção abaixo) |
| `VAPID_SUBJECT` | `mailto:admin@cypher65.local` | Contato do push service (mailto:) |

> ⚠ **NÃO configure `MRR_API_KEY` / `MRR_API_SECRET` / `BRAIINS_API_KEY` no `.env`**
> em um deploy **multi-tenant** (veja a seção "Credenciais por usuário" abaixo).

---

## 🔑 Credenciais por usuário (MRR/Braiins) — NUNCA chave global

**Regra do produto:** nenhuma chave MRR/Braiins existe como chave global ou
compartilhada. **Cada usuário configura a própria** no app
(`Settings ⚙ → MRR credentials` / `Braiins credentials`), e a chave fica
armazenada **criptografada em repouso** (Fernet derivada de `SECRET_KEY`) na
linha `tenant_settings` daquele tenant — nunca no código, nunca no `.env`,
nunca no repositório. (Sem `SECRET_KEY` em open self-host, as chaves são
armazenadas em texto plano — por isso **sempre** setar `SECRET_KEY` em
qualquer deploy com usuários.)

Como o app garante isso:

1. **Isolamento hermético por tenant** — os resolvers
   (`mrr_credentials`/`braiins_credentials`) leem **somente** as linhas do
   próprio tenant em `tenant_settings`. Env vars e a tabela global **nunca**
   são consultadas para um tenant nomeado — um usuário sem chave própria
   recebe vazio (`🔑` no painel), **nunca** a chave do operador.
2. **Env vars são só do tenant default (self-host)** — `MRR_API_KEY` /
   `MRR_API_SECRET` / `BRAIINS_API_KEY` afetam **apenas** a própria instância
   do operador (comportamento legado de self-host). Em deploy multi-tenant o
   boot **avisa** se elas existirem: remova-as do ambiente.
3. **Settings UI avisa override** — se uma env var estiver setada, o modal
   mostra "⚠ env var SOBRESCREVE o valor abaixo" para MRR e Braiins.
4. **Testes fixam a regra** — `test_named_tenant_without_own_key_never_inherits_env`
   garante que um tenant sem chave própria nunca herda env/global.

**Em deploy multi-tenant:** não definir nenhuma dessas env vars. Cada usuário
entra, abre Settings e adiciona a própria chave. O operador (tenant default)
usa as próprias chaves da mesma forma.

**Fluxo de validação por usuário** (passo a passo completo no guia do usuário,
`docs/AGENT_SETUP_GUIDE.md` → **Passo 5**):

1. **MRR**: `miningrigrentals.com → My Account → API Access` → gerar/copiar a
   **API key + secret** do site → `Settings ⚙ → MRR credentials` → **Salvar** →
   o painel RENTALS mostra as contagens reais (sem 🔑/⚠).
2. **Braiins**: `hashpower.braiins.com → API Tokens` → copiar o **owner token**
   → `Settings ⚙ → Braiins credentials` → **Salvar** → **🔑 TESTAR CHAVE
   BRAIINS** (verdict ok/rejected na hora, sem esperar o painel).
3. **Estados do painel**: 🔑 = chave não configurada · ⚠ = chave configurada
   mas **REJEITADA** pela API (regenerar no site do provider) · número = conta
   real OK.
4. **Bad Nonce (MRR)**: a chave salva é inválida/desatualizada — **regenerar**
   (copiar a antiga não resolve). Ver `Troubleshooting — Bad Nonce` abaixo.

## 📲 Web Push (VAPID) — Issue #15

Web Push de alertas (ex: auto-exclusão, worker offline) entrega para o browser
mesmo com a aba fechada. Fica **OFF** até o par VAPID ser configurado — sem ele
o frontend nem oferece subscrição e `notify_tenant_alert` degrada silencioso.

### 1. Gerar o par de chaves (uma vez)

```bash
pip install pywebpush
python -c "from py_vapid import Vapid; import base64; \
from cryptography.hazmat.primitives import serialization as S; \
v=Vapid(); v.generate_keys(); \
print(base64.urlsafe_b64encode(v.public_key.public_bytes(S.Encoding.X962, \
S.PublicFormat.UncompressedPoint)).rstrip(b'=').decode()); \
print(base64.urlsafe_b64encode(v.private_key.private_numbers() \
.private_value.to_bytes(32,'big')).rstrip(b'=').decode())"
# linha 1 = VAPID_PUBLIC_KEY · linha 2 = VAPID_PRIVATE_KEY
```

### 2. Setar no Render (dashboard → Environment)

| Variável | Valor | sync |
|---|---|---|
| `VAPID_PUBLIC_KEY` | pública (base64url) | `false` (fora do git) |
| `VAPID_PRIVATE_KEY` | **secreta** (base64url) | `false` |
| `VAPID_SUBJECT` | `mailto:voce@dominio.com` (opcional) | `false` |

As chaves **nunca** entram no git — o `render.yaml` as provisiona com
`sync: false` e o valor real vai só no Render dashboard.

### 3. Validar entrega real

1. Abra o dashboard no domínio **https** (Web Push exige contexto seguro).
2. O frontend registra o service worker e pede permissão automaticamente
   (apenas quando a rota `/api/push/vapid-key` retorna a chave).
3. Settings → alertas → **🧪 TESTAR ALERTA** — responde `push_targets >= 1`
   quando a entrega real chegou (mesmo payload que o sweep envia).
4. Se `push_targets: 0`, confira: https no navegador, permissão concedida,
   chaves batendo (a privada deve corresponder à pública) e `pywebpush`
   instalado (`requirements.txt` já o inclui).

### Arquitetura

`services/push_notifier.py` (VAPID + `pywebpush`) → `/api/push/subscribe`
(autenticado por JWT — Issue #115) → tabela `push_subscriptions` por tenant →
`notify_tenant_alert()` (sweep/auto-exclusão) → `static/sw.js` listener `push`
→ notificação OS com clique foca o dashboard.

---

## 📊 Camada de Dados (`core/data_layer.py`)

```python
from core.data_layer import write_metric, query_recent, query_historical

write_metric("192.168.1.50", "temperature", 61.5)          # SQLite (durable)
rows = query_recent("192.168.1.50", "temperature", minutes=15)   # cache 5min
hist = query_historical("192.168.1.50", "temperature", hours=24)
```

- **SQLite-first**: `metric_samples` com índice `(device_id, metric, ts)`.
- **Mirror opcional**: se `INFLUXDB_URL` setada, espelha best-effort.
- **Circuit breaker**: 3 falhas/60s → mirror desligado por 5min (retry automático).
- **Cache quente**: consultas recentes memoizadas por 5min.

---

## 🤖 Automação com Deadlock Prevention

`core/alerts/automation_engine.py` agora resolve **conflitos de ação no mesmo
device** em um ciclo:

- Pares conflitantes: `overclock/underclock`, `pause/resume`, `restart/poweroff`,
  `start/stop`.
- **Prioridade maior vence**; empate cancela **ambas** (log + auditoria
  `CANCELLED_BY_CONFLICT`).
- Adicione `priority` na regra para controlar quem ganha.

---

## 🧪 Testes

```bash
python -m pytest tests/ --cov=app --cov=helpers --cov=axe_fleet --cov=services --cov=core --cov-fail-under=45
node --test tests/test_app_js_core.js
npm run test:e2e        # Playwright
```

O CI (`ci.yml`) roda o gate completo + cobertura em todo push/PR para `master`.

---

## 📦 Atualizações

```bash
git pull
docker compose build cypher65-app
docker compose up -d
```

---

## 🔭 Observabilidade (custo $0 — Issue #30)

| Recurso | Como ativar | Notas |
|---|---|---|
| **Sentry** (erros + traces) | env: `SENTRY_DSN=...`, opcional `SENTRY_TRACES_SAMPLE_RATE=0.1`, `SENTRY_RELEASE`, `SENTRY_ENVIRONMENT` | `services/sentry_telemetry.py` (Issue #176) — request_id em breadcrumbs/events, release = git SHA, PII-safe; 5k errors/mês free |
| **Logs JSON** | env: `LOG_JSON=1` | `services/observability.py` — um JSON por linha, `jq`-able |
| **Boot health** | sempre | linha estruturada `[boot] ready` com port/worker/db |
| Admin CFO + pool stats | sempre | `/api/admin/sessions` (sessions, polls/s, fila, threads) |
| **Error rate local** (self-host) | sempre | `services/error_tracker.py` — todo ERROR/CRITICAL do log vira bucket por hora com `request_id`; view no Admin `/api/admin/error-rate` (funciona SEM Sentry) |

Matriz de decisão: Datadog/NewRelic são paid → **não adotados** (regra de ouro
CFO/CRO $0). OpenTelemetry é o caminho futuro (exporter OTLP → Sentry) quando
houver tração (gated por tração, ver `docs/AUDITORIA_ESTRATEGICA.md`).

Exemplo:
```bash
LOG_JSON=1 SENTRY_DSN=https://xxx@sentry.io/123 python app.py
# opcional: SENTRY_TRACES_SAMPLE_RATE=0.1 · SENTRY_ENVIRONMENT=cloud ·
# SENTRY_RELEASE=cypher65-war-room@<sha> (default: git short SHA do deploy)
```

---

## 🛡 Segurança

- `.env` **nunca** é commitado (gitignored); segredos ficam só no servidor.
- App bindado em `127.0.0.1` no compose — exposição pública só via Tailscale
  Serve (TLS) ou proxy reverso.
- Código roda como usuário não-root (`USER cypher` no Dockerfile).
- Sem chaves de wallet/seed no servidor — apenas endereços públicos.

## 🧯 Troubleshooting — MRR: `Not Authenticated - Invalid Key - Bad Nonce.`

**Sintoma:** o painel RENTALS mostra `Provider error: Not Authenticated -
Invalid Key - Bad Nonce.` (ou `API key rejected` com o mesmo motivo) para um
tenant com chave configurada no Settings.

**Causa raiz:** a **credencial MRR é inválida/desatualizada** (key/secret que
não batem mais com a conta) **ou o tracker de nonce da chave ficou preso** no
servidor do MRR (último nonce registrado acima do tempo atual, envenenado por
algum cliente com data futura). **NÃO é bug de concorrência** — os nonces já
são monotônicos desde a Issue #150 (fix #148/#150), idênticos ao cliente
oficial.

**Diagnóstico (por usuário, sem tocar no `.env`):**

```bash
python scripts/probe_mrr_api.py --check --key SUA_KEY --secret SEU_SECRET
# VALID  → credencial ok (o erro era transitório — tente de novo)
# INVALID → regenerar a chave (abaixo)
```

**Solução:** regenerar a **API key + secret** na conta MRR
(`miningrigrentals.com → My Account → API Access` — a chave nova nasce com
tracker de nonce zerado) e atualizar:

- **Tenants multi-usuário** → Settings → MRR credentials (cada usuário usa a
  PRÓPRIA chave — nunca a do operador);
- **Self-host** → `.env` (`MRR_API_KEY`/`MRR_API_SECRET`) + restart.

O painel agora classifica esse erro como **credencial rejeitada** e mostra
essa orientação diretamente no card/empty state (Issue #152).

---

MIT © 2026 [0xjc65eth](https://github.com/0xjc65eth)
