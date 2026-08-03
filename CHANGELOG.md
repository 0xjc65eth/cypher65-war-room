# Changelog

Todas as mudanças notáveis do **CYPHER65 War Room** são documentadas aqui.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e versionamento semântico ([SemVer](https://semver.org/lang/pt-BR/)).

## [Unreleased]

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
