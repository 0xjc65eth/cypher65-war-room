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

1. Crie um **Personal Access Token** do GitHub com scope `gist`:
   GitHub → Settings → Developer settings → Personal access tokens →
   **Generate new token (classic)** → marque `gist` → copie.
2. Adicione ao Render (Dashboard → o serviço → Environment):
   - `GITHUB_TOKEN` = o token (guarde como secret)
   - `REMOTE_BACKUP_INTERVAL` = `300` (5 min — opcional, default 600)
3. **Redeploy**. Confira no log: `[remote_backup] snapshot pushed ... -> gist ...`
4. Teste: conecte uma wallet/salve uma chave → force um redeploy → os dados
   **voltam** (o log mostra `[remote_backup] restored ... from gist`).

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
| **Sentry** (erros + traces) | env: `SENTRY_DSN=...`, opcional `SENTRY_TRACES_SAMPLE_RATE=0.1` | já integrado em `app.py`; 5k errors/mês free |
| **Logs JSON** | env: `LOG_JSON=1` | `services/observability.py` — um JSON por linha, `jq`-able |
| **Boot health** | sempre | linha estruturada `[boot] ready` com port/worker/db |
| Admin CFO + pool stats | sempre | `/api/admin/sessions` (sessions, polls/s, fila, threads) |

Matriz de decisão: Datadog/NewRelic são paid → **não adotados** (regra de ouro
CFO/CRO $0). OpenTelemetry é o caminho futuro (exporter OTLP → Sentry) quando
houver tração (gated por tração, ver `docs/AUDITORIA_ESTRATEGICA.md`).

Exemplo:
```bash
LOG_JSON=1 SENTRY_DSN=https://xxx@sentry.io/123 python app.py
```

---

## 🛡 Segurança

- `.env` **nunca** é commitado (gitignored); segredos ficam só no servidor.
- App bindado em `127.0.0.1` no compose — exposição pública só via Tailscale
  Serve (TLS) ou proxy reverso.
- Código roda como usuário não-root (`USER cypher` no Dockerfile).
- Sem chaves de wallet/seed no servidor — apenas endereços públicos.

---

MIT © 2026 [0xjc65eth](https://github.com/0xjc65eth)
