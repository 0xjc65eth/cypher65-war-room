# RFC — Decomposição dos god files (`static/app.js` 13k / `app.py` 9.4k)

> Issue #478 · auditoria enterprise 2026-09-10 (achado M9) · Frontend + Backend
> Status: **APROVADO** (PR #488) — **Opção A** ratificada pelo mantenedor.
> Execução em andamento — frontend: PR 1 (build + extração do core `fmt`/`escape`) = Issue #489 (PR #491 · mergeada).
> Achado do PR 1: o espelho do `fmt` no harness divergia do fonte e escondia 3 
> defeitos reais de produção — corrigidos na Issue #490 (PR 2 do frontend).
> Backend: PR B1 (admin gate + `/api/admin/*`) = Issue #495 — 300 linhas movidas
> para `routes/admin_routes.py`, `url_map` idêntico, gate re-exportado por `app.py`.
> Achado do B1: `/api/admin/sessions` não usa o gate — Issue #496, **corrigida**
> (PR #498: a rota passa a usar `_admin_request_allowed()`, sem um PR-B de
> extração).
> Backend: PR B2 (SSE fan-out) = Issue #499 — `_sse_clients` +
> `broadcast_snapshot()` + `GET /api/stream` movidos para `services/sse.py`,
> `url_map` idêntico (178 regras).
> Backend: PR B3 (snapshot assembly) = Issue #501 — correção de premissa: o
> código **não** estava em `app.py` e sim em `services/user_polling.py`; a cache
> global + a camada de fetchers + `_build_snapshot` foram para
> `services/snapshot_assembly.py` (user_polling: 1.606 → 1.152 linhas).
> Backend: Issue #508 (sub-issue do B4) — `get_db()` passa a ser definido em
> `services/bootstrap.py` e `services/db.py` vira re-export (uma implementação
> só); o import de telemetria virou tardio dentro do `init_db()` para não fechar
> ciclo. A parte "reconciliar `config.DB_PATH` × `app.DB_PATH`" da issue era
> **premissa falsa** (a linha 27 é do `config.py`; o `app.py` já importa de lá).
> Backend: PR B4 (DB bootstrap) = Issue #507 — `SCHEMA_VERSION`,
> `_record_schema_version`, `init_db()` (576 linhas) e `purge_old()` para
> `services/bootstrap.py`; `app.py` 9.084 → 8.444 linhas. Achado: o `get_db` do
> `app.py` era uma **duplicata idêntica** de `services.db.get_db` — eliminada.
> **Postmortem da trilha backend: [`478-postmortem.md`](./478-postmortem.md)**
> (Issue #511) — divergências plano × realidade, achados por PR e lições
> acionáveis para os PRs de frontend 2–6.
> **Alerta ao executar o PR 2 (Market):** a descrição "orderbook, rent offers"
> desta tabela **não corresponde ao código** (não existe orderbook); o cluster é
> o grid de venues do `/api/market/*` + `market_data.offers`, espalhado em 4
> regiões disjuntas com o domínio Admin inteiro entre duas delas. Detalhes no
> postmortem, §7.
> **Reordenacão de 2026-09-12 (Issue #525):** o frontend entregou 1, 1b, 2, 2b,
> 3, 4a e 4b — e depois 5 (#529) e 6 (#540); a **§3.3** mede os domínios que faltavam (a lista original parava
> em "5" e "6", mas são **cinco** PRs mais um residual) e fixa a ordem e o alvo
> de linhas. Também registra duas restrições estruturais recém-descobertas: o
> `boot()` é chamado **dentro** de `40-app-logic.js` (linha 6.388) e a lógica de
> **reconexão SSE** mora **dentro** do `boot`, não num módulo.

## 1. Contexto e problema

| Arquivo | Linhas | Consequência |
|---|---|---|
| `static/app.js` | 13.062 | Escopo global único; 171 `innerHTML` vs 294 `escapeHtml`; qualquer mudança de UI arrisca colisão de nome e regressão em domínio alheio |
| `app.py` | 9.435 | Bootstrap, SSE fan-out, snapshot assembly, gate de admin, licenças e rotas no mesmo módulo — todo PR de produto toca o monólito |

O objetivo **não** é reescrita: é extração mecânica e incremental, um domínio por PR, sem mudança de comportamento. O guard DOM (GUARD_REPORT por PR) é a régua: superfície XSS não pode crescer durante o split.

## 2. Restrições descobertas (investigação de 2026-09-10)

1. **Cache-bust single-file**: `dashboard.html` carrega `<script src="/static/app.js?v63" defer>` — uma tag, uma versão. Multi-arquivo exige bump de versão em todas as tags a cada PR (ou passos de build — rejeitados: custo $0 e zero-toolchain são princípios do repo).
2. **Harness JS core não importa o app.js**: `tests/test_app_js_core.js` **espelha** os helpers puros (re-implementações com o mesmo contrato) e `check_frontend.sh` roda `node --check static/app.js` — ambos assumem **um arquivo**.
3. **Sem bundler**: nenhuma build step hoje; manter assim.
4. **Contrato do backend é estável**: `routes/` já existe como padrão de extração provado (blueprints), e os guards DOM/mobile-XSS ignoram fronteiras de arquivo — operam por regex de conteúdo.

## 3. Estratégia proposta

### 3.1 Frontend — "concatenated modules" (zero build, zero risk de runtime)

Convencão por comentário-bloco + ordem de inclusão controlada. Duas opções tecnológicas:

- **Opção A (recomendada)**: um único `app.js` **gerado** por concatenação (`static/src/*.js` → `static/app.js`) via script `scripts/build_app_js.cjs` (Node puro, ~40 linhas, sem dependências), rodado no pre-commit e validado no CI por `git diff --exit-code` pós-build. Preserva: single `<script>` tag, `node --check` direto, harness existente, cache-bust `?v64+`.
- **Opção B**: múltiplos `<script src>` com convenção de namespace por arquivo (`window.C65.market = {...}`). Simples, mas multiplica tags de cache-bust e permite dependência implícita de ordem de carregamento escondida.

**Decisão pedida**: A vs B. Ambas mantêm escopo global (refactor puro); módulos ES `type="module"` ficam explicitamente fora do escopo (mudaria semântica de `defer` + this + hoisting — não é extração mecânica).

Ordem de extração (uma PR por domínio, cada uma ≤ ~1500 linhas movidas):

| PR | Domínio | Conteúdo aproximado |
|---|---|---|
| 1 | Infra de build + `fmt/escape` | ✅ #489 (PR #491) — `build_app_js.cjs`, `static/app.js` vira artefato gerado; a suíte core passa a carregar os helpers puros **do fonte** via `loadFragment()`, eliminando o drift do espelho |
| 1b | Correção dos defeitos revelados pelo PR 1 | ✅ #490 — `fmt.age` (`0h ago` para 1h-24h), `fmt.secsToHuman(null)` (TypeError) e `fmt.pct(null)` (`0.00%`) |
| 2 | Market | ✅ #513 — **premissa da tabela corrigida**: não existe `orderbook` no código (zero ocorrências em `static/`); o domínio real é o grid de venues do `/api/market/*` + `market_data.offers` + BUY afiliado + tendência 7d, e ele **não é contíguo** — estado, grid/render e controles/tendência estão em 3 regiões disjuntas com o domínio Admin (~1.050 linhas) e Decision Matrix/Command Center entre elas. Foram para `static/src/45-market.js` (455 linhas): `_mktFilter`…`_mktInstitutional`, `_fmtBtcPerTh`/`_mktUsdPerTh`/`_mktSourceLabel`/`_mktBestIndex`, `MKT_RENDER_CAP`/`_mktRenderCap`/`sortMarketVenues`/`renderMarketGrid` (+ `venueFreshness` aninhada), `renderMarket`, `initMarketControls`, `buildMarketTrendDatasets`/`loadMarketTrend`. `40-app-logic.js` 12.666 → 12.236 linhas. **Prova de movimento mecânico**: `static/app.js` gerado é uma permutação do anterior — 0 linhas perdidas, 25 adicionadas (todas comentário). Achado: o harness JS ainda espelha helpers do Market e carrega uma **suíte legada** do card grid substituído pelo redesign institucional — **resolvido na Issue #515**: os 6 espelhos fiéis passaram a carregar de `loadFragment('45-market.js')` e as 108 asserções que espelhavam código inexistente (card grid + gráfico antigo) foram removidas |
| 3 | Rentals | ✅ #517 — **fronteira corrigida no número**: o nome `55-rentals.js` previsto não existe porque `50-close.js` FECHA o IIFE (nada pode vir depois); o fragmento é `static/src/46-rentals.js`. O cluster é **contíguo** (4.616–6.385, **1.770 linhas**) mas **excede o guardrail de ~1.500** — aceito explicitamente pelo mantenedor num único PR, já que o cluster é coeso e a prova de permutação torna a revisão mecânica. Conteúdo: estado (`_rentalsLoaded`…`_rentalsRigChart`), núcleo (`_setRentalsFilter`, `_renderRentalsPortfolio`, `_mrToTh`, `_rentalStatus`/`_rentalHashrateStr`/`_rentalPriceStr`/`_rentalRigTrust`/`_rentalIsBad`), painéis (reco, accepted, auto-exclusions, market timing, forecast, risk banner, signals, consolidado), série + drill-down, analytics click-first (rankings, heatmap, expiring, worst-rig, exposure, concentration), modais (`openRigTrackRecord`, `runBacktest`, `openBacktestModal`, `openRentalDetail`) e `loadRentals`/`renderRentals`/`_initRentalsPanel`. `40-app-logic.js` 12.236 → **10.465 linhas**. **Zero statements no topo** (verificado) → o fragmento entra antes de `50-close.js` sem TDZ; acoplamento externo de só 4 pontos (`_initRentalsPanel`, `loadRentals`, `_rentalsLoaded`, `_rentalsData`). **Prova**: 0 linhas perdidas no artefato gerado (24 adicionadas, todas comentário) + 8 specs e2e do domínio verdes. Ficaram fora: modal de compra spot da Braiins, AI Operator e Auto-Pilot |
| 2b | Admin/CFO/CRO *(não estava no plano original)* | ✅ #518 — o bloco ficou **isolado e visível** quando o Market saiu (é o vizinho que separava as regiões R1 e R2 dele), então virou extração própria. `static/src/47-admin.js` (**1.057 linhas movidas**): builders puros do audit trail, `fetchAdminData`, `_renderAdmin` + renderers (analytics, docs feedback, features, funnel trend, coortes LTV, pool metrics, error rate, degradação, audit trail) e CSV/filtros. `40-app-logic.js` 10.465 → **9.407 linhas**. Nome corrigido: o previsto era `52-admin.js`, mas `50-close.js` fecha o IIFE → é `47-admin.js`. **Único dos três fragmentos com execução no topo**: 4 statements registram listeners (`#admin-panel` change, `#admin-audit-csv`/`#admin-funnel-csv`/`#admin-refresh-btn` click); nenhum depende de ordem e o `app.js` é `defer`, então mover para o fim do mesmo IIFE é inócuo — **provado com mutação**: desligar o listener de refresh faz a e2e falhar |
| 4a | Fleet/AXE · Fleet Command Center + telemetria | ✅ #521 — **o PR 4 foi dividido em dois** (ratificado pelo mantenedor): o cluster tinha **1.695 linhas** e a seção 4 fixa ≤ ~1.500 por fragmento. `static/src/48-fleet-cc.js` (**393 linhas movidas**): `parseBestDiff`, `_numOrNull`, `_ccKpiAgg`, `_ccShareBar`, `_ccSvgSparkline`, `_ccTempBand`, `_ccRenderNetwork`, `_updateFleetBestShare`, `renderFleetCommandCenter`, `_logMiningEvent`, `_ccRenderFleet`, `_ccRenderExceptions`, `_ccRenderThermal`, `_ccRenderCards`, `_ccRenderTable`. `40-app-logic.js` 9.407 → **9.011 linhas**. **Duas regiões disjuntas** (4.792-4.987 e 5.031-5.227 no pré-recorte): `_initLmEventLogControls` — UI do terminal de eventos do Live Mining, que é **PR 5** — ficava **entre** as metades e permanece no app-logic. **Zero execução no topo** e **zero `const`/`let`/`var`** na região → nenhuma superfície de TDZ, mesmo com o fragmento entrando depois de `47-admin.js`. Acoplamento externo de 3 pontos, todos no mesmo IIFE: `renderFleetCommandCenter` ← `render()`, `_ccRenderFleet` ← `initFleetCommandCenterControls()`/chip de view, `_numOrNull` ← `buildCommandCenterRows` (região B). **Prova**: 0 linhas **não-brancas** perdidas no artefato gerado (28 adicionadas, todas comentário) + `live-mining.spec.js` (4) e `dashboard.spec.js` (58) verdes |
| 4b | Fleet/AXE · AXE Fleet (cards, scan LAN, wizard, agente, remoto) | ✅ #523 — fecha o domínio Fleet/AXE. `static/src/49-axe-fleet.js` (**1.304 linhas movidas**, dentro do guardrail): `renderTailscale`/`fetchTailscale`/`renderRemoteOnboarding`/`fetchRemoteOnboarding`, `fetchAxeFleet`, `scanNetwork`/`renderScanResults`/`renderAxeScanResults`/`startAxeScan`/`initAxeScanControls`, `renderAxeFleet`/`_renderAxeCard`/`_handleAxeCmdClick`/`openAxeDetail`/`loadDeviceHistoryChart`, `buildCommandCenterRows`, o hash-flow raster (`_lmShareDelta`/`_lmFlowSampleFromDelta`/`_lmFlowDetail`/`_pushLmFlowSample` — prefixo `_lm` mas consumidos **só** pelo `_ccRenderFleet`), `fetchFleetCommandCenter`/`initFleetCommandCenterControls`, o wizard (`gotoAxeWizStep`/`setAxeWizMode`/`resetAxeWizard`/`renderAxeConfirm`/`testAxeConnectivity`/`buildConnectivityReport`/`renderConnectivityReport`/`openAxeAddForm`), `initAxeFleetControls`, `initAxeAgentPanel` e `addAxeDevice`. `40-app-logic.js` 9.011 → **7.706 linhas**. **Um statement de topo** (o listener de `#remote-test-btn`), igual ao Admin; **7 `const`/`let` na região, nenhuma referenciada fora dela** e **sem TDZ** — o prefixo síncrono do `boot()` chama `initAxeFleetControls()` → `initAxeScanControls()`/`initAxeAgentPanel()`, e os três corpos foram varridos sem acesso síncrono a variável movida. Acoplamento externo de 6 nomes (`fetchAxeFleet`, `fetchRemoteOnboarding`, `fetchTailscale`, `initAxeFleetControls`, `openAxeDetail`, `initFleetCommandCenterControls`). **Prova**: 0 linhas perdidas (nem brancas) no artefato gerado — 36 adicionadas, todas comentário — + `auth` (20), `live-mining` (4), `operational-overview` (6), `auto-pilot-advisory` (2) e `dashboard` (58) verdes. **Wart RESOLVIDO na Issue #525** (PR de limpeza): o resíduo do FCC que ficou aqui por vizinhança textual — o raster de hash-flow (`_lmFlow`/`_lmLastCounters`/`_LM_FLOW_MAX`/`_LM_FLOW_LABELS` + `_lmFlowSampleFromDelta`/`_lmShareDelta`/`_lmFlowDetail`/`_pushLmFlowSample`), o `fetchFleetCommandCenter()` e o `initFleetCommandCenterControls()` — **75 linhas** voltaram para `48-fleet-cc.js`. Isso eliminou uma **dependência invertida** que a divisão 4a/4b criou: o `48` (avaliado ANTES) consumia 8 nomes definidos no `49` |
| 5 | Terminal/SSE | ✅ reordenado e detalhado em **§3.3** (Issue #525 mediu o residual) |
| 6 | Alerts/Auto-Pilot | ✅ reordenado e detalhado em **§3.3** (a lista original tinha só 2 PRs restantes; são **5**, mais o residual) |

### 3.3 Frontend — domínios que NÃO estavam no plano original + reordenação até a meta

**Reconhecimento de 2026-09-12 (Issue #525).** Depois do 4b, `40-app-logic.js` estava em **7.706 linhas** — contra a meta de ~4.000 do §7. A tabela original do §3.1 parava em "5 Terminal/SSE" e "6 Alerts/Auto-Pilot", o que dava a entender que faltavam **2 PRs**. O inventário linha a linha mostra que faltam **cinco domínios** (e um residual).

**Método.** Todas as 381 declarações de topo do `40-app-logic.js` foram mapeadas com sua linha de início; os blocos abaixo são intervalos **contíguos** que cobrem o arquivo **sem lacuna nem sobreposição** (somam 7.700 linhas; a diferença para 7.706 são as bordas do IIFE).

| Bloco | Linhas | Domínio |
|---|---|---|
| R1 | 923 | **Billing/Auth** — sessão, licença/\(PRO\), fluxo de upgrade on-chain (BTC/WebLN), `auth*`, indicador de instância, `handleLicenseRequired` |
| R2 | 38 | Theme (apply/toggle/persistência) |
| R3 | 599 | **Wallet crypto** — WebLN (`detectWebLN`/`connectWebLN`), bech32, validação de endereço, gerador de QR inteiro (`QrPoly`/`qrEncode`/`qrSvg`) |
| R4 | 163 | Primitivas DOM/UX — skeletons, `smoothUpdate`, `countUpValue`, `setBtnLoading`, modais animados |
| R5 | 333 | HUD/StatusBar + **Operational Overview** (`buildOperationalOverviewModel`) |
| R6 | 233 | Painéis do dashboard — `renderWalletIdentity`/`renderHostCore`/`renderHero`/`renderMinersXRay`/`renderNetwork` |
| R7 | 143 | **Alerts/eventos** — `renderAlerts`/`renderEvents`/`renderLeaderboard` + preços/halving/mempool |
| R8 | 102 | Gráficos do dashboard + share-dist |
| R9 | 243 | **Terminal de eventos/Timeline** — `logMessage`, error beacon do cliente (`window.onerror`), `renderTerminalEvents`/`renderTimelineFeed` |
| R10 | 276 | **Probability/Block Model** — `renderProximity`, `renderQuantumLock`, `renderLiveCalc`, `renderNetworkGauge` |
| R11 | 214 | Profitability/Comparison/SoloStats/Milestones |
| R12 | 145 | Block Hunt (what-if de dificuldade) |
| R13 | 140 | Decision Matrix + Command Center |
| R14 | 270 | Modal de compra spot da Braiins (vizinho do Market) |
| R15 | 41 | AI Operator |
| R16 | 538 | **Auto-Pilot** — arming, advisory, dry-run |
| R17 | 178 | AI Chat |
| R18 | 360 | `render()` + infraestrutura de gráficos (SMA, anotações, zoom, `makeChart`) |
| R19 | 277 | **Settings** (`renderSettingsForm`/`loadSettings`) |
| R20 | 433 | **Support** — doações, Lightning (`sendLNPayment`), modal/histórico da wallet |
| R21 | 19 | Modal de export |
| R22 | 161 | **Terminal do Live Mining** (`_lm*`, `_initLmEventLogControls`) + estado do FCC |
| R23 | 369 | **Terminal solo / live terminal** (`_soloTerm*`, `_termBindInput`, `_liveTermInit`) |
| R24 | 40 | Loop de poll/relógio/snapshot |
| R25 | 148 | **`boot()`** |
| R26 | 241 | **Automations** (`ac*` — `acLoadRules`/`acRenderExecutions`/tabs) |
| R27 | 323 | Shell — sidebar, `MODULE_MAP`, sistema de módulos, beta analytics, `activateModule` |
| R28 | 131 | Status da sidebar + refresh de wallet |
| R29 | 196 | `InstitutionalUI`/`DashboardCore` |
| R30 | 395 | **Docs** — índice, busca, snippets, feedback |
| R31 | 28 | `renderKpiCards` |

#### Reordenação dos PRs restantes (domínio por PR, nunca por tamanho)

**O erro que esta reordenação corrige é de método, não de ordem.** O 4a/4b foi dividido **por tamanho** (o cluster tinha 1.695 linhas e o guardrail manda ≤ ~1.500), e essa divisão cortou no meio de um bloco fisicamente entrelaçado — o que produziu exatamente o resíduo de posse que a Issue #525 acabou de realocar (75 linhas de FCC morando no fragmento do AXE Fleet, com a dependência entre os dois **invertida**). A partir daqui a regra é: **um PR = um domínio, e nenhum PR parte um domínio ao meio.** Todos os blocos abaixo são ≤ 1.500, então a régua não força mais nenhum corte.

| PR | Domínio | Blocos | Linhas movidas | `40-app-logic.js` após | Execução no topo |
|---|---|---|---|---|---|
| **5** | Terminal/SSE | R9 + R22 + R23 | ✅ **#529** (PR #530) — **752 linhas** movidas para `static/src/39-terminal.js` (804 com cabeçalho) | **6.959** | 3 (`window.onerror`, `unhandledrejection`, `#clear-logs` click) |
| **6** | Automations + Alerts + Auto-Pilot + Decision Matrix/Command Center | R7 + R13 + R16 + R26 | ✅ **#540** (PR #541) — **1.073 linhas** movidas para `static/src/41-automations.js` (1.140 com cabeçalho): R7 2.275–2.423 (149), R13 3.165–3.305 (141), R16 3.615–4.155 (541), R26 5.630–5.871 (242) — recorte medido sobre a master **pós-#538**, que deslocou o arquivo em −13 linhas antes do corte (2.288→2.275). A projeção era 1.062 — a diferença são os **comentários de seção**, que viajam com o recorte verbatim | **5.877** | 1 (`if (dom.openAlertCenter)` em R26) |
| **7** | Probability/Block Model | R10 + R11 + R12 | ✅ **#542** (PR #543) — **635 linhas** para `static/src/42-probability.js` (670 com cabeçalho); o cluster é **contíguo** (2.381–3.015, exatamente a projeção de 635) | **5.243** | 1 (`window.setProfitMode = …`) |
| **8** | Billing/Auth | R1 | ✅ **#545** (PR #547) — **924 linhas** (linhas 1–924) para `static/src/38-billing-auth.js` (969 com cabeçalho), que entra **ANTES** do 40 | **4.320** | 1 (`window.openUpgradeModal = …`) |
| **9** | Wallet + Support | R3 + R20 | **1.032** | **3.307** | **17** — o maior de todos: listeners de WebLN/wallet, `renderSupportMethods()`/`loadDonations()` chamados direto no topo, e a região **vendorada do QR** (`(function buildQrMath(){…})()` + `QrPoly.prototype.*`) |
| — | **residual** — Dashboard (`render()`/gráficos/HUD/overview/painéis), Docs, Settings, Export, Braiins buy, AI Chat/Operator, Theme, primitivas DOM, shell (sidebar/módulos), `boot()` | R2+R4+R5+R6+R8+R14+R15+R17+R18+R19+R21+R24+R25+R27+R28+R29+R30+R31 | — | **≈3.307** | — |

Os valores de `40-app-logic.js` após cada PR carregam o delta real do PR 5 (−747, não −773): ficaram no god file o bloco de estado do FCC (`_cc*`, 5 linhas, que **não pode** mover — ver abaixo) e o global compartilhado `_lastSnapshot` (5 linhas).

**A meta de ~4.000 linhas é atingida no PR 9** (com os PRs 6, 7 e 8 executados, o PR 8 para em **4.320** — ainda acima da meta — e o PR 9 leva a ~3.288: 4.320 − 1.032). O residual ainda tem domínios extraíveis — inclusive um PR 10 natural de **Dashboard/`render()`** (R5+R6+R8+R18+R24+R31 ≈ 1.096) — mas eles ficam **fora da meta**; a lista acima é o que fecha o objetivo.

**Nota de risco do PR 6.** O bloco R26 (Automations) tem 1 statement de topo (`if (dom.openAlertCenter)`, listener do Alert Center) e R7/R13/R16 têm 0. O PR deve rodar a mesma varredura de TDZ do 4b antes de mover — com um cuidado a mais: o scan ingênuo de "linha não-declaração em indent 2" acusa **12 statements** no PR 6, dos quais **11 são falsos positivos** das funções sem indentação (`acctRankLabels`/`renderAccount`). Quem for medir precisa tratar declarações em **coluna 0** também.

**Achado do PR 6 (posicionamento) — a varredura confirmou a previsão, e o fragmento pôde ir DEPOIS do 40.** O scan de indent 2 acusou exatamente 12 "statements" (11 deles corpos das funções em coluna 0: `acctRankLabels`, `renderAccount`); o único statement real é o `if (dom.openAlertCenter)` do R26. Como a regra da §3.3 é sobre **estado** lido por chamada de nível de módulo — e não sobre statements —, o teste decisivo foi outro: varredura dos **12 nomes de estado movido** (`_lastCcKey`, `_apArmed`, `_apToggleInit`, `_apAuto`, `_apAutoToggleInit`, `_apRecs`, `_apAudit`, `_apRecsInit`, `_apDrInit`, `acState`, `severityClass`, `severityLabel`) em todo o `40-app-logic.js` fora dos blocos e em todos os outros fragmentos → **0 leituras** (a única menção é um comentário em `setHtmlIfChanged` citando o `_lastCcKey` do Command Center). O prefixo síncrono do `boot()` chama deste domínio só `initDecisionMatrixControls()`/`initCommandCenterControls()` (R13) — declarações de função, hoisted, e ambas leem apenas `document`. O resto (`render()` → `renderAccount`/`renderBtcPrices`/`renderHalving`/`renderMempoolFees`/`renderDecisionMatrix`/`renderAlerts`/`renderEvents`/`renderLeaderboard`/`renderCommandCenter`, e `renderAiOperator` → `_apSetUi`/`_initAutoPilot*`) só roda via `await fetchSnapshot()` ou pelo `onmessage` do SSE — isto é, depois de o IIFE inteiro ser avaliado. O `restoreActiveModule` (IIFE de topo) → `activateModule` → `_doActivateModule` foi varrido e não toca nenhum símbolo movido. Consequência: o PR 6 é o **primeiro fragmento de domínio que entra depois do 40 sem precisar de exceção** — a exceção do `39-terminal.js` continua sendo a única.

**Onde ele entra.** `41-automations.js`, entre `40-app-logic.js` e `45-market.js` (ordem de execução preservada quanto ao resto: os 4 blocos já eram lidos só por funções). **Prova**: `app.js` = os fragmentos do `HEAD` com os 4 blocos realocados **verbatim** — sequência de linhas de código (não-comentário/não-branco) idêntica, 10.924 = 10.924; 0 linhas perdidas e 0 linhas de código adicionadas (só comentários e espaços). **Prova de mutação**: desligar a injeção da tab-strip dentro do statement de topo do R26 derruba `alert-center-tabs` (4/4 falham) — o único código de execução no topo do fragmento está coberto.

**Ganho de cobertura de boot:** como os blocos saíram do meio do god file para um fragmento próprio, a e2e de alert-center/automations/auto-pilot passa a exercitar o domínio a partir do fragmento (nenhuma mudança de comportamento — a ordem de avaliação do IIFE é a mesma para funções).

**Achado do PR 7 (#542) — contiguidade confirmada e a mesma régua, sem exceção.** O cluster R10+R11+R12 é **fisicamente contíguo** (2.381–3.015 na master pós-#541): 635 linhas, exatamente a projeção da §3.3 — nenhum corte precisou ser negociado (ao contrário do 4a/4b). A varredura de TDZ deu o mesmo veredito do PR 6: o único statement de topo da faixa (`window.setProfitMode = setProfitMode;`) viaja junto, e os 5 nomes de estado (`_proxSparklineData`, `_profitMode`, `_lastProfitability`, `_bhBase`, `_bhSliderEl`) têm **zero** leituras fora da faixa — inclusive o bloco de topo do `#bh-whatif-slider`, que **fica** no god file e apenas registra handlers (`input` → `_bhRenderWhatIf`, reset). O `boot()` síncrono não toca o domínio; `42-probability.js` entra depois do 40.

**Achado do PR 8 (#545) — o primeiro domínio que PRECISA vir antes do 40 desde o PR 5.** O R1 é o topo do god file (linhas 1–924) e a régua da §3.3 reprova o "depois do 40": o prefixo **síncrono** do `boot()` chama `initLicensing()` (lê o `let _license`, via `renderLicenseBadge`/`syncUpgradeModal`/`syncAiPremiumUi`), `initAuth()` e `initInstanceIndicator()`. Com o fragmento depois do 40, esse estado estaria em **TDZ** no boot → `ReferenceError`. Antes, o estado já está inicializado. É também a **ordem original** (o R1 era a linha 1, antes do bloco de terminal da linha 2.540): como o `39-terminal.js` já mora antes do 40, o novo fragmento entra como `38` — antes do 39 — e o error boundary volta a cobrir a avaliação do domínio, exatamente como cobria antes do split. Verificações: 1 statement de topo na faixa (`window.openUpgradeModal = openUpgradeModal;`, que só atribui referência), **zero** declarações/statements em coluna 0, nenhuma linha de nível de módulo do R1 lê estado definido depois no IIFE, zero colisão dos 7 nomes de estado com os outros 13 fragmentos, e o único consumo externo (`_license` em `aiCanUseReal()`, aninhada no `_initAiChat`) é caminho de runtime.

**Duas lacunas de cobertura registradas pelo PR 7 (honestidade > prova bonita).** (1) Uma mutação no *math* (`simulateDifficultyShift` retornando `base`) **sobrevive**: `probability-whatif.spec.js` pula a comparação numérica quando o servidor não tem dados de pool (guard `hasData`, com `#bh-whatif-diff` = '—'), e `base` coincide com o resultado correto com o slider em 0. (2) A SUITE 33 do harness JS **espelha** o what-if em vez de carregar o fragmento — o mesmo padrão que escondeu 3 defeitos reais no PR 1. A prova de mutação válida foi feita no caminho que o spec sempre executa (o badge do `_bhRenderWhatIf` → 6/6 falham). Follow-up natural: estender o `loadFragment()` do PR 2 (#515) à SUITE 33 e dar ao spec um caminho de dados determinístico.

#### Duas restrições estruturais que governam todos os PRs §3.3

1. **`boot()` é chamado no topo do IIFE — em `40-app-logic.js`, linhas 6245–6388.** O `boot();` nu está na linha 6388, ou seja: ele é executado **durante a avaliação do 5º de 11 fragmentos**, ANTES de `45-market.js` … `49-axe-fleet.js` existirem (os `function` declarations sofrem hoisting no IIFE único, então são chamáveis; os `const`/`let` deles ainda estão em **TDZ**). É essa a origem de toda a análise de TDZ registrada no Admin (2b) e no 4b — e a razão pela qual o prefixo síncrono do `boot` não pode ser tocado.

   **Correção (medida ao executar o PR 5, Issue #529):** a previsão original desta seção — "o fragmento de Terminal/SSE entra **depois** do `boot`, como todos os outros" — estava **errada**, e o erro é instrutivo. O corpo síncrono do `boot` **lê estado do Terminal**: `_initLmEventLogControls()` (que chama `_lmRenderStats()` → `const _lmStats`), `_liveTermInit()` e `logMessage('SYSTEM', …)` (que faz `events.push(...)` → `let events`). Com o fragmento **depois** do 40, esse estado estaria em **TDZ** nesse instante → `ReferenceError` no boot. Logo:

   > **Regra de posicionamento.** Um domínio cujo estado seja lido por uma chamada de **nível de módulo** do `40-app-logic.js` (o `boot();` da linha 6.388, ou qualquer `X()` executado no topo, como o `renderSupportMethods()` do domínio Wallet) tem de ser posicionado **ANTES** do god file. Caso contrário, seu estado precisa permanecer no god file. É a primeira exceção à regra "45–49 vêm depois".

   O PR 5 usou a primeira opção: `static/src/39-terminal.js` é o primeiro fragmento **anterior** ao 40. A consequência deliberada é que o error boundary global (`window.onerror`/`unhandledrejection`) passa a cobrir também a avaliação do `40-app-logic.js` — estritamente mais proteção, nunca menos.

   **O PR 6 (#540) passou pela mesma régua e NÃO precisou da exceção:** nenhum dos 12 nomes de estado do domínio é lido por chamada de nível de módulo do 40, e o fragmento `41-automations.js` entrou **depois** dele. A varredura é o que decide — não o tamanho nem a posição textual do bloco original.
2. **A lógica de conexão/reconexão SSE mora DENTRO do `boot()`** (o `EventSource`, o debounce de 2s e o fallback para polling após 5 erros vivem em `40-app-logic.js`, ~6.340–6.383) — **não** em um módulo próprio. O item "reconexão" do PR 5, portanto, **não é uma extração mecânica**: tem duas opções. **(a)** mover só os terminais (R9+R22+R23) e deixar o bloco SSE no `boot`, documentando o acoplamento — é o que mantém a disciplina de "nenhum comportamento novo" e é a recomendação. **(b)** extrair o bloco SSE para uma função `connectLiveStream()` no fragmento do Terminal/SSE — é um refactor pequeno e legítimo, mas **não** é movimento verbatim e merece PR próprio. Registro isto agora para ninguém descobrir no meio do PR (o fan-out do lado do servidor já foi para `services/sse.py` no B2).

**Achado de forma, não de estrutura.** R6/R7 contêm uma "bolha" sem indentação: `renderPool` (2.242), `acctRankLabels` (2.294) e `renderAccount` (2.320) estão **em coluna 0** enquanto o resto do arquivo usa 2 espaços para declaracões de topo. Não quebra nada (`acctRankLabels` é espelhado nos testes), mas quem for mover R6/R7 deve preservar o recorte verbatim e não "aproveitar" para reindentar — isso infla o diff e destrói a prova de permutação.

**O que os relatórios de guard DOM esperam.** R13/R16/R26 são os domínios com mais `innerHTML` dinâmico da parte restante; a régua do §4 (superfície XSS não cresce) continua valendo por PR.

### 3.2 Backend — continuar o padrão `routes/` + extrair módulos de domínio

O padrão já existe (`routes/*.py` com blueprints) — o RFC o estende:

| PR | Extração | De `app.py` para |
|---|---|---|
| B1 | Admin gate + licenças | ✅ #495 — gate `_admin_request_allowed` + 10 rotas `/api/admin/*` → `routes/admin_routes.py` (blueprint `admin_bp`), `app.py` re-exporta o gate. `issue_license` já vivia em `services/licensing.py`: nada a mover. Achado: `/api/admin/sessions` sem gate → #496 ✅ corrigida (gate aplicado, conjunto de rotas sem gate agora vazio) |
| B2 | SSE fan-out | ✅ #499 — `_sse_clients` + lock, `broadcast_snapshot()` e `GET /api/stream` → `services/sse.py` (blueprint `sse_bp`, sem `url_prefix`), `app._broadcast_snapshot` re-exporta o MESMO objeto. `url_map` provado idêntico (178 regras, mesmo path/método) e o `import queue` do `app.py` saiu junto. O módulo nasceu com contrato próprio (11 testes) — antes o SSE tinha **zero** cobertura, porque a única régua era um navegador |
| B3 | Snapshot assembly | ✅ #501 — **premissa corrigida**: a origem é `services/user_polling.py`, não `app.py` (o `app.py` só importava `_build_snapshot`). Foram para `services/snapshot_assembly.py`: cache global LRU + `_get_global`/`_update_global`/`_cached_user_fetch`, constantes de fetch, `btc_price_cache`, `_fetch_json`/`_fetch_text`, os 6 `_fetch_global_*`, `_fetch_user_data`/`_fetch_account` e `_build_snapshot` (528 linhas). `user_polling.py` 1.606 → 1.152 linhas e re-exporta os 24 nomes. **Caveat de monkeypatch**: o fetch layer resolve os nomes nos globals do módulo novo — quem patcheava `services.user_polling._fetch_*` passou a mirar `services.snapshot_assembly` (3 arquivos de teste retargetados, um deles passava *vacuamente* sem interceptar) |
| B4 | DB bootstrap/schema | ✅ #507 — `SCHEMA_VERSION` + `_record_schema_version` + **`init_db()` (576 linhas: tabelas, ALTERs guardados por `PRAGMA table_info`, índices, pragmas e o carimbo da revisão)** + `purge_old()` → `services/bootstrap.py` (678 linhas, sem importar `app`). Schema provado **idêntico** antes/depois (73 objetos no `sqlite_master`, mesmo SQL) e idempotente. O item **“WAL”** do RFC era o `get_db()` — que existia **duplicado**: `app.get_db` ≡ `services.db.get_db` (mesma expressão de fallback `os.environ.get("DB_PATH", "data/war_room.sqlite")`, mesmos pragmas). A duplicata morreu: `app.get_db is services.db.get_db`, uma implementação só. `app.py` 9.084 → 8.444 linhas |

Regra dura: **cada PR-B mantém o gate de cobertura 80% e não pode reduzir a cobertura de `app.py`** (linhas movidas continuam cobertas nos novos módulos — import re-export temporário em `app.py` permite migração sem big-bang).

Mecanismo fixado no B1 (#495): o módulo extraído entra no `--cov` do `ci.yml` (`--cov=routes.admin_routes`). O código sai de `app.py` mas **não** sai da régua — o conjunto medido continua sendo o mesmo, então o TOTAL não pode "melhorar por subtração". Cada PR-B acrescenta o módulo novo da vez ao mesmo `--cov`.

Nuance fixada no B2 (#499): se o destino já está dentro de um `--cov` agregado, **nada** é acrescentado — `services/` é medido inteiro por `--cov=services`, então `services/sse.py` (B2) e `services/snapshot_assembly.py` (B3) nasceram na régua. O `--cov` explícito por arquivo só é necessário para módulos **fora** de `services/` (caso de `routes.admin_routes` no B1).

## 4. Guardrails por PR (checklist de aceite)

- [ ] `node --check static/app.js` (ou `python -m flake8` no módulo novo) verde
- [ ] `tests/test_app_js_core.js` 100% verde (Opção A: passa a validar contrato extraído do fonte)
- [ ] `npm run check:frontend` completo verde
- [ ] GUARD_REPORT: superfície XSS (counts TL/concat/innerHTML) não cresce
- [ ] pytest completo verde, cobertura global ≥ 83% (não menor que a anterior)
- [ ] Nenhuma mudança de: rotas, ids DOM, contratos de fetch, formato de snapshot
- [ ] Diff do PR ≤ ~1500 linhas movidas (revisável em uma passada)

## 5. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Ordem de concatenação muda hoisting/ TDZ | Opção A mantém ordem atual dos blocos; `node --check` + suíte e2e pegam quebra |
| Drift entre arquivo gerado e fontes | CI roda build + `git diff --exit-code` (fonte des-sincronizada bloqueia merge) |
| Colisão de nomes entre domínios durante a migração | Nomes não mudam nesta fase (refactor puro); renames ficam para fase posterior opt-in |
| Cobertura cai com a mudança de módulo | Import re-export + `--cov` por módulo novo em cada PR-B |
| PRs interferindo (front × back) | Frontend e backend alteram arquivos disjuntos; sequência Front 1→6 e Back 1→4 pode rodar em paralelo |

## 6. Fora de escopo (explícito)

- Migrar para bundler/TS/ES modules
- Renomear identificadores ou reorganizar escopo global
- Mudar o protocolo SSE ou contratos de API
- Touch em `mobile/` (já modularizado; Knip + Biome cobrem)

## 7. Critério de sucesso

`static/app.js` torna-se artefato gerado; os domínios vivem em `static/src/*.js` de ≤ ~1500 linhas cada; `app.py` cai para ≤ ~4000 linhas (bootstrap + glue), com cada domínio em módulo testável isoladamente. Tudo isso **sem um único comportamento novo** entre PRs.

**Alvo do frontend (fixado em §3.3, 2026-09-12; PR 5 executado).** `40-app-logic.js` sai de **7.706** para **~3.288 linhas** ao fim do **PR 9**, atingindo a meta de ~4.000 (o PR 8 para em 4.320). O que sobra são ~3.300 linhas de **orquestração**: `boot()`, o loop de poll, o sistema de módulos/sidebar, `render()` e as primitivas de DOM — mais os blocos de Dashboard/Docs/Settings que ainda são extraíveis num PR 10+, fora desta meta.

Estado de execução:

| Trilha | Entregue | Restante até a meta |
|---|---|---|
| Frontend | 1, 1b, 2, 2b, 3, 4a, 4b (+ limpeza #525), 5 (#529), 6 (#540), 7 (#542) e 8 (#545) | **9** (§3.3) |
| Backend | B1, B2, B3, B4 (+ #496, #508) | **nenhum** — a trilha B fechou em 8.444 linhas de `app.py` |
