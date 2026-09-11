# Postmortem — RFC #478 (decomposição dos god files)

> **Issue:** #511 · **RFC:** [`478-god-files-decomposition.md`](./478-god-files-decomposition.md)
> **Escopo avaliado:** trilha backend B1–B4 (completa) + frontend PR 1/1b (completa). Frontend PRs 2–6 seguem pendentes.
> **Data:** 2026-09-11 · **Autor:** agente de execução do RFC
> **Método:** comparação do plano ratificado contra os diffs reais (`git show` por commit), contagem de linhas por etapa e revisão dos achados de cada PR.

---

## 1. Veredito

O RFC cumpriu o objetivo **sem um único comportamento novo** — nenhuma rota mudou, nenhum contrato de resposta mudou, nenhum id de DOM mudou. `app.py` saiu de 9.448 para 8.443 linhas (−10,6%) e `services/user_polling.py` de 1.606 para 1.152 (−28,3%).

Mas o plano **acertou menos do que parecia**: das 4 extrações backend, **uma tinha o alvo errado** (B3) e **uma escondia uma duplicação que o plano não suspeitava** (B4). Duas premissas escritas no próprio RFC e na issue derivada eram falsas. O maior valor entregue não foi o código movido — foi o que a movimentação **revelou**: 3 defeitos de produção no frontend, 1 rota de admin sem gate expondo dados de todos os tenants, 1 duplicata de conexão de DB e 1 teste que passou a não testar nada.

A lição central: **em refactor mecânico, a fase de recon é o produto.** Cada premissa não verificada virou retrabalho.

---

## 2. Cronologia

| Etapa | Issue | PR | Commit | Entrega |
|---|---|---|---|---|
| RFC ratificado (Opção A) | #478 | #488 | `741edb8` | Plano de split front + back |
| Frontend PR 1 | #489 | #491 | `359e35b` | `build_app_js.cjs`; `static/app.js` vira artefato gerado de `static/src/*.js`; harness passa a carregar o **fonte** |
| Frontend PR 1b | #490 | #494 | `7b3fc57` | 3 defeitos revelados pelo PR 1 (ver §4) |
| Backend B1 | #495 | #497 | `7b12097` | admin gate + 10 rotas `/api/admin/*` → `routes/admin_routes.py` |
| Segurança | #496 | #498 | `49c1ae8` | `/api/admin/sessions` ganha o gate (achado do B1) |
| Backend B2 | #499 | #500 | `ee45896` | SSE fan-out → `services/sse.py` |
| Backend B3 | #501 | #502 | `4e8e2ec` | cache + fetchers + `_build_snapshot` → `services/snapshot_assembly.py` |
| Limpeza | #503 | #504 | `d86f90b` | remove o ruído de `black` que eu introduzi no B3 |
| Guard de CI | #505 | #506 | `eb03762` | `scripts/check-monkeypatch-targets.py` (achado do B3) |
| Backend B4 | #507 | #509 | `1241b01` | `init_db()` + `purge_old()` → `services/bootstrap.py` |
| Sub-issue do B4 | #508 | #510 | `52fa57a` | `get_db()` passa a ser definido no bootstrap; `services/db.py` vira re-export |
| Este documento | #511 | — | — | Postmortem |

---

## 3. Divergências plano × realidade

Esta é a seção que importa para quem for executar o que resta.

