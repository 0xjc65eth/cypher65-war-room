# 🤖 MULTI-AGENT TEAM — Orquestração de 30 papéis

> **Status:** ADOTADO (Issue #596) · **Escopo:** processo de trabalho, não runtime.
> Leia junto com [`PROJECT_WORKFLOW.md`](../PROJECT_WORKFLOW.md) e
> [`docs/AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md) — este documento **não** substitui nenhum dos dois.

---

## 1. O que isto é (e o que não é)

Isto é um **modelo de organização de trabalho** — 30 papéis especializados, com fronteira de
responsabilidade, contrato de handoff e regra de evidência. Não é uma frota de processos
autônomos: cada papel é uma instrução carregável (`.agents/agents/**/*.md`) que um agente de
qualquer modelo — ou uma pessoa — assume, uma por vez.

Não existe orquestração de runtime aqui. Não há scheduler, não há daemon, não há API
chamando modelo. Um "wave" é uma sessão de trabalho com dono, entrada e saída.

**Por que não automatizar já:** o projeto tem dois gates duros que exigem julgamento humano
— o gate de confirmação de comando físico (`FW-03`) e a decisão de aceitar risco residual
(`OPS-01`). Um scheduler autônomo nesses dois pontos é um risco maior que o ganho. Primeiro
processo, depois automação.

---

## 2. As 6 equipes (30 papéis)

| Equipe | Papéis | Label GitHub | Arquivo |
|---|---|---|---|
| **A. Frontend & Motion** | 5 | `team:frontend` | `.agents/agents/frontend/` |
| **B. Backend & Data** | 5 | `team:backend` | `.agents/agents/backend/` |
| **C. Fleet & Firmware** | 5 | `team:backend` `team:security` | `.agents/agents/fleet/` |
| **D. QA & Test** | 5 | `team:qa` | `.agents/agents/qa/` |
| **E. Research & Improvement** | 5 | `team:product` `team:data-ai` | `.agents/agents/research/` |
| **F. Ops, Security & Observability** | 5 | `team:devops` `team:security` | `.agents/agents/ops-security/` |
| | **30** | | |

### A. Frontend & Motion — `.agents/agents/frontend/`

| ID | Papel | Mandate em uma linha |
|---|---|---|
| `FE-01` | Frontend Orchestrator | Porta de entrada; `static/app.js` é gerado, nunca editado à mão |
| `FE-02` | Motion Engineer | Dono do comportamento temporal; rejeita motion decorativo |
| `FE-03` | DOM & XSS Guardian | Dado externo → `escapeHtml`; veta `innerHTML` inseguro |
| `FE-04` | Module Router & Build Integrity | Fragmentos de `static/src/` + drift gate |
| `FE-05` | Accessibility & Responsive Auditor | Mede e reprova; **não** implementa feature |

### B. Backend & Data — `.agents/agents/backend/`

| ID | Papel | Mandate em uma linha |
|---|---|---|
| `BE-01` | Backend Orchestrator | Ponto de entrada; rota sem teste não passa |
| `BE-02` | API Contract Engineer | Todo caminho de erro é `4xx` JSON, nunca `500` por payload |
| `BE-03` | Data Layer Steward | Isolamento de teste (CRÍTICO) + Postgres gated por tração |
| `BE-04` | Numeric Honesty Engineer | Veto sobre número que não se deriva dos inputs exibidos |
| `BE-05` | Poll & Snapshot Engineer | Degradação é declarada (`stale`), nunca virando `0` |

### C. Fleet & Firmware — `.agents/agents/fleet/`

| ID | Papel | Mandate em uma linha |
|---|---|---|
| `FW-01` | Fleet Orchestrator | Ponto de entrada do maior risco: hardware real |
| `FW-02` | Adapter & Protocol Engineer | Identifica por **protocolo**, não por porta |
| `FW-03` | Command Safety Gate | Dono do token de confirmação; veto absoluto |
| `FW-04` | Physical Validation Officer | Sem hardware ⇒ `BLOCKED_EXTERNAL`, nunca "aprovado" |
| `FW-05` | Pool Registry & Chain Detection | Declara pool, chain e fonte dos números |

### D. QA & Test — `.agents/agents/qa/`

| ID | Papel | Mandate em uma linha |
|---|---|---|
| `QA-01` | Test Lead | Dono da matriz de gates; veto de merge por evidência ausente |
| `QA-02` | Python Suite Engineer | pytest + cobertura 80% + isolamento de banco |
| `QA-03` | JS Core Suite Engineer | Carrega o **fonte real** de `static/src/`, não o artefato |
| `QA-04` | E2E Playwright Engineer | Specs determinísticos, sempre `--file=` |
| `QA-05` | Adversarial Verification | Tenta quebrar; pode reprovar qualquer PR |

### E. Research & Improvement — `.agents/agents/research/`

| ID | Papel | Mandate em uma linha |
|---|---|---|
| `RS-01` | Research Lead | Dono do método e das 3 classes de evidência |
| `RS-02` | Miner & Hashpower Pain Researcher | Dores de quem minera e de quem aluga hashrate |
| `RS-03` | Revenue & Payments Researcher | Canais de receita e tradeoff de custódia BTCPay |
| `RS-04` | Roadmap Synthesis | Research vira fila de Issues com métrica e critério de parada |
| `RS-05` | Competitive UX Teardown | Lacuna de jornada nas lentes A/B/C/D, sem copiar |

### F. Ops, Security & Observability — `.agents/agents/ops-security/`

| ID | Papel | Mandate em uma linha |
|---|---|---|
| `OPS-01` | Security & Ops Orchestrator | Pode congelar merge; risco residual não decide sozinho |
| `OPS-02` | Security Auditor | Checklist pré-merge + superfícies de risco do projeto |
| `OPS-03` | Observability Engineer | Sentry env-gated + logs JSON; sem APM pago |
| `OPS-04` | Deploy & CI Pipeline | CI verde é pré-requisito; nunca push direto em `master` |
| `OPS-05` | Docs & Runtime Contract | Doc que diverge do runtime é bug (`inconsistency`) |

---

## 3. Como uma wave funciona

```text
Wave (issue/objetivo)
  ↓
Orquestrador de Waves        ← humano ou agente coordenador
  ├─ decompõe em Issues (Rule 1: tudo vira Issue antes do código)
  ├─ escolhe o orquestrador de equipe dono
  └─ define critério de parada
  ↓
Orquestrador de equipe (FE-01 / BE-01 / FW-01 / QA-01 / RS-01 / OPS-01)
  ├─ distribui para os até 4 especialistas
  ├─ recebe handoff e valida contra o contrato de done
  └─ devolve para QA-01 (gate) — nunca auto-aprova
  ↓
QA-01 valida com o gate da superfície  →  QA-05 tenta quebrar
  ↓
OPS-0x gate de CI  →  PR  →  review  →  squash merge  →  deploy
  ↓
OPS-03 observa o sinal
```

### Regra de wave

Uma wave tem **um** objetivo, **um** dono e **um** critério de parada escrito antes de
começar. Wave que descobre escopo novo abre Issue e **não** expande no meio — expansão
silenciosa é como um PR de 40 arquivos nasce.

### Tamanho

| Tamanho | Papéis ativos | Quando |
|---|---|---|
| Micro | 1 papel | correção localizada, doc, teste único |
| Padrão | 1 orquestrador + 2–3 especialistas | uma Issue de feature/fix normal |
| Completa | 6–8 papéis, 2+ equipes | epic, cross-cutting, incidente |

Não acionar os 30 de uma vez. Os 30 são um **catálogo** de especialidade, não um time que
roda em paralelo. Acionar 30 produz 30 handoffs mal revisados, não 30× de throughput.

---

## 4. Protocolo de handoff

Todo handoff entre papéis carrega, sem exceção:

| Campo | Regra |
|---|---|
| **De → Para** | IDs explícitos (`BE-02` → `QA-02`) |
| **Entrada** | Issue + branch + arquivos tocados |
| **Saída** | O que ficou pronto, com caminho de arquivo |
| **Evidência** | Comando exato + resultado colado (não "funciona") |
| **Não feito** | O que ficou de fora, explicitamente |
| **Bloqueio** | Se houver, com a Issue que o rastreia |

Handoff sem campo **Evidência** ou sem campo **Não feito** é devolvido. O campo "não feito"
é o mais importante: é o que impede o próximo papel de assumir que o anterior cobriu tudo.

### Cadeia de escalação

| Sinal | Escala para | SLA de resposta |
|---|---|---|
| Suspeita de comando físico indevido | `OPS-01` + `SEC-02` | imediato |
| Secret em código/log/resposta/audit | `OPS-01` | imediato |
| Vazamento entre tenants | `OPS-01` | imediato |
| Vetor XSS real (não teórico) | `OPS-02` | imediato |
| Teste contaminando banco operacional | `BE-03` | imediato |
| Gate vermelho sem causa clara | `QA-05` | mesma wave |
| Doc divergindo do runtime | `OPS-05` | mesma wave |
| Número que não reconcilia com o input | `BE-04` | mesma wave |
| Precisa de hardware/signing/secret | `FW-04` / `OPS-01` → `BLOCKED_EXTERNAL` | registra e segue |

---

## 5. Regra de evidência (a que sustenta o resto)

O projeto proíbe fabricar número, uptime, rentabilidade, prevalência de mercado, transação
real ou estado de deploy. Isso vale para **todo** papel, não só research.

Três classes, sempre rotuladas:

| Classe | Prova |
|---|---|
| **Evidence** | caminho de arquivo + linha, ou teste que passa |
| **Primary-source claim** | URL + data de consulta + o que a fonte diz |
| **Hypothesis** | rótulo explícito + como seria falseada |

### Proibido em qualquer saída de qualquer papel

- Marcar como concluído o que não tem evidência reproduzível.
- Baixar gate de cobertura, adicionar `skip`, ou afrouxar guard para destravar PR.
- Fechar Issue física (hardware/signing) sem hardware/signing.
- Registrar secret, token, chave, dado de pagamento ou dado pessoal.
- Documentar env var ou funcionalidade que não existe no código.

**Quando não há evidência, a resposta correta é `BLOCKED_EXTERNAL` com a razão escrita.**
Isso é uma entrega válida. Fingir que está pronto não é.

---

## 6. Mapa dos 30 papéis → backlog real

Estado capturado em 2026-09-16: 6 Issues abertas, 1 PR aberto (#590, dependabot).

| Issue | Título curto | Situação real | Papéis donos | Ação |
|---|---|---|---|---|
| **#567** | docs(research): dores de minerador e hashpower + roadmap de pagamento | **Doável** com fonte primária | `RS-01`, `RS-02`, `RS-03`, `RS-04` | produzir o brief e fechar |
| **#566** | docs(product): reconciliar walkthrough do operador com as fronteiras reais | **Doável** — divergência documentada | `OPS-05`, `RS-01`, `QA-01` | corrigir a doc (não o runtime) e fechar |
| **#330** | ops: ativar canal BTC em produção (BTCPay + endereço) | **Bloqueada externamente** — exige secrets no Render | `OPS-01`, `OPS-04`, `RS-03` | manter aberta; marcar `BLOCKED_EXTERNAL` |
| **#386** | test: matriz física Bitaxe/NerdQaxe/Antminer | **Bloqueada externamente** — exige hardware real | `FW-04`, `QA-05` | manter aberta; `BLOCKED_EXTERNAL` |
| **#399** | epic: app iOS production + pool intelligence universal | **Bloqueada externamente** — exige signing/TestFlight | `FW-05`, `OPS-04`, `FE-04` | manter aberta; `BLOCKED_EXTERNAL` |
| **#22** | Migração Postgres (Neon/Supabase free) — gated por tração | **Deliberadamente adiada** — gate de tração não satisfeito | `BE-03` | manter aberta; sem iniciar migração |

> **Nota de honestidade (Issue #596):** "fechar todos os issues" não é alcançável sem
> fabricar evidência. Duas Issues são fecháveis com trabalho real; as outras quatro têm
> bloqueio externo ou gate de produto não satisfeito. Fechá-las como concluídas violaria a
> `PROJECT_WORKFLOW.md` §8 e o próprio critério de aceite de #386 ("resultado físico nunca é
> marcado como aprovado sem hardware").

---

## 7. RACI por tipo de tarefa

`R` = responsável · `A` = aprova · `C` = consultado · `I` = informado

| Tarefa | FE | BE | FW | QA | RS | OPS |
|---|---|---|---|---|---|---|
| Mudança de UI/motion | **R** | I | – | **C** | – | I |
| Rota/contrato de API | C | **R** | C | **C** | – | **A** |
| Comando físico/ASIC | C | C | **R** | **C** | – | **A** |
| Fórmula/probabilidade | C | **R** | C | **C** | C | I |
| Migração/ schema | – | **R** | – | **C** | I | **A** |
| Research/brief | I | C | C | – | **R** | C |
| Gate de CI/deploy | C | C | C | **R** | I | **A** |
| Security review | C | C | **R** | C | C | **A** |
| Observabilidade | C | C | C | I | – | **R** |
| Docs do operador | C | C | C | **C** | C | **R** |

Nenhuma linha tem `R` e `A` no mesmo papel: quem produz não aprova. É o mesmo princípio de
"skill de review obrigatório" da `PROJECT_WORKFLOW.md` §11.

---

## 8. Fila de waves sugerida (a partir de 2026-09-16)

| Wave | Objetivo | Papéis | Critério de parada |
|---|---|---|---|
| **W1** | Fechar o doável: brief de research (#567) + reconciliação de docs (#566) | `RS-01/02/03/04` + `OPS-05` + `QA-01` | PR mergeado, #566/#567 fechadas |
| **W2** | Triar backlog bloqueado: rotular e documentar o bloqueio de #330/#386/#399/#22 | `OPS-01` + `FW-04` + `BE-03` | cada Issue com razão de bloqueio e caminho de desbloqueio |
| **W3** | Reduzir lacunas de teste da matriz `docs/TEST_STRATEGY.md` (`MF-003`, `NUM-002`, `TIME-001`, `LOAD-001`) | `QA-02/03/04/05` | IDs sem cobertura com Issue própria |
| **W4** | Roadmap: fold dos achados validados em `docs/IMPROVEMENT_ROADMAP.md` | `RS-04` + `RS-05` | itens com métrica e critério de parada |
| **W5** | Higiene: artefatos órfãos **não versionados** no working tree (`services/rental_performance.py.bak`, `.tmp-*`) | `OPS-04` + `FE-04` | working tree sem artefatos; `.gitignore` cobre `*.py.bak` e `.tmp-*` |

> **Correção de registro (2026-09-16, execução de W5).** A Issue #597 foi aberta afirmando que
> esses dois artefatos estavam **versionados**. A verificação mostrou que **nunca foram** —
> `git ls-files` e `git log --all` voltam vazios para ambos, e o `.gitignore` já os cobria
> (linhas 26 `.tmp-*` e 29 `*.py.bak`) desde antes. W5 realizou a limpeza do *working tree*
> e **não** houve reparo de versionamento. Fechar como premissa incorreta, não como conserto.

---

## 9. Anti-patterns (reprovados no review)

| Anti-pattern | Por que |
|---|---|
| Acionar os 30 papéis de uma vez | gera handoff não revisado, não throughput |
| Auto-aprovar o próprio PR | viola a separação `R`/`A` (§7) |
| Editar `static/app.js` direto | quebra o drift gate; o fonte é `static/src/` |
| Fechar Issue física sem hardware | fabrica evidência |
| Baixar cobertura/skip para destravar PR | o gate existe para isso |
| Wave que expande escopo no meio | é assim que nasce um PR irrevisável |
| Research sem data de consulta | claim não é falsificável |
| Papel implementando fora da própria superfície | a fronteira existe para o handoff funcionar |

---

## 10. Referências

- Processo: [`PROJECT_WORKFLOW.md`](../PROJECT_WORKFLOW.md) · [`docs/AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md)
- Qualidade: [`docs/QUALITY.md`](QUALITY.md) · [`docs/TEST_STRATEGY.md`](TEST_STRATEGY.md)
- Research: [`docs/RESEARCH_LOG.md`](RESEARCH_LOG.md) · [`docs/IMPROVEMENT_ROADMAP.md`](IMPROVEMENT_ROADMAP.md)
- Skills: `.agents/skills/design-motion-principles` · `.agents/skills/enterprise-code-review`
- Auditoria profunda: [`AUDIT_PROMPT.md`](../AUDIT_PROMPT.md)
- Papéis: `.agents/agents/**/*.md` (30 arquivos)
