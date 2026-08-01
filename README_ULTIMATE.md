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

## 🛡 Segurança

- `.env` **nunca** é commitado (gitignored); segredos ficam só no servidor.
- App bindado em `127.0.0.1` no compose — exposição pública só via Tailscale
  Serve (TLS) ou proxy reverso.
- Código roda como usuário não-root (`USER cypher` no Dockerfile).
- Sem chaves de wallet/seed no servidor — apenas endereços públicos.

---

MIT © 2026 [0xjc65eth](https://github.com/0xjc65eth)
