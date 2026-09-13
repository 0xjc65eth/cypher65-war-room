# Pre-public deploy checklist

Roteiro vivo para o deploy `cypher65-war-room.onrender.com`. **Não trata o
serviço como 100% seguro** — marca cada item com evidência e dono.

Legenda:

| Estado | Significado |
|---|---|
| **PASS** | Código + teste (e, quando aplicável, sonda ao vivo) sustentam o item |
| **PARTIAL** | Existe proteção, mas depende de operador, plano pago, ou follow-up |
| **OPERATOR** | Só o painel do Render / Sentry / GitHub secrets fecha o item. O git não consegue setar o valor |

Flags de hardware e pagamento (`ENABLE_PHYSICAL_COMMANDS`,
`ENABLE_AUTONOMOUS_COMMANDS`, `ENABLE_REAL_HASHRATE_PURCHASES`,
`ENABLE_REAL_PAYMENTS`) permanecem **desligadas**. Ver README
[Beta safety gates](../README.md#beta-safety-gates).

Sonda ao vivo citada abaixo: 2026-09-13 contra
`https://cypher65-war-room.onrender.com`.

---

## 1. Segurança crítica

### SECRET_KEY estável em produção — **PARTIAL / OPERATOR**

- **Código (Issue #535):** `services/boot_policy.py` recusa boot em
  `is_cloud_deploy()` sem `SECRET_KEY` / `JWT_SECRET_KEY`. Self-host local
  ainda pode gerar chave efêmera via `os.urandom`.
- **Blueprint:** `render.yaml` usa `generateValue: true` — o Render gera e
  persiste uma chave no primeiro deploy do blueprint.
- **Operador:** confirme no painel Environment que `SECRET_KEY` existe e
  **não** mude o valor a cada Manual Deploy. Teste prático: sessão →
  redeploy → a sessão continua válida.

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### API_KEY / TENANT_API_KEYS — **PASS (desenho do produto)**

`GET /api/snapshot` e o dashboard de pool são **públicos por desenho**.
Sonda 2026-09-13: `GET /api/snapshot` → HTTP 200 sem credencial, sem
`WWW-Authenticate`. Mutações de fleet exigem sessão/tenant + papel
`member` (`axe_fleet/routes.py`). Não trancar o snapshot atrás de
`API_KEY` por padrão — isso quebraria o produto.

Para um deploy **privado**, sete `API_KEY` e/ou `TENANT_API_KEYS` no
Render; rotas de escrita já falham fechado sem credencial.

### Trava dry-run / confirmação em comandos físicos — **PASS**

Default `dry_run=True`. `dry_run:false` exige `confirmation_token` de
uso único e `can_execute_physical_command()`. License ao vivo
2026-09-13: `safety_policy.physical_commands=false` (e os outros três
flags também false). Um POST sem dispositivo conhecido devolve 404
(fail-closed, nada executa):

```bash
curl -i -X POST \
  https://cypher65-war-room.onrender.com/api/axe-fleet/devices/x/restart \
  -H "Content-Type: application/json" \
  -d '{"dry_run":false}'
```

Hardware público continua bloqueado até
[`PHYSICAL_VALIDATION_MATRIX.md`](PHYSICAL_VALIDATION_MATRIX.md).

### CORS_ORIGINS restrito (não `*`) — **PASS**

- Unset (produção atual): nenhum `Access-Control-Allow-Origin`. Sonda
  `Origin: https://site-qualquer.com` em 2026-09-13 → header ausente.
- Issue #535: em cloud, `CORS_ORIGINS=*` aborta o boot e o after-request
  não emite wildcard mesmo que a env escape.
- Self-host local ainda aceita `*` para o companion mobile em dev.

### Disco persistente SQLite — **PARTIAL / OPERATOR**

Free tier do Render é efêmero. Persistência $0 =
`GITHUB_TOKEN` + `REMOTE_BACKUP_ENCRYPTION_KEY` (gist cifrado,
`services/remote_backup.py`, intervalo 300s no blueprint). Disco pago
está comentado em `render.yaml`. O git **não** consegue verificar se o
PAT está no painel — rode
`python scripts/verify_remote_backup.py --roundtrip` no serviço.

### Flask debug desativado — **PASS**

`app.run(debug=False)` está hardcoded. Issue #535: cloud com
`FLASK_DEBUG=1` ou `FLASK_ENV=development` aborta o boot. Header ao vivo:
`x-render-origin-server: Werkzeug/3.1.8` (dev server, não gunicorn — ver
comentário no `render.yaml` sobre workers em-processo) **com debug off**.

### Escaneamento de dependências — **PASS**

Dependabot semanal (pip/actions) + mensal (docker). CI: `bandit -ll` +
`pip-audit -r requirements.txt` (Issue #535). 2026-09-13: pip-audit →
*No known vulnerabilities found*.

---

## 2. Confiabilidade / operação

### Backup do SQLite — **PARTIAL / OPERATOR**

Código de backup remoto existe. Sem `GITHUB_TOKEN` + chave Fernet no
Render, um redeploy apaga `data/war_room.sqlite`. Confirme as env vars
e um roundtrip. Off-site extra (S3/Backblaze) não está no app — cron
do operador.

### Sentry (`SENTRY_DSN`) — **OPERATOR**

SDK env-gated (`services/sentry_telemetry.py`). Sem DSN o app sobe
normal (honest telemetry). Cole o DSN no Render e force um 500 para
ver o evento no painel.

### Suíte de testes antes de cada deploy — **PASS**

`.github/workflows/ci.yml` (`CI · Gate`) roda pytest (`--cov-fail-under=80`),
JS core, DOM/mobile guards, Playwright job, bandit, pip-audit. Render
`autoDeploy: true` no `master`; o ruleset exige checks + squash. O
Render **não** espera o CI por si só — o merge no `master` é o gate.

### Rate limiter compartilhado entre instâncias — **PARTIAL**

Contagem in-memory por processo, persistida em SQLite a cada 30s. Uma
instância (free tier) é o desenho atual. Horizontal scale exigiria
Redis/store compartilhado — não urgente enquanto `plan: free` for
single-instance. Não tratar como teto contra abuso distribuído.

---

## 3. Fluidez / leitura de dados

| Item | Estado | Evidência |
|---|---|---|
| Separar LIVE / SYNCED / ESTIMATED / NO DATA | **PASS** | `metricProvenance` + topbar LIVE/SYNCED/DADOS ANTIGOS/NO DATA (Issue #536). Overview usa LIVE/NO DATA/STALE/PARTIAL |
| Timestamp de idade ("atualizado há Xs") | **PASS** | Topbar sempre visível com idade (`snapshotFreshnessLabel`) |
| WebSocket/SSE atualização parcial | **PASS** | SSE `{type:live}` atualiza hashrate/temp/idade; poll 15s faz o render completo (Issue #539) |
| Nunca esconder que lucro é estimado | **PASS** | Badge ESTIMATED + nota "actual earnings may vary" no painel de scenario economics |
| Cache dificuldade / preço BTC | **PASS** | `btc_price._age_s` no snapshot; poll de mercado não é 15s para cada fonte |
| Paginação listas longas | **PASS** | Leaderboard LOAD MORE 50 + `has_more`; history pagina com `limit`/`offset`; audit já paginado (#536/#539) |

---

## O que o git não fecha

1. Confirmar `SECRET_KEY` estável no painel do Render após este merge.
2. Setar `SENTRY_DSN`, `GITHUB_TOKEN`, `REMOTE_BACKUP_ENCRYPTION_KEY`.
3. Persistent Disk pago (opcional; blueprint documenta o bloco).
4. Redis para rate-limit multi-instância.
5. Matriz física e checkout BTCPay — continuam bloqueados de propósito.

Enquanto os itens OPERATOR e a matriz física estiverem abertos, **não**
chame o deploy público de 100% seguro. `/api/healthz` agora reporta
`persistence.remote_backup` e `persistence.sentry` (bool) para o operador
confirmar o painel do Render sem ler secrets.
