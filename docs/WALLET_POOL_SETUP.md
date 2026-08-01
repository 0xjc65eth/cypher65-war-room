# CYPHER65 · WAR ROOM — Configuração de Wallet e Pool

> Guia operacional para configurar a carteira monitorada, o worker name e as
> premissas de pool usadas nos cálculos de lucratividade do painel.
> Escrito contra o código real (`app.py`, `routes/settings_routes.py`,
> `services/settings.py`, `.env.example`) — sem dados inventados.

---

## 1. Visão geral

O painel monitora **uma** carteira Bitcoin por sessão (endereço + worker name).
A partir dela ele consulta telemetria real de pool (Parasite Pool / APIs
configuradas), calcula hashrate, shares, dificuldade e lucratividade.

| Item | Onde é definido | Persistência |
|---|---|---|
| Endereço BTC | Env `BTC_ADDRESS` ou via UI (`⚡ CONNECT` / API) | Env **ou** tabela `settings` (chave `_wallet_address`) |
| Worker name | Env `WORKER_NAME` ou via UI / API | Env **ou** tabela `settings` (chave `_wallet_worker`) |
| Premissas de pool | Tabela `settings` (via modal Settings) | SQLite |
| Histórico de carteiras | Tabela `wallet_address_history` | SQLite (últimas 20) |

---

## 2. Configuração da wallet

### 2.1 Via variável de ambiente (boot)

No `.env` (ou exportado antes de iniciar):

```bash
# Endereço BTC monitorado (bc1…, 1… ou 3…) — opcional. Se vazio, o
# dashboard inicia VAZIO: os dados só aparecem depois de conectar a
# própria wallet pela UI (⚡ CONNECT), que persiste em settings.
# BTC_ADDRESS=

# Nome do worker (opcional; aparece na telemetria e no terminal)
# WORKER_NAME=
```

O boot carrega estes valores (`app.py`) e, se a tabela `settings` tiver valores
persistidos (`_wallet_address` / `_wallet_worker`), estes **têm prioridade**
sobre o env — ou seja, uma carteira trocada pela UI sobrevive a reinícios.

### 2.2 Via UI — botão `⚡ CONNECT` (topbar)

1. Clique em **`⚡ CONNECT`** no canto superior direito.
2. Conecte via **WebLN** (navegador com extensão LN) — o endereço é lido
   automaticamente da carteira — ou cole o endereço manualmente.
3. O painel cria uma sessão e faz o **primeiro poll imediato** — os números
   aparecem sem precisar recarregar.

Internamente isso chama `POST /api/connect-wallet` com body
`{"address": "...", "worker": "..."}`. Validações aplicadas (código real):

- `address` é obrigatório.
- Deve começar com `bc1` (bech32) ou `1` (legacy).
- Comprimento entre **26 e 64** caracteres.

> **Nota:** endereços `3…` (P2SH) são rejeitados pelo CONNECT — o prefixo `3`
> é aceito apenas no `POST /api/set-address` (seção 2.3), que faz validação
> de checksum mais estrita.

### 2.3 Via API — `POST /api/set-address`

Endpoint para trocar a carteira de uma sessão já ativa:

```bash
curl -X POST http://localhost:8765/api/set-address \
  -H "Content-Type: application/json" \
  -d '{"address": "bc1q...", "worker": "minha-frota"}'
```

Validações (código real, mais estritas que o connect-wallet):

- Prefixo `bc1` / `1` / `3`.
- **Checksum verificada** via `helpers.validate_btc_address()` — endereço com
  checksum inválido é rejeitado com `400`.
- Worker name: 1–64 caracteres.
- Endereço idêntico ao atual sem mudança de worker → `400` ("no change needed").

Ao persistir, a troca é registrada na tabela `wallet_address_history`
(endereço, worker, `connected_at`, label) e o estado da sessão é resetado.

### 2.4 Histórico de carteiras

`GET /api/wallet/history` retorna as **últimas 20** trocas de carteira
(mais recente primeiro):

```json
{ "success": true, "history": [
  { "address": "bc1q...", "worker": "cypher65", "connected_at": 1785615000, "label": "" }
] }
```

Use este endpoint para auditar quando a carteira foi alterada e por quem.

---

## 3. Configuração da pool

### 3.1 APIs de dados (env)

