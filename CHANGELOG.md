# Changelog

Todas as mudanças notáveis do **CYPHER65 War Room** são documentadas aqui.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e versionamento semântico ([SemVer](https://semver.org/lang/pt-BR/)).

## [Unreleased]

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
