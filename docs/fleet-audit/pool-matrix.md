# Pool Matrix — Fleet audit (Issue #627)

> Método: fontes oficiais quando acessíveis + validação passiva de protocolo
> (TCP + `mining.subscribe`, **nunca** authorize/submit). Pools do prompt
> original foram tratados como *leads*, não como verdade — vários não
> sobreviveram à verificação. Última verificação: **2026-09-17**.

## Veredito sobre os "pools" citados no relato original

| Nome citado | Verificável como pool BTC? | Evidência |
|---|---|---|
| AtlasPool | ⚠️ **Sim (infra) / Não (web)** — `solo.atlaspool.io` responde Stratum V1 válido, mas site oficial não localizável (atlaspool.com = empresa de piscinas Kuwait; atlaspool.org = cert TLS inválido) | probe passivo 2026-09-17, 346ms |
| SoloMining.de | ❌ É **loja** de Bitaxe, não pool | site |
| Noderunners | ❌ noderunners.io é blog estacionado/vazio | site |
| Satoshi Radio | ❌ `satoshiradio.xyz` não resolve DNS | DNS |
| SoloHash | ⚠️ solohash.io existe mas é conteúdo educacional; endpoint de stratum não confirmado | site |

Consequência de arquitetura: o sistema **não depende** de hardcode — o fallback
genérico Stratum (`generic-stratum`, pool_type `custom`) aceita qualquer
host:port, e os providers registrados abaixo só **enriquecem** metadados.

## Providers registrados nesta auditoria

| Pool | Host | Portas | TLS | V1 | V2 | Worker | REST | Solo/Shared | Auth | Adapter | Verificado |
|---|---|---|---|---|---|---|---|---|---|---|---|
| AtlasPool (solo) | `solo.atlaspool.io` | 3333 | — | ✅ | ? | wallet.worker | ❌ | Solo | BTC address | `stratum_only` | 2026-09-17 probe passivo |
| EU CKPool (solo) | `solo.ckpool.org` | 3333 | — | ✅ | ? | BTC address | ❌ | Solo | BTC address | `stratum_only` | registro (conhecido) |
| Braiins Pool | `stratum.braiinspool.com` | 3333 | — | ✅ | ✅ (SV2) | subaccount.worker | ✅ (token) | Shared | user+token | existente | registro |
| Braiins Solo | `solo.braiinspool.com` | 3333 | — | ✅ | ? | BTC address | ❌ | Solo | BTC address | `stratum_only` (novo) | registro |
| SoloHash | `solo.hashport.io` | 3333 | — | ✅ | ? | BTC address | ❌ | Solo | BTC address | `stratum_only` (novo) | registro |
| Satoshi Radio | `pool.satoshiradio.xyz` | 3333 | — | ✅ | ? | BTC address | ❌ | Solo | BTC address | `stratum_only` (novo) | registro |

## Registro existente coberto pela suíte (~30 providers)

CK Pool, Public Pool, Parasite Pool, ViaBTC, F2Pool, AntPool, Luxor, OCEAN,
Foundry, SpiderPool, SBI Crypto, EMCD,UIH, Binance Pool, Bitcoin.com,
Mara Pool, BTC.com, Genesis Mining, Bitfury, MiningPoolHub, etc. — todos com
`detect_provider()` cobrindo hostname exato + aliases + subdomínios wildcards.

## Regras de identidade (implementadas)

1. `detect_provider(host, stratum_port)` → `ProviderMatch` com `pool_type`
   (`SOLO`/`BTC`/`MERGE`), `capabilities` (WORKER_LIST, HASHRATE,
   ACCEPTED_SHARES, REJECTED_SHARES, BEST_SHARE, PAYOUTS, BLOCKS, REST_API,
   STRATUM, TLS, SV2) e `docs` (evidência de verificação).
2. Pool desconhecido → `generic-stratum` **honesto**: detectado, sem métricas
   prometidas, editável, nunca crasha.
3. `stratum_only` = sem REST público: só identidade + ports, sem prometer
   stats que não dá para buscar.
4. Pools de solo autenticam por **endereço BTC** — o worker identity parsing
   trata `wallet.worker` como formato canônico solo.
