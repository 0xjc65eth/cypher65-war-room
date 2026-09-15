# Changelog

Todas as mudanças notáveis do **CYPHER65 War Room** são documentadas aqui.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e versionamento semântico ([SemVer](https://semver.org/lang/pt-BR/)).

## [Unreleased]

### Corrigido — `/api/agent/token` cunhava JWT de 1 ano sem credencial numa instância de nuvem (Issue #578)
- **Achado na sonda de produção** (pós-deploy do #577), sem usar o token:
  `POST /api/agent/token` **sem nenhum header** devolveu **200** com um JWT de
  **1 ano**, claim `agent: true`, `tenant_id: "default"`. Com ele dava para
  registrar devices na frota do operador, injetar telemetria nos painéis e
  **puxar os comandos enfileirados**.
- **Causa-raiz:** `role_required` é **no-op** quando `auth_configured()` é False
  (modo aberto: sem `API_KEY`/`TENANT_API_KEYS` o operador é implicitamente
  admin). Correto num self-host, **errado numa instância pública** — a produção
  responde `cloud: true` e não tinha auth configurado. A docstring da rota
  sempre prometeu "logged-in user (member+)"; o modo aberto nunca cumpriu.
- **`_require_caller_identity_on_cloud` (novo decorator em `axe_fleet/routes.py`):**
  em deploy de nuvem, cunhar token exige **JWT verificável** ou `X-API-Key` que
  resolva para um tenant — as mesmas credenciais que `_require_local_or_session`
  já aceita (header opaco nunca é autenticação). **Self-host preservado**: sem
  flag de nuvem nada muda. **Sem exceção para localhost**: numa instância de
  nuvem `127.0.0.1` é a infraestrutura da plataforma, não a máquina do operador.
  O 403 é acionável (diz o que configurar) e não traz token no corpo.
- **Prova negativa medida** (decorator removido, estado pré-fix): **4 dos 7**
  testes novos falham — o mint anônimo volta a responder 200 com token. Os
  outros 3 passam nos dois estados de propósito: fixam que JWT, API key e o
  modo aberto do self-host continuam funcionando.
- **⚠ Nota operacional:** depois deste deploy, o `Fleet → CONNECT AGENT` da
  instância pública passa a exigir `API_KEY` (ou `TENANT_API_KEYS`) no Render,
  enviado como `X-API-Key` — ou a geração do token rodando o dashboard
  localmente. Sem isso o botão responde 403 com a instrução.

### Corrigido — `/api/snapshot` não entregava `pool_detection`/`pool_worker`: a faixa da pool não aparecia em produção (Issue #576)
- **Achado na verificação pós-deploy do #575**, com o bundle novo já no ar:
  `static/app.js` servido com md5 **idêntico** ao local, e `/api/snapshot` com
  **35 chaves** — `pool_detection` e `pool_worker` entre as ausentes. Com o
  bundle novo e o JSON sem as chaves, `poolDetectionView()` devolvia `null` e a
  faixa ficava **oculta para sempre**: a feature passou em toda a suíte e não
  existia em produção.
- **Causa-raiz:** existem **três** dicts que constroem o snapshot global e o
  #574 só tocou o caminho de *sessão*. `/api/snapshot` — a rota que o
  `fetchSnapshot()` polla — serve `enrich_snapshot(state.latest_snapshot)`, o
  dict do `_do_poll()`, que tem a própria lista explícita de chaves.
- **`services/pool_detection.attach_to_snapshot()` (novo):** o **único** lugar
  que escreve as duas chaves, usado pelos **dois** produtores
  (`_build_snapshot` e `_do_poll`) — o seam `snapshot_assembly._detect_pool`
  morreu. Nunca levanta, e preserva o que um poll anterior achou quando a
  leitura atual não reporta nada.
- **Sem vazamento:** as chaves ficam **fora** da whitelist `public_keys` de
  `dashboard_routes.py` — o dict global é do **operador** da instância (a
  detecção sai da frota e da carteira dele), e servir isso a um tenant nomeado
  entregaria pool, host e hashrate dos ASICs do dono. Tenant nomeado recebe a
  própria detecção via `/api/session-snapshot`. Fail-closed por omissão, com
  teste.
- **Guard da CLASSE do bug, não da instância:** `ast` sobre `app.py` acha todo
  literal que constrói o snapshot global e falha se algum esquecer as chaves.
  Prova negativa medida: com `app.py` revertido para o estado pré-fix o guard
  falha apontando as **três** linhas (`2119, 4299, 2790`); com o fix, verde. Os
  outros 3 testes de payload passam nos dois estados de propósito — eles fixam
  o contrato da rota, não a regressão.
- **Um teste que passava sozinho e falhava na suíte inteira** foi corrigido no
  caminho: `create_token` (sem contexto de request) lê o env, enquanto
  `verify_token` (no request) prefere `app.config["JWT_SECRET_KEY"]` — um teste
  anterior que setava o config sem restaurar fazia o token não verificar, a
  request cair no tenant `default` e a asserção de não-vazamento **não testar
  nada**. O secret agora é fixado nos dois lugares e o `tenant_scope` é
  assertado **antes** das chaves, para o modo de falha ser explícito.
- **Evidência:** pytest **3.514** (+10) · `check-monkeypatch-targets` verde.

### Adicionado — snapshot e painel dizem QUAL pool o ASIC reporta, em qual chain e de onde vêm os números (Issue #574)
- **O problema:** o `stratumURL` que cada minerador reporta **já estava no banco**
  (`axe_telemetry.payload.pool_url`, gravado pelo agente) e **ninguém lia**. O
  `snapshot["pool"]` continuava vindo só do `pool-stats` do parasite.space, então
  um operador em OCEAN/CKPool/qualquer `stratum_only` via o painel falar de uma
  pool que não era a dele — ou de zeros silenciosos.
- **`services/pool_detection.py` (novo):** a cada poll lê o report de pool mais
  recente do **tenant** (janela de 50 linhas, cache de 60s), detecta o provider e
  resolve as estatísticas. Duas propriedades deliberadas: **nenhuma requisição de
  rede por iniciativa própria** (sem report de ASIC devolve `{}` na hora, e pool
  `stratum_only` nunca chama API) e **nunca levanta** (enriquecimento; tabela
  ausente/DB fora/API caída degradam para `{}`). Falha de API de uma pool que
  **tem** API não é cacheada — o próximo poll tenta de novo em vez de servir
  números do ASIC por um minuto inteiro.
- **`services/snapshot_assembly.py`:** `_build_snapshot(address, worker_name,
  tenant_id="")` ganha o tenant (para o isolamento da leitura) e as chaves
  `pool_detection` / `pool_worker` **no schema**, nulas quando não há o que
  reportar — o front nunca precisa distinguir "ausente" de "não se aplica".
  `services/user_polling.py` passa `worker.tenant_id`; os doubles de teste que
  stubavam `_build_snapshot` com 2 parâmetros passaram a aceitar o terceiro.
- **Painel (`#pool-overview`):** faixa que mostra **provider**, **chain** e
  **fonte** (`API DA POOL` ou `ASIC`). O view-model sai de `poolDetectionView()`
  — função **pura**, sem DOM nem globais — e o `renderPoolDetection()` só escreve.
  Três distinções que o painel faz questão de não achar: pool `stratum_only` (o
  ASIC é a única fonte que existe, e isso é normal) ≠ pool que **tem** API e
  respondeu pelo ASIC (**borda âmbar**: a chamada falhou); host fora do registro
  (neutro, rotulado "fora do registro"); e **chain ausente não é inventada** —
  BTC e BSV compartilham base58 `1…`/`3…`, então a assinatura diz "não declarada"
  em vez de chutar. A faixa fica **oculta** sem report: células vazias leriam
  como "pool desconhecida" quando o fato é "nada a reportar ainda".
- **Evidência medida:** pytest **3.504** · JS core **1.463** (+28, SUITE 38 carrega
  `39b-dashboard.js` via `loadFragment` — o fonte real) · e2e
  `pool-detection-panel.spec.js` **12/12** (chromium + mobile-chrome) com fixture
  determinístico. **Prova de mutação** (`apiMiss = false`, ou seja, esconder a
  falha da API): JS core **3 asserções falham**, e2e **2/10 falham, exit 1** —
  mutante revertido e `build_app_js --check` em sincronia.
- **Achado de CSS do próprio guard:** o primeiro check de overflow do spec
  comparava `scrollWidth > clientWidth` — que é o **comportamento normal** de uma
  linha recortada com ellipsis, não um defeito; ele acusava o próprio clip. O
  guard foi reescrito para medir o que importa (a faixa e as células, não a linha
  cliada) e, com ele, a medição virou documentação: sem `min-width: 0` na célula,
  um host de 1.778px produz trilha de **1.790px** e painel com `scrollWidth`
  **1.814** contra `clientWidth` **361** (1.453px de estouro, zero ellipsis); com
  ela, trilha de **318px** e recorte correto. `min-width: 0` é carga, não higiene.

### Adicionado — spec determinístico dos KPI cards fecha a lacuna de cobertura do PR 10 (RFC #478, Issue #568)
- **A lacuna:** o PR 10 (#561) registrou, em vez de esconder, que a mutação que
  provaria o movimento — desligar a escrita de `#kpi-hashrate` dentro de
  `renderKpiCards` (R31) — **sobrevivia** à suíte inteira. A asserção que pegaria
  isso em `dashboard.spec.js` (`#kpi-hashrate` ≠ `—`) é **condicional** a um worker
  conectado (`#hud-hashrate` visível), e o servidor local de e2e sobe **sem worker**.
- **`tests/e2e/dashboard-kpi-cards.spec.js` (novo):** fixture determinístico via
  `page.route('**/api/snapshot*')` + `route.fetch()` com override de
  `worker.hashrate`/`bestDifficulty`, `pool.hashrate` e
  `proximity.share_rate_hourly`, com `/api/stream` abortado (para o poll mockado ser
  a única fonte) e a guarda de service worker compartilhada da #562 — necessária
  porque `page.route` não intercepta fetch originado do SW.
- **Asserções incondicionais nos 4 cells** (valores medidos contra o `fmt` real):
  `#kpi-hashrate` = `2.00 TH/s`, `#kpi-bestdiff` = `5.00 M`, `#kpi-poolhr` =
  `3.00 TH/s`, `#kpi-shares` = `42/h` — mais um segundo caso cobrindo o fallback do
  share rate (`1234 total` quando a taxa horária é 0 mas há shares na sessão).
- **Prova de mutação:** a **mesma** mutação que sobreviveu ao PR 10 agora
  **derruba o spec — 4/4 falhas, exit 1** (a célula fica presa no placeholder `—`
  e o `waitForFunction` estoura o timeout). O mutante foi revertido e o
  `build_app_js --check` confirma os 17 fragmentos em sincronia.
- **Verde:** spec 4/4 (chromium + mobile-chrome) · `check:frontend` · JS core 1.435.

### Adicionado — registry multi-pool chain-aware (BTC + BSV) com detecção automática (Issue #571)
- **O problema:** 100% dos dados de pool vinham de um único host (`PARASITE_API`,
  `config.py:21` — `app.py:3225-3231`, `services/snapshot_assembly.py:107,157`,
  `solo_mining.py:19,75`). Um worker apontado para qualquer outra pool
  renderizava zeros — não por incompatibilidade, mas porque **nenhum outro
  formato era parseado**. Não existia registry: busca por `ckpool`,
  `public-pool`, `ocean.xyz` no código de produção retornava zero.
- **`services/pool_intelligence/providers.py` (novo):** registry chain-aware com
  **32 providers SHA-256** — BTC solo/pool e **BSV** (CKPool BSV, GorillaPool,
  TAAL, AntPool/ViaBTC/SBI BSV). `detect_provider()` identifica o provider pelo
  host de stratum com **precedência do padrão mais longo** (sem isso,
  `solo.bsv.ckpool.org` casaria com o `ckpool.org` genérico e um worker BSV
  seria marcado BTC) e **respeita limite de label** (`notbraiins.com` não é
  Braiins). `stratum_host()` extrai o host das formas que o firmware realmente
  reporta (`stratum+tcp://`, `stratum2+tcp://`, `tcp://`, `host:porta`, path,
  userinfo, IPv6 com colchetes).
- **Endpoints verificados, não inventados.** Só entram com API pública os que
  têm API documentada: parasite.space, CKPool (`solo.ckpool.org/users/{addr}` /
  `solo.bsv.ckpool.org/users/{addr}`) e Public Pool e forks
  (`public-pool.io:40557/api/client/{addr}`). Todo o resto entra como
  `stratum_only` — reconhecido, rotulado e chain-tagged, com os dados vindos do
  **próprio ASIC**.
- **`services/pool_intelligence/stats.py` (novo):** normaliza as três APIs
  públicas para **um único shape** (`PoolWorkerStats`) e adiciona a quarta e mais
  importante fonte: o hardware (`source: "asic"`). `parse_hashrate_to_hs()`
  aceita número cru **e** as strings de unidade que as pools publicam
  (`"1.21T"`, `"12 PH/s"`, `"950G"`) — e devolve `None` (não 0) quando não
  reconhece, porque 0 na pool é um fato e falha de parse não é. `fields_found`
  registra **quais** chaves foram entendidas, então "a pool respondeu 0" nunca
  se confunde com "não entendemos o payload".
- **Detecção automática ao conectar o endereço:** `resolve_pool_stats()` usa
  evidência em ordem — (1) endpoint reportado pelo ASIC, que é **autoritativo**
  por ser medido no hardware; (2) probe dos providers com API pública, o
  primeiro que conhece o endereço é a pool; (3) desconhecida, com o host cru
  como label. A chain **nunca** é inferida do endereço: BTC e BSV compartilham
  os formatos base58 `1…`/`3…`, então inferir seria sinal fabricado.
- **`POST /api/connect-wallet`** passa a resolver a pool no ato da conexão e
  devolver `pool`; **`GET|POST /api/pool/resolve`** (novo) expõe a detecção sob
  demanda, com `pool_url` opcional (endpoint do ASIC).
- **Testes:** `tests/test_pool_providers.py` (90 casos) — extração de host,
  precedência de padrão mais longo, guarda de limite de label, chain honesta vs.
  inventada, parsing de hashrate nas duas formas, os três normalizadores, a
  ordem de evidência da resolução e as duas rotas.
- **Docs:** `docs/WALLET_POOL_SETUP.md` deixa de dizer "Parasite Pool / APIs
  configuradas" (que prometia mais do que existia) e documenta a tabela real de
  providers, a ordem de detecção e o que significa `source: "asic"`.

### Corrigido — scan/agente identificam mineradores com evidência de protocolo, não por porta (Issue #569)
- **A causa dos "vários IPs diferentes com `port:80 braiins`":**
  `services/lan_scanner.py` derivava o `firmware_hint` **só da porta TCP aberta**
  (`8080 → bitaxe`, `80 → braiins_rest`, `80+4028 → braiins`, `4028 → cgminer`).
  Qualquer host com :80 — roteador, NAS, impressora, TV — virava "braiins". Pior:
  AxeOS/Bitaxe é **:80** (`axe_fleet/scanner.py BITAXE_PORT = 80`,
  `agent/agent.py AXEOS_PORT = 80`), então um Bitaxe **real** era rotulado
  `braiins_rest`. A string `braiins_reset` citada no relato **não existe** no
  repositório nem no histórico (`git log -S` → vazio): é a leitura de
  `braiins_rest` + `ports: 80` (e/ou do erro de conexão `RESET` de
  `axe_fleet/connector.py`).
- **Novo contrato:** porta aberta é apenas *candidato*. O `firmware_hint` agora vem
  exclusivamente de um protocolo de miner validado (`_identify_miner` →
  `core/registry/detector.detect_firmware`). Host que abre porta e não responde
  nenhum protocolo entra em `candidates` (com `alive`/`alive_ips`), **nunca** em
  `devices` — e o UI não oferece "+ Add" para ele. mDNS deixou de carimbar
  `firmware_hint: "braiins"` incondicionalmente: virou outra fonte de candidatos.
- **Detector fail-closed:** `detect_firmware` agora exige os marcadores de
  identidade do firmware — `/api/system/info` precisa de `hashrate`/`ASICModel`/
  `boardVersion`/`frequency` (ESP-Miner) e `/api/v1/miner/stats` precisa de
  `miner_stats` (Braiins OS+). Um `HTTP 200` com JSON — catch-all de roteador,
  portal cativo — **não** é mais classificado como minerador. Ganhou também um
  parâmetro `timeout`, usado pelo scanner (1,5 s) para não travar a varredura.
- **Agente:** `_probe_axeos` rejeita JSON sem marcadores ESP-Miner (antes qualquer
  200 com dict virava `type: "bitaxe"`, registrado no cloud e empurrando
  telemetria `{}` para sempre); `_probe_host` passa a tentar
  **AxeOS → Braiins OS+ REST → cgminer**, o que torna **visível** o hardware
  Braiins/Antminer REST-only (sem :4028) que antes não era descoberto de forma
  alguma. Novo `_braiins_rest_telemetry` traz hashrate, temps (board/ASIC), power,
  shares aceitas/rejeitadas/stale, uptime, best share, eficiência J/TH e
  `pool_url`/`pool_user` — mesmos campos de `braiins_adapter._parse_rest_telemetry`.
  Comandos: `restart` (cgminer) e `identify` (`led`); `pause`/`resume` são
  **rejeitados** em vez de reportar sucesso falso.
- **Guard de cloud simétrico:** `/api/network/scan` agora responde `400 ·
  is_cloud: true` em deploy cloud (como `/api/axe-fleet/scan`), em vez de varrer a
  sub-rede do datacenter e devolver "IPs" que não são do operador. O UI mostra a
  mensagem apontando para o AGENTE LOCAL.
- **Testes:** `tests/test_scan_protocol_evidence.py` (24 casos) fixa as duas
  direções — o falso positivo **deixa** de ser miner e o miner real **continua**
  sendo detectado.

### Alterado — extração do domínio Dashboard/render() para `static/src/39b-dashboard.js` (RFC #478 · PR 10, Issue #561)
- O cluster **Dashboard / `render()`** saiu de `static/src/40-app-logic.js` para
  `static/src/39b-dashboard.js` — **1.082 linhas movidas verbatim** em **6 recortes**
  (R5 `209–504`, R6 `506–753`, R8 `769–869`, R18 `1364–1723`, R24 `2031–2082`,
  R31 `3264–3288`): HUD/status bar/freshness + Operational Overview, painéis
  (`renderWalletIdentity`, `renderHostCore`, `renderHero`, `renderMinersXRay`,
  `renderPool`, `renderNetwork`), infraestrutura de gráficos (`CHART_METRICS`,
  `makeChart`, `loadChart`, `initCharts`, `bindChartRanges`, …), o `render()`
  principal, poll/relógio/snapshot (`fetchSnapshot`, `_snapshotFetching`) e
  `renderKpiCards`. **40 declarações** (31 funções + 9 de estado),
  **zero statements de topo** — o primeiro domínio extraído sem nenhum.
- O god file vai de **3.292 → 2.219 linhas**; `static/app.js` (17 fragmentos) é
  regenerado e fica em sincronia.
- **Posicionamento — o fragmento entra ANTES do 40** (como `37`/`38`/`39`), porque o
  prefixo síncrono do `boot()` chama `initCharts()` (lê/escreve `const charts`) e
  `fetchSnapshot()` (lê/escreve `let _snapshotFetching`). **Prova A/B medida:** com o
  fragmento depois do 40 o boot lança `Cannot access 'charts' before initialization`
  (probe e2e, chromium + mobile-chrome); antes, 0 pageerrors.
- **Prova de permutação:** o corpo do fragmento é um recorte contíguo e byte-idêntico
  das 1.082 linhas removidas; as 11 linhas adicionadas ao god file são as 6 costuras
  + 5 linhas de uma edição de doc (o comentário de fecho do IIFE, que citava
  `renderKpiCards`). No bundle, toda diferença é comentário — nenhuma linha executável
  criada, perdida ou alterada.
- **Prova de mutação:** desligar o ramo `CRITICAL` de `buildOperationalOverviewModel`
  derruba `operational-overview.spec.js` (**2 falhas**). **Honestidade:** duas mutações
  **sobreviveram** e ficam registradas — a asserção de `#kpi-hashrate` em
  `dashboard.spec.js` é condicional a um worker conectado, e `renderOperationalOverview`
  também é chamado pelo `49-axe-fleet.js`, de modo que o spec é alimentado por esse
  caminho (não pelo `render()`).
- **Verde:** JS core 1.435 · pytest 3.366 · `check:frontend` completo · e2e **82 testes**
  (dashboard 58 + operational-overview/live-metrics-pagination/probability-whatif/
  wallet-identity/market-affiliate 24).

### Alterado — guarda do service worker vira infra compartilhada dos e2e que mockam `/api/*` (RFC #478, Issue #562)
- O PR #550 registrou que o **service worker** (e não o guard `hasData`) era a causa
  raiz do spec do Block Hunt falhar — e que **qualquer** e2e que mocke `/api/*`
  precisaria da mesma guarda. Esta mudança fecha a varredura:
  - **`tests/e2e/support/sw-guard.js`** (novo) expõe `denyServiceWorker(page)`: a
    guarda canônica em `page.addInitScript` (`navigator.serviceWorker.register → reject`),
    com a causa raiz explicada num só lugar.
  - Aplicada aos **2 specs que mockavam `/api/*` sem guarda alguma**: `auth.spec.js`
    (5 `page.route` em `/api/auth/*` e `/api/axe-fleet/*`) e
    `live-metrics-pagination.spec.js` (patch de `window.fetch` em `/api/snapshot` +
    `/api/leaderboard`).
  - `probability-whatif.spec.js` passou a usar o helper em vez da cópia inline.
- **Não precisavam de mudança:** os outros **13** specs que mockam `/api/*` já
  neutralizavam o SW via `test.use({ serviceWorkers: 'block' })` (nativo do Playwright,
  equivalente à guarda); `market-affiliate.spec.js` já tinha guarda própria (stub de
  `navigator.serviceWorker` no `addInitScript`); e `conversion-admin`,
  `wallet-identity`, `pause-resume-agent` e `restart-agent` **não interceptam**
  `/api/*` (só observam ou usam `page.request`, que não passa pelo SW).
- **Prova medida (probe com/sem guarda, chromium + mobile-chrome):** sem a guarda a
  página termina com `controller: true, registrations: 1, caches: ['cypher65-v12']`;
  com a guarda, `controller: false, registrations: 0, caches: []`. Honestidade: hoje
  os 2 specs corrigidos **passavam mesmo sem** a guarda — a mudança é **preventiva**
  (remove o reload do `controllerchange` e o bypass do `page.route` pelo SW), não o
  fix de uma falha observada.
- Nenhum código de produção mudou (`static/app.js` em sincronia com `static/src/`);
  `check:frontend` verde e os 3 specs afetados verdes em chromium + mobile-chrome.

### Alterado — harness JS carrega os helpers de auth do fragmento real (RFC #478, Issue #559)
- O `tests/test_app_js_core.js` deixou de **espelhar** `authBuildHeaders`,
  `authIsExpired` e `authSessionValid`: agora carrega **o código real** de
  `static/src/38-billing-auth.js` via `loadFragment(...)`, com um sandbox
  mínimo (`window` para o único statement de topo e um `localStorage` que é
  o que o `licenseKey()` real consulta). As 18 asserções do espelho seguem
  válidas contra o fonte; 7 foram adicionadas.
- **O espelho havia divergido do fonte.** Ele ignorava `licenseKey()`, então a
  asserção `'no token -> empty headers'` ("`authBuildHeaders(null) === {}`")
  codificava o contrato **do espelho**: com licença PRO persistida em
  `_cypher65_license`, o fonte real devolve `{ 'X-License-Key': … }`. O header
  do tier PRO passa a ser testado de verdade (licença + token, licença sem
  token, valor preservado sem trim, licença vazia ignorada e limpeza).
- **Prova de mutação no fragmento real**: desligar o branch do `X-License-Key`
  — que é exatamente o contrato do espelho antigo — derruba a suíte
  (**3/1.435 falhas, exit 1**); zerar a margem de 30s do `authIsExpired` derruba
  1. Ambos restaurados; o mutante do header **sobrevivia** antes desta mudança.
- JS core: **1.428 → 1.435** testes. Nenhuma mudança de comportamento no
  fragmento de produção (só o comentário de cabeçalho, que passa a apontar o
  harness) e nenhuma mudança em auth, licença, checkout ou UI.

### Adicionado — SSE live-metrics, load-more do leaderboard, healthz de persistência (Issue #539)
- `/api/stream` envia `{type:"live", ts, worker_hashrate, pool_hashrate,
  fleet_avg_temp}` em vez do snapshot inteiro. O cliente atualiza só
  hashrate/temp/idade; o poll HTTP 15s continua sendo a fonte do dashboard.
- `GET /api/leaderboard?limit=&offset=` devolve `has_more`; o painel tem
  **LOAD MORE** (50). `/api/history` pagina quando `limit`/`offset` vêm
  na query (sem eles o contrato antigo — todas as rows — permanece).
- `/api/healthz` inclui `persistence.remote_backup` / `persistence.sentry`
  (bool) e `rate_limit_scope: process`. Cloud boot **loga** aviso se
  backup/Sentry faltam — não aborta.
- Secrets do Render, disco pago, Redis e flags de hardware/pagamento
  continuam OPERATOR / bloqueados. O deploy **não** é 100% seguro.

### Adicionado — selos LIVE/SYNCED/ESTIMATED/NO DATA, idade sempre visível, audit paginado (Issue #536)
- `metricProvenance` + `snapshotFreshnessLabel` no núcleo JS: o topbar mostra
  a idade do snapshot mesmo quando fresco (LIVE · Ns / SYNCED · …).
- Painel de scenario economics carrega badge **ESTIMATED** e a nota
  "actual earnings may vary".
- `GET /api/audit-logs?limit=&offset=` devolve `has_more` (default 50, cap 200).

### Adicionado — boot fail-closed em cloud + pip-audit + checklist pré-deploy (Issue #535)
- `services/boot_policy.py`: em `is_cloud_deploy()`, o processo recusa
  `SECRET_KEY` ausente, `CORS_ORIGINS=*` e Flask debug (`FLASK_DEBUG` /
  `FLASK_ENV=development`). Self-host local continua permitindo secret
  efêmera e CORS wildcard.
- After-request CORS deixa de emitir `Access-Control-Allow-Origin: *`
  quando o host é PaaS, mesmo que a env escape do boot.
- CI: `pip-audit -r requirements.txt` entra no job `pytest + JS core`
  (0 CVEs conhecidas em 2026-09-13).
- `docs/PRE_PUBLIC_DEPLOY_CHECKLIST.md` mapeia o roteiro de segurança /
  operação / fluidez em PASS, PARTIAL e OPERATOR. O deploy público
  **não** é declarado 100% seguro.

### Adicionado — adapter Stratum V2 SetupConnection limitado (Issue #533, Gate 082)
- Framing Common-layer binário com teto de 4 KiB; o adapter envia somente
  `SetupConnection` sem credencial, canal de mining ou submit de shares.
- `SetupConnectionSuccess` sanitizado (versão 2); Noise, tipos recusados e
  frames oversized falham closed (`noise_required` / `unsupported_message`).
- Lab virtual hermético; DNS continua pinado na resolução V1. Discovery
  ativo (Gate 083) permanece desligado.

### Alterado — extração do domínio Billing/Auth para `static/src/38-billing-auth.js` (RFC #478, Issue #545)
- O bloco **Billing/Auth** (o R1, topo do god file) saiu de
  `static/src/40-app-logic.js` para `static/src/38-billing-auth.js` (**924 linhas
  movidas verbatim**): sessão/tenant (`AUTH_SESSION_KEY`, `authLoadSession`,
  `authBuildHeaders`, `authFetch`, `authRefresh`, `authLogin`/`authLogout`,
  `authUpdateUi`, `authIsExpired`/`authSessionValid`/`authGetToken`, `initAuth`),
  licença/PRO (`LICENSE_STORAGE_KEY`, `_license`, `fetchLicenseStatus`,
  `initLicensing`, `renderLicenseBadge`, `syncAiPremiumUi`,
  `handleLicenseRequired`), funil + upgrade on-chain
  (`openUpgradeModal`/`syncUpgradeModal`, `buyUpgrade`/`buyPro`, `_btcUpgrade`,
  `setUpgradeTab`, `startBtcUpgrade`, `pollBtcStatus`, `startBtcCountdown`,
  `copyBtcPayload`, `payBtcWithWebLN`, `applyUpgradeKey`, `renderBtcPending`) e o
  indicador de instância (`instanceClassify`, `initInstanceIndicator`).
  `40-app-logic.js` 5.243 → **4.320 linhas**.
- **Primeiro domínio desde o PR 5 que PRECISA vir ANTES do god file** (ordinal
  `38`, antes do `39-terminal.js`). A régua é sobre *estado* lido por chamada de
  nível de módulo, e o prefixo **síncrono** do `boot()` chama `initLicensing()`
  (lê o `let _license`, via `renderLicenseBadge`/`syncUpgradeModal`/
  `syncAiPremiumUi`), `initAuth()` e `initInstanceIndicator()`. Depois do 40 o
  estado estaria em **TDZ** no boot → `ReferenceError`.
- **É também a ordem original:** o R1 era a **linha 1** do god file, antes do
  bloco de terminal (linha 2.540+). Entrar como `38` restaura a ordem relativa do
  arquivo original — e o error boundary do `39` volta a cobrir a avaliação do
  domínio, como cobria antes do split.
- **Prova de movimento mecânico**: `static/app.js` == fragmentos do
  `origin/master` com as 924 linhas realocadas verbatim — sequência de código
  idêntica, 10.924 = 10.924; **0 removidas**, 46 adicionadas (45 de cabeçalho + 1
  marcador) + 1 separador em branco.
- **Prova de mutação**: `renderBtcPending` com `return;` antecipado em
  `38-billing-auth.js` → `upgrade-btc.spec.js` falha **10/18**. Restaurado.
- **Verificações antes de mover:** 1 statement de topo na faixa
  (`window.openUpgradeModal = openUpgradeModal;`, que só atribui referência),
  **zero** declarações/statements em coluna 0, nenhuma linha de nível de módulo do
  R1 lê estado definido depois no IIFE, e zero colisão dos 7 nomes de estado com
  os outros 13 fragmentos. O harness JS **espelha** `authBuildHeaders`/
  `authIsExpired`/`authSessionValid` (Suite 22), portanto não carrega o god file.

### Alterado — extração do domínio Wallet + Support para `static/src/37-wallet-support.js` (RFC #478 · PR 9, Issue #551)
- **A meta do RFC #478 foi atingida**: `static/src/40-app-logic.js` sai de **4.320**
  para **3.292 linhas** (partiu de 7.706), abaixo da meta de ~4.000. A projeção
  publicada antes do merge era 3.288; as **4 linhas de diferença** são a costura
  (2 linhas de comentário `// → … extraídos para static/src/37-wallet-support.js`
  + 2 linhas em branco), contabilizadas na Issue #557 (PR #558).
- **1.032 linhas movidas verbatim** em **2 blocos contíguos** para
  `static/src/37-wallet-support.js` (1.062 com cabeçalho):
  - **R3** `44–642` (599) — Wallet crypto: WebLN (`detectWebLN`/`connectWebLN`),
    bech32 (`_bech32Polymod`), validação de endereço
    (`validateBitcoinAddress`/`_updateWalletValidation`), o gerador de QR
    inteiro (`buildQrMath`/`QrPoly`/`qrEncode`/`qrSvg`) e identidade/health da
    wallet (`walletAddressParts`/`walletHealth`).
  - **R20** `2599–3031` (433) — Support: doações
    (`renderSupportMethods`/`loadDonations`), LN
    (`_populateLNAddress`/`sendLNPayment`), modal/histórico da wallet
    (`openWalletModal`/`closeWalletModal`/`toggleWalletCTA`/
    `fetchWalletHistory`/`walletGreeting`/`walletHasFullAccess`).
- O fragmento entra **ANTES** do god file (como o `38` e o `39`), desta vez por
  **ordem de execução**, não por TDZ: as **18 statements de topo** do domínio
  rodavam em 2711–2928, ou seja **antes** do `boot();` (linha 3260). Depois do
  40 elas rodariam depois do boot — inversão silenciosa, sem erro e sem teste.
  Todas as dependências resolvem por *hoisting* (`escapeHtml`, `cssVar`,
  `openModalAnimated`, `authFetch` são `function` declarations do IIFE único)
  ou por fragmento anterior (`dom`, `const` no `20-dom-primitives.js`).
- **Prova de permutação**: `static/app.js` gerado tem **11.029 = 11.029**
  linhas de código — **0 removidas, 0 adicionadas**; o `40` novo é byte-idêntico
  ao antigo menos as duas faixas, e o `37` termina exatamente no corpo verbatim
  após um cabeçalho de 31 linhas só de comentário.
- **Prova de mutação dupla (2 caminhos)**: mutar o *listener de topo* do
  `_onSupportOpen` derruba `webln.spec.js` **10/26** (a statement de topo
  relocada realmente executa); mutar o *opening tag* do `qrSvg` derruba
  `upgrade-btc.spec.js` **6/18** (a ponte com o `38-billing-auth.js` segue viva
  por hoisting). Ambos restaurados.
- **Gates**: pytest 3366 · JS core 1406 · `check:frontend` completo · guards
  DOM · e2e `webln` 26, `upgrade-btc` 18, `wallet-identity` 2, `modals` 26,
  `dashboard` 58, `probability-whatif` 6.
- **Achado de cobertura registrado pelo PR 9 — fechado depois na Issue #553
  (PR #554)**: o harness JS ainda **espelhava** `validateBitcoinAddress` e
  `QrPoly`, os dois recém-movidos para o `37-wallet-support.js`. Mesmo padrão já
  corrigido no #515 (Market) e no #548 (Block Hunt); entrou como follow-up
  explícito em vez de silêncio.

### Alterado — harness JS carrega validação, identidade e QR do fragmento real (RFC #478, Issue #553)
- O `tests/test_app_js_core.js` deixou de **espelhar** `validateBitcoinAddress`,
  o núcleo QR (`buildQrMath`/`QrPoly`/`qrEncode`/`qrSvg`) e
  `walletAddressParts`/`walletHealth`: agora carrega **o código real** de
  `static/src/37-wallet-support.js` via `loadFragment(...)`, com um sandbox
  mínimo que mantém listeners e requests de topo inertes (sem DOM, rede,
  pagamento ou efeitos assíncronos).
- **−441 / +35 linhas** no harness (437 linhas duplicadas removidas).
- **Prova de mutação no fragmento real**: `validateBitcoinAddress` forçado a
  rejeitar tudo → **7/16 falhas, exit 1**; `qrEncode` forçado a devolver matriz
  vazia → **37 falhas, exit 1**. Ambos restaurados, fonte sem diff.
- **Corrigido no caminho — fail-closed da suíte**: os blocos legados `[btc-valid]`
  e `[chunk]` imprimiam `FAIL` mas **não incrementavam o contador global**, então
  o processo terminava com **exit 0 mesmo com asserts quebrados**; ambos agora
  delegam ao `assertEqual`.
- JS core: **1.406 → 1.428** testes (`check:frontend` completo, axe 100/100).
  Nenhuma mudança no fragmento de produção, wallet, QR, checkout ou UI.

### Corrigido — cobertura do Block Hunt: harness carrega o fonte e e2e tem fixture determinístico (RFC #478, Issue #548)
- O PR 7 (#542) registrou duas lacunas de cobertura em vez de escondê-las. Esta
  issue fecha as duas:
  - **SUITE 33 do harness JS** deixou de **espelhar** o what-if e passa a carregar
    `static/src/42-probability.js` via `loadFragment(..., { window: {} })` —
    `simulateDifficultyShift`/`_bhFinitePositive` agora são o **código real**.
    Mutar o fragmento derruba **5 asserções** da suíte.
  - **`tests/e2e/probability-whatif.spec.js`** ganhou `forceBlockHuntData()`:
    intercepta `/api/snapshot` e injeta `network.difficulty = 110 T` +
    `worker.bestDifficulty = 10 G`, corta `/api/stream` e compara os readouts
    **numéricos** (9.09e-3% / 8.26e-3% / 6.99e-3% / 1.21e-2%) em vez de só o
    sinal. Antes o spec **pulava** a comparação quando o servidor não tinha
    dados de pool (guard `hasData`).
- **Achado — o service worker, não o `hasData`, era a causa raiz.** O boot
  registra um SW; quando ele assume o controle o app faz `location.reload()` e o
  **próprio SW passa a responder `/api/snapshot` do cache**. `page.route` não
  intercepta request originado de dentro do SW, então o fixture era ignorado e o
  painel voltava ao snapshot real (`0.00e+0%`, 127 T). Corrigido negando o
  registro via `page.addInitScript` (`navigator.serviceWorker.register → reject`).
  Qualquer e2e futuro que dependa de `page.route` em `/api/*` precisa da mesma guarda.
- **Prova de mutação dupla**: mutar o *math* no fragmento derruba a SUITE 33
  (**5 asserções**); mutar o mesmo ponto no **bundle** `static/app.js` — o
  artefato que o navegador realmente executa — derruba o spec (**4/4**).
  Nenhum código de produção mudou (`static/app.js` em sincronia, 15 fragmentos).

### Alterado — extração do domínio Probability/Block Model para `static/src/42-probability.js` (RFC #478, Issue #542)
- O cluster **Probability/Block Model** saiu de `static/src/40-app-logic.js` para
  `static/src/42-probability.js` (**635 linhas movidas verbatim** — o cluster é
  contíguo, 2.381–3.015, então não houve corte no meio de domínio como no
  4a/4b): probabilidade + block model (`renderProximity`,
  `_drawProximitySparkline`, `renderQuantumLock`, `_setQlComp`, `renderLiveCalc`,
  `renderNetworkGauge`, `_drawGauge`), rentabilidade/comparação/solo/marcos
  (`profitModeView`, `setProfitMode`, `renderProfitability`, `renderComparison`,
  `renderSoloStats`, `renderMilestones`) e o **Block Hunt** what-if
  (`_bhSliderValue`, `_bhFinitePositive`, `simulateDifficultyShift`,
  `_bhRenderWhatIf`, `renderBlockHunt`). `40-app-logic.js` 5.877 → **5.243
  linhas**.
- **Sem exceção de posicionamento:** o fragmento entra **depois** do god file,
  como o `41`. O único statement de topo da faixa
  (`window.setProfitMode = setProfitMode;`) viaja junto; os 5 nomes de estado
  (`_proxSparklineData`, `_profitMode`, `_lastProfitability`, `_bhBase`,
  `_bhSliderEl`) não são lidos em nenhum outro ponto do 40 nem em outro
  fragmento; o prefixo síncrono do `boot()` não chama nada do domínio; e o bloco
  do `#bh-whatif-slider` que **fica** no god file só registra handlers.
- **Prova de movimento mecânico**: `static/app.js` == fragmentos do
  `origin/master` com as 635 linhas realocadas verbatim — sequência de código
  (não-comentário/não-branco) idêntica, 10.924 = 10.924; **0 removidas**, 36
  adicionadas (35 de cabeçalho + 1 marcador) + 1 separador em branco.
- **Prova de mutação**: mutação no badge do `_bhRenderWhatIf`
  (`badge.textContent = 'MUTADO'`) em `42-probability.js` →
  `probability-whatif.spec.js` falha **6/6** nos dois projetos. Restaurado.
- **Lacuna de cobertura registrada (não corrigida neste PR)**: uma mutação no
  *math* (`simulateDifficultyShift` retornando `base`) **sobrevive** — o spec
  pula a comparação numérica quando o servidor não tem dados de pool (guard
  `hasData`, `#bh-whatif-diff` = '—'), e a SUITE 33 do harness JS **espelha** o
  what-if em vez de carregar o fragmento. O caminho aberto pelo `loadFragment()`
  do PR 2 (#515) para o Market é o candidato natural a follow-up.

### Alterado — extração de Automations/Alerts/Auto-Pilot/Decision Matrix para `static/src/41-automations.js` (RFC #478, Issue #540)
- Quatro blocos contíguos do `40-app-logic.js` foram para
  `static/src/41-automations.js` (**1.073 linhas movidas verbatim**): os feeds de
  **alertas/eventos** do dashboard + painel de conta (`acctRankLabels`,
  `renderAccount`, `_staleChip`, `renderBtcPrices`, `renderHalving`,
  `renderMempoolFees`, `renderAlerts`, `renderEvents`, `renderLeaderboard`), a
  **Decision Matrix + Command Center** (`renderDecisionMatrix`,
  `commandCenterCardHtml`, `renderCommandCenter` + os dois `init*Controls`), o
  **Auto-Pilot** (arming/advisory/dry-run: `_apSetUi`, `_apRefreshStatus`,
  `_apSetArmed`, `_initAutoPilot*`, `_apDr*`) e o **Alert Center/Automations**
  (`acState`, `ac*`, `acShowTab` + o bloco de topo que injeta a tab-strip e
  registra os listeners). `40-app-logic.js` 6.946 → **5.877 linhas**.
- **Primeiro fragmento DEPOIS do god file que passa na régua sem exceção:** os
  12 nomes de estado do domínio não são lidos por nenhuma chamada de nível de
  módulo do 40 (varredura do arquivo inteiro e dos outros 12 fragmentos), e o
  prefixo síncrono do `boot()` só toca o domínio por
  `initDecisionMatrixControls()`/`initCommandCenterControls()` — que leem apenas
  `document`. Ficaram no god file, de propósito, o `_lastSnapshot` (poll/SSE
  escrevem, terminais e AXE Fleet leem) e o estado do Fleet Command Center
  (`_cc*`), que o `boot()` toca antes de o fragmento 48 existir.
- **Prova de movimento mecânico**: 0 linhas removidas e **0 linhas de código
  adicionadas** (só comentários e separadores); sequência de código
  10.924 = 10.924 contra os fragmentos do `origin/master` com os 4 blocos
  realocados.
- **Prova de mutação**: desligar a injeção da tab-strip no único statement de
  topo do fragmento derruba `alert-center-tabs.spec.js` (**4/4**). Restaurado.

### Alterado — extração do domínio Terminal/SSE para `static/src/39-terminal.js` (RFC #478, Issue #529)
- O domínio **Terminal/SSE** saiu de `static/src/40-app-logic.js` para
  `static/src/39-terminal.js` (**752 linhas movidas verbatim**): o terminal de
  eventos do **LIVE MINING** (`_lm*` + `_initLmEventLogControls`, com o ring
  buffer limitado, scroll lock, filtro e stats), o **log/timeline de eventos**
  com o **error boundary global** (`logMessage`, `window.onerror` +
  `unhandledrejection`, `renderTerminalEvents`/`renderTimelineFeed`/
  `renderTimelineStats`) e o **TERMINAL SOLO** interativo (`_soloTerm*`,
  `_termBindInput`, `_soloTermInit`, `_liveTermInit`).
  `40-app-logic.js` 7.706 → **6.959 linhas**.
- **Este é o primeiro fragmento que vem ANTES do god file** — e isso não foi
  escolha estética. O `boot()` é **chamado no topo do IIFE, dentro do próprio
  `40-app-logic.js`** (linha 6.388), então o corpo síncrono dele roda **durante a
  avaliação do fragmento 40**, antes de 45–49 existirem. E esse corpo **lê estado
  do Terminal**: `_initLmEventLogControls()` (que termina em `_lmRenderStats()` →
  `const _lmStats`), `_liveTermInit()` e `logMessage('SYSTEM', 'WAR ROOM ONLINE')`
  (que faz `events.push(...)` → `let events`). Com o fragmento **depois** do 40,
  esse estado estaria em **TDZ** nesse instante → `ReferenceError` no boot.
- **Regra nova e sistêmica:** domínio cujo estado seja lido por uma chamada de
  **nível de módulo** do `40-app-logic.js` (o `boot();` ou um `X()` no topo, como
  o `renderSupportMethods()` do domínio Wallet no PR 9) tem de vir **antes** do
  god file — ou deixar o estado no god file. É a primeira exceção à regra
  "45–49 vêm depois". A previsão do RFC §3.3 que dizia o contrário foi **corrigida
  no próprio RFC**, com o motivo.
- **Consequência deliberada:** o error boundary global passa a cobrir também a
  avaliação do `40-app-logic.js` (antes ele só existia a partir da linha 2.625 do
  arquivo original). É estritamente mais proteção, nunca menos — e o handler usa
  apenas `window`/`document` + funções do próprio fragmento.
- **Ficou no god file, de propósito:** o bloco de estado do **Fleet Command
  Center** (`_ccLastFleet`/`_ccView`/`_ccHrSeries`/`_ccHrHist`/`_ccShareSeen`)
  morava no meio do bloco de estado do Terminal, mas mover para `48-fleet-cc.js`
  seria um `ReferenceError`: o `boot()` chama `initFleetCommandCenterControls()`
  (que lê/escreve `_ccView`) de forma síncrona **antes** do fragmento 48 ser
  avaliado. E `_lastSnapshot` é global compartilhado (poll/SSE escrevem, AXE Fleet
  lê).
- **Prova de movimento mecânico**: `static/app.js` gerado — **0 linhas
  removidas**, 56 adicionadas (todas comentário de cabeçalho) + 5 separadores em
  branco. **0 diferenças não-comentário/não-branco**.
- **Prova de que a e2e exercita o código no novo fragmento**: mutação de
  `_soloTermPrint` (early return) em `39-terminal.js` → `terminal.spec.js` falha
  em 4 testes nos dois projetos (`✘ status command`, `✘ workers command`, chromium
  + mobile-chrome). Restaurado.
- **O item "reconexão" do PR 5 NÃO foi extraído:** a lógica de `EventSource`
  (debounce de 2s, fallback para polling após 5 erros) mora **dentro do `boot()`**
  e permanece lá — é o caminho síncrono do boot, e extrair mudaria o instante de
  execução. Fica como PR próprio, se valer.

### Documentação — RFC #478: domínios não planejados e reordenação dos PRs até a meta (Issue #527)
- A seção de frontend do RFC parava em "PR 5 Terminal/SSE" e "PR 6
  Alerts/Auto-Pilot", sugerindo **2 PRs** restantes. O inventário linha a linha
  de `40-app-logic.js` (381 declarações de topo, 31 blocos contíguos que cobrem o
  arquivo sem lacuna) mostra **cinco domínios** mais um residual, e a **§3.3**
  nova fixa a ordem: **5** Terminal/SSE (773), **6** Automations+Alerts+
  Auto-Pilot+Decision Matrix (1.062), **7** Probability/Block Model (635),
  **8** Billing/Auth (923) e **9** Wallet+Support (1.032). A meta de ~4.000
  linhas é atingida no PR 9 (`7.706 → 3.281`; os PRs 5–8 param em 4.313).
- **A regra muda de "por tamanho" para "um PR = um domínio".** A divisão 4a/4b
  foi feita **por tamanho** e cortou um bloco fisicamente entrelaçado, o que
  produziu o resíduo de posse que a Issue #525 acabou de realocar. Todos os
  blocos medidos agora são ≤ 1.500, então a régua não força mais nenhum corte.
- **Duas restrições estruturais documentadas.** (1) `boot();` é chamado no topo
  do IIFE **dentro de `40-app-logic.js`** (linha 6.388) — ou seja, durante a
  avaliação do 5º de 11 fragmentos, antes de `45-market.js`…`49-axe-fleet.js`
  existirem: é a origem real da disciplina de TDZ de Admin/4b. (2) A lógica de
  **reconexão SSE** (EventSource, debounce de 2s, fallback para polling após 5
  erros) mora **dentro do `boot()`**, então o item "reconexão" do PR 5 não é
  extração mecânica — recomenda-se mover só os terminais e documentar o
  acoplamento, deixando a extração do `connectLiveStream()` para um PR próprio.
- Registrado também um achado de forma: `renderPool`, `acctRankLabels` e
  `renderAccount` estão em **coluna 0** (bolha sem indentação) no meio de R6/R7 —
  quem mover esses blocos deve preservar o recorte verbatim em vez de reindentar.

### Corrigido — resíduo do Fleet Command Center realocado para seu dono (RFC #478, Issue #525)
- O 4b (#523) havia deixado em `static/src/49-axe-fleet.js`, por **vizinhança
  textual**, código que pertence ao **Fleet Command Center**. Voltaram verbatim
  para `static/src/48-fleet-cc.js`: o **raster de hash-flow** (`_lmFlow`,
  `_lmLastCounters`, `_LM_FLOW_MAX`, `_LM_FLOW_LABELS` + os 4 helpers puros que
  os consomem) e o `fetchFleetCommandCenter()` + `initFleetCommandCenterControls()`.
  **75 linhas movidas** (o wart documentado dizia ~53: faltavam na conta o
  `fetchFleetCommandCenter` — também FCC, também deixado para trás — e os
  comentários das declarações). `48-fleet-cc.js` 424 → **500 linhas**,
  `49-axe-fleet.js` 1.342 → **1.267 linhas**.
- **Achado que dá o real motivo da limpeza: a dependência entre os dois
  fragmentos estava INVERTIDA.** O `48-fleet-cc.js` é avaliado **antes** do `49`,
  mas o `_ccRenderFleet()` (no `48`) lia **8 nomes definidos no `49`**. Funcionava
  por acidente feliz — `function` declarations sofrem hoisting no IIFE
  compartilhado e os `const` do `49` já estavam inicializados quando o
  `_ccRenderFleet` **rodava** (o `48` só o chama em runtime). A fronteira do
  domínio estava violada nas duas direções; agora todo o código do FCC vive no
  `48` e a única travessia que resta é a natural: o poll do AXE Fleet
  (`fetchAxeFleet`, no `49`) chama `fetchFleetCommandCenter()` para o FCC andar no
  mesmo cadence.
- **Prova de movimento mecânico**: `static/app.js` gerado é uma **permutação** do
  anterior — multiset comparado linha a linha, **0 linhas não-brancas/não-comentário
  alteradas** (17 comentários removidos, 32 adicionados, 2 em branco).
- **Prova de que os testes exercitam o código no novo dono**: mutação de
  `_LM_FLOW_MAX` (24 → 1) em `48-fleet-cc.js` faz `live-mining.spec.js` falhar nos
  dois projetos (`✘ chromium`, `✘ mobile-chrome`).
- **Fora do escopo, registrado**: `_ccShareSeen` continua em `40-app-logic.js`
  porque é **compartilhado** (usado pelo `_ccRenderFleet` no `48` **e** pelo ticker
  do Live Mining); e o harness ainda **espelha** os 3 helpers puros em vez de
  carregar via `loadFragment()` — follow-up no padrão da Issue #515.

### Alterado — extração do AXE Fleet para `static/src/49-axe-fleet.js` (RFC #478, Issue #523)
- O domínio **AXE Fleet** saiu de `static/src/40-app-logic.js` para
  `static/src/49-axe-fleet.js` (**1.304 linhas movidas verbatim**): acesso remoto
  (`renderTailscale`/`fetchTailscale`/`renderRemoteOnboarding`/
  `fetchRemoteOnboarding`), `fetchAxeFleet`, o scanner de LAN
  (`scanNetwork`/`renderScanResults`/`renderAxeScanResults`/`startAxeScan`/
  `initAxeScanControls`/`openAxeAddForm`), os cards e a inteligência por worker
  (`renderAxeFleet`/`_renderAxeCard`/`_handleAxeCmdClick`/`openAxeDetail`/
  `loadDeviceHistoryChart`/`buildCommandCenterRows`), o hash-flow raster
  (`_lmShareDelta`/`_lmFlowSampleFromDelta`/`_lmFlowDetail`/`_pushLmFlowSample`
  — prefixo `_lm`, mas consumidos **só** pelo `_ccRenderFleet`),
  `fetchFleetCommandCenter`/`initFleetCommandCenterControls`, o wizard
  (`gotoAxeWizStep`/`setAxeWizMode`/`resetAxeWizard`/`renderAxeConfirm`/
  `testAxeConnectivity`/`buildConnectivityReport`/`renderConnectivityReport`),
  `initAxeFleetControls`, `initAxeAgentPanel` e `addAxeDevice`.
  `40-app-logic.js` 9.011 → **7.706 linhas**. Isso **fecha o domínio Fleet/AXE**
  (o 4a levou o Fleet Command Center para `48-fleet-cc.js`).
- **Um statement de execução no topo** — igual ao Admin, e diferente do Market/
  Rentals/4a: o listener de `#remote-test-btn` (`click` → `fetchTailscale()`).
  Nenhum listener do IIFE depende de ordem e `static/app.js` é `defer`, então
  registrar mais tarde dentro do mesmo IIFE síncrono não muda o resultado.
- **Sem TDZ.** A região declara 7 variáveis (`_scanning`, `_lmFlow`,
  `_lmLastCounters`, `_LM_FLOW_MAX`, `_LM_FLOW_LABELS`, `_axeDetailChart`,
  `_axeWizState`) e **nenhuma** é referenciada fora dela. O único caminho que
  entra na região antes da avaliação do fragmento é o prefixo síncrono do
  `boot()`, que chama `initAxeFleetControls()` → `initAxeScanControls()` /
  `initAxeAgentPanel()`: os três corpos foram varridos e não tocam nenhuma
  dessas variáveis em nível síncrono.
- **Acoplamento externo de 6 nomes**, todos no mesmo IIFE (function declarations
  são hoisted): `fetchAxeFleet` (4 locais), `fetchRemoteOnboarding`,
  `fetchTailscale`, `initAxeFleetControls`, `openAxeDetail` e
  `initFleetCommandCenterControls`.
- **Prova de movimento mecânico**: `static/app.js` gerado é uma permutação do
  anterior — **0 linhas perdidas** (nem as em branco), 36 adicionadas (todas
  comentário de cabeçalho).
- ~~**Wart documentado**: `initFleetCommandCenterControls` (13 linhas) é controle
  do painel **Fleet Command Center**, mas é vizinho físico de
  `fetchFleetCommandCenter` e veio junto para o recorte continuar verbatim e
  contíguo. Candidato a realocação mecânica posterior.~~ **RESOLVIDO na Issue
  #525** — o resíduo do FCC (75 linhas) voltou para `48-fleet-cc.js`.

### Alterado — extração do Fleet Command Center para `static/src/48-fleet-cc.js` (RFC #478, Issue #521)
- O painel **Fleet Command Center** + a telemetria saíram de
  `static/src/40-app-logic.js` para `static/src/48-fleet-cc.js` (**393 linhas
  movidas verbatim**): `parseBestDiff`, o guard numérico `_numOrNull`, a agregação
  pura `_ccKpiAgg`, `_ccShareBar`/`_ccSvgSparkline`/`_ccTempBand`/
  `_ccRenderNetwork`, o destaque de best-share `_updateFleetBestShare`,
  `renderFleetCommandCenter` + `_logMiningEvent` (alimentação do terminal de
  eventos) e os renderers fleet-fed `_ccRenderFleet`/`_ccRenderExceptions`/
  `_ccRenderThermal`/`_ccRenderCards`/`_ccRenderTable`.
  `40-app-logic.js` 9.407 → **9.011 linhas**.
- **O PR 4 do RFC foi dividido em dois.** O cluster Fleet/AXE tem 1.695 linhas e
  a seção 4 do RFC fixa ≤ ~1.500 linhas movidas por PR. Este é o **4a** (painel +
  telemetria, 393 linhas); o **4b** (`49-axe-fleet.js`, cards/scan/wizard/agente/
  Tailscale, ~1.300 linhas) vem em seguida.
- **Duas regiões disjuntas.** O cluster não é contíguo: `_initLmEventLogControls`
  — UI do terminal de eventos do módulo LIVE MINING, que pertence ao **PR 5**
  (Terminal/SSE) — estava **entre** as duas metades e **permanece** no app-logic.
  A metade de baixo carrega junto o comentário de seção ("FLEET-fed rendering")
  para o recorte seguir verbatim.
- **Zero execução no topo e zero `const`/`let`** na região extraída: só
  declarações de função, nenhuma variável. O fragmento entra depois de
  `47-admin.js` e antes de `50-close.js` sem TDZ — e como não há variável movida,
  não existe superfície de TDZ nem para os consumidores que rodam antes.
- **Acoplamento externo de 3 pontos**, todos no mesmo IIFE (function declarations
  são hoisted, a ordem de concatenação não muda nada): `renderFleetCommandCenter`
  é chamado por `render()`; `_ccRenderFleet` por `initFleetCommandCenterControls()`
  (região B, permanece) e pelo chip de view; `_numOrNull` é consumido por
  `buildCommandCenterRows` (região B).
- **Prova de movimento mecânico**: `static/app.js` gerado é uma permutação do
  anterior — **0 linhas não-brancas perdidas**, 28 adicionadas (todas comentário
  de cabeçalho) e 1 linha em branco a menos (normalização das costuras).

### Alterado — extração do domínio Admin/CFO/CRO para `static/src/47-admin.js` (RFC #478, Issue #518)
- O bloco **Admin/CFO/CRO** saiu de `static/src/40-app-logic.js` para
  `static/src/47-admin.js` (1.092 linhas, sendo **1.057 movidas verbatim**):
  estado (`_adminLoaded`, `_adminAuditDecisions`, `_adminAuditChart`,
  `_adminAnalyticsCharts`, `_adminMetricsChart`, `_adminErrorChart`,
  `_adminFunnelTrendChart`), os builders puros do audit trail
  (`adminAuditIsoWeekKey`, `buildAdminAuditWeekly`, `buildFeatureAlert`,
  `buildFeatureBreakdown`, `buildCohortRows`, `buildFunnelTrend`,
  `filterAdminAuditDecisions`, `adminAuditVerdictMeta`,
  `buildAdminAnalyticsModel`), `fetchAdminData`, `_renderAdmin` + os renderers
  (analytics, docs feedback, features, funnel trend, coortes LTV, pool metrics,
  error rate, degradação, audit trail) e os CSV/filtros do painel.
  `40-app-logic.js` 10.465 → **9.407 linhas**.
- **Correção da previsão da issue**: o fragmento previsto era `52-admin.js`, mas
  `50-close.js` **fecha o IIFE** — o arquivo é `47-admin.js`, antes do
  fechamento (mesma correção feita no PR 3 para o Rentals).
- **Este cluster NÃO contém só declarações** — ao contrário do Market e do
  Rentals, ele tem **4 statements de topo** que executam na avaliação do script:
  o listener delegado de `#admin-panel` (`change` → filtros do audit trail) e os
  `click` de `#admin-audit-csv`, `#admin-funnel-csv` e `#admin-refresh-btn`.
  Verificado: nenhum depende de ordem em relação aos outros listeners do IIFE e
  `static/app.js` é carregado com `defer` (o DOM já está parseado), então rodar
  mais tarde dentro do **mesmo IIFE síncrono** não altera o resultado.
- **A verificação dos listeners tem dentes**: a e2e
  `admin-audit.spec.js` já provava o listener de filtro (muda a contagem de
  linhas ao selecionar tenant/verdict); para o refresh, a
  `conversion-admin.spec.js` foi **fortalecida** — agora conta as requisições a
  `/api/admin/sessions` e exige que o clique dispare uma nova leva (antes só
  afirmava "clicar não lança", o que passaria sem listener nenhum). Mutação que
  desliga o listener de refresh faz a spec falhar nos dois projetos.
- **Movimento mecânico provado**: recorte verbatim byte-idêntico e
  `static/app.js` gerado é uma **permutação** do anterior — 0 linhas perdidas,
  34 adicionadas (todas comentário). Nenhum id de DOM, contrato de fetch ou
  formato de payload mudou.
- Ficou registrado como follow-up: os builders puros do audit trail continuam
  **espelhados** em `tests/test_app_js_core.js`; a conversão para
  `loadFragment('47-admin.js')` segue o padrão fixado na Issue #515.

### Alterado — extração do domínio Rentals para `static/src/46-rentals.js` (RFC #478 · PR 3, Issue #517)
- O domínio **Rentals** saiu de `static/src/40-app-logic.js` para o fragmento
  `static/src/46-rentals.js` (1.795 linhas, sendo **1.770 movidas verbatim**):
  estado do módulo, núcleo (`_setRentalsFilter`, `_renderRentalsPortfolio`,
  `_mrToTh`, `_rentalStatus`, `_rentalHashrateStr`, `_rentalPriceStr`,
  `_rentalRigTrust`, `_rentalIsBad`), painéis (recomendações, accepted,
  auto-exclusões, market timing, forecast, risk banner, signals, consolidado),
  série temporal + drill-down por bucket, analytics click-first (rankings,
  heatmap, expiring, worst-rig leaderboard, exposure, concentration), modais
  (`openRigTrackRecord`, `runBacktest`, `openBacktestModal`, `openRentalDetail`)
  e `loadRentals`/`renderRentals`/`_initRentalsPanel`.
  `40-app-logic.js` 12.236 → **10.465 linhas**.
- **Correção da previsão do RFC**: o fragmento previsto era `55-rentals.js`, mas
  `50-close.js` **fecha o IIFE** — nenhum fragmento pode ter ordinal maior. O
  arquivo é `46-rentals.js`, imediatamente antes do fechamento. Registrado no
  RFC e na Issue #517.
- **Movimento mecânico provado**: recorte verbatim (fidelidade byte-idêntica
  conferida contra o `40-app-logic.js` anterior) e `static/app.js` gerado é uma
  **permutação** do anterior — 0 linhas perdidas, 24 adicionadas (comentário de
  cabeçalho). Nenhum id de DOM, contrato de fetch, formato de payload ou ordem
  de execução mudou.
- **Zero execução no topo** (verificado): o cluster contém só declarações, então
  o fragmento entra antes de `50-close.js` sem TDZ. O acoplamento externo é de
  **4 pontos** — `_initRentalsPanel()` (boot), `loadRentals()` (poll + ativação
  do módulo), `_rentalsLoaded` (guard de lazy-load) e `_rentalsData` — todos
  dentro de funções que rodam depois da avaliação do IIFE. Os listeners do
  painel vivem dentro de `_initRentalsPanel()`, não no nível do módulo.
- Ficaram **fora** do fragmento (seguem em `40-app-logic.js`): o modal de compra
  spot da Braiins, o AI Operator e o Auto-Pilot.
- Escopo ampliado por decisão explícita: o cluster tem 1.770 linhas, acima do
  guardrail de ~1.500 do RFC. Aceito num único PR porque o cluster é coeso e
  contíguo.

### Alterado — harness do Market passa a testar o FONTE, não um espelho (Issue #515)
- `tests/test_app_js_core.js` agora carrega os helpers puros do Market de
  `static/src/45-market.js` via `loadFragment()` — `_fmtBtcPerTh`,
  `_mktUsdPerTh`, `_mktBestIndex`, `_mktRenderCap`, `sortMarketVenues` e
  `buildMarketTrendDatasets`. Antes eram **cópias à mão** no harness, o mesmo
  padrão que escondeu 3 bugs de produção no PR 1 (Issue #490).
- **Removidas 108 asserções de suítes legadas** (1.492 → 1.384 testes), todas
  espelhando código que **não existe** em `static/src/*.js`:
  - *card grid* (SUITE 17): `formatMarketPrice`, `formatOfferHashrate`,
    `formatOfferCount`, `computeBestPrice`, `findBestOfferIndex`,
    `filterOffersByProvider`, `renderMarketOfferHtml`, `renderMarketGridHtml`,
    `fmtHashrateThToHps` — operavam no campo `price_btc_per_th_day`, que o
    backend não envia mais.
  - *gráfico antigo* (SUITE 18): `renderMarketTrend`, `getProviderColor`,
    `_providerColors`, `formatTrendLabel`, `buildTrendDatasets` — montavam
    datasets num formato que produção não produz (`(TH/s)`/`(PH/s)` com eixo
    duplo, cor por mapa fixo, rótulo MM/DD HH:mm).

  Passavam sempre e não protegiam nada. O caminho vivo (tabela institucional +
  render cap + BUY afiliado + gráfico 7d de sats/TH/d) segue coberto por
  `tests/e2e/market-affiliate.spec.js` e pelos helpers carregados do fragmento.
- **Prova de dentes**: mutar `_mktRenderCap` no fragmento (deixar de capar as
  50 linhas, regressão do Issue #185) faz o harness falhar
  (`1/1412 TESTS FAILED`); antes da conversão, a mutação passava invisível.
- Contrato do fragmento: um teste novo falha se `45-market.js` deixar de expor
  qualquer um dos 6 helpers puros.

### Alterado — extração do domínio Market para `static/src/45-market.js` (RFC #478 · PR 2, Issue #513)
- O domínio **Market** saiu de `static/src/40-app-logic.js` para o fragmento
  `static/src/45-market.js` (455 linhas): estado do módulo, helpers de preço
  (`_fmtBtcPerTh`, `_mktUsdPerTh`, `_mktSourceLabel`, `_mktBestIndex`), o grid
  institucional (`MKT_RENDER_CAP`, `_mktRenderCap`, `sortMarketVenues`,
  `renderMarketGrid` + `venueFreshness`), `renderMarket`, `initMarketControls`,
  `buildMarketTrendDatasets` e `loadMarketTrend`. `40-app-logic.js`
  12.666 → 12.236 linhas.
- **Correção de premissa do RFC**: a tabela listava o PR 2 como *"orderbook,
  rent offers"* — **não existe orderbook no código**. O domínio real é o grid de
  venues do `/api/market/*` + `market_data.offers` + BUY afiliado + tendência 7d,
  e ele **não é contíguo**: as três regiões estão separadas pelo domínio Admin
  (~1.050 linhas) e por Decision Matrix/Command Center, que **não** foram movidos.
  `_adminLoaded` mora dentro do bloco de estado do market mas pertence ao Admin
  — a fronteira foi por posse do estado, não por adjacência textual.
- **Movimento mecânico provado**: recorte verbatim das três regiões (fidelidade
  byte-idêntica conferida contra o `40-app-logic.js` anterior) e o `static/app.js`
  gerado é uma **permutação** do anterior — 0 linhas perdidas, 25 adicionadas
  (todas de comentário de cabeçalho do fragmento novo). Nenhum id de DOM,
  contrato de fetch, formato de snapshot ou ordem de execução mudou.
- Ordem de execução preservada: as regiões movidas contêm só **declarações**
  (nenhuma lê o estado durante a avaliação do IIFE), e todos os consumidores
  (`render()` no poll, `boot()` no DOM-ready, `_doActivateModule()` na troca de
  aba) rodam depois — então o fragmento entra antes de `50-close.js` sem TDZ.
- Achado registrado (Issue #515): `tests/test_app_js_core.js` ainda **espelha**
  os helpers puros do Market em vez de carregá-los com `loadFragment()`, e
  mantém uma **suíte legada** do card grid que o redesign institucional
  substituiu — o mesmo padrão de drift que escondeu 3 bugs de produção no PR 1.
  Fica para PR próprio.

### Adicionado — postmortem do RFC #478 (Issue #511)
- `docs/rfc/478-postmortem.md` — postmortem da trilha backend (PRs B1–B4) e do
  frontend PR 1/1b: cronologia, tabela de **divergências plano × realidade**,
  achados por PR, controles que funcionaram, os três erros do agente e lições
  acionáveis para os PRs de frontend 2–6. Linkado a partir do RFC.
- Achado de recon registrado no postmortem e no RFC: a descrição do domínio
  **Market** no RFC ("orderbook, rent offers") **não corresponde ao código** —
  não existe orderbook; o cluster real (grid de venues do `/api/market/*` +
  `market_data.offers` + BUY afiliado) está espalhado em 4 regiões disjuntas de
  `static/src/40-app-logic.js`, com o domínio Admin (~1.100 linhas) entre duas
  delas.

### Alterado — `get_db` passa a morar em `services/bootstrap.py` (Issue #508)
- `get_db()` — a conexão SQLite com os pragmas WAL/`synchronous=NORMAL`/
  `busy_timeout` — passa a ser **definido** em `services/bootstrap.py`, o dono do
  bootstrap/schema do SQLite. `services/db.py` vira um re-export: o caminho
  histórico `from services.db import get_db` (~90 usos em rotas, serviços e
  testes) continua devolvendo o **mesmo objeto**. Uma implementação só nos três
  caminhos: `bootstrap` → `services.db` → `app`.
- **Sem ciclo, de propósito**: `doc_feedback`, `conversion` e `beta_analytics`
  importam `services.db` — que re-exporta o `get_db` do bootstrap — então eles
  entram por **import tardio dentro do `init_db()`** (o único lugar que os usa).
  No topo do módulo o grafo fecharia um ciclo na inicialização parcial.
  `tenant`, `error_tracker` e `schema` foram verificados sem dependência de
  `services.db` e seguem no topo. Há teste travando isso no AST.
- O alias morto `DB_PATH = config.DB_PATH` do `services/db.py` saiu (ninguém o
  importava). **Correção de registro**: a premissa anotada na Issue #508 de uma
  duplicata `config.DB_PATH` × `app.DB_PATH` era **falsa** — a linha 27 que
  originou a nota é do `config.py`, e o `app.py` já importa `DB_PATH` de lá
  (com comentário explícito de "single source of truth"). Nada a reconciliar.
- **Achado real do levantamento**: `core/data_layer.py` deriva o próprio caminho
  (`CYPHER65_DATA_DIR` + `war_room.sqlite`), **ignorando** o `DB_PATH` do
  ambiente — e o usa como default de argumento do `__init__`. Hoje o módulo só é
  exercitado por `tests/test_data_layer.py` (sem chamador de produção), então
  ficou fora deste PR para não mudar a semântica dele em silêncio.

### Alterado — extração do bootstrap de DB para `services/bootstrap.py` (RFC #478 · PR B4, Issue #507)
- `init_db()` (576 linhas de DDL: tabelas, ALTERs guardados por
  `PRAGMA table_info` para DBs legados, todos os índices, os pragmas da conexão
  e o carimbo da revisão) e `purge_old()` (retenção de 30 dias + o passe de
  `pool_metrics`) saíram do `app.py` para `services/bootstrap.py`, junto de
  `SCHEMA_VERSION` e `_record_schema_version()`. O `app.py` cai de 9.084 para
  **8.444 linhas**.
- Schema provado **idêntico** antes/depois: dump completo do `sqlite_master`
  (73 objetos, mesmo SQL) e **idempotência** verificada nas duas árvores.
- O `app.py` re-exporta os nomes movidos (mesmo objeto), então `app.init_db()`,
  `appmod.purge_old()` e `app_module.SCHEMA_VERSION` — usados pela suíte —
  seguem válidos, e a chamada de boot `init_db()` continua no lugar, na mesma
  ordem em relação a `ensure_users_schema()`, Sentry e `error_tracker`.
- **Duplicata eliminada**: o `get_db()` do `app.py` era funcionalmente idêntico
  ao de `services/db.py` (mesma leitura de `DB_PATH` no call time, mesmos
  pragmas WAL/synchronous/busy_timeout, mesmo fallback). O `app.py` passa a
  importar o canônico — `app.get_db is services.db.get_db` — e o item "WAL" da
  tabela do RFC vira a remoção de uma segunda implementação em vez de mover
  código.
- Contrato novo: `tests/test_bootstrap_schema.py` (13 testes) — identidade dos
  re-exports, `get_db` de fonte única, ausência de ciclo (AST), schema exato,
  idempotência, carimbo da revisão, tabelas de telemetria delegadas, o boot
  criando o schema no `DB_PATH` do env (contrato do `conftest`) e a retenção de
  30 dias do `purge_old`.
- Achado de fronteira registrado no teste: `devices` e `axe_agent_commands`
  **não** vêm do `init_db` — são criadas pelos registries no boot.

### Adicionado — guard de alvo de patch órfão no CI (Issue #505)
- `scripts/check-monkeypatch-targets.py`: guard **blocking** no job `gate` que
  falha quando um teste patcheia um nome que o módulo alvo **não possui**. Um
  patch só intercepta se o nome for **usado pelo próprio módulo** (o lookup de
  global acontece no dicionário dele) — se o módulo apenas **re-exporta** o
  símbolo, o patch vira no-op silencioso: nada falha, o teste só deixa de
  injetar o fake.
- É a armadilha que o PR B3 (#502) expôs: `tests/test_anti_mock.py` patcheava
  `services.user_polling._fetch_*`, os patches deixaram de interceptar, o
  `_build_snapshot` foi à rede de verdade e caiu no `except`, e as asserções
  continuaram satisfeitas pelos defaults. O guard reproduz esse caso real e
  falha apontando o arquivo e a linha exatos.
- Análise estática (só AST, sem importar o alvo). "Dono" = o módulo define o
  nome **ou** o referencia no corpo; nomes que ele só importa e nunca usa ficam
  de fora. Alvo não resolvido é ignorado (fail-open) e exceções documentadas
  passam com `# orphan-patch-ok: <motivo>`.
- Self-test próprio: `python tests/test_monkeypatch_targets_guard.py` (10
  casos) ou pelos testes do pytest.
- Documentado em `docs/QUALITY.md` e nos comandos rápidos do `AGENTS.md`.

### Alterado — extração da montagem de snapshot para `services/snapshot_assembly.py` (RFC #478 · PR B3, Issue #501)
- `_build_snapshot` (as ~240 linhas que montam o dict consumido pelo painel) e a
  camada de fetch global que a alimenta saíram de `services/user_polling.py` para
  `services/snapshot_assembly.py`: cache global LRU (`_global_cache`,
  `_update_global`, `_cached_user_fetch`), `_get_global`, as constantes de fetch,
  `btc_price_cache`, `_fetch_json`/`_fetch_text`, os 6 fetchers `_fetch_global_*`
  e os per-address `_fetch_user_data`/`_fetch_account`.
- `services/user_polling.py` cai de 1.606 para 1.152 linhas e **re-exporta** os
  24 nomes movidos — `from services.user_polling import _build_snapshot` (o
  contrato que o `app.py` e a suíte usam) segue válido e aponta para o mesmo
  objeto.
- Premissa do RFC corrigida: o B3 estava descrito como extração "de `app.py`" e
  o código vivia em `services/user_polling.py` — o `app.py` apenas importava a
  função. O RFC foi atualizado com a origem real.
- ⚠️ **Alvo de monkeypatch**: o fetch layer agora resolve os nomes nos globals
  de `services.snapshot_assembly`, então `setattr(services.user_polling,
  "_fetch_json", …)` deixou de interceptar. Três arquivos de teste foram
  retargetados — incluindo `test_anti_mock.py`, que passava **vacuamente**: os
  patches não interceptavam mais e o snapshot montado caía no except, com as
  asserções ainda satisfeitas pelos defaults (e indo à rede de verdade).
- Contrato novo: `tests/test_snapshot_assembly.py` (24 testes) — identidade dos
  nomes re-exportados, ausência de ciclo (checada no AST), schema e defaults do
  snapshot, contagem do halving, short-circuit de endereço vazio, e o teste
  **negativo** do alvo de patch (patchear `user_polling` não intercepta).

### Alterado — extração do SSE fan-out para `services/sse.py` (RFC #478 · PR B2, Issue #499)
- O fan-out Server-Sent Events saiu do meio do `app.py`: o registry de clientes
  (`_sse_clients` + lock), o `broadcast_snapshot()` chamado pelo `poll_loop` e a
  rota `GET /api/stream` agora vivem em `services/sse.py` (blueprint `sse_bp`).
  O `app.py` registra o blueprint e re-exporta `_broadcast_snapshot` — o
  `poll_loop` segue chamando o **mesmo objeto**.
- `url_map` provado idêntico (178 regras antes e depois, mesmo path e método) e
  o `import queue` do `app.py` saiu junto — o módulo era o único consumidor.
  Mimetype (`text/event-stream`) e headers (`Cache-Control`, `Connection`,
  `X-Accel-Buffering`) inalterados: o `EventSource` do dashboard não percebe.
- O SSE tinha **zero testes** (a única régua era um navegador). Nasce com
  `tests/test_sse_fanout.py` (11 testes): propriedade do blueprint, headers,
  identidade do `_broadcast_snapshot` re-exportado, sem import circular,
  entrega do payload, `default=str`, evicção de cliente com fila cheia e
  keepalive do gerador.
- Cobertura: nada a acrescentar no `--cov` — o pacote inteiro já é medido por
  `--cov=services`, então o módulo novo nasce dentro da régua. O `--cov`
  explícito por arquivo só é necessário para módulos fora de `services/`
  (como `routes.admin_routes` no PR B1).

### Segurança — `/api/admin/sessions` sem gate expunha sessões de todos os tenants (Issue #496)
- A rota era a **única** `/api/admin/*` sem o gate compartilhado: respondia a
  qualquer origem e devolvia `sessions[].to_dict()` de **todos** os tenants
  (incluindo `btc_address` e `tenant_id`), além do bloco de observabilidade do
  pool. Foi encontrada pelo contrato do PR B1 (Issue #495), que fixou o
  conjunto de rotas sem gate.
- Agora aplica `_admin_request_allowed()` como as rotas vizinhas: localhost sem
  credencial declarada (dev / Render Shell) continua liberado, origem remota
  exige `X-API-Key` válida, e credencial declarada e errada falha fechada
  (matriz #481).
- **Sem impacto no painel admin**: `fetchAdminData()` já busca as 8 rotas admin
  num único `Promise.all` e trata 403 no lote inteiro — o comportamento visível
  não muda.
- O contrato `tests/test_admin_routes_blueprint.py` passa a exigir
  `KNOWN_UNGATED == set()`: rota nova `/api/admin/*` sem gate quebra o CI.

### Alterado — extração do admin gate + rotas /api/admin/* (RFC #478 · PR B1, Issue #495)
- O gate compartilhado `_admin_request_allowed` e as **10 rotas `/api/admin/*`**
  saíram de `app.py` para `routes/admin_routes.py` (blueprint `admin_bp`,
  `url_prefix="/api/admin"`). É o primeiro PR da trilha backend do RFC #478 —
  extração mecânica, **sem um único comportamento novo**.
- `app.py` cai de 9.448 para 9.137 linhas (300 linhas movidas verbatim —
  mesmos corpos, mesma formatação). O gate fica re-exportado
  (`from app import _admin_request_allowed` segue válido) e o `SessionManager`
  do boot é injetado via `init_admin_routes()` — sem import circular.
- `url_map` provado idêntico antes/depois: mesmos paths, mesmos métodos, mesma
  decisão de gate (as 9 rotas gateadas continuam negando origem remota sem key
  e credencial declarada e errada — matriz #481).
- Cobertura preservada: `--cov=routes.admin_routes` entra no CI para as linhas
  movidas não saírem da régua — o conjunto medido é o mesmo do master, então o
  TOTAL (83,99%) não melhora por subtração.

### Adicionado — build determinístico do app.js + extração do core (Issue #489)
- `static/app.js` (13k linhas num IIFE único) passa a ser **artefato gerado**
  por `scripts/build_app_js.cjs`: concatenação na ordem do MANIFEST, Node puro
  e sem dependências (Opção A do RFC #478). A fonte vive em `static/src/*.js`.
- O CI roda `node scripts/build_app_js.cjs --check` e **bloqueia o merge** se o
  artefato divergir das fontes; editar `static/app.js` à mão não passa. Um
  fragmento órfão em `static/src/` falha o build em vez de nunca chegar ao
  navegador e escapar dos guards (DOM/XSS, tokens-hex, a11y).
- Zero mudança de comportamento: mesma tag `<script>`, mesma ordem lexical dos
  blocos (hoisting/TDZ intactos), mesmos ids, rotas e contratos de fetch.

### Corrigido — formatters do dashboard exibiam dado errado ao operador (Issue #490)
- `fmt.age` dividia por **86400** na branch de horas: toda idade entre 1h e 24h
  renderizava `0h ago` (último bloco, last share, linha de tempo, eventos,
  alertas, last-seen do fleet). Agora 1h→`1h ago`, 23h59→`23h ago`.
- `fmt.secsToHuman(null)` estourava `TypeError` (`isFinite(null)` é `true`, o
  guard não pegava) e `fmt.pct(null)` devolvia `0.00%` — dado ausente
  apresentado como medição real, contra o princípio de honest telemetry.
- Causa-raiz comum: `isFinite(...)` global coage (`null`, `''` e `' '` passam).
  Um guard único (`_finiteNum`) aceita só número real ou string numérica
  não-vazia e devolve em-dash para o resto; saída para números válidos
  permanece idêntica.
- O ledger de drift (`KNOWN_FMT_DRIFT`) e o espelho do `fmt` do harness foram
  removidos: a suíte passa a ter uma única implementação — a do fonte.

### Segurança — rollback cifrado e confirmado de pool (Issue #471)
- Antes de um `update_pool` físico, telemetria recente deve comprovar a
  configuração anterior completa; sem alvo ou `SECRET_KEY` estável, nenhum
  comando é enviado ao ASIC.
- O alvo anterior fica cifrado, vinculado a tenant/device/operação, expira e é
  removido; endpoint e worker não entram em resposta, audit ou log.
- Rollback exige novo preflight, confirmação humana one-time e idempotência;
  um claim atômico impede segundo dispatch, e telemetria posterior reconcilia
  o retorno pelo hash esperado.
- O contrato foi comprovado apenas em testes herméticos. O Gate 095 permanece
  parcial e a execução física continua condicionada à matriz #386.

### Adicionado — dry-run de pool com DNS, SSRF e Stratum V1 (Issue #469)
- `update_pool` valida configuração completa, resolve DNS uma vez, aplica a
  política de destino público/portas e exige um subscribe V1 saudável antes de
  retornar dry-run positivo ou emitir confirmação humana.
- Respostas omitem endpoint, IP, worker e payload remoto; falhas de configuração,
  DNS, SSRF, timeout, TLS e protocolo usam somente códigos controlados.
- O caminho continua read-only: não autentica worker, envia share ou chama o
  adapter do ASIC; pools locais e portas customizadas permanecem bloqueados.

### Corrigido — instalação Playwright resiliente a race do índice APT (Issue #467)
- Os jobs frontend e E2E reutilizam um instalador que isola temporariamente o
  repositório Chrome não utilizado e repete somente a etapa idempotente de
  dependências do sistema, com cinco tentativas e backoff limitado; as fontes
  são restauradas e falhas persistentes continuam bloqueando o merge.
- Self-test hermético comprova recuperação transitória, exaustão fail-closed,
  erro do browser sem retry indevido, isolamento/restauração da fonte externa
  e rejeição de configuração inválida.

### Adicionado — rollout canário fail-closed de pool (Issue #465)
- Máquina de estados imutável libera primeiro o canário obrigatório e depois
  lotes determinísticos, sem executar rede, retry ou comando físico.
- Todos os devices do lote ativo exigem reconciliação explícita; qualquer
  `failed` ou `unknown` interrompe a frota antes do próximo lote.
- Planos limitam devices e batches e referenciam a configuração somente por
  SHA-256, sem endpoint, worker ou credencial.

### Segurança — fuzzing e red team do conector Stratum V1 (Issue #463)
- Validador público e limitado rejeita IDs booleanos, JSON duplicado, shapes de
  subscribe inválidos, extra nonce malformado e respostas acima de 64 KiB.
- Corpus determinístico cobre 6.000 payloads arbitrários/estruturados sem
  exceção não controlada; ataques herméticos cobrem SSRF e DNS rebinding.
- O conector revalida escopo do IP e metadados da resolução antes de criar o
  socket, inclusive contra objetos tipados forjados com destino privado.

### Adicionado — compatibilidade ASIC e failover ordenado (Issue #461)
- Perfis tipados de device e pool avaliam somente estados efetivos do grafo de
  capabilities; ausência ou evidência não suportada falha como incompatível.
- Política pura e limitada preserva o pool ativo saudável ou escolhe o menor
  priority de forma estável, respeitando cooldown, saúde e compatibilidade.
- A decisão não resolve DNS, usa credenciais, abre conexão ou altera ASIC; a
  integração com comandos físicos permanece bloqueada pelos gates 092–096.

### Adicionado — grafo de capabilities e classificação por evidência (Issue #459)
- Grafo imutável e limitado resolve provenance, dependências ausentes,
  conflitos e ciclos sem executar I/O ou carregar payload remoto.
- Fingerprinting de provider e classificação de chain exigem dois sinais
  fortes e independentes; evidência fraca, inferida ou conflitante fica unknown.
- O probe V1 pode alimentar apenas a capability Stratum comprovada, sem inferir
  provider, chain, autenticação, payout ou compatibilidade física.

### Segurança — `js-yaml` transitivo corrigido (Issue #457)
- Lockfile mobile resolve `js-yaml` 3.15.2 no Jest/Istanbul, corrigindo o
  advisory HIGH `GHSA-2883-xcg3-v3hh` sem override major.
- Instalação limpa, árvore npm, audit, Expo Doctor 21/21, Biome, TypeScript,
  91 testes Jest e exports iOS/Android/Web permanecem verdes.

### Adicionado — probe Stratum V1 fixado ao destino validado (Issue #455)
- Resolver de passagem única aplica a política SSRF a todas as respostas DNS;
  o conector usa diretamente o IP aprovado, sem uma segunda resolução.
- Probe somente leitura envia apenas `mining.subscribe`, limita timeout,
  tentativas e resposta, preserva SNI/validação TLS e retorna erros sanitizados.
- Laboratório virtual stateful comprova V1, latências, timeout, JSON inválido e
  resposta excessiva sem autenticar worker, enviar share ou alterar ASIC.

### Documentação — walkthrough do operador para Flyovers (Issue #452)
- Novo roteiro bilíngue conecta arquitetura, dor operacional, percurso inicial
  de 15 minutos e benefícios permitidos sem inventar telemetria ou retorno.
- Quickstart e runtime map registram os limites fail-closed: advisory apenas
  audita e navega, comandos físicos exigem dry-run e confirmação humana, e
  checkout permanece indisponível até a reconciliação BTCPay.
- Teste de contrato mantém módulos, headings e sentenças de segurança alinhados
  com a narrativa usada no walkthrough.

### Corrigido — uuid transitivo do toolchain Expo (Issue #393)
- Override `uuid@11.1.1` no `xcode` usado por `@expo/config-plugins`.
  Override `decode-uri-component@0.5.0` elimina os quatro advisories restantes
  de `query-string` / React Navigation sem downgrade major. `npm audit`: 0.
- Expo atualizado para `57.0.21`, mantendo Expo Doctor 21/21 e builds iOS,
  Android e web verdes. Sem `--force`.

### Corrigido — mutation score mobile acima do baseline (Issue #439)
- Stryker nos hooks/services: **25,56% → 47,56%** (115→214 mutantes mortos;
  335→236 sobreviventes; 450 mutantes; zero erros/timeouts).
- `useAuth` 77%, `biometrics` 74%, `offline` 78%, `useBatteryMode` 61% e
  `useSnapshot` 68%. Threshold incremental: `break: 40` / `low: 40` /
  `high: 80`.
- Sem excluir arquivos nem enfraquecer mutadores.

### Corrigido — Knip mobile reconcilia dependências e exports (Issue #440)
- `expo-constants` passa a ser dependência direta (já era importada).
- `@babel/core` permanece como peer do Babel/Jest; `expo-updates` não é
  usado e fica ignorado. `config/api-url.d.ts` descreve o loader CJS.
- APIs de offline, push, auth, biometria e device history ganharam testes
  comportamentais. Exports de tipos internos e o default duplicado de `theme`
  foram removidos. `npx knip` exit 0.

### Corrigido — flakes residuais da suíte E2E completa (Issue #450)
- Testes Braiins e Rentals bloqueiam o service worker, evitando reload por
  `controllerchange` durante navegação controlada pelo Playwright.
- O contrato visual de LEASE usa snapshot determinístico; disponibilidade de
  venues externos permanece responsabilidade dos testes de integração.
- A suíte atual tem 290 casos: a #438 consolidou um contrato duplicado de
  `detect-endpoint` em um teste fail-closed, executado nos dois viewports.

### Corrigido — suíte e2e local alinhada ao fail-closed (Issue #438)
- `POST /api/axe-fleet/devices` registra primeiro e limita o probe de firmware
  a 1s; TEST-NET/loopback não são sondados (SSRF fail-closed).
- WHAT-IF deixa de renderir probabilidade a partir de `netDiff` não-finito.
- Specs e2e passam a exigir consentimento no ARMAR, 400 no detect inválido,
  confirm no Resume, sidebar mobile aberta e KPI de analytics sem exigir top.

### Corrigido — runner E2E falha se a porta já estiver ocupada (Issue #437)
- `run-e2e.sh` sonda `127.0.0.1:$PORT` (padrão 8765) antes de spawnar o Flask.
  Um listener antigo que já responda 200 em `/api/healthz` deixa de sequestrar
  a suíte.
- A mensagem inclui PID/comando via `lsof` quando disponível. O runner nunca
  mata o processo ocupante: pare-o ou rode `PORT=<livre> bash run-e2e.sh`.
- Override explícito de `PORT` continua prevalecendo; o guard só valida a
  porta escolhida.

### Corrigido — recomendações do Auto-Pilot estritamente consultivas (Issue #433)
- Aceitar uma recomendação não executa mais restart/pause, não altera a
  blacklist e não abre uma compra; apenas registra a intenção no audit log.
- A resposta preserva os campos legados e passa a declarar explicitamente
  `advisory_only`, `executed: false` e o módulo seguro de revisão.
- A interface usa CTAs de revisão, mostra estado de registro e encaminha para
  Fleet ou Rentals, onde continuam valendo dry-run, confirmação e proteções.

### Corrigido — árvore Stryker/Babel válida no mobile (Issue #431)
- Stryker Core e Jest Runner foram alinhados e fixados em 9.6.1, versão que
  preserva Babel 7 e a compatibilidade com Expo 57/Metro/Jest.
- A opção de timeout usa o nome suportado `timeoutMS`; o glob de exclusão
  redundante foi removido do conjunto de arquivos já restrito a hooks/services.
- O downgrade deliberado da linha 10 evita peers Babel 8 inválidos sem alterar
  dependências ou comportamento de runtime do aplicativo.

### Corrigido — Command Center operacional e Rentals recuperável (Issue #424)
- O Command Center deixa de emitir ofertas afiliadas e não abre URLs externas;
  seus cards agora encaminham apenas para diagnósticos internos.
- Contagens desconhecidas usam travessão no primeiro paint, evitando zeros
  falsos antes do primeiro snapshot real.
- Falhas HTTP, de rede ou de payload em Rentals mostram estado de erro
  explícito, sem estimativas, com retry acessível e estado de carregamento.

### Corrigido — patches compatíveis e triagem mobile (Issue #393)
- Expo SDK 57 foi atualizado somente dentro da faixa recomendada pelo Expo
  Doctor: Expo 57.0.20, Metro Runtime 57.0.15, Notifications 57.0.17 e Secure
  Store 57.0.3.
- `@xmldom/xmldom` transitivo subiu para 0.9.12, removendo o advisory corrigível
  sem `--force`; Expo Doctor volta a 21/21.
- A suíte Jest mobile roda em série para evitar contenção entre workers no
  runner compartilhado; timeouts e assertions permanecem inalterados.
- Permanecem 15 findings moderate transitivos sem correção compatível, ligados
  a Expo/Xcode/UUID e React Navigation/query-string. O downgrade automático
  para Expo 46/React Navigation 3 segue rejeitado e o risco está documentado.

### Corrigido — estabilidade e diagnóstico do boot E2E (Issue #430)
- O servidor com banco temporário do `run-e2e.sh` usa o mesmo teto de 10.000
  req/min do CI, evitando HTTP 429 em suítes longas de desktop + mobile sem
  desativar o limiter.
- `CI=false` agora é interpretado como falso de verdade e executa sem retry;
  `CI=true` preserva um retry e o bloqueio de `test.only`.
- Dashboard e modais validam HTTP 200 antes de esperar `#app-shell`, expondo
  imediatamente 429/5xx em vez de reportar um timeout DOM enganoso.
### Corrigido — AxeOS POST/PATCH fail-closed em HTTP de erro (Issue #422)
- 4xx/5xx viram `AxeOSConnectorError` (antes estouravam `HTTPError` no Flask).
- Corpo não-JSON em 2xx continua ACK de texto do firmware.
- Falha de audit log de comando deixa de ser `except: pass`.

### Corrigido — pico de hashrate do Auto-Pilot isolado por tenant (Issue #423)
- `proximity_history` passa a registrar `tenant_id`; bancos legados recebem a
  coluna de forma idempotente e suas linhas existentes ficam atribuídas ao
  tenant operador `default`, sem perda de histórico.
- O pico de sete dias usado pelo modo advisory e pelo snapshot é consultado
  apenas no tenant resolvido. Sem histórico próprio, o valor é `0` e nenhuma
  recomendação de queda é inventada a partir dos dados de outro usuário.
- Índice `(tenant_id, ts)` preserva o custo das consultas por janela; testes
  cobrem migração, isolamento A/B, ausência de dados e fechamento de conexão.

### Corrigido — SafetyEngine no plano da frota e cooldown persistente (Issue #415)
- Comandos `axe-fleet` (restart/identify/pause/resume/config) passam por
  `SafetyEngine.validate_command` antes do dispatch.
- Cooldown de restart persiste em SQLite e sobrevive a reboot do processo.
- Overclock/pool exigem telemetria fresca; `pause` continua permitido a quente.
- `min_hashrate` default 0 deixa de bloquear miner idle; o engine lê `hashrate_hs`.
- Automação chama `adapter.execute_command(command, parameters)` e não audita
  `success: false` como EXECUTED.

### Corrigido — linguagem de probabilidade e economia não-promissória (Issue #378)
- Rótulos de prazo/progresso foram substituídos por **model mean interval**,
  **session P(≥1) estimate**, **best-share/target ratio** e **modeled cost
  threshold**, preservando chaves de API e IDs DOM legados.
- Tooltips e payloads agora expõem fonte, janela, unidade, premissas e avisos de
  independência; cenários econômicos deixam explícito que não prometem lucro.
- “Quantum Lock” virou **session work signal — heuristic** e alertas de “hot
  streak” deixaram de incentivar ação com base em shares passados.
- Corrigida a fórmula de probabilidade de exceder um threshold de share para
  `1-(1-1/(difficulty·2³²))^N`, com teste do vetor `lambda=1`.
- Auditoria e testes de compreensão: `docs/PROBABILITY_LANGUAGE_AUDIT.md` e
  `tests/test_probability_language.py`.

### Alterado — mobile: Expo SDK 57 e gates reproduzíveis (Issue #379)
- Atualização compatível para Expo SDK 57, React Native 0.86 e React 19, com
  assets reais do produto e configuração moderna de splash screen.
- CI mobile agora bloqueia em Expo Doctor, vulnerabilidades high/critical,
  Biome sem warnings, TypeScript, Jest e export dos bundles iOS, Android e web.
- O handler de notificações preserva alerta, som e badge e também declara os
  campos de banner/lista exigidos pelo SDK atual.
- Documentação mobile registra requisitos de runtime e distingue export de
  bundle de compilação nativa assinada.

### Adicionado — disclaimer no módulo Probability — risco regulatório (Issues #347/#350)
- **Disclaimer visual** no bloco Block Hunt: box amber "Estes valores são
  estatísticos e não representam previsão nem garantia de resultado... Mining é
  probabilístico — a sorte real pode diferir significativamente das estimativas."
- **Callout warn** na seção docs Probability do dashboard.
- CSS `.prob-disclaimer` consistente com `.doc-callout--warn` do design system.

### Adicionado — EULA + consent explícito para Auto-Pilot (Issues #348/#350)
- **Modal ARMAR**: checkbox "Li e aceito os termos" obrigatório antes de habilitar
  o botão ARMAR — aviso de que comandos são executados em hardware real.
- **Modal AUTONOMO**: checkbox equivalente com aviso de risco para execução autônoma.
- JS: `_checkArmReady()` e `_checkAutoReady()` verificam consent + text input.
- Botão desabilitado até AMBOS (consent checked + "ARMAR"/"AUTONOMO" digitado).
- CSS `.ap-arm-modal__eula` amber box consistente com o design system.

### Adicionado — ICPs, Beta Program e script de trial keys (Issue #349/#350)
- **docs/ICPS.md**: 3 perfis de cliente (Solo Miner, Small Farm, Rental Op) com
  dor, oferta, mensagem comercial, canal, ticket e critérios de validação.
- **docs/BETA_PROGRAM.md**: programa de beta com regras, EULA summary, instruções
  de trial key (3 métodos) e métricas de rastreamento.
- **scripts/issue-beta-trial.sh**: emissor de N trial keys com expiração, health
  check prévio, suporta --count/--days/--email/--url/--api-key.

### Adicionado — cap de render no HASH MARKET (top-50 do sort) com nota honesta (Issue #185)
- **`MKT_RENDER_CAP = 50`** no `renderMarketGrid()`: o DOM renderiza só as **top-50
  venues do sort atual** (helper puro `_mktRenderCap`, aplicado DEPOIS do sort) —
  a lista pode crescer sem travar o render. O badge de contagem segue honesto
  com o **total real** (cap é só de render).
- **Nota visível** `#mkt-render-cap-note` quando o cap ativa: *"mostrando as 50
  melhores venues do sort atual — N venues no total (use sort/filtro para
  refinar)"* — nada some silenciosamente (mesmo padrão da nota "sem data" do
  audit admin, #205). CSS espelha `.admin-audit__note`; hidden por padrão.
- **Chart.js under-demand**: critério da issue já satisfeito pelo `defer` no head
  (Issue #186) — sem custo de parse no boot; quem usa Chart guarda com
  `typeof Chart === 'undefined'` e re-renderiza no próximo poll.
  `prefers-reduced-motion` intacto (sem mudança de motion).
- Testes: JS core +12 asserts (`mktRenderCap` null / <cap / 60→50 / ordem); e2e
  `market-affiliate.spec.js` +1 caso (60 venues → 50 linhas + nota visível nos
  dois viewports). Bump CDN-safe `app.js` (render do mercado).

### Corrigido — run-e2e.sh: health-check usa /api/healthz com 200 explícito e janela de 30s (Issue #336)
- **Boot frio (~16s) estourava a janela de 15s** do harness: `bash run-e2e.sh
  --file=...` falhava com "Flask server failed to start" apesar do boot normal.
- **3 problemas corrigidos**: endpoint pesado `/api/snapshot` → `/api/healthz`
  (leve, isento do rate limiter); `curl -s` sem status → `-w '%{http_code}' ==
  200` explícito (HTTP 500 não passa mais como "ready"); janela 15s → **30s**
  (alinhada ao `check_frontend.sh`) + erro claro com tail do log se estourar.
- Validação: `bash run-e2e.sh --file=admin-audit.spec.js` verde em boot frio
  (10/10, chromium + mobile-chrome).

### Alterado — docs: README com contagens/gate reais + seção BTC; DATA_MODEL com ledgers (Issue #333)
- **README**: badge corrigido para **2651 pytest + 1401 JS core** (medido; era
  1878 + 1261), `--cov-fail-under` **65** (gate real do CI, era 45), multi-tenant
  "1000+ tenants" (isolamento JWT é por tenant, não users) e `/api/v1/status`
  confirmado. Nova seção **R2 — Bitcoin channel (off-by-default)** com as env
  vars reais de `services/btcpay.py` (BTCPAY_* / PAYMENT_BTC_ADDRESS /
  LN_INVOICE_ENDPOINT) e o 503 sem config (linka com a Issue #330 de ops).
- **DATA_MODEL.md v1.1**: nova seção **9. LEDGERS & PAYMENTS** com os schemas
  reais — `donations`, `pro_licenses` (sources `manual`/`lemon_squeezy`/
  `btcpay`/`webln`), `btcpay_invoice_plans`, `processed_invoices`,
  `conversion_events`, `subscription_events`, `audit_logs` + nota de
  `schema_version`.

### Adicionado — mobile: theme.ts com a paleta RN (149 hex → 0) e guard vira GATE (Issue #239)
- **`mobile/src/theme.ts`** (novo): 26 tokens tipados (`as const`) espelhando o
  DSv2 web — App.tsx + 6 componentes + 9 screens importam o theme; **149 hex
  hardcoded → 0** fora do theme.
- **Guard `check-tokens-hex.sh`**: o scan do mobile virou **GATE** (exit 1 quando
  um hex fora do theme aparece; era INFO não-bloqueante). `theme.ts` é excluído
  do scan (fonte dos tokens, simétrico ao `style.css` no web). Self-test +2 casos
  (hex fora do theme → exit 1; só theme → exit 0) — 10/10.
- Validação: typecheck ✓, jest 7/7 (20 tests) ✓, guard exit 0 ✓, pipeline
  frontend verde ✓.

### Corrigido — audit admin: buckets semanais contam ts≤0 em "sem data" + meta corrompido vira null (Issue #205)
- **Buckets semanais**: `buildAdminAuditWeekly` não dropa mais decisões com
  `ts≤0`/nulo silenciosamente — contabiliza em `withoutDate` e o gráfico do
  admin mostra a nota visível **"N decisões sem data (ts inválido) fora do
  gráfico semanal"** (`#admin-audit-note`). Honest telemetry: dado nunca some
  sem aviso.
- **`meta` corrompido**: `/api/share_timeline` degrada para `null` +
  `log.warning` (antes a string crua vazava no payload; o evento continua
  renderizando).
- Testes: JS core +1 (`withoutDate` conta `ts<=0`/`null`/garbage), pytest +1
  (meta corrompido → null + warning via caplog), e2e `admin-audit.spec.js` +1
  caso (decisões `ts: 0`/`null` → nota visível com "2 decisões sem data" e
  linhas ainda renderizam com data `—`).

### Corrigido — RENTALS: histórico real visível + veredito de performance por aluguel (UX do operador)
- **Bug de descoberta**: o painel RENTALS abria na aba "Active" (0 rentals ativos) e escondia o
  histórico atrás do chip History — parecia que a conta não tinha nada. Agora o painel **cai
  direto na primeira aba com dados** (History quando Active está vazio; clique manual sempre vence).
- **Credenciais nunca mais silenciosas**: cards do strip mostram **🔑** (tooltip) quando a
  credencial do provider falta e **⚠** com o erro real quando o fetch falha — nunca um 0/—
  enganoso. O empty state mostra o erro do provider e um CTA **⚙ OPEN SETTINGS** que abre o modal.
- **Performance por aluguel** (decidir onde alugar de novo): o detail agora traz um veredito —
  **PERFORMANCE** (% do hashrate anunciado, verde ≥95% / âmbar 80–95% / vermelho <80%),
  **AVG/ADVERTISED**, **COST** (sats/TH/h efetivo) e **DELIVERED** (TH·h totais entregues).
- **Settings didáticos**: hints novos em `mrr_api_key`/`mrr_api_secret` (onde criar:
  miningrigrentals.com → My Account → API Access) e o hint do Braiins agora diz que o owner
  token pode ser **regenerado se perdido** (era mostrado 1x no registro).
- **Verificações ao vivo**: MRR testado com as credenciais reais (34 rentals; detail/graph/log
  OK) e endpoints Braiins `/contract`/`/contract/active` confirmados (401 só sem a key).
- E2E: 3º teste novo (aba Braiins sem key → CTA → Settings modal) + asserts de auto-aba History
  e banner de performance (4 células). Bumps CDN-safe `app.js?v55→v56`, `style.css?v51→v52`.

### Adicionado — Webhook unificado Discord/Telegram para alertas (notifier centralizado)
- **`send_webhook_notification()`** em `services/push_notifier.py` (novo): auto-detecta o
  canal pelo URL — **Discord** (embed rico com cor por severidade, fields de
  severity/category/worker/address, footer com timestamp UTC), **Telegram** (mensagem
  MarkdownV2 com escape de caracteres especiais via `_tg_escape` e `chat_id` lido do
  query string) e **fallback genérico** (payload JSON legado `cypher65_war_room_alert`).
  Nunca lança — todo erro vira log + `False`.
- **Gate de severidade com fonte única**: o rank `INFO < WARN < CRIT` (default WARN)
  antes vivia duplicado em `app.py` e `services/polling.py`; agora o `AlertEngine` ganhou
  `webhook_callback` + `dispatch_webhook()` (mesmo contrato do `push_callback`) e o
  `app.py` injeta `_webhook_dispatch` que lê `webhook_url`/`webhook_min_severity` dos
  settings. O bloco inline de POST do `polling.py` foi removido — **um único caminho de
  disparo** (engine + poll loop) sem dedup duplicado.
- Testes em `tests/test_push_notifier.py`: payloads Discord/Telegram/genérico, escape
  MarkdownV2, threshold de severidade e integração do `AlertEngine.dispatch_webhook`.

### Adicionado — Workers idle (hr=0) no dashboard + histórico por device com Chart.js (Fleet)
- **Idle workers**: quando TODOS os workers reportam hashrate 0, o `_do_poll` agora
  seleciona o primeiro worker como primário em vez de deixar o snapshot em branco — o
  dashboard mostra **IDLE** (nunca mais OFFLINE falso para wallets com histórico de
  mineração) e continua surfacing `bestDifficulty`/`lastSubmission`/`uptime`. UI: pill de
  status `IDLE`, métrica com classe `metric__value--idle` e legenda "connected · no
  shares", e o contexto do AI Operator segue o mesmo estado.
- **História do device (Phase C)**: novo `GET /api/axe-fleet/devices/<id>/history`
  (`limit` opcional, default 120) devolve pontos `{ts, hashrate, temperature,
  efficiency_jth, fan_rpm, power_watts}` reutilizando a série `get_telemetry_chart_data`;
  eficiência derivada on-the-fly quando o firmware não reporta. O painel de detalhe do
  device renderiza **gráfico multi-linha** (HR TH/s no eixo esquerdo, Temp °C + Eff J/TH
  no direito, tooltip index-mode) com contagem de pontos.
- Bumps CDN-safe `app.js?v55` / `style.css?v51`. Endpoint testado (auth, tenant, limit)
  em `tests/test_axe_routes_integration.py`.

### Adicionado — HashratePulse Enterprise: grid institucional de venues no HASH MARKET
- **`snapshot_enrichment`** agora computa a visão institucional (`regime`, `snapshot`,
  `venues`, `notes`) a partir de TODAS as offers do market via
  `compute_institutional_view` e a anexa ao `market_data` — nos caminhos fresh, cached
  e loading (consistente com os highlights).
- **UI**: o grid de cards virou **tabela de venues** (`#mkt-table`): venue, regime,
  spread, tier, notes, badge de best-price, chips de filtro por provider e o CTA
  afiliado (BUY) da Decision Matrix. Guard de retry quando o DOM ainda não parseou
  (CDN do Chart.js bloqueando o `<head>`).
- **Debuggability**: falha no cálculo de profitability agora loga **traceback completo**
  (antes só a mensagem) — cold-server vira diagnóstico acionável.
- E2E: `dashboard.spec.js` + `market-affiliate.spec.js` reescritos para asserir a tabela
  institucional (linhas de venue / empty state agnóstico a dados).

### Corrigido — E2E: sidebar off-canvas inalcançável no viewport mobile (375px)
- **Bug real nos specs** (falhas pré-existentes): no breakpoint ≤768px a sidebar é um
  drawer off-canvas (`translateX(-100%)`) que precisa ser aberto via
  `#sidebar-mobile-toggle` — `docs-autocomplete.spec.js` e `alert-center-tabs.spec.js`
  clicavam direto em `.sidebar__link` e estouravam timeout. O app estava correto
  (design responsivo); os **testes** é que não abriam o menu.
- Fix: helper `ensureSidebarOpen()` (mesmo padrão do `dashboard.spec.js` — no-op em
  desktop, onde o toggle é invisível) antes de cada navegação.
- Validação: 6/6 mobile + 6/6 desktop; bloco de 7 specs no mesmo servidor 33/33.

### Adicionado — Docs: busca com autocomplete (auditoria UX · Módulo_09)
- **Dropdown de sugestões** no campo de busca do módulo Docs (`#docs-search-suggestions`):
  ao digitar, as 6 seções mais relevantes aparecem com **título + snippet** da região
  do match e o termo destacado em `<mark>` (âmbar). Ranking honesto: hit no **título**
  vale mais que hit só no corpo (posições anteriores também vencem).
- **Navegação por teclado**: ↓/↑ movem o cursor (estado `active` visível), **Enter** abre
  a seção selecionada (`scrollIntoView` + destaque do link no índice), **Escape** fecha
  o dropdown. Mouse: hover move o cursor e `mousedown` abre — o `blur` nunca engole o
  clique. Sem match → estado vazio honesto ("no matches for …"), nunca sugestão velha.
- **Acessibilidade**: `role="combobox"`/`listbox`/`option` + `aria-expanded`/`aria-selected`.
- **Helpers puros** `docsBuildIndex/docsSearchSuggestions/docsSnippet/docsHighlight` em
  `static/app.js` espelhados em `tests/test_app_js_core.js` (SUITE 34, 19 asserts): ranking
  título>corpo, cap de limite, janela de snippet com elipses, highlight case-insensitive
  com escaping HTML.
- **Bug pré-existente corrigido no caminho** (achado pelo E2E): o botão ✕ de limpar busca
  usava `style.display = ''` que remove o inline style e restaura o `display:none` do CSS
  — o botão **nunca ficava visível**. Agora usa `display:block` (span vira flex-item).
- **E2E** `tests/e2e/docs-autocomplete.spec.js` (4 testes): sugestões com highlight, teclado
  ↓+Enter navega, Escape fecha + clear restaura as seções, estado vazio. Bumps CDN-safe
  `app.js?v54` / `style.css?v50`.

### Adicionado — Probability: slider WHAT-IF de dificuldade (auditoria UX · Módulo_05)
- **Simulador "e se a dificuldade subir X%?"** no painel Block Hunt (`data-module="probability"`):
  slider de −50% a +100% que recomputa **na hora** o impacto em P(block)/share,
  expected time, distance e cumulative P — sem tocar no snapshot ao vivo.
- **Matemática honesta**: dificuldade ↑ → P(block)/share ↓ (inversa, p = bestDiff/diff);
  expected time e distance escalam linearmente (Poisson: E[t] = diff·2³²/hashrate);
  cumulative P é re-derivado do p deslocado × shares da sessão. Sem dados base,
  células mostram em-dash (estado vazio honesto), nunca valor fabricado.
- **Pure function** `simulateDifficultyShift(base, pct)` em `static/app.js` — o
  `renderBlockHunt` captura os valores do snapshot atual em `_bhBase` a cada poll,
  então o slider preserva a posição do operador e re-renderiza com dados frescos.
  Espelhada em `tests/test_app_js_core.js` (SUITE 33, 19 asserts): shifts +10%/−25%/0%,
  fallback de pBlock sem bestDiff, estado vazio.
- **CSS** `.bh-whatif*`: slider estilo terminal (thumb roxo com glow, faixa cyan→purple),
  badge `badge--purple` com o shift %, grid de 4 células (2 colunas no mobile).
- **E2E** `tests/e2e/probability-whatif.spec.js` (3 testes): render do slider+badge+reset,
  drag live (badge + célula P(block) estritamente menor com shift maior), shift negativo
  e reset → 0%. Bumps CDN-safe `app.js?v53` / `style.css?v49`.

### Fechado — Hash Market: gráfico 7d por provider (backlog da auditoria UX)
- **Verificação de ponta a ponta**: o pipeline já existia e estava vivo —
  `persist_market_history` roda nos 2 pontos de fetch (rota `/api/hashrate-market`
  + warm-up de 5min) e a tabela real tinha 965 rows braiins/nicehash/parasite,
  178 mrr (o legado kissmyhash parou de persistir no dia da remoção — correto).
  O gráfico per-provider já era servido por `/api/market/trend` e renderizado
  pelo `loadMarketTrend()` lazy (Chart.js multi-line + legend + null-gaps).
  O gap real era **zero cobertura**: `/api/market/trend` e `/api/market/history`
  (série flat que o mobile consome) não tinham NENHUM teste.
- **Backend**: 6 testes novos em `TestApiMarketTrendAndHistory` — agregação por
  provider com ordem ts asc, cutoff de 7d (trend) / janela `hours` (history),
  conversão TH→PH (×1000), e asserts **herméticos** (escopados ao provider
  distintivo `utrend-*`, já que testes anteriores do arquivo persistem
  providers reais via `/api/hashrate-market` com offers mockadas).
- **Frontend**: lógica pura do chart extraída para `buildMarketTrendDatasets()`
  (providers → `{times, labels, datasets}` com gaps null por provider e
  conversão BTC/TH/d → sats/TH/d ×1e8) e refatorado o `loadMarketTrend` para
  usá-la; badge agora mostra **frescor honesto** (`N providers · HH:MM` via
  `updated_at` real do endpoint) e estado vazio explica que o histórico é
  persistido a cada fetch (warm-up 5min) em vez de silêncio.
- **Filtro de atividade de 48h no `/api/market/trend`** (pós-review): provider
  sem cotação há >48h (ex.: kissmyhash, removido do pipeline mas com rows
  legados dentro da janela de 7d) é **descartado** do chart de comparação —
  a linha morta não infla mais o badge "N providers" nem engana o operador.
  Teste de regressão novo (`test_trend_drops_provider_inactive_48h`).
- **JS**: SUITE 32 (13 asserts do `buildMarketTrendDatasets` — união de ts,
  gaps null, conversão de sats, empty). Bump CDN-safe `app.js?v51→v52`.

### Adicionado — Quick Wins da auditoria UX (KPIs navegáveis + preview/teste de webhook + fim da caixa-preta de automações)
- **KPI cards clicáveis** (drill-down): Hashrate/Share Rate → `live`, Best
  Difficulty/Pool Hashrate → `probability` — `data-kpi-target` no HTML,
  handler delegado em `#kpi-row` (reusa `activateModule`), affordance de
  hover (`→` no subtítulo + cursor). Nada de nova navegação — mesmo
  mecanismo dos links da sidebar.
- **Settings → WEBHOOK PREVIEW + ENVIAR TESTE**: o modal agora renderiza o
  JSON exato que o polling dispara a cada alerta (shape idêntico ao
  `services/polling.py`) e atualiza ao vivo conforme o operador edita
  `webhook_url`/`webhook_min_severity`. Botão `📡 ENVIAR TESTE` chama o novo
  `POST /api/settings/test-webhook` (mesmo PRO gate do `webhook_url`, mesmo
  payload shape, 400 quando não configurado, 502 honesto em erro de rede) —
  valida o canal Discord/Telegram sem esperar evento real.
- **Fim da caixa-preta de automações**: `GET /api/automation-executions`
  (novo) expõe o `automation_execution_log` — que o `_audit_automation_result`
  já populava em produção desde o boot — tenant-scoped via JOIN nas rules do
  tenant (a tabela não tem coluna tenant; órfãos de regra deletada nunca
  vazam). No Alert Center: cada regra mostra **"última: <tempo> — <status>"**
  (verde/vermelho por status) e um strip **ÚLTIMAS EXECUÇÕES** com as 6 mais
  recentes (regra → ação → status → motivo).
- Nota de auditoria: feedback de copy (`[copied]`) já existia em todos os
  pontos (wallet, footer, support) — nenhuma mudança necessária.
- Testes: `tests/test_ux_quickwins.py` (8: 400/403/204/502 do test-webhook,
  isolamento tenant, clamp de limit, órfão de regra deletada) + SUITE 31
  (mirror do `webhookPreviewPayload`, 10 asserts). Bumps CDN-safe
  `app.js?v50→v51`, `style.css?v47→v48`.

### Refatorado — Fase 6 completa: export + dashboard migrados para blueprints (app.py encolheu ~700 linhas)
- **`export_bp`** (`routes/export_routes.py`): 3 rotas migradas de app.py
  (`api_export`, `api_config_backup`, `api_config_restore`) — mesma auth
  (`require_tenant` + `role_required`), mesmas respostas.
- **`dashboard_bp`** (`routes/dashboard_routes.py`): **14 rotas** migradas
  de app.py — `/snapshot`, `/history`, `/diff_events`, `/leaderboard`,
  `/share_timeline`, `/event_stats`, `/halving`, `/mempool_fees`,
  `/profitability`, `/network_share`, `/milestones`, `/workers`,
  `/monte_carlo`, `/proximity`. Enriquecimento do snapshot extraído para
  `services/snapshot_enrichment.py::enrich_snapshot` (helper compartilhado
  entre app.py e o blueprint — payload idêntico). Gates `pro_required` de
  `/monte_carlo` e `/proximity` preservados.
- **Contrato `/api/history` preservado**: a rota migrada retorna a chave
  `rows` (não `history`) — mesma resposta da versão pré-migração, para não
  quebrar clientes existentes.
- **`/api/alerts`**: a cópia morta de app.py (shadowed pelo `alerts_bp`,
  registrado antes) foi **removida** — `routes/alerts_routes.py` é a única
  fonte (com tenant-scoping da Fase 4 · B2).
- **Dead code removido de app.py**: implementações legacy shadowed de
  `build_auto_pilot_context`/`_compute_block_hunt` (wrappers de delegação
  no fim do arquivo agora são a única fonte), import morto de
  `enrich_snapshot` e imports de `random`/`pro_required`/`AP_*`.
- **Fix real da migração**: `snapshot_enrichment.build_auto_pilot_context`
  construía `AutomationEngine()` sem os args obrigatórios (`db_path` +
  `safety_engine`) e chamava `preview_rules` sem devices — o preview de
  automação **falhava silenciosamente em produção** (testes mockavam o
  engine e não pegavam). Agora o app injeta o `AutomationEngine` +
  `CoreDeviceRegistry` **vivos** no módulo via `set_auto_pilot_deps()`
  (mesmo padrão do `_set_get_db` de alerts_routes) — o preview avalia
  contra a telemetria em memória do poll loop (um reload frio do DB
  perderia `current_telemetry` e nenhuma regra casaria). Fallback de
  construção fresca quando não injetado (testes/standalone) e constante
  compartilhada `AP_TEMP_HIGH_C` (era 75.0 hardcoded).
- **Testes**: `tests/test_dashboard_routes_migration.py` (15 testes de
  regressão: chave `rows` do history, rotas simples, gates pro, snapshot
  enriquecido, non-mutation do `enrich_snapshot`). Suíte completa 1508
  Python ✅ + JS ✅.

### Adicionado — Fase 5: telemetria completa do CgminerAdapter (fan, voltage, power, pool)
- **Novos campos** no `get_telemetry()` do `CgminerAdapter`:
  `fan_rpm` (chain `fan_num` + `fan1`/`fan_rpm`/`fan_speed`),
  `voltage` (chain `voltage`/`chain_voltage`), `power` (chain
  `power`/`chain_power`/`power_watts`) — todos com coerção de tipo via
  `_safe_number()` (cgminer retorna strings).
- **`pool_status` derivado** do comando `pools` (CONNECTED quando Alive,
  DISCONNECTED quando configurado mas morto, NOT CONFIGURED quando vazio).
- **`pool` dict** com `url`/`user` do primeiro pool alive.
- **`hashrate_1m/10m/1h` explícitos como `None`** — cgminer não expõe janelas;
  `normalize_telemetry()` preenche `NOT AVAILABLE`.
- **Helper `_safe_number()`** espelhado do `BitaxeAdapter` para coerção segura
  de strings→float/int.
- `BitaxeAdapter` já estava completo (todos os campos da Fase 5 coletados desde
  a implementação inicial).
- Suíte completa: 1310 Python ✅ + 1190 JS ✅.

### Corrigido — dedup das rotas /api/settings (shadowed dead code)
- `app.py` ainda registrava GET/POST `/api/settings` próprios, mas o
  `settings_bp` (routes/settings_routes.py, registrado antes) já atendia a
  rota — os handlers do app.py e o `_settings_label()` nunca eram chamados
  (shadowing silencioso do werkzeug). Removidos; o blueprint é a única fonte
  (mesma auth + PRO gate do webhook + labels reais de services/settings.py).
- Sincronizado o `DEFAULT_SETTINGS` local do app.py com as 3 chaves de
  credenciais (mrr_api_key/mrr_api_secret/braiins_api_key) para parar o drift
  entre os dois subsistemas de settings.
- Validação ao vivo: GET 18 keys com labels reais, POST aplica, limpeza OK;
  1310 Python + 1190 JS ✅.

### Adicionado — BRAIINS_API_KEY no modal Settings (destrava bids/contratos/saldo Braiins)
- **Novo campo** `braiins_api_key` no modal Settings (⚙) seguindo o padrão MRR:
  schema em `DEFAULT_SETTINGS`, label humano, hint com instruções (owner token
  mostrado 1x no registro de hashpower.braiins.com, header `apikey`), ordem no
  form após as keys MRR.
- **Resolver compartilhado** `braiins_credentials()` em
  `agents/solo_mining_advisor/tools.py` (env → Settings DB, igual ao MRR):
  - painel RENTALS (`fetch_braiins_contracts`/`contract_speed`) agora usa a key
    do Settings — sem env var, `needs_auth` some e a chamada real é feita;
  - `get_braiins_orderbook` envia o header `apikey` no probe `/spot/settings`
    quando a key existe (obtém a camada de pricing individual; sem key, o 401
    degrada para a unidade padrão como antes).
- Labels das 3 keys (mrr_api_key/secret + braiins_api_key) adicionadas em
  `services/settings.py::settings_label` (o modal mostrava label cru).
- Testes: fallback env→Settings (key do DB vence quando env ausente, env vence
  quando presente), header `apikey` no settings probe com/sem key, E2E do modal.
  Suíte completa 1310 Python ✅ + 1190 JS ✅ + E2E rentals 4/4.

### Adicionado — RENTALS panel: performance dos aluguéis do operador (MRR + Braiins)
- **Novo módulo RENTALS** na sidebar (⛁): lista os rentals do operador com
  **dados reais da conta MRR** (34 rentals históricos verificados ao vivo),
  filtros Active / History / Owner / Braiins, strip de resumo
  (MRR renter/history/owner + Braiins contracts) e detail clicável com
  grid de métricas, **gráfico de hashrate** e log de eventos.
- **Backend** (`services/rental_performance.py`):
  - MRR `GET /rental` (+`/rental/{id}`, `/graph`, `/log`) com HMAC-SHA1
    via helper compartilhado `_mrr_signed_headers` (extraído do
    `get_mrr_listings`);
  - Braiins `GET /contract` + `/contract/{id}/speed` (requer
    `BRAIINS_API_KEY`, degrada com nota honesta quando ausente);
  - Rotas `GET /api/rentals` (consolidado) e `/api/rentals/detail`
    (detail+graph+log) — fail-closed: credencial faltando → `needs_auth`
    explícito, nunca lista vazia falsa.
- **Fix de integração real**: o MRR assina o **path SEM query params** —
  assinar `/rental?type=...` falha com "Signature Failure" (verificado
  ao vivo); os filtros vão como request params separados.
- E2E `tests/e2e/rentals.spec.js` (chromium + mobile) valida o histórico
  real + detail com gráfico. Suíte completa 1305 Python ✅ + 1190 JS ✅.

### Corrigido — HASH MARKET real-first: cotações reais antes das estimadas no grid
- **Bug real**: o grid ordenava por `metrics.score` (ROI estimado) — o modelo
  pool-fee do Parasite (ESTIMATED, ~1 sat/TH/d) carrega score inflado e
  **roubava o topo do grid**, fazendo a aba parecer cheia de cotação fake.
- **Fix**: chave compartilhada `market_offer_sort_key` (services/hashrate_market.py)
  aplicada nos 4 pontos que ordenam offers (build_highlights, api_snapshot,
  /api/hashrate-market ×2): `(estimated, -score)` — quotes reais primeiro,
  estimadas por último; dentro de cada grupo o EV score segue desc. O
  `max_items` continua intacto: quotes reais preenchem os slots primeiro e
  as estimadas só ocupam o que sobrar (parasite nunca desloca uma real).
- **Efeito ao vivo**: grid agora mostra `nicehash → braiins` (reais) e
  `parasite` (ESTIMATED) por último.
- Testes: novo caso em TestBuildHighlights (ordem + max_items=2 corta a
  estimada) + asserts de ordem real-first nos testes de snapshot
  (test_market_intelligence). Suíte completa 1296 Python ✅ + 1190 JS ✅ +
  E2E market-affiliate/wallet-identity 6/6.

### Removido — Provider KissMyHash + fallback NiceHash+10% (quotas fabricadas)
- **Problema real**: a API pública antiga do KissMyHash morreu —
  `https://app.kissmyhash.com/api/v1/market` → **404 `Cannot GET`** (verificado
  ao vivo; a API nova exige `x-api-key`/auth, não configurada). Todo fetch caía
  no fallback `NiceHash +10%` que **fabricava uma cotação ESTIMATED** e disputava
  vaga de cotação real no top-3 do grid (HASH MARKET mostrava 2 cards fake).
- **Fix**: provider `kissmyhash` removido do pipeline (`fetch_all_offers`), do
  estado (`last_known_prices`), da UI (chip ♡ KissMyHash, badge de origem), dos
  docs (README, EXECUTION_PLAN) e de 6 suítes de teste (9 testes removidos).
- **Efeito real ao vivo**: com o cap de 3 slots livre, a **cotação real da Braiins
  entrou no grid** — HASH MARKET agora mostra `braiins` + `nicehash` reais (e o
  best price honesto vem do NiceHash, nunca de estimado).
- Suíte completa: 1295 testes Python ✅ + 1190 JS ✅.

### Corrigido — LIVE LOG inalcançável em module-mode (#terminal oculto no E2E)
- **Bug real**: o painel `#logs-panel` (LIVE LOG, `data-module="live"`) morava
  dentro de `#tab-fleet`, mas o módulo `live` só ativa `tab-charts` +
  `tab-terminal` (mapa `_MODULE_OWNED_PANES`, fix do overflow de 3 abas).
  Resultado: o LIVE LOG ficava **invisível em todos os módulos** — nem no
  dashboard (o `data-module="live"` o escondia) nem no Live Mining (o pane
  pai desativado o escondia). O E2E `Live Log contains system message`
  pegou a regressão.
- Fix: painel **movido para dentro de `#tab-terminal`** (pane owned pelo
  módulo live) — mantém o layout de 2 abas (sem re-introduzir o scroll
  infinito) e o LIVE LOG volta a aparecer no LIVE MINING, escondido nos
  demais módulos pelo próprio `data-module="live"`.
- Prova: suíte E2E completa no servidor frio — antes `148 passed / 3 failed`,
  depois **`151 passed / 0 failed`** (3 skips = restart-agent sem harness).

### Corrigido — topbar address colapsava em boot sem wallet (E2E topbar-responsive)
- **Bug real**: `fmt.shortAddr('')` retorna `''` — o `#topbar-address` ficava
  com texto vazio → span de largura zero → o Playwright (e flex/UX) o
  reportava hidden no breakpoint 1100px em servidor frio (sem wallet).
- Fix: fallback `'—'` nos dois call sites do topbar (mesma convenção do
  `#sb-wallet-addr` da P0-4) — o elemento sempre tem box real.

### Adicionado — E2E `wallet-identity.spec.js` (P0-4: QR + checksum + health de ponta a ponta)
- Novo Playwright spec que roda contra o servidor padrão do `run-e2e.sh`
  (sem harness): conecta um bech32 real via UI (modal → SAVE →
  `/api/set-address` real), valida o toast do servidor + fechamento
  automático do modal, e então verifica no card WALLET IDENTITY:
  - QR SVG inline do encoder puro (viewBox determinístico `0 0 37 37` para
    o endereço de teste 29×29 ECC M + quiet zone 4, path com centenas de
    células);
  - endereço dividido `bc1 | corpo | checksum` (`.addr-ck` = últimos 6
    chars) e que a recombinação devolve o endereço exato;
  - botão COPY + health strip conectado (`N/6 checks`, nunca NO WALLET) e
    os 6 checks honestos renderizados;
  - status bar também destaca os check-digits (`.addr-ck` em `#sb-wallet-addr`).
- **Idempotente + sem poluir o DB do dev**: decide o connect pelo snapshot
  do servidor (não por `window.BTC_ADDRESS`, que tem race), suporta rerun
  já-conectado sem o erro "same as current", e em `finally` restaura o
  endereço anterior (ou limpa a chave persistida quando não havia wallet).
- Roda nos 2 projetos (chromium + mobile-chrome) — 2 testes verdes.

### Adicionado — P0-4: Wallet QR + checksum + health (identity card no modal CONNECT WALLET)
- **QR code puro JS** (ISO/IEC 18004, byte mode, ECC L/M/Q/H, versions 1-10):
  encoder do zero em `static/app.js` (~320 linhas, sem dependência externa —
  o endereço **nunca sai do navegador**, sem serviço de QR de terceiros).
  Renderiza SVG inline crisp com quiet zone de 4 módulos.
- **WALLET IDENTITY card** no modal CONNECT WALLET: QR escaneável do endereço
  completo, endereço com o **checksum destacado** (`addr-ck` — os 6 chars
  finais de bc1, o trecho que o operador confere na carteira), botão COPY e
  strip de **health ao vivo** (NO_WALLET / HEALTHY / DEGRADED / CRITICAL com
  6 checks honestos: address set, data fresh, worker found, hashing, recent
  share, pool responding — nunca fabrica dados).
- **Status bar**: o endereço exibido em `sb-wallet-addr` agora destaca os
  check-digits — o clássico matador de tickets de endereço errado (−15%
  support tickets, Hidden Tax).
- Testes: golden fixtures geradas da lib independente `qrcode-terminal`
  (Kazuhiko Arase QRCode, MIT — agora devDependency raiz) — o encoder
  reproduz as **12 matrizes cell-for-cell** cobrindo **versões 1-10**
  (21×21 a 57×57, ECC L/M/Q/H): v1-6 da entrega inicial + v7-10 novas
  (45×45, 49×49, 53×53, 57×57) que exercitam o path de **BCH version-info**
  (type number + placement) — antes só coberto até v6. Regenerável via
  `node scripts/gen_qr_golden.cjs`. + determinismo, guard de capacidade,
  checksum split e health scoring.

### Adicionado — P1 Auto-Pilot advisory (fase inicial do Big Bet — read-only)
- **Cards consultivos de decisão** no Command Center alimentados por DADOS
  reais do snapshot (`auto_pilot` block injetado em `/api/snapshot`):
  1. `hashrate_drop` (gold) — hashrate atual < 70% do pico REAL de 7d
     (`MAX(worker_hashrate)` em `proximity_history`, janela `AP_PEAK_WINDOW_S`);
  2. `temp_high` (warn) — device da frota ≥ `AP_TEMP_HIGH_C` (75°C);
  3. `automation_ready` (info) — `AutomationEngine.preview_rules()` reporta
     uma regra que DISPARARIA agora (avalia condição + cooldown, NUNCA
     executa, valida ou audita).
- **Fail-closed por design**: qualquer hiccup (DB, registry, engine) vira o
  bloco vazio/zero — o snapshot nunca quebra e a regra de drop nunca dá
  falso positivo em boot frio (gate `> 0`).
- **Tenant-scoped**: o preview roda com o `tenant_id` resolvido da request
  (fallback 'default') — um card advisory nunca expõe nomes de regra de
  outro tenant (mesmo rigor do teste B2 de isolamento).
- Testes: unitários das 3 regras em `test_command_center.py` + testes
  diretos do `build_auto_pilot_context` real (fail-closed em erro de DB,
  fechamento de conexão, threading de tenant) + `preview_rules` em
  `test_automation_engine.py` (seed no DB, cooldown, tenant, never-execute).

### Corrigido — hardening pós-review do P0-4/P1 + validação E2E
- `build_auto_pilot_context`: conexão sqlite agora fecha em `finally` (sem
  leak por poll), parâmetro `resp` morto removido, fallback usa a constante
  compartilhada `AP_TEMP_HIGH_C` (sem drift de 75.0 hardcoded) e o preview
  de automação é **scoped por tenant** (antes carregava regras de TODOS os
  tenants — leak de nomes de regra no card advisory).
- `TestPreviewRules` agora faz seed das regras no sqlite (como o resto da
  suíte) — `preview_rules` lê do DB, então os testes sem seed falhavam 4/8.
- E2E `wallet-identity.spec.js` validado nos 2 projetos (chromium +
  mobile-chrome, rerun idempotente incluso — 2×2 verdes). **Pré-requisito
  documentado no header**: o servidor precisa subir via `run-e2e.sh`
  (`RATE_LIMIT_PER_MINUTE=1000`, env vence o `.env`) — um dev server que
  carrega `.env` com `RATE_LIMIT_PER_MINUTE=60` (via `load_dotenv()` em
  config.py) 429a o 2º projeto silenciosamente. **Causa raiz investigada**: o
  `.env` local do projeto tinha 60 (não era default de código antigo) —
  corrigido para 300 no `.env` local do dev.

### Corrigido — caps do /summary agora serializam como array (Restart do Fleet Command Center)
- **Bug real**: `buildCommandCenterRows` (JS) renderiza os botões Restart/Identify
  a partir de `capabilities` como ARRAY, mas o `GET /api/axe-fleet/summary`
  devolvia o dict cru do registry — `Array.isArray()` falhava e todo device
  agent-managed caía em READ-ONLY, tornando o restart inalcançável pela UI.
- `fleet_summary` agora acha o mesmo `supported_cmds` (lista de chaves
  truthy) que o `fleet_health` já produzia — paridade de schema mantida.
- Teste de regressão em `TestFleetSummary.test_capabilities_serialized_as_supported_command_array`
  + E2E novo `tests/e2e/restart-agent.spec.js` (toast + prova de execução no
  log do agente real).

### Adicionado — E2E `restart-agent.spec.js` (round-trip completo do comando)
- Novo teste Playwright que exige o harness `scripts/e2e_browser_session.py`
  (servidor real + 2 miners mock + agente REAL): clica no botão ↻ Restart de
  um card agent-managed, aceita o `confirm`, valida o toast de sucesso
  (`'restart' enviado para o agente local executar`) e PROVA a execução real
  contando `executing restart` no log do agente (anti-teatro).
- Sem o harness rodando, o teste dá SKIP (não quebra o `run-e2e.sh`/CI).

### Reformulado — aba Live Mining → FLEET COMMAND CENTER (rebuild total)
- **Todas as funções da aba antiga removidas**: `renderLiveMining` (já morta —
  sem `#lm-grid` no HTML), `_updateLiveMiningSummary`, `_updateLmNetworkStatus`,
  `_updateBestShare`, `_updateLmSummaryExtras`, `_applyLmFleetKpis`/
  `_lmFleetKpiAgg`, `_logMiningEvent` (mantido), o bloco `_hunt*` inteiro
  (CALC STREAM / RECENT SHARES / sparkline+gauge canvas), `buildWorkerIntelligenceRows`
  e `renderWorkerIntelligence` (substituídos) e `fetchWorkerIntelligence`.
  No HTML: `lm-cyber-header`, `lm-summary`, `lm-network`, `lm-workers` (tabela
  antiga), `hunt-layout`, `hunt-shares` e `lm-best-share` antigo foram
  reconstruídos. CSS: blocos `.lm-*`/`.hunt-*` (incl. `.lm-worker*` mortos de
  versão antiga) trocados por estilos `.fcc-*`; media queries atualizadas.
- **Novo painel "CYPHER65 // FLEET COMMAND CENTER"** (baseado em pesquisa de
  dashboards HiveOS/Minerstat/Foreman + padrões de UI):
  - **KPI strip fleet-fed**: TOTAL HR (com sparkline SVG do histórico),
    ONLINE / WARNING / OFFLINE, AVG TEMP, POWER (kW), EFFICIENCY (J/TH),
    AVG PING, EST. EARNINGS — agregados por `_ccKpiAgg` (honesto: OFFLINE
    nunca contribui com shares/temp/power, senão a EFFICIENCY congelaria).
  - **Exception hierarchy** (`_ccRenderExceptions`): workers com problema
    sobem num banner "⚠ N WORKER(S) PRECISAM DE ATENÇÃO" (manage by
    exception) e a ordenação do grid coloca WARNING/OFFLINE primeiro.
  - **Worker cards** (grid default) com health ring SVG, hashrate + sparkline
    SVG inline (`_ccSvgSparkline`, sem canvas/ids), temp colorida por banda
    (`_ccTempBand` ≤60/70/80), power, eficiência, fan, last share, PING e
    **share-quality bar** segmentada A/S/R (`_ccShareBar`, estilo HiveOS) +
    botões Restart/Identify (handler compartilhado `_handleAxeCmdClick` com a
    grade do Fleet).
  - **Dense table** (toggle ▦ GRID / ☰ TABLE persistido): colunas WORKER / HR
    / TEMP / POWER / EFF / SHARES A/S/R / REJ% / LAST SHARE / PING / HEALTH.
  - **THERMAL MAP** (`_ccRenderThermal`): grade T / CHIP / VR por worker com
    cores por threshold (crit piscando).
  - **Network/pool strip** e **event stream** (terminal P0-6 com filtros)
    mantidos; BEST SHARE agora vem do best_diff do fleet (flash novo).
- **Dados**: painel alimentado por `/api/axe-fleet/summary` (mesma cadência de
  poll do Fleet) + snapshot para network/profitability/ticker de shares.
- **Testes**: SUITE 26b → `buildCommandCenterRows` (ordenação por exceção +
  campos novos), SUITE 26d → `_ccKpiAgg`, SUITE 26e nova (`_ccShareBar` /
  `_ccSvgSparkline` / `_ccTempBand`); E2E `live-mining.spec.js` atualizado
  (cards + KPI + toggle tabela + raster). **1094 testes JS + 127 Python
  passando**; E2E chromium verde com 0 erros de console; painel verificado no
  Chrome real com agente mock (2 cards, KPIs populados, 6 células térmicas,
  48 células de raster).

### Corrigido — botão Restart/Identify do Fleet (auditoria UI no browser)
- **Bug real encontrado com o dashboard aberto no browser**: os cards do AXE
  FLEET postavam o comando para a rota **core** `/api/devices/<id>/command`
  (`_core_registry`), que não conhece devices do axe registry → **404 "device
  not found"** → toast de erro → o miner **nunca reiniciava** (mesmo padrão
  "teatro" da auditoria anterior, agora no caminho real da UI).
- **Fix**: o handler `.axe-cmd-btn` do `static/app.js` agora roteia
  restart/identify para `/api/axe-fleet/devices/<id>/{restart|identify}` com
  `authFetch` (Bearer do tenant) — a rota axe-fleet enfileira no AGENTE LOCAL
  para devices agent-managed (ou executa via `AxeOSConnector` para devices axe
  não-agent). `pause`/`resume` mantêm a rota core como fallback (caps axe não
  os anunciam hoje). Toast de sucesso prefere `data.message` do servidor.
- **Verificação de ponta a ponta (browser + servidor real + mocks)**: novo
  harness `scripts/e2e_browser_session.py` (servidor+mocks+agente vivos p/ UI),
  confirmado no Chrome: 2 cards, PING `—` (latency_ms nulo para agent-managed),
  summary `2 online / 1.00 TH/s`, e o restart enfileirado executado de verdade
  pelo agente na LAN mock (`executing restart → 127.0.0.1 / localhost`).
- **Espelhos JS novos** em `tests/test_app_js_core.js` (`routeAxeCmd`):
  restart/identify → axe-fleet com authFetch; pause/resume → core. 1049 testes
  JS + 151 testes Python passando.
- **Nota de contrato**: restart/identify agora exigem sessão de tenant (ou
  localhost) — em open-mode self-host acessado de outra máquina sem login a
  resposta passou de 404 (core) para 401 honesto "authentication required".

### Corrigido — auditoria CFO do fluxo SaaS do agente (6 bugs reais)
- **Comandos restart/identify agora executam de verdade** (`agent_pull_commands`
  passa `ip_address` no payload — antes o agente recebia o UUID do registry e
  tentava abrir socket para uma string não-resolvível; o miner nunca reiniciava).
  O agente executa AxeOS via HTTP :80 e cgminer via JSON-over-TCP :4028.
- **Heartbeat `{}` não zera mais o hashrate no snapshot**: `_cache_axe_telemetry`
  preserva a última leitura real quando um poll falha (antes o topo da página
  caía para 0 enquanto o /health mostrava o dado real — duas verdades).
- **`/health` e `/summary` não fazem probe TCP a IPs privados de devices
  agent-managed** (inalcançáveis da nuvem — cada chamada bloqueava N×0.75s).
- **Capabilities por tipo**: device cgminer não anuncia mais o botão identify
  (API cgminer não tem esse comando); capabilities são recalculadas quando o
  tipo chega num register posterior.
- **Re-scan do agente** só adiciona ao poll set devices que o servidor admitiu
  (plano cheio / removido → não gera 403-spam de telemetria).
- **Tombstone soft-delete (`removed_at`)**: device removido pelo operador não
  ressuscita mais via push do agente (zumbi). Register/telemetria retornam
  blocked/410, `count_tenant_workers` ignora tombstones, `+ ADD` manual revive,
  GC de 30 dias limpa tombstones antigos + telemetria.
- **Testes**: +19 novos (comandos com ip, heartbeat cache, caps por tipo,
  tombstone, GC, latency skip, protocolo do agente) + etapa 7 no E2E que prova
  restart real nos miners mock (AXEOS + cgminer). Suíte: 1274 passando.
- **E2E PLAN CAP** (`scripts/e2e_agent_plan_cap.py`): tenant com max_workers=1
  e agente descobrindo 2 miners — confirma que o device não admitido é
  bloqueado no register (audit `agent.register_blocked`) e NUNCA gera
  403-spam de telemetria (`agent.telemetry_blocked` = 0), estável por ~17
  ciclos de re-scan. Prova: 43 requests no servidor, 43 × HTTP 200.

### Removido — Canvas de partículas "nonce search" (Live Mining)
- **Removido por completo** o quadro preto de radar com gradiente gold, linha
  pontilhada do alvo e rodapé `NONCES SEARCHED` (`#hunt-canvas-wrap` + engine
  `_hunt.draw`/`resize`/`fmtNum`/`totalHashes`) — o usuário não queria mais
  ele no projeto.
- **Intocados**: ⚡ LIVE ACTION FEED (agora ocupa a coluna da esquerda),
  métricas (INSTANT HR / CUMULATIVE P / EXP BLOCKS / BEST DIFF + sparkline +
  gauge), RECENT SHARES, topbar e demais painéis. O tick de 1s que alimenta o
  feed e as métricas continua (sem o draw do canvas). Grid do hunt-layout
  passou de `1fr 2fr 1fr` para `1fr 1fr`.
- Grid do hunt-layout: `2fr 1fr` (feed com 2/3 da largura, métricas 1/3).
- Bumps CDN-safe: `app.js?v46→v47`, `style.css?v40→v42`.

### Adicionado — Guia do agente dentro do app (`/docs/agent`)
- **Nova rota pública** `/docs/agent`: renderiza `docs/AGENT_SETUP_GUIDE.md`
  (fonte única de verdade — o mesmo arquivo do repo) convertido para HTML com
  a lib `markdown` (nova dep pinada `markdown==3.10.3`). Página standalone
  `templates/agent_guide.html` reutilizando o tema do dashboard (style.css +
  CSS vars), com voltar ao dashboard.
- **Link no painel CONNECT AGENT** (Fleet → 🤖 CONNECT AGENT): "📖 GUIA
  COMPLETO DO AGENTE" abre o guia em nova aba.
- Extensões markdown: `tables`, `fenced_code`, `nl2br` (cobre code blocks,
  tabela de troubleshooting e blockquotes do guia). 404 honesto se o arquivo
  faltar. Testes: `TestDocsAgent` (render 200, público sem auth, 404).

### Adicionado — CI: imagem do agente publicada no GHCR
- **Novo workflow** `.github/workflows/agent-image.yml`: builda `agent/Dockerfile`
  e publica `ghcr.io/0xjc65eth/cypher65-agent` (tags `latest` + `sha-<commit>`)
  a cada push na branch `master` (+ `workflow_dispatch`). Permissão `packages:
  write` via `GITHUB_TOKEN` — sem credenciais extras. Smoke test pós-push
  (import do agent.py na imagem, guard `__main__`).
- **One-liner Docker do painel** (Fleet → CONNECT AGENT), `docs/AGENT_SETUP_GUIDE.md`,
  `docs/AGENT_ARCHITECTURE_NOTE.md` e `agent/README.md` agora apontam para
  `ghcr.io/0xjc65eth/cypher65-agent` (antes: `cypher65/agent` no Docker Hub,
  que não era publicado por CI). Bump CDN-safe `app.js?v45→v46`.

### Adicionado — Live Mining: LIVE ACTION FEED (substitui debug CALC STREAM)
- **Removido** o header de debug `> CALC STREAM` e o cabeçalho de colunas
  `TIME EVENT DIFFICULTY GAP` — lixo de interface interna sem valor pro usuário.
- **Novo feed de eventos** (`#live-action-feed`): shares aceitas/rejeitadas/stale
  (verde/âmbar) + transições de status dos workers do fleet (offline → vermelho
  acionável, online → verde) — auto-scroll com os mais novos por cima, cap 6.
- **Clique → modal** com o log bruto do evento (substitui a "função CALC STREAM"
  de debug). **Ação inline**: worker offline → botão ↻ Reconectar (rota de
  restart do fleet; devices agent-managed vão para a fila do agente local).
- Estado vazio honesto: "📡 Aguardando atividades dos workers...". Métricas
  superiores (WALLET/WORKERS/HR/BEST DIFF/…), NETWORK strip, canvas e share
  cards intocados. Engine `_laf` em `static/app.js` + CSS + SUITE 28 de testes
  JS (event builders puros mirror).

### Adicionado — SaaS: agente local (dashboard na nuvem → LAN do usuário)
- **`agent/` (novo)**: agente standalone (Docker/Pi/PC na rede do usuário) que
  conecta PARA FORA ao dashboard no Render — resolve o caso "deploy na nuvem,
  miners em casa": a nuvem não roteia para `192.168.x.x`, então o agente
  descobre a LAN local (AxeOS :80 / cgminer :4028), registra os devices e
  empurra telemetria em batch a cada 30s (NAT/CGNAT-safe, sem abrir porta).
- **Instalador de 1 linha (novo)**: `curl -sSL <url>/agent/install.sh \
  | CYPHER65_SERVER_URL=… CYPHER65_AGENT_TOKEN=… bash` — sem Docker, sem pip
  (agente 100% stdlib/urllib): baixa o agent.py do próprio dashboard, instala
  como serviço (launchd no macOS / systemd no Linux / nohup fallback) e sobe.
  O painel CONNECT AGENT imprime o comando pronto com token+URL embutidos.
- **`/agent/install.sh` + `/agent/agent.py`**: rotas públicas que servem o
  instalador e o agente (o usuário os baixa de uma máquina FORA do dashboard).
- **Fix**: `CYPHER65_DEVICES` roda o probe de descoberta completo (cgminer :4028
  incluído) — antes forçava `type=bitaxe` e só tentava :80, perdendo ASICs.
- **Fixes do teste E2E real (curl|bash)**: (1) `$SERVER_URL…` com reticências
  unicode coladas no nome da variável quebrava sob `set -u` — agora `${SERVER_URL}`;
  (2) branch launchd não criava `~/Library/LaunchAgents/` — agora `mkdir -p`.
- **Docs**: `docs/AGENT_SETUP_GUIDE.md` (guia do usuário com comandos copy-paste)
  e `docs/AGENT_ARCHITECTURE_NOTE.md` (por que agente conecta para fora).
- **API `/api/agent/*`**: `token` (JWT de 1 ano scoped ao tenant), `register`,
  `telemetry`, `commands/pull` + `commands/<id>/ack` — autenticação por JWT
  com claim `agent:true`, isolamento estrito por tenant.
- **Fila de comandos**: restart/identify em devices agent-managed são
  enfileirados no servidor e executados pelo agente local (com re-queue se o
  agente cair antes do ack).
- **Poll skip**: `_do_poll` nunca toca devices `agent_managed` (o servidor não
  alcança a LAN deles — pollaria OFFLINE em todo tick). Schema migrado no boot
  (`ensure_tables()` no app.py: coluna `agent_managed` + tabela
  `axe_agent_commands`).
- **UI**: painel "CONNECT AGENT" no Fleet — gera o token e imprime o comando
  `docker run` para colar na rede do usuário.

### Corrigido — AXE FLEET descoberta cega (engenharia de protocolo)
- **Hint de topologia no scan (A)**: CIDR privado + 0 found → o scan agora
  anexa o aviso "IP privado (LAN)" ao resultado (dashboard na nuvem não
  roteia para a rede caseira) — antes o wizard explicava, o scan ficava mudo.
- **Camada alive-vs-miner (B)**: `scan_subnet` agora reporta `alive` /
  `alive_ips` — hosts cuja porta TCP abriu mas não responderam como miner
  (ASIC com API autenticada/firewall) — transformando "no miners found"
  genérico em diagnóstico acionável na UI.
- **Fingerprint cgminer tolerante (C)**: aceita delimitadores `\x00` e `~`
  (Avalon) e extrai JSON leniente (banner/bytes extras/pretty-print) em vez
  de descartar a resposta — cobre variações de firmware que antes davam
  falso-negativo.
- **Probes de presença (D)**: `diagnose_host` agora detecta porta TCP :443
  aberta (Braiins OS+/Antminer moderno com API autenticada) e servidor HTTP
  em :80 que não é ESP-Miner (página de login de ASIC) — mensagens acionáveis
  no wizard em vez de "no miner protocol" seco.
- Scan-store repassa `alive`/`alive_ips`/`hint` para o endpoint de status;
  UI mostra contagem de hosts alive + hint no resultado vazio.

### Adicionado — Cobertura 62% → 66% (gate CI 45% → 65%)
- **108 testes novos** cobrindo módulos de baixa cobertura:
  `services/ai_operator.py` (12% → ~72%), `services/session_manager.py`
  (28% → ~92%), `services/push_notifier.py` (34% → ~86%),
  `core/adapters/cgminer_adapter.py` (44% → ~80%),
  `services/proximity.py` (45% → ~85%).
- **Gate do CI elevado**: `--cov-fail-under` 45 → **65** no `ci.yml`.

### Corrigido (bugs reais descobertos pelos testes novos)
- `ai_operator._fmt_diff`: quebrava com `ValueError` quando a API enviava
  bestDifficulty como string com sufixo (ex.: `"2.5P"`) — agora usa
  `helpers.parse_diff_to_float` (tolerante a K/M/G/T/P).
- `session_manager.get_session/get_snapshot`: usavam o TTL hardcoded do módulo
  em vez do `self._ttl` configurável — sessões podiam expirar cedo demais ou
  sobreviver além do TTL configurado.
- `proximity._compute_rolling_avg_share_diffs`: `old_avg_raw` era declarado no
  dict de resultado mas nunca populado (sempre `None`); agora calcula a média
  da janela antiga corretamente.

### Adicionado — P0-6 LIVE MINING terminal profissional
- **Ring buffer**: feed de eventos agora é um buffer limitado a 200 linhas
  (antes crescia sem limite na DOM — risco de memory leak).
- **Scroll lock**: o terminal só auto-scrolla quando o usuário está no rodapé
  (threshold 24px) — nunca mais "puxa" o leitor de volta ao ler histórico.
- **Botão Jump to Bottom**: aparece quando o usuário rola para cima; um clique
  volta ao final do stream.
- **Pause / Resume**: pausa descarta eventos (recomendado p/ velocidade) e
  mostra um marcador visual de onde o stream reiniciou.
- **Filtro por tipo**: chips ALL / SHARE / BEST / JOB / ERR — filtragem
  reativa sem recarregar a página.
- **Stats ao vivo**: contadores EVENTS / SHARES / ERR no cabeçalho do terminal.
- **Conexão dot**: LED verde (live) / âmbar (stale) / vermelho (sem poll),
  baseado no flag `network.stale` do servidor (sem clock skew de cliente).
- **Timestamps com milissegundos** e cores por tipo de evento
  (SHARE azul, BEST dourado, JOB âmbar, ERR vermelho).
- **Altura fixa (220px) + scrollbar customizada** — comportamento previsível.

### Corrigido — P0-5 audit de UI (wallet ranks, share chart, fleet, hashmarket, Command Center)
- **Wallet ranks**: o account agora é enriquecido com os ranks REAIS da leaderboard
  (`diff_rank` / `loyalty_rank` / `combined_score` via `helpers.enrich_account_ranks`,
  puro + testado). O frontend ganhou `acctRankLabels()` com fallback C3 (TOP 1%/
  10%/25%/ACTIVE a partir de `block_count`) — antes o `DashboardCore.updateDataGrids`
  sobrescrevia tudo com `--` e o campo COMBINED **nunca era populado**.
- **Share Difficulty chart**: o histograma era renderizado como line chart com
  `pointRadius 0` + fill 10% — com poucos shares a série ficava invisível
  ("gráfico vazio" com 13+ shares no log). Agora renderiza como **bar chart**
  (`type: 'bar'`, fill 55%) — uma coluna visível por bucket de dificuldade.
- **Fleet layout**: células de métrica ganharam guards de overflow
  (`white-space: nowrap` + `text-overflow: ellipsis` + `min-width`) — o fallback
  honesto `NOT AVAILABLE` (13 chars) não empurra mais a grade 5-up para fora
  de alinhamento.
- **Hashmarket / Decision Matrix**: safety guard no `lender_market_rate_btc`
  (clamp 1e-8..1e-2 BTC/TH/d + log) — um rate implausível (unidade confundida
  sats↔BTC, TH↔PH) não gera mais lease P&L fake (medido ao vivo: $55.411/d para
  um rig de ~87 TH, 100× o real). Rate fora da banda → `None` → painel honesto.
- **Command Center**: `renderCommandCenter` agora pula o write de `innerHTML`
  quando os cards serializados são idênticos (id|severity|url|title|message) —
  o "blink infinito" a cada 15s (destroy/recreate de botões) sumiu; o badge
  continua atualizando a severidade.
- **DB local**: `data/war_room.sqlite` estava corrompido (index
  `idx_maintenance_records_ts` com entradas erradas) — restaurado do backup
  íntegro `war_room.sqlite.bak.audit.1785684824` (86.941 snapshots preservados,
  o corrupto foi preservado como `war_room.sqlite.corrupt.*`).

### Adicionado — AXE FLEET onboarding wizard (3 passos + teste de conectividade)
- **UI**: o formulário de add do AXE FLEET virou um wizard passo a passo:
  1. **method** — escolha entre "🔍 Scan network" (auto-discovery do subnet scan)
     ou "⌨️ Enter IP manually"; 2. **connect** — progresso do scan OU teste de
     conectividade embutido (🔌 TEST CONNECTIVITY); 3. **confirm** — resumo do
     miner detectado (model/hostname/firmware/hashrate) + nome opcional + ADD.
- **Teste de conectividade unificado** (`GET /api/axe-fleet/diagnose/<ip>`):
  agora testa **AxeOS HTTP :80** (Bitaxe/ESP-Miner) **e** cgminer TCP :4028,
  retornando um relatório passo a passo (DNS → Bitaxe → cgminer) com flags
  `bitaxe_http` / `cgminer_tcp` / `protocol` / `device_info` — o usuário vê
  exatamente onde a conexão falha e recebe orientação acionável.
- **Fluxo do scan**: o botão "+ ADD" dos miners encontrados agora abre o passo
  3 do wizard com os dados pré-preenchidos (em vez de registrar direto).
- **Backend**: novo `diagnose_host()` em `axe_fleet/scanner.py` (nunca lança,
  cobre DNS/IP inválido, fallback HTTP→TCP) reutilizado pela rota de diagnose.
- **Testes**: `TestDiagnoseHost` (10 testes) em `tests/test_axe_fleet_scanner.py`
  (40 no total) + SUITE 26 (wizard connectivity report) em
  `tests/test_app_js_core.js` (938 no total).

### Adicionado — LAN miner discovery (subnet scan)
- **`axe_fleet/scanner.py`** (novo): detecção automática de miners na rede local —
  `parse_cidr` (CIDR/range/IP único/hostname, cap 1024 hosts), `probe_host`
  (Bitaxe/AxeOS HTTP porta 80 + fingerprint cgminer TCP 4028 via `version`),
  `scan_subnet` (ThreadPoolExecutor com callback de progresso) e
  `suggest_subnets` (deriva subnets das interfaces locais do host).
- **Rotas** `/api/axe-fleet/scan` (POST assíncrono, 202 + scan_id, um scan ativo
  por tenant — anti-flood 409), `/api/axe-fleet/scan/<id>` (progresso/resultados,
  isolado por tenant) e `/api/axe-fleet/scan/subnets` (sugestão de subnets).
- **UI**: botão 🔍 SCAN LAN no formulário + ADD do AXE FLEET COMMAND com campo de
  subnet pré-preenchido, progresso ao vivo (hosts sondados) e lista de miners
  encontrados com botão ADD por dispositivo (reusa o fluxo de registro existente).
- **Testes**: `tests/test_axe_fleet_scanner.py` (30 testes) cobrindo parsing,
  probes (Bitaxe/cgminer), scan concorrente, sugestão de subnets e rotas
  (incluindo o guard de scan concorrente por tenant).

### Corrigido — SHARE TIMELINE summary cards (LAST SHARE / 1H / 24H / BUMPS)
- Os cards de resumo e os badges da SHARE TIMELINE ficavam em `—` para sempre:
  os nós DOM (`t-stat-lastshare`, `t-stat-1h`, `t-stat-24h`, `t-stat-bumps` e os
  badges) eram definidos mas **nunca atualizados** pelo frontend, apesar do backend
  já entregar `event_stats` (contagens DB 1h/24h/bumps, last_submit_ts).
- Novo `renderTimelineStats()` consume `snap.event_stats`; fallback client-side
  `computeTimelineStats()` agrega a lista de eventos quando as contagens DB
  faltam (primeiro poll/falha de escrita), e `lastShareTsFromTimeline()` deriva
  o LAST SHARE do SHARE_FOUND mais recente após restart do servidor.
- 0 é renderizado como "0" (contagem real); só ausência de dado vira `—`.
- Testes: SUITE 15b em `tests/test_app_js_core.js` (920 no total).

### Corrigido
- **`static/app.js`** — corrigido `ReferenceError: dom is not defined` no LIVE LOG
  a cada ~30–60s. O IIFE principal (`(() => {`) era fechado por um `})();` solto na
  linha 5157, jogando `renderKpiCards()` + ~140 linhas (sidebar toggle, docs
  observer/search, FAQ, painéis colapsáveis) para o escopo **global**, onde a const
  `dom` do IIFE não existe — todo render lançava o erro (engolido pelo error
  boundary, throttled a 5/min). O fechamento do IIFE agora está no **final** do
  arquivo, devolvendo o escopo correto. Bônus: os KPI cards (`kpi-hashrate` etc.)
  que nunca populavam agora renderizam. (`app.js?v40` + `sw.js` cache v6)
- **`tests/e2e/dashboard.spec.js`** — o teste "no JavaScript ReferenceErrors"
  agora também lê o texto do painel `#terminal` (o boundary engole erros no painel,
  não no console — o buraco que escondia o bug) e asserta que `kpi-hashrate` não
  fica no placeholder.

### Adicionado
- **`services/workers.py`** — entrypoint standalone para workers de background
  (`python -m services.workers`): roda poll loop, hash-market warmup, donation
  watcher e auto-backup em **processo separado**, destravando deploys
  gunicorn/multi-instância sem mudar o comportamento de `python app.py`.
- **`REVOKED_TOKENS_DB=1`** — persistência opcional da blacklist JWT no SQLite
  (tabela `revoked_tokens`), compartilhando logout entre múltiplos processos.
  Off por default (memória permanece a fonte primária no single-process).
- `requirements-dev.txt`, `.github/dependabot.yml`, `.pre-commit-config.yaml`
  (hygiene-only), `CONTRIBUTING.md`, `CHANGELOG.md`.
- CI: job `mobile` (typecheck + jest) gateando merges.

### Corrigido
- **Dashboard em branco após conectar wallet (race do refresh)**: o
  `/api/set-address` reseta o snapshot (ts=0) e força um poll que só carimba
  `ts` no FIM (medido: 2–12s+ com APIs externas lentas) — o fetch cego de
  1.2s renderizava o estado vazio e o dashboard ficava em branco até o
  próximo poll de 15s. Agora o frontend faz retry determinístico
  (`refreshUntilWalletReady`: a cada 1.5s, até ~30s) até o snapshot ter o
  endereço novo E `ts>0` — o dashboard acende no momento exato em que os
  dados reais chegam. (`static/app.js` + 10 asserts de espelho JS)
- **Isolamento multi-tenant da frota (audit de escopo)**: `axe_fleet` do
  `/api/snapshot` era servido do cache GLOBAL do poll — agora é filtrado por
  tenant no serve-time (fail-closed). Rotas `remote/*` (health/devices/test)
  agora exigem `@require_tenant` + role e filtram `list_devices(tenant_id)`;
  rotas de leitura do fleet exigem `viewer` (anônimo remoto → 403 em vez de
  ler o tenant `default`); `diagnose/<ip>` (superfície SSRF) exige auth;
  `test-devices` semeia só no tenant do chamador; `_require_local_or_session`
  valida JWT/API-key em vez de aceitar qualquer header; power-cycle tasks
  escopadas por tenant. (13 testes de regressão em `test_fleet_tenant_scope.py`)
- Gate de cold boot do Command Center: `worker_offline` só dispara após o
  primeiro poll real (`ts > 0`), nunca em boot limpo sem wallet.
- Card `affiliate_buy` do Command Center agora enxerga o link real
  (`build_command_center` roda após `attach_affiliate` no `/api/snapshot`).
- Watchdog do poll loop: lock travado por >60s é substituído + alerta CRIT
  (snapshots nunca mais congelam silenciosamente).
- Índices `idx_highest_diff_events_ts` / `idx_maintenance_records_ts` e
  `UNIQUE(snapshots.ts)` + `INSERT OR IGNORE` (dedup de snapshots).
- `pool_last_block_height` recebe fallback de `lastBlockTime` (API Parasite).
- Multi-moeda: `btc_jpy/krw/cny` + migração ALTER TABLE para DBs legados.
- JWT migrado de hmac/base64 caseiro para **PyJWT** com claims `aud`/`nbf`/`jti`.

### Alterado
- Config consolidada em `config.py` (fonte única; `app.py` importa de lá).
- SQLite: `PRAGMA journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=3000`
  em toda conexão.
- Documentação consolidada: auditorias históricas movidas para `docs/archive/`,
  `README_ULTIMATE.md` → `docs/DEPLOYMENT_OPS.md` (README único).

## [0.1.0] — histórico

Versão inicial não taggeada. Consulte `git log` e `docs/archive/` para o
histórico completo de auditorias e milestones.
