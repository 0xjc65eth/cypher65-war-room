# Hashrate Market APIs — Referência completa para máximo controle

> Documentação consolidada das duas APIs de mercado de hashrate integradas ao
> CYPHER65: **Braiins Hashpower** e **MiningRigRentals (MRR)**.
> Todos os endpoints foram verificados ao vivo em 2026-08-06 (respostas reais
> abaixo). O spec OpenAPI oficial da Braiins está em
> `https://hashpower.braiins.com/api/openapi.yml` (~30 endpoints) e o da MRR
> é REST v2 com assinatura HMAC-SHA1.

---

## 1. Braiins Hashpower — `https://hashpower.braiins.com/v1`

### Autenticação

- **Header:** `apikey: <seu-token>` (exatamente este nome — `X-API-Key`,
  `Authorization`, query params **não** funcionam; todos retornam
  `401 {"message":"No API key found in request"}`).
- **Onde gerar:** ao registrar em `hashpower.braiins.com` (verificação via
  Telegram) o site gera **2 tokens, mostrados UMA única vez**:
  - **Owner token** → acesso total (criar/editar/cancelar bids).
  - **Read-only token** → mercado + leitura da conta.
- `demo` como token exercita os endpoints autenticados com dados mockados
  (nesta instância retorna `401 Unauthorized` — válido na doc oficial).
- **Públicos (sem auth):** `orderbook`, `trades`, `stats`, `bars` (verificados).
  `settings`/`fee` também retornam dados genéricos, mas hoje 401 sem key — o
  adaptador do CYPHER65 chama `settings` sem auth e **degrada com graça**
  (fallback para `price_unit` padrão `sats/PH/day`).

### Endpoints públicos (já usados pelo CYPHER65)

| Endpoint | Método | O que retorna | Resposta real (2026-08-06) |
|---|---|---|---|
| `/spot/orderbook` | GET | Snapshot do book: asks + bids | `asks[0]: {"price_sat":50013000,"hr_available_ph":121.9,"hr_matched_ph":121.9}` · `bids[0]: {"price_sat":65003000,"amount_sat":2056,"speed_limit_ph":1.85,"hr_matched_ph":2.07}` · 8 asks / 127 bids |
| `/spot/trades` | GET | Últimos trades | `{"trades":[{"timestamp":"2026-08-06T10:15:45Z","volume_m":160.9,"price_sat":50856307.99}]}` |
| `/spot/stats` | GET | Estatísticas do mercado | `{"best_ask_sat":50011000,"best_bid_sat":65003000,"volume_24h_m":24636960,"hash_rate_available_10m_ph":3237.4,"hash_rate_matched_10m_ph":993.1,"last_avg_price_sat":50856307.99,"status":"SPOT_INSTRUMENT_STATUS_ACTIVE"}` |
| `/spot/bars` | GET | OHLCV agregado | `{"bars":[{"timestamp":"2026-08-06T10:15:00Z","open":...,"high":...,"low":...,"close":...,"vwap":...,"volume":...}]}` |

> **Nota de unidades:** todos os preços vêm em **satoshis** (`price_sat`) por
> PH/dia por padrão. Consulte `/spot/settings` para o `hr_unit`/`price_unit`
> vigente (ex.: `sats/PH/day` vs `sats/TH/day`). O adaptador
> `get_braiins_orderbook()` em `agents/solo_mining_advisor/tools.py` já
> normaliza para BTC/TH/dia.

### Endpoints autenticados (máximo controle — requerem `apikey`)

#### Market (spot)
| Endpoint | Método | O que faz |
|---|---|---|
| `/spot/settings` | GET | Regras do mercado, unidades de preço, tick sizes, cooldowns (com key: camada de pricing individual) |
| `/spot/fee` | GET | Estrutura de fees (com key: camada individual do caller) |
| `/spot/bid/current` | GET | **Bids ativos do usuário** (lista) |
| `/spot/bid` | GET | **Bids do usuário, históricos + ativos** (query: `limit` 1-1000, `offset`, `reverse`, `created_after`) |
| `/spot/bid` | POST | **Criar bid** (buy order) — body: `cl_order_id`, `client_name`, `subaccount`, `dest_upstream`, `speed_limit_ph`, `amount_sat`, `price_sat` |
| `/spot/bid` | PUT | **Editar bid existente** |
| `/spot/bid` | DELETE | **Cancelar bid** |
| `/spot/bid/detail/{order_id}` | GET | Detalhe completo de um bid (metadata, history de status) |
| `/spot/bid/speed/{order_id}` | GET | **Série temporal de speed do bid** (performance do aluguel) |
| `/spot/bid/delivery/{order_id}` | GET | **Série temporal de delivery do bid** (entrega real do hashrate) |

