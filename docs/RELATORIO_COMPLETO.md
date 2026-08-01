# CYPHER65 — RELATÓRIO COMPLETO DO PROJETO

> **Data:** 2026-07-28
> **Propósito:** Diagnóstico completo do estado atual do sistema

---

## 1. VISÃO GERAL DO LAYOUT (24 PAINÉIS)

### 1.1 Estrutura Física

```
┌─────────────────────────────────────────────────────┐
│ TOPBAR (36px) — endereço, status, clock, ações      │
├─────────────────────────────────────────────────────┤
│ STATUS BAR (5 blocos) — SYSTEM / MINING / POOL /    │
│                       NETWORK / FLEET               │
├──────┬──────────────────────────────────────────────┤
│      │ COMMAND CENTER GRID (12 colunas)             │
│ S    │ ┌──────────────────────────────────────────┐ │
│ I    │ │ 1. HOST CORE (hero-worker) — span 12     │ │
│ D    │ ├──────────────────────────────────────────┤ │
│ E    │ │ 2. HASH PROXIMITY METER — span 12        │ │
│ B    │ ├──────────────┬──────────────┬────────────┤ │
│ A    │ │3. Pool (6)  │4. Acct (3)  │5. Net (3)  │ │
│ R    │ ├──────────────┴──────────────┴────────────┤ │
│      │ │ 6. GAUGE PANEL — span 12                 │ │
│ 160px │ ├──────────┬──────────┬───────────────────┤ │
│      │ │7.Halv(4) │8.Fees(4) │9.Milestones(4)   │ │
│      │ ├──────────────────────────────────────────┤ │
│      │ │ 10. LIVE MINING — span 12                │ │
│      │ ├──────────┬──────────┬───────────────────┤ │
│      │ │11.Chrt(4)│12.Chrt(4)│13.Chrt(4)        │ │
│      │ ├──────────────────────────────────────────┤ │
│      │ │ 14. NETWORK CHART — span 12              │ │
│      │ ├────────────────────┬────────────────────┤ │
│      │ │ 15. Timeline (8)  │ 16. Events (4)     │ │
│      │ ├────────────────────┬────────────────────┤ │
│      │ │ 17. Leaderboard (8)│ 18. Logs (4)      │ │
│      │ ├──────────────────────────────────────────┤ │
│      │ │ 19. ALERTS — span 12                    │ │
│      │ ├──────────────────────────────────────────┤ │
│      │ │ 20. BLOCK HUNT — span 12                │ │
│      │ ├──────────────────────────────────────────┤ │
│      │ │ 21. MARKET — span 12                    │ │
│      │ ├──────────────────────────────────────────┤ │
│      │ │ 22. AI OPERATOR — span 12               │ │
│      │ ├──────────────────────────────────────────┤ │
│      │ │ 23. AXE FLEET — span 12                 │ │
│      └─┴──────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

### 1.2 Status do Layout

| Aspecto | Status | Observação |
|---------|--------|------------|
| Sidebar | ✅ Funcional | 7 itens, colapsável, backdrop mobile |
| Topbar | ✅ Funcional | 10 botões de ação, pill de status, clock |
| Status Bar | ✅ Funcional | 5 blocos com dados reais |
| 24 painéis | ✅ Existem | Todos renderizam sem erro |
| 3 modais | ✅ Existem | Wallet, Alert Center, Settings |
| Responsivo <768px | ⚠️ Parcial | Todos panels viram span 12, mas sem reorganização |
| **Design System v2** | ⚠️ Parcial | Paleta simplificada, decorativos removidos, radius 2px |

---

## 2. SIDEBAR — DIAGNÓSTICO

### 2.1 Estrutura Atual

```html
<aside class="sidebar" id="sidebar">
  <div class="sidebar__brand">     <!-- Logo "65" + "CYPHER65" -->
  <nav class="sidebar__nav">       <!-- 7 links: Command, Fleet, Block Hunt, Market, AI, Alerts, P&L -->
  <div class="sidebar__footer">    <!-- Status LED + Collapse toggle -->