| Variável | Função |
|---|---|
| `PARASITE_API` | URL base da API da Parasite Pool — telemetria da pool (hashrate, workers, shares). Se vazia, os dados da pool ficam indisponíveis (o painel mostra o estado honesto, nunca dados inventados) |
| `MEMPOOL_API` | URL da API do mempool (preço, fee rate, confirmações). Se vazia ou indisponível, os dados ficam marcados como indisponíveis/offline — o painel nunca inventa valores (Honest Telemetry) |

Exemplo no `.env`:

```bash
PARASITE_API=https://pool.parasite.pool/api/
MEMPOOL_API=https://mempool.space/api
```

> **Premissa do projeto (Honest Telemetry):** se a API da pool não responde ou
> não está configurada, o painel marca os dados como indisponíveis/offline em
> vez de exibir valores falsos. Não há mock em produção (`DEBUG_MOCK=1` é
> somente para desenvolvimento local).

### 3.2 Premissas de lucratividade (modal Settings)

No painel, abra **Settings** (ícone `::` na topbar) e ajuste as premissas que
alimentam os cálculos de pool:

| Chave | Padrão | Significado |
|---|---|---|
| `pool_fee_pct` | `1.5` | Fee da pool em % (descontada da receita estimada) |
| `orphan_rate_pct` | `0.5` | Taxa assumida de órfãos/stale em % |
| `btc_block_reward` | `3.125` | Recompensa atual de bloco (BTC) — atualize após cada halving |
| `btc_avg_tx_fee` | `0.05` | Fee médio assumido por bloco (BTC) |
| `cost_mode` | `none` | Modelo de custo: `none`, `rental` (você paga aluguel) ou `power` (eletricidade) |
| `power_watts` | `3000` | Consumo estimado do rig (W) — usado no modo `power` |
| `power_kwh_usd` | `0.10` | Tarifa de energia ($/kWh) — usado no modo `power` |
| `rental_usd_per_th_day` | `0.00` | Taxa de aluguel que **você cobra** como locador ($/TH/dia) — receita no modo LEASE |

Todas as chaves são persistidas na tabela `settings` via `POST /api/settings`
(JSON `{"key": "value", ...}`) e carregadas em cache.

---

## 4. Fluxo recomendado de primeira configuração

1. **Defina `BTC_ADDRESS` e `WORKER_NAME`** no `.env` (ou conecte pela UI).
2. **Configure `PARASITE_API` / `MEMPOOL_API`** no `.env` para habilitar a
   telemetria real de pool.
3. **Abra Settings** e confira `pool_fee_pct`, `orphan_rate_pct` e o modelo de
   custo (`cost_mode` + `power_watts`/`power_kwh_usd` ou `rental_usd_per_th_day`).
4. **Confira a aba FLEET** — os dispositivos aparecem com telemetria real
   (temperatura, eficiência J/TH, ping, firmware). Veja
   [REMOTE_ACCESS_TUTORIAL.md](REMOTE_ACCESS_TUTORIAL.md) para acesso remoto
   via Tailscale e as limitações do que pode ser executado de fora da rede.
5. **Audite trocas de carteira** com `GET /api/wallet/history`.

---

## 5. Perguntas frequentes

**Posso monitorar mais de uma carteira?**
Não simultaneamente — o painel monitora uma carteira por sessão. Troque via UI
ou `POST /api/set-address`; o histórico fica em `/api/wallet/history`.

**Por que a pool aparece sem dados?**
Se `PARASITE_API` não estiver configurada/respondendo, o painel exibe o estado
indisponível honestamente em vez de números falsos. Configure a env e reinicie.

**Onde estão os tooltips?**
Passe o mouse sobre o ícone `?` dos KPI cards (Hashrate, Best Difficulty,
Share Rate, Pool Hashrate) — tooltips explicativos via atributo `data-tip`
(100% CSS, sem JS). Botões da interface (topbar, painéis) usam tooltips
nativos via atributo `title=`.

---

## 6. Referência de código

- Rotas de wallet: `POST /api/connect-wallet`, `POST /api/set-address`,
  `GET /api/wallet/history` — em `app.py` e `routes/settings_routes.py`.
- Chaves de settings: `services/settings.py` (`DEFAULT_SETTINGS` +
  `settings_label`).
- Validação de endereço: `helpers.validate_btc_address()`.
- Tabela de histórico: `wallet_address_history` (schema em `app.py init_db`).