#### Contract (aluguel agendado/termo)
| Endpoint | Método | O que faz |
|---|---|---|
| `/contract` | GET | Lista contratos do caller |
| `/contract` | POST | Agenda novo contrato (termo) |
| `/contract/quote` | POST | Cota e valida uma criação de contrato |
| `/contract/pricing` | GET | Pricing atual de contratos (requer query params — 400 vazio) |
| `/contract/cancel-fee` | GET | Fees de cancelamento (requer query params — 400 vazio) |
| `/contract/availability` | POST | Checa se a velocidade pedida está disponível |
| `/contract/active` | GET | Contratos pending/running/paused do caller |
| `/contract/{id}/detail` | GET | Detalhe de um contrato |
| `/contract/settings` | GET | Política efetiva do contrato |
| `/contract/activity` | GET | **Accounting do contrato** (créditos/débitos) |
| `/contract/{id}/reservation` | GET | Histórico de reservas |
| `/contract/{id}/settlement` | GET | **Histórico de settlements** (quanto foi pago/entregue) |
| `/contract/{id}/speed` | GET | **Série temporal de speed do contrato** (performance) |
| `/contract/{id}/delivery` | GET | **Série temporal de delivery do contrato** |
| `/contract/{id}:cancel` | POST | Cancela contrato |
| `/contract/{id}:terminate` | POST | Termina contrato |

#### Account
| Endpoint | Método | O que faz |
|---|---|---|
| `/account/balance` | GET | Saldo da conta |
| `/account/transaction` | GET | Transações mistas (deprecated) |
| `/account/transaction/settlement` | GET | Transações de settlement |
| `/account/transaction/lock` | GET | Transações de lock |
| `/account/transaction/on-chain` | GET | Transações on-chain |

### Uso no CYPHER65 (hoje)
- `fetch_braiins_offer()` → `GET /spot/orderbook` (público) + `GET /spot/settings`
  (sem auth, degrada para `price_unit` padrão quando 401), escolhe o ask mais
  barato → **cotação real no HASH MARKET**.
- **Não usado ainda (potencial P1/P2):** `/spot/bid/*` (criar/gerir bids do
  operador), `/contract/*` (performance do aluguel: speed/delivery/settlement),
  `/account/balance`. Exigem o **owner token** no `.env` (`BRAIINS_API_KEY`).

---

## 2. MiningRigRentals (MRR) — `https://www.miningrigrentals.com/api/v2`

### Autenticação (HMAC-SHA1)

3 headers obrigatórios em **toda** requisição autenticada:

| Header | Valor |
|---|---|
| `x-api-key` | Sua API key (account → API) |
| `x-api-nonce` | Timestamp em **ms** (estritamente crescente) |
| `x-api-sign` | `HMAC_SHA1(api_key + nonce + endpoint_path)` em hex |

```python
import hmac, hashlib, time
endpoint = "/rig?type=sha256&order=price"   # path SEM o host, SEM o base
nonce = str(int(time.time() * 1000))
sign = hmac.new(SECRET.encode(), (KEY + nonce + endpoint).encode(), hashlib.sha1).hexdigest()
headers = {"x-api-key": KEY, "x-api-nonce": nonce, "x-api-sign": sign}
```

> ⚠️ O `endpoint` assinado **deve ser exatamente o path** usado no request
> (query params inclusos, sem trailing slash). Implementação de referência:
> `get_mrr_listings()` em `agents/solo_mining_advisor/tools.py`.

### Endpoints verificados ao vivo (2026-08-06, com as credenciais do .env)

| Endpoint | Método | Resultado real |
|---|---|---|
| `/whoami` | GET | `{"success":"True","data":{...8 campos...}}` — **credenciais válidas** |
| `/rig?type=sha256&order=price` | GET | `success:true` — listings ordenados por preço (usado pelo CYPHER65) |
| `/rental` | GET | `success:true` — rentals (filtros: `type=owner\|renter`, `history=true`, `rig`, `algo`, paginação `start/limit`) |
| `/rental?type=renter` / `?type=owner` / `?type=renter&history=true` | GET | `success:true` — todos os modos respondem |
| `/rental/{id}` | GET | Detalhe: performance, hashrate advertised/average, price paid, rig info, start/end, extensões |
| `/account/profile` | GET | `success:true` — perfis de pool salvos (ex.: sha256, `suggested_price 0.00088500 BTC/ph*day`, stats do mercado sha256: 201 rigs available / 83 rented) |
| `/info/algos` | GET | `success:true` — `list[128]` algoritmos com preço sugerido, rigs disponíveis/alugados |
| `/account` | GET | `success:false` → **`"No Permission - withdraw"`** (a key atual não tem esse escopo) |
| `/account/balance` | GET | `success:false` → **`"No Permission - balance"`** |
| `/account/transactions` | GET | `success:false` → **`"No Permission - balance"`** |
| `/rig/my` | GET | `success:false` → **`"Rig not found"`** (a conta não tem rigs próprios listados) |