```

### 2.2 Comportamentos

| Funcionalidade | Status | Detalhes |
|---------------|--------|----------|
| Navegação por clique | ✅ | Scroll suave para seção via hash link |
| Item ativo destacado | ✅ | Classe `.active` com borda laranja 2px |
| Colapso (toggle) | ✅ | Botão ◀ / ▶, largura 180px → 48px |
| Mobile overlay | ✅ | <1100px: sidebar vira fixed com backdrop |
| Fechar backdrop | ✅ | Click no backdrop fecha sidebar |
| Fechar com Escape | ✅ | Tecla Escape fecha sidebar |
| Scroll tracking | ⚠️ | IntersectionObserver existe, mas pode não destacar corretamente |
| Ícones (emoji) | ❌ Ainda usa emoji | ⌘ ⚙ ◈ ⟐ ◆ ⚠ Ξ — pendente substituir por Lucide |

### 2.3 Problemas Conhecidos

1. **Ícones emoji** — Não substituídos por Lucide ainda. Visualmente inconsistentes.
2. **Scroll tracking impreciso** — O IntersectionObserver usa `rootMargin: '-20% 0px -70% 0px'` que pode não destacar o item correto em painéis longos.
3. **Mobile em 480px** — Largura reduz para 160px, mas o conteúdo dos itens pode truncar.
4. **Sem highlight inicial** — Se o snapshot ainda não carregou, o item "Command" fica ativo mas nenhum dado aparece.

---

## 3. CONNECT WALLET — DIAGNÓSTICO

### 3.1 Fluxo Completo

```
[Usuário clica ⟐ no topbar]
       │
       ▼
[Modal wallet-modal abre]
  - Mostra: wallet-current-addr (BTC_ADDRESS atual)
  - Mostra: wallet-current-worker (WORKER_NAME atual)
  - Input: wallet-address-input (novo endereço)
  - Input: wallet-worker-input (novo worker)
  - Botão: wallet-save (CONNECT)
       │
       ▼
[wallet-save click handler]
  1. Valida address (não vazio, bc1... ou 1..., 26-64 chars)
  2. POST /api/set-address com JSON {address, worker}
       │
       ▼
[Backend: /api/set-address]
  1. Valida inputs
  2. Persiste no SQLite (settings._wallet_address)
  3. Atualiza BTC_ADDRESS e WORKER_NAME globais
  4. Chama _reset_session_state() — limpa todo estado
  5. Retorna {success, address, worker}
       │
       ▼
[Frontend: response]
  1. window.BTC_ADDRESS = data.address
  2. window.WORKER_NAME = data.worker
  3. Fecha modal
  4. Dispara refresh (fetchSnapshot)
```

### 3.2 Persistência

| Etapa | Local | Funciona? |
|-------|-------|-----------|
| Salvamento | SQLite `settings(key='_wallet_address')` | ✅ |
| Restore no startup | `_load_persisted_address()` no `app.py` | ✅ |
| Testes | `tests/test_persistence.py` (3 testes) | ✅ Passam |
| Session wipe | `_reset_session_state()` limpa 15+ estruturas | ✅ |

### 3.3 Problemas Conhecidos

1. **Sem validação de endereço real** — A validação só confere prefixo bc1/1 e comprimento. Não verifica checksum ou se o endereço existe na pool.
2. **Sem confirmação de worker** — Se o worker não existir na pool, a API do Parasite retorna vazio, mas o sistema aceita.
3. **Sem feedback visual de sucesso** — O modal apenas fecha. Não mostra toaster/notificação de "wallet changed".
4. **Dados demoram a aparecer** — Após trocar address, o próximo poll (15s) só então carrega dados do novo worker. Nenhum feedback intermediário.

---

## 4. ENDEREÇOS PASSADOS — DIAGNÓSTICO

### 4.1 State Atual

| Fonte | Valor | Origem |
|-------|-------|--------|
| `config.BTC_ADDRESS` | `""` (vazio por padrão — sem wallet default) | Env ou vazio |
| `app.BTC_ADDRESS` | Mesmo valor + persistido | DB ou env |
| `window.BTC_ADDRESS` (JS) | Mesmo valor | Injeta via `<script>` no HTML |
| `config.WORKER_NAME` | `""` | Env ou default |

### 4.2 Como o Endereço é Usado

```
app.BTC_ADDRESS
  ├── poll_once() → user/{address} (API Parasite)
  ├── poll_once() → account/{address}
  ├── poll_once() → highest-diff?address={address}
  ├── renderHero() → exibe métricas do worker
  ├── renderBlockHunt() → cálculos de probabilidade
  └── dashboard_routes → leaderboard destaca "is_me"
