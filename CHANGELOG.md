# Changelog

Todas as mudanças notáveis do **CYPHER65 War Room** são documentadas aqui.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e versionamento semântico ([SemVer](https://semver.org/lang/pt-BR/)).

## [Unreleased]

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