> **Escopo da key atual:** market/rental/profile OK; `withdraw`/`balance` e
> rigs próprios **sem permissão** — erro explícito `{"success":false,
> "data":{"permission":"<escopo>","message":"No Permission - ..."}}`.
> Para saldo/transações, gerar nova key com escopo `balance`+`withdraw` em
> MiningRigRentals → Settings → API.

### Diretório completo de endpoints MRR v2 (da doc oficial)

**Info:**
- `GET /whoami` — credenciais/permissões (`withdraw`, `rent`, `rigs`)
- `GET /info/servers` — servidores/regiões
- `GET /info/algos` / `GET /info/algos/{name}` — stats por algoritmo
- `GET /info/currencies` — moedas suportadas, fees de saque, mínimos
- `GET /pricing` — benchmarks de pricing

**Account & Wallet:**
- `GET /account` — perfil, notificações, address book
- `GET /account/balance` · `PUT /account/balance` (solicitar payout) ·
  `DELETE /account/balance` (cancelar payout)
- `GET /account/transactions` — histórico (créditos, payouts, fees, refunds)
- `GET /account/profile` · `GET|POST|PUT|DELETE /account/pool` ·
  `POST /account/pool/test` — perfis/pools de destino

**Rigs (dono):**
- `GET /rig` / `GET /rig/search` — market listings (`type`, `minhours`,
  `maxhours`, `rpi`, `hash`, `price`, `region`, `order`…)
- `GET /rig/my` — rigs do usuário
- `POST /rig` / `POST /rig/batch` — criar listings
- `GET|PUT|POST|DELETE /rig/{id}` — detalhe/atualização/delete
- `GET /rig/{id}/graph` — **performance/hashrate do rig no tempo**
- `POST /rig/batch/extend` — estender rentals em lote
- `GET|PUT|POST|DELETE /rig/{id}/pool/{priority}` — pools do rig

**Rentals (renter & owner):**
- `GET /rental` — listar rentals (filtros acima)
- `GET /rental/{id}` — **performance detalhada** (hashrate advertised/average,
  price paid, start/end, rig, extensões)
- `POST /rental` — alugar um rig (`rig`, `length`, `profile`, `currency`, `rate`)
- `GET /rental/{id}/log` — log de atividade
- `GET /rental/{id}/graph` — **histórico de hashrate/performance do aluguel**
- `GET|PUT /rental/{id}/message` — mensagens renter↔owner
- `GET|PUT|POST|DELETE /rental/{id}/pool` — pools do aluguel ativo

### Uso no CYPHER65 (hoje)
- `get_mrr_listings()` → `GET /rig?type=sha256&order=price` com HMAC →
  **cotação real MRR no HASH MARKET** (credenciais já no `.env`).
- **Não usado ainda (potencial P1/P2):** `/rental` (performance dos aluguéis do
  operador: `graph`/`log`), `/account/balance` (requer key com escopo),
  `POST /rental` (alugar direto da UI).

---

## 3. Mapa de implementação sugerida (próximos passos)

| Capacidade | Braiins | MRR | Bloqueio |
|---|---|---|---|
| Cotação real (grid) | ✅ `orderbook` | ✅ `/rig` | — |
| Bids/asks do usuário | 🟡 `/spot/bid/*` | 🟡 `POST /rental` | Key owner Braiins no `.env` |
| Performance do aluguel | 🟡 `/contract/{id}/speed·delivery·settlement` | 🟡 `/rental/{id}/graph·log` | Requer contrato/rental ativo |
| Saldo da conta | 🟡 `/account/balance` | 🔴 `/account/balance` | Braiins: owner key; MRR: key com escopo `balance` |
| History de trades | ✅ `/spot/trades·bars` (públicos) | 🟡 `/rental?history=true` | — |

Legenda: ✅ implementado · 🟡 endpoint mapeado, falta integrar · 🔴 bloqueado por credencial/permissão.

---

## 4. Configuração (resumo)

```bash
# .env — credenciais (MRR já configurado)
MRR_API_KEY=...
MRR_API_SECRET=...

# Braiins — owner token (mostrado 1x no registro); necessário para
# bids/contratos/saldo. Também configurável pelo modal Settings (⚙) — o
# campo braiins_api_key segue o padrão MRR (env → Settings DB fallback).
BRAIINS_API_KEY=
```

Credenciais MRR validadas ao vivo em 2026-08-06 (`/whoami` ok). A key MRR
atual **não** cobre `balance`/`withdraw` — saldo/transações exigem nova key
com escopo em MiningRigRentals → Settings → API.