```

### 4.3 Problemas Conhecidos

1. **Sem histórico de endereços** — Quando o usuário troca de address via `/api/set-address`, o anterior é sobrescrito. Não há "past addresses" armazenados.
2. **Sem fallback se address for inválido** — Se `BTC_ADDRESS` estiver vazio (ou inválido), o poll_once() loga "No wallet address configured" mas continua rodando. A UI mostra travessões (—) nos lugares dos dados.
3. **Monitor de disconnect wallet não integrado** — Existe `tests/test_app_js_core.js` com testes, mas a funcionalidade de desconectar wallet não está implementada na UI.

---

## 5. DADOS — ERROS E PROBLEMAS

### 5.1 Dados do Snapshot Atual

Com base no snapshot ao vivo:

| Campo | Valor | Problema? |
|-------|-------|-----------|
| `worker.hashrate` | `0` | ❌ **Zerado** — O worker existe mas hashrate = 0 |
| `worker.bestDifficulty` | `170120161069` (170G) | ✅ Válido |
| `worker.lastSubmission` | Timestamp recente | ✅ Válido |
| `pool` | `null` | ❌ **Pool retornou null** — API da pool pode estar instável |
| `network.difficulty` | `126231507121868.0` | ✅ Válido |
| `btc_price.usd` | `63945` | ✅ Válido |
| `alerts_recent` | 12 alertas ativos | ⚠️ Verificar se são reais ou duplicados |

### 5.2 Problemas de Dados Conhecidos

| # | Problema | Impacto | Causa Provável |
|---|----------|---------|----------------|
| 1 | **hashrate = 0** | Todo painel mostra "—" ou 0 | Worker pode estar offline ou pool não reporta hashrate atual |
| 2 | **pool = null** | Painel Pool Overview vazio | API da Parasite pode estar instável ou sem resposta |
| 3 | **all_workers = []** (inferido) | Live Mining sem dados | Sem workers = sem visualização |
| 4 | **Mercado sem dados** | Market panel mostra "no data" | MRR credentials não configuradas |
| 5 | **12 alertas sem contexto** | Podem ser duplicados | Dedup pode não estar funcionando |
| 6 | **Dados de 15s atrás** | Latência de até 15s | Poll interval de 15.000ms |

### 5.3 Raiz dos Problemas

1. **API Parasite instável** — hashrate 0 e pool null sugerem que a API pública do Parasite Pool pode estar com problemas de conectividade ou rate limiting.
2. **Sem fallback de dados** — Se a API falha, o sistema não tem dados de cache para mostrar. Fica tudo "—".
3. **Missing MRR credentials** — O mercado de hashrate (MRR) precisa de API key/secret que não estão configuradas.
4. **Hashrate reportado como 0** — Pode ser porque:
   - O worker está realmente offline
   - A pool mostra hashrate como 0 durante certos períodos
   - O parsing do campo hashrate no JSON da API está falhando

---

## 6. AI OPERATOR — POR QUE NÃO RESPONDE

### 6.1 Arquitetura Atual

```javascript
function _initAiChat() {
    const responses = {
      'hashrate': 'Current hashrate is **{hr}**...',
      'temperature': 'Monitoring fleet temperature...',
      'probability': 'Block finding probability depends...',
      'difficulty': 'Network difficulty adjusts...',
      'best diff': 'Your best difficulty...',
      'market': 'Hashrate market data shows...',
      'fleet': 'Your fleet dashboard shows {fleet}...',
      'profitability': 'Profitability depends...',
      'hello': 'I\'m CYPHER AI...',
    };

    function findBestResponse(query) {
      // Keyword matching: split query into words, score by overlap
      // Score >= 5 → return key
      // Score < 5 → return null → "I'm not sure"
    }

    function getResponse(query) {
      const key = findBestResponse(query);
      if (!key) return 'I\'m not sure about that...';
      return responses[key];
    }
}
```

### 6.2 O Problema: É UM SISTEMA DE KEYWORD MATCHING, NÃO UMA IA

**A IA NÃO É UMA IA.** É um sistema de correspondência de palavras-chave com **9 respostas pré-escritas** em um objeto JavaScript.

| Característica | Atual | O Que Deveria Ser |
|---------------|-------|-------------------|
| Engine | Keyword matching | LLM (GPT/Claude) ou backend processando NLP |
| Respostas | 9 hardcoded | Ilimitadas, geradas com contexto |
| Contexto | Apenas {hr}, {pblock}, {fleet} | Snapshot completo + histórico + analytics |
| Precisão | Baixa | Alta com contexto real |
| Respostas "I don't know" | Qualquer pergunta sem match | Minimizadas |

### 6.3 Por Que Falha para Perguntas Reais

1. **Score threshold de 5** — Para uma pergunta como "qual a temperatura do device axe-fleet?", as palavras "temperature" (score 10) + "device" (score 5) = 15 ≥ 5, então responde sobre temperatura genérica. Mas perguntas como "por que meu hashrate caiu?" não têm match.

2. **Apenas 9 tópicos** — Fleet, hashrate, probability, difficulty, temperature, market, profitability, best diff, hello. Fora disso, sempre retorna "I'm not sure".

3. **Sem contexto real da operação** — A resposta substitui `{hr}`, `{pblock}`, `{fleet}` mas eles vêm do DOM (`document.getElementById`), não de dados estruturados.

4. **Sem chamada de backend** — O operador não chama nenhuma API. Todo o processamento é 100% local no navegador.

5. **Prompt engineering zero** — Não há system prompt, não há contexto de conversa, não há memória.

### 6.4 O Que Precisa Mudar

| Mudança | Prioridade | Esforço |
|---------|------------|---------|
| Conectar a um LLM real (GPT/Claude via backend) | 🔴 Alta | Médio |
| Criar endpoint `/api/ai/query` no Flask | 🔴 Alta | Baixo |
| Enviar contexto real (snapshot, histórico) | 🟡 Média | Baixo |
| Manter histórico da conversa | 🟡 Média | Baixo |
| Tool calling (restart device, calcular probabilidade) | 🟢 Baixa | Alto |

---

## 7. RESUMO DE PROBLEMAS PRIORIZADOS

| Prioridade | Problema | Impacto | Solução |
|------------|----------|---------|---------|
| 🔴 **CRÍTICO** | AI Operator não responde perguntas reais | Usuário não consegue suporte | Conectar a LLM via backend |
| 🔴 **CRÍTICO** | hashrate = 0 no snapshot | Dashboard todo mostra vazio | Investigar API Parasite + fallback |
| 🟡 **ALTO** | pool = null | Pool Overview sem dados | Debug da resposta da API |
| 🟡 **ALTO** | Emoji icons no sidebar/topbar | Aparência inconsistente | Substituir por Lucide SVG |
| 🟡 **ALTO** | Eyebrow text com emoji | Profissionalismo reduzido | Limpar 24 headers de painéis |
| 🟡 **ALTA** | Layout não reorganizado em mobile | Experiência mobile ruim | Repriorizar painéis por função |
| 🟢 **MÉDIO** | Sem histórico de endereços | Usuário não vê past addresses | Criar tabela + endpoint |
| 🟢 **MÉDIO** | Market sem MRR creds | Painel sempre vazio | Configurar variáveis de ambiente |
| 🟢 **MÉDIO** | Scroll tracking impreciso | Sidebar não destaca seção correta | Ajustar IntersectionObserver |
| 🟢 **BAIXO** | Sem toaster de confirmação | Feedback fraco ao trocar wallet | Adicionar notificação |

---

## 8. RECOMENDAÇÕES IMEDIATAS

### Curto Prazo (dias)
1. **Substituir AI keyword matching por LLM real** — Criar endpoint Flask `/api/ai/query` que chama OpenAI/Anthropic com contexto do snapshot
2. **Corrigir hashrate=0** — Verificar parsing da API Parasite, adicionar fallback com último valor válido
3. **Substituir emoji por Lucide** — Sidebar + topbar + badges consistentes

### Médio Prazo (semanas)
4. **Reorganizar layout para 3 colunas** — Left rail (colônias), Center (core), Right rail (oportunidades)
5. **Histórico de endereços** — Salvar trocas de wallet em tabela SQLite, expor em UI
6. **Alertas com spores** — Redesenhar alertas como pequenos elementos precisos

### Longo Prazo (meses)
7. **App mobile nativo** - React Native + Expo com as 10 tarefas do MILESTONE 8
8. **Automações** — Sistema completo WHEN→THEN com safety engine
9. **Multi-wallet** — Suporte a múltiplos endereços simultâneos

---

## 9. ESTATÍSTICAS DO PROJETO

| Métrica | Valor |
|---------|-------|
| Arquivos frontend | 5 (dashboard.html 1.552 linhas, style.css ~3.000, app.js 2.158, sw.js 117, manifest.json) |
| Arquivos backend | ~20 (app.py, config.py, services/*, routes/*, agents/*, core/*) |
| Arquivos de teste | ~15 |
| Total estimado de linhas | ~15.000+ |
| Painéis UI | 24 |
| Modais | 3 |
| Funções JS de render | 23 |
| IDs HTML únicos | 293 |
| Milestones concluídos | 9 de 12 |
| Testes unitários | ~30+ |

---

*Fim do relatório. Gerado em 2026-07-28.*