| # | O plano dizia | A realidade | Custo |
|---|---|---|---|
| 1 | **B3 extrai a montagem de snapshot de `app.py`** | O código estava em **`services/user_polling.py`**; o `app.py` só importava `_build_snapshot` | O B3 **não encolheu o monólito** (`app.py` 9.084 → 9.084). O alvo real foi `user_polling.py` (1.606 → 1.152). Recon corrigiu a fronteira antes de mover código |
| 2 | **O item "WAL" do B1 era só "aplicar os pragmas"** | Os pragmas já existiam — em **duas** implementações idênticas: `app.get_db` ≡ `services.db.get_db` (mesma expressão de fallback, mesmos pragmas) | Duplicata eliminada no B4 e a #508 promoveu o `bootstrap.py` a dono único; o `services/db.py` virou re-export |
| 3 | **B1 inclui "licenças"** | `issue_license` **já vivia** em `services/licensing.py` | Nada a mover — o PR B1 ficou só com o gate e as rotas |
| 4 | **A #508 devia "reconciliar `config.DB_PATH` × `app.DB_PATH`"** | Premissa **falsa** — a linha 27 que originou a nota é do `config.py`, e o `app.py` já importa `DB_PATH` de lá com comentário explícito de *single source of truth* | Trabalho cancelado e registro corrigido na issue. **Erro meu**, escrito por leitura apressada de um grep sem checar de qual arquivo vinha a linha |
| 5 | **O harness JS "espelha" os helpers puros** (tratado como equivalente) | O espelho **divergia** do fonte: os helpers puros reais produziam saída diferente | Virou a Issue #490 (PR 1b): `fmt.age` (`0h ago` para 1h–24h), `secsToHuman(null)` (TypeError) e `pct(null)` (`0.00%`) — 3 defeitos **de produção** que o espelho mascarava. O espelho e o ledger `KNOWN_FMT_DRIFT` foram removidos |
| 6 | **B2 move o SSE** (sem menção a testes) | O SSE tinha **zero** cobertura — a única régua era um navegador | O módulo nasceu com contrato próprio (11 testes), incluindo evicção de fila cheia e keepalive |
| 7 | **Cada PR-B "mantém o gate de 80%"** (mecanismo não especificado) | Mover linhas para fora do `--cov` **melhora** o TOTAL por subtração | Mecanismo fixado no B1: o módulo novo entra no `--cov` do `ci.yml`. Nuance fixada no B2: se o destino já está num `--cov` agregado (`--cov=services`), nada é acrescentado |
| 8 | **O PR 2 do frontend cobre "orderbook, rent offers, BUY button"** | **Não existe orderbook no código** (zero ocorrências em `static/`). O que existe é o grid de venues do `/api/market/*` + `market_data.offers` e o BUY afiliado — e ele **não é contíguo**: estado em ~3.422, grid em ~4.552–4.793, `renderMarket`/handlers em ~4.784–4.930, `loadMarketTrend` em ~5.007, e **dois pontos de chamada fora do bloco** (~7.896 e ~11.841) | Recon obrigatório antes de fixar a fronteira (§7) |

---

## 4. Achados por PR

### Frontend PR 1 (#489) — o drift que escondia bugs

`static/app.js` passou a ser **gerado** de `static/src/*.js` (concatenação pura, zero bundler). O ganho imediato não foi a modularização: foi que o harness de testes passou a carregar os helpers **do fonte**, e aí a divergência entre o espelho e a produção ficou visível. Daí o PR 1b.

**Padrão reutilizável:** um teste que re-implementa a coisa testada não é um teste — é uma segunda implementação com o mesmo nome. Ele só detecta o que ambas as cópias erram igual.

### Backend B1 (#495) — a rota sem gate

`GET /api/admin/sessions` era a **única** rota `/api/admin/*` sem `_admin_request_allowed()` e devolvia `btc_address` + `tenant_id` de **todos** os tenants para qualquer origem. A rota vizinha (`/pool-metrics`) era gateada.

O refactor **não** corrigiu isso (mudança de comportamento sai do escopo de extração mecânica) — abriu a Issue #496 (P1, security), corrigida no PR #498. O teste novo travou o conjunto: uma rota `/api/admin/*` futura sem gate **quebra o CI**, e gatear o `sessions` também (obrigando a movê-lo para `GATED_ROUTES`).

**Não quebrou o painel:** `fetchAdminData()` já buscava as 8 rotas num único `Promise.all` e tratava 403 no lote.

### Backend B2 (#499) — o módulo que nasceu com contrato

O SSE era o único subsistema **sem nenhum teste**. A extração foi a oportunidade de escrever o contrato. A única régua anterior era um navegador aberto.

### Backend B3 (#501) — o teste que passava sem testar

O achado mais desconfortável do RFC. `tests/test_anti_mock.py` patcheava `services.user_polling._fetch_*`. Com o fetch layer mudando de casa, os patches **deixaram de interceptar**: o `_build_snapshot` foi à rede real, caiu no `except` e devolveu o snapshot default — e as asserções (`network.stale` / `btc_price.stale` presentes e `False`) **continuavam satisfeitas pelos defaults**.

Passou verde no primeiro run. Só apareceu porque o retarget dos 3 arquivos foi verificado um a um.

**Mitigação:** o guard `scripts/check-monkeypatch-targets.py` (#505) detecta patch em alvo órfão (re-export puro), com escape hatch documentado (`# orphan-patch-ok: <motivo>`) e exceção para **import tardio dentro de função** (que de fato intercepta). O guard reproduz esse caso real como caso de teste.

### Backend B4 (#507) — a duplicata que o item "WAL" escondia

`app.get_db` era funcionalmente **idêntico** a `services.db.get_db` — mesma leitura de `DB_PATH` em call time, mesmos pragmas, mesmo fallback. O `app.py` já contornava isso importando o canônico *dentro* de funções. A duplicata morreu.

O contrato novo separa duas responsabilidades que estavam confundidas: `init_db()` cria **30** tabelas; o boot completo chega a **32** (`devices` e `axe_agent_commands` nascem dos registries, não do DDL). E `init_db()` **não é só DDL** — ele delega `ensure_table()` de `doc_feedback`, `error_tracker`, `conversion` e `beta_analytics`.

### Sub-issue #508 — o ciclo que o caminho direto travaria

Mover o `get_db` para o bootstrap era trivial; o risco era o **grafo de imports**. Os módulos de telemetria importam `services.db`, que passou a re-exportar `get_db` do bootstrap → `services.db → bootstrap → doc_feedback → services.db` fecha ciclo na inicialização parcial.

Saída: import **tardio dentro do `init_db()`** (o único lugar que os usa). Um teste lê o AST do módulo e falha se qualquer um desses voltar ao topo.

**Padrão reutilizável:** ao inverter a propriedade de um símbolo, verifique quem o importa **e por qual caminho** — o ciclo não aparece no arquivo que você está editando, aparece em quem depende dele.

### Guard de CI (#505) — o guard pegou o meu PR seguinte

O `check-monkeypatch-targets.py` **bloqueou o PR #510** porque `tests/test_command_center.py` patcheia `services.db.get_db` — e isso é **legítimo**: vários módulos fazem `from services.db import get_db` *dentro de função*, e esse lookup lê o atributo de `services.db` na hora da chamada. A regra inicial ("o módulo precisa definir/usar o nome") não contemplava o caso; entrou a exceção `deferred_import_targets`.

Um guard que nunca dispara em nada é um guard não testado. Este disparou no primeiro PR seguinte — em um falso positivo, que foi o que o calibrou.

---

## 5. Controles que funcionaram

| Controle | O que provou |
|---|---|
| **`url_map` idêntico** (B1/B2) | Dump das 178 regras antes/depois de cada PR-B, capturado via **worktree do `master`**. Mesmos paths, mesmos métodos. O único delta é o prefixo do endpoint (`api_admin_*` → `admin.api_admin_*`), idêntico ao de todo blueprint já migrado |
| **Extração verbatim por AST** (B1/B4) | Blocos recortados por fronteira de `decorator` + `end_lineno`, com verificação por substring contra o arquivo de origem antes da remoção. Zero risco de transcrição |
| **Identidade de objeto no re-export** (todos) | `from app import _admin_request_allowed` continua válido porque `app.py` re-exporta o **mesmo objeto** (`is` → `True`), não uma cópia |
| **Schema idêntico** (B4) | Dump de `sqlite_master` (73 objetos) antes/depois: mesmo SQL, e idempotência verificada nas duas árvores |
| **`--cov` explícito para módulos fora de `services/`** | Impede o ganho por subtração. O TOTAL ficou em 84,20% — estável, não inflado |
| **Contratos de teste por extração** | `test_admin_routes_blueprint.py` (27), `test_sse_fanout.py` (11), `test_snapshot_assembly.py` (24), `test_bootstrap_schema.py` (15), `test_monkeypatch_targets_guard.py` (10) — 87 testes que **não existiam** antes |
| **Guard de rota sem gate** | `KNOWN_UNGATED == set()`: nova rota `/api/admin/*` sem gate quebra o CI |

---

## 6. Erros do agente (accountability)

Três erros meus, todos com custo real:

1. **Ruído de formatação no B3 (#502 → corrigido na #503).** Rodei `black` nos 3 arquivos de teste que retargetei, mas **`tests/` não está no gate de black do CI** (o gate cobre `app.py helpers.py solo_mining.py services core axe_fleet routes agents`). Resultado: ~420 linhas de reformatação num PR que se apresentava como extração mecânica. Corrigido reconstruindo os arquivos a partir da versão pré-B3 com só os retargets, e provando que a diferença era puramente de formatação.
   → **Lição:** só formate o que o gate formata. Verifique o gate antes de rodar a ferramenta.

2. **Premissa falsa na #508.** Afirmei uma duplicata `config.DB_PATH` × `app.DB_PATH` a partir de um grep sem verificar **de qual arquivo** vinha a linha 27 (era do `config.py`). O registro foi corrigido por comentário na issue.
   → **Lição:** toda premissa de issue precisa citar `arquivo:linha`. Um grep sem arquivo é uma hipótese, não um fato.

3. **Bug aritmético no halving (B3).** Errei a próxima altura de halving no contrato de teste (`857200 // 210000`), pego pela própria suíte.
   → **Lição:** menos grave, mas mostra que teste novo precisa rodar antes de virar contrato.

---

## 7. Lições para os PRs de frontend 2–6

O que resta (`static/src/40-app-logic.js` = 12.666 linhas) tem um risco **diferente** do backend: sem rede de segurança de `url_map` nem de schema.

1. **O alvo pode não estar onde o RFC diz.** O PR 2 descreve "Market" como `orderbook, rent offers, BUY button, _mktRenderCap`. **Não existe orderbook no código** (zero ocorrências em `static/`). O que existe — o grid de venues do `/api/market/*` + `market_data.offers` e o BUY afiliado — está **espalhado em 4 regiões disjuntas** de `40-app-logic.js`:

   | Região | Linhas | Conteúdo |
   |---|---|---|
   | Estado | ~3.422–3.428 | `_mktFilter`, `_mktOffers`, `_mktBtcUsd`, `_mktAffiliate`, `_mktSnapTs`, `_mktTrendLoaded`, `_mktInstitutional` |
   | Grid institutional | ~4.552–4.793 | `_mktSort`, `MKT_RENDER_CAP`, `_mktRenderCap`, `sortMarketVenues`, `renderMarketGrid` |
   | Render + handlers | ~4.784–4.930 | `renderMarket`, chips de filtro, sort por header, BUY delegado |
   | Trend | ~4.966–5.034 | `buildMarketTrendDatasets`, `loadMarketTrend` |

   E **dois pontos de chamada fora do bloco**: `renderMarket(snap)` no poll em ~7.896 e o lazy-fetch de trend no `activateModule` em ~11.841 (+ o `gridEmpty` em ~11.868). Meça os usos **antes** de fixar a fronteira, como o B3 ensinou.
2. **Estado compartilhado é o risco novo.** `_adminLoaded` mora *dentro* do bloco de estado do market (linha 3.429, imediatamente depois de `_mktInstitutional`) mas pertence ao domínio **Admin** (usado em ~3.595, ~3.618, ~3.631 e ~4.482) — e o bloco Admin inteiro (~1.100 linhas, de ~3.437 a ~4.551) está **espremido entre** as regiões 1 e 2 do Market. Extrair por proximidade de linha arrastaria estado e funções alheias. A fronteira é por **posse do estado**, não por adjacência textual — e o Market é o primeiro caso onde os dois critérios dão respostas diferentes.
3. **O IIFE é único e a ordem é o runtime.** O `MANIFEST` do `build_app_js.cjs` **é** a ordem de execução. Ao extrair, o fragmento novo entra na posição exata do trecho removido — e `let`/`const` em TDZ respeitam essa ordem.
4. **Todo fragmento precisa estar no `MANIFEST`** — há invariante de ÓRFÃO no build (um `.js` fora do manifest nunca chega ao navegador e escapa de **todos** os guards, que leem só `static/app.js`).
5. **Monkeypatch não existe no frontend, mas o análogo existe:** o harness JS carrega helpers **do fonte** desde o PR 1. Ao mover um helper puro entre fragmentos, o teste que o carrega por `loadFragment()` precisa apontar para o fragmento novo — e o guard do #505 tem o padrão para detectar alvo órfão em Python.
6. **Escopo de comportamento: zero.** O RFC é explícito (e foi respeitado): renames ficam para depois. Mover código com nomes intactos é o que mantém `node --check`, os guards DOM/XSS e o e2e como rede de proteção.

---

## 8. Métricas

### Distribuição de `app.py` por etapa

| Etapa | Commit | `app.py` | Δ | Alvo real | Módulo novo |
|---|---|---|---|---|---|
| Baseline (pós PR 1/1b) | `7b3fc57` | 9.448 | — | — | — |
| B1 #495 | `7b12097` | 9.137 | −311 | `app.py` | `routes/admin_routes.py` (385) |
| B2 #499 | `ee45896` | 9.084 | −53 | `app.py` | `services/sse.py` (117) |
| B3 #501 | `4e8e2ec` | 9.084 | **0** | `services/user_polling.py` (1.606 → 1.152) | `services/snapshot_assembly.py` (528) |
| B4 #507 | `1241b01` | 8.443 | −641 | `app.py` | `services/bootstrap.py` (682) |
| #508 | `52fa57a` | 8.443 | 0 | — | `get_db` dentro do bootstrap (721) |

**Total: 9.448 → 8.443 linhas (−1.005, −10,6%).** Meta do RFC: ≤ ~4.000 (restam os PRs 2–6 do frontend; o backend não tem mais PRs previstos).

### Qualidade

| Métrica | Antes | Depois |
|---|---|---|
| Suíte pytest | 3.240 | **3.329** (+89) |
| Testes dos módulos extraídos | 0 | **87** |
| TOTAL de cobertura | 83,9% | **84,20%** (gate 80) |
| Módulos novos | — | `admin_routes` 96% · `sse` 96% · `snapshot_assembly` 96% · `bootstrap` (medido por `--cov=services`) |
| `url_map` | 178 regras | **178 regras** (idêntico) |
| Gates de qualidade | — | +1 guard blocking de CI (#505) |

### Custo

| Tipo | Quantidade |
|---|---|
| Issues criadas | 11 (#489, #490, #495, #496, #499, #501, #503, #505, #507, #508, #511 + o RFC #478) |
| PRs mergeadas em squash | 11 |
| PRs que existiram só porque uma premissa estava errada | **4** (#496, #490, #503, #508) |
| Comportamento novo introduzido | **0** (uma correção de segurança deliberada e isolada, #496, fora do escopo de extração) |
