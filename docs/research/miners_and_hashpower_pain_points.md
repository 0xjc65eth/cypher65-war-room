# Miner & Hashpower Renter Pain Points — Evidence-Led Brief

| Campo | Valor |
|---|---|
| Issue | #567 |
| Data da pesquisa | 2026-09-16 |
| Papéis responsáveis | `RS-01` (método) · `RS-02` (dores) · `RS-03` (pagamento/custódia) · `RS-04` (síntese) |
| Status | `descoberto` — brief de pesquisa, **nenhuma** mudança de código ou deploy |
| Escopo | Desk research sobre fontes primárias + evidência do próprio produto |
| Revisão | **rev. 2 (2026-09-16)** — gap de fontes de P2 fechado com S13 e S14 (§3 P2). Nenhuma outra seção mudou de conclusão |

---

## Resumo executivo (PT)

Esta pesquisa olhou para as dores de quem minera e de quem **aluga hashrate**, e chegou a
cinco dores principais. Duas conclusões de maior valor:

**1. A dor mais concreta é de liquidação, não de preço.** A estrutura de payout de uma pool
é condicional ao **trilho** e ao **tamanho**: na Braiins Pool o saque on-chain é gratuito a
partir de 0,005 BTC e custa 0,0001 BTC abaixo disso, enquanto o trilho Lightning tem **teto**
de 0,005 BTC. Ou seja: o mesmo saldo vale coisas diferentes dependendo de como sai. Um
operador pequeno não consegue responder "quanto eu recebo de fato, e quando" sem fazer essa
conta por conta própria. E o ciclo é no máximo diário ("payout rules" são avaliadas uma vez
por dia, 9:00 UTC).

**2. Para o renter de hashrate, o risco não é o preço — é a ausência de recurso.** Nos termos
primários de um marketplace real (MiningRigRentals), **todas as transações são finais e não
reembolsáveis**, não há proteção de preço, e pedido de reembolso só existe via ticket dentro
da plataforma ("We will not answer refund requests via email"). O documento de termos estava
modificado pela última vez em **julho de 2017**. A promessa de "escrow-backed" existe na
página de marketing, mas o recurso contratual do renter é fino.

**3. Custódia BTC: endereço de referência fixo não é liquidação nem forwarding.** A
documentação oficial do BTCPay é explícita: **não há reuso de endereço** — cada invoice usa um
endereço novo, gerado da wallet do merchant. Um endereço fixo, portanto, não consegue
liquidar invoice nenhuma. E forwarding/payout **não é automático** por padrão: o BTCPay
"does not approve and pay a payout automatically"; exige aprovação e assinatura do remetente
(automação só via Greenfield API).

**O que esta pesquisa não provou:** economia/rentabilidade típica, uptime real de
fornecedores, prevalência de mercado de cada dor, e nenhuma transação real. Nada aqui vira
número de produto sem medição própria.

---

## 1. Método e classes de evidência

Regra herdada de `RS-01` (`docs/RESEARCH_LOG.md`): toda afirmação é classificada antes de ser
usada.

| Classe | Significado |
|---|---|
| **E** — Evidence | observável no código/produto atual, com caminho de arquivo |
| **P** — Primary-source claim | o que a fonte externa **literalmente** diz, com URL + data |
| **H** — Hypothesis | inferência do time; rotulada e falsificável |

Limites do método, declarados de saída:

- Web search não retornou resultados nesta sessão; as fontes foram obtidas por **acesso direto
  à URL** e leitura do conteúdo extraído.
- Páginas renderizadas só no cliente não puderam ser lidas (detalhado em §6).
- Nenhuma credencial, conta, transação ou dado de operador foi usado.

---

## 2. Fontes primárias consultadas

Todas com data de consulta **2026-09-16**.

| # | Fonte | URL | O que foi efetivamente lido |
|---|---|---|---|
| S1 | Braiins Academy — *Rewards & Payouts* | `https://academy.braiins.com/braiins-pool/rewards-and-payouts` | Pool fee 2,5%; payouts criados diariamente 9:00 UTC; on-chain confirma em 1–2 h; taxa on-chain grátis ≥0,005 BTC e 0,0001 BTC abaixo; Lightning grátis; mínimos/máximos por trilho; payout rules avaliadas 1×/dia |
| S2 | Braiins Academy — *Solo Mining* | `https://academy.braiins.com/braiins-pool/solo-mining` | Solo só paga se o bloco for encontrado; nenhum sat acumulado antes; "odds might be 1-in-a-million"; 3,125 BTC no epoch atual + fees; 0,5% para os autores do CKPool; shares são só conveniência |
| S3 | BTCPay — *General FAQ* | `https://docs.btcpayserver.org/FAQ/General/` | Non-custodial; chave privada nunca exigida para receber; **"no address re-use since each invoice uses a new address"** |
| S4 | BTCPay — *Wallet FAQ* | `https://docs.btcpayserver.org/FAQ/Wallet/` | Só xpub por padrão; wallet interna é opcional; **gap-limit problem** (novo endereço por invoice; wallet externa para de rastrear após 20 invoices não pagas) |
| S5 | BTCPay — *Pull Payments* | `https://docs.btcpayserver.org/PullPayments/` | Sender configura limites/período; **"does not approve and pay a payout automatically"**; batch a partir da wallet interna; API Greenfield permite automação |
| S6 | BTCPay — *Payouts* | `https://docs.btcpayserver.org/Payouts/` | Status `Awaiting Approval` → aprovar/enviar; assinatura obrigatória; "a future release ... presumably will have automation options for payouts" |
| S7 | BTCPay — *Wallet* | `https://docs.btcpayserver.org/Wallet/` | Wallet interna non-custodial verificada pelo próprio full node; Payouts gerencia Pull Payments |
| S8 | MiningRigRentals — *Terms of Service* | `https://www.miningrigrentals.com/tos` | **"All transactions, including rentals, are final and non-refundable"**; sem price protection; taxas por transação; termos modificados em julho/2017 |
| S9 | MiningRigRentals — home | `https://www.miningrigrentals.com/` | "escrow-backed transactions"; pool manager com até 5 failover pools; analytics de hashrate/uptime |
| S10 | MiningRigRentals — *Help* | `https://www.miningrigrentals.com/help` | Reembolso/review só via ticket logado: "We will not answer refund requests via email" |
| S11 | Cambridge CBECI — *Methodology* | `https://ccaf.io/cbnsi/cbeci/methodology` | abordagem híbrida top-down; três estimativas (floor/best-guess/ceiling); assume miners como agentes racionais que só usam hardware lucrativo; custo de eletricidade é **estimativa estática** |
| S12 | Cambridge CBECI — landing | `https://ccaf.io/cbnsi/cbeci` | valores numéricos **não** capturados (página renderiza no cliente) — apenas a nota de média móvel de 7 dias |
| S13 | Solo CKPool — landing + FAQ | `https://solo.ckpool.org/` | "This is NOT a pool despite its name; it is a service to allow miners to mine solo blocks"; FAQ: shares são "cosmetic for feedback only here" e o client-diff "has no influence on your chance of finding a block"; "Hashrates below 100GH are not recommended to mine Bitcoin as it is unrealistic they will ever find a block"; uso enquadrado como "lottery"; taxa de 2% sobre o reward |
| S14 | M. Rosenfeld — *Analysis of Bitcoin Pooled Mining Reward Systems* (arXiv:1112.4980) | `https://arxiv.org/html/1112.4980v1` | §1.2: block finding em solo é **processo de Poisson** com λ = ht/2³²D, e esse mesmo λ é a variância do número de blocos; "the process is completely random and memoryless"; exemplo de 2011 (1 GH/s, D=1.690.906, B=50 BTC): ~3 meses em média até o primeiro pagamento e 1,18% de chance de receber algo em um dia; §1.3: pool reduz a variância por fator q; §2.2: PPS absorve toda a variância e exige reserva R = B·ln(1/δ)/2f |

---

## 3. Dores ranqueadas

Critério de ranking, declarado: **recorrência declarada na fonte × severidade do dano ×
custo de não resolver × verificabilidade no nosso código**.

### P1 — Transparência de liquidação: quanto, quando, por qual trilho

**Afirmação (P).** A liquidação é condicional ao trilho e ao tamanho do saldo, com teto no
trilho mais barato.

Evidência literal (S1):

| Trilho | Mínimo | Máximo | Taxa |
|---|---|---|---|
| On-chain | 0,0002 BTC | 5 BTC | grátis ≥0,005 BTC · 0,0001 BTC abaixo |
| Lightning | 1 satoshi | 0,005 BTC | grátis |

**Dor.** O trilho gratuito (Lightning) tem **teto de 0,005 BTC** — acima disso o operador
precisa do trilho on-chain e passa a depender do threshold para não pagar taxa. O saldo bruto
não é o valor recebido. S1 diz que as payout rules são avaliadas e pagas **uma vez por dia**
(9:00 UTC), com "Immediate Payout" disponível acima do mínimo.

**O que não sabemos (H).** Não medimos quantos operadores são afetados, nem qual o saldo típico
do nosso público. Nada aqui autoriza afirmar prevalência.

**MVP proposto (mapeado a código existente).** Mostrar **valor líquido por trilho** junto do
saldo: bruto → taxa → líquido, com o teto do Lightning explícito.
- Backend: `services/poll_compute.py` (cálculo puro), `services/hashrate_market.py`, `services/pool_metrics.py`.
- Snapshot: `api_snapshot` em `app.py`.
- Frontend: `static/src/45-market.js`, `static/src/39b-dashboard.js`.
- Regra: número indisponível continua indisponível — sem estimativa (herdado de `BE-04`).

**Experimento.** Comparar, com dados mockados explícitos, o líquido calculado em 3 cenários
(0,0001 · 0,004 · 0,01 BTC) contra a tabela de S1.

**Métrica.** Divergência entre líquido exibido e o valor de S1 = 0 nos 3 cenários.

**Critério de parada.** Parar se o cálculo exigir dado de trilho que não temos de forma
confiável — nesse caso exibir "indisponível" em vez de estimar.

**Fontes:** S1 · S2 · S8 · S9 · S6 (5 fontes primárias) ✅

---

### P2 — Variância do solo mining: nenhum pagamento intermediário

**Afirmação (P).** Solo mining não acumula saldo: só paga quando o bloco é encontrado.

Evidência literal (S2): "Unlike mining in pool, where you earn small, steady rewards, solo
mining only pays out if you find a block yourself"; "there are no sats being accumulated for
you until you hit the jackpot"; "the odds might be 1-in-a-million". Shares submetidas são
"only there for your convenience to check that the mining device is working correctly" —
exceto se atingirem a dificuldade da rede.

**Corroboração por um segundo operador de solo (S13).** O Solo CKPool — citado por S2 como a
origem da taxa de 0,5% dos autores do CKPool — confirma a mesma coisa de forma independente e
de dentro do próprio serviço: as shares são "**cosmetic for feedback only here**", e ajustar o
client-diff "**has no influence on your chance of finding a block**". O mesmo FAQ declara que
hashrate abaixo de 100 GH/s é "unrealistic" para encontrar um bloco e enquadra o uso do
serviço como deixar o equipamento minerando "as a **lottery**". Dois fornecedores distintos,
com interesses comerciais distintos, descrevem shares como cosméticas.

**Mecanismo formal (S14).** S14 dá a forma matemática do que S2 e S13 dizem em linguagem de
produto. O §1.2 enuncia que block finding em solo é um **processo de Poisson** com parâmetro de
taxa h/2³²D, e que esse mesmo λ é a **variância** do número de blocos encontrados — a média
não informa o desvio. Mais relevante para o nosso caso, a fonte afirma que o processo é
"completely random and **memoryless** – If the user has gone 3 months without finding a block,
he isn't any closer than he was in the beginning and must wait on average 3 more months". Isso
é a forma formal da regra `C65-R001`: hashes e shares acumulados **não** são progresso. S14
também nomeia, de forma independente, o problema de operação que o MVP abaixo ataca: "the lack
of regular payments could make it technically more difficult to verify that all systems are
working correctly".

> **Nota de vigência de S14.** Os números de S14 são de **2011** (D = 1.690.906, B = 50 BTC,
> exemplo com 1 GH/s). O que citamos é o *mecanismo* — Poisson, memoryless, variância crescendo
> com a dificuldade. Os valores numéricos do exemplo **não** descrevem 2026 e não devem ser
> reapresentados como se descrevessem.

**Dor.** O operador solo não tem sinal de progresso financeiro por longos períodos, e **dois**
fornecedores independentes admitem que as shares são cosméticas. Isso cria pressão para
transformar estatística em expectativa — exatamente o risco que o projeto já mapeou como
`C65-R001`. S14 acrescenta a consequência operacional: sem pagamento regular, é mais difícil
verificar que o sistema está funcionando.

**Evidência interna (E).** `docs/PROBABILITY_LANGUAGE_AUDIT.md` e o teste de regressão de copy
existem justamente porque termos como *expected time*, *proximity*, *luck* e *ROI* foram
interpretados como prazo ou progresso. A dor externa (P2) e a regra interna (`C65-R001`)
apontam para o mesmo lugar.

**MVP proposto.** Bloco de variância honesto na superfície de Probability: o que é média, o que
é razão histórica, e o que é **incerteza não reduzida** por shares acumuladas. Sem contagem
regressiva, sem barra de progresso.
- Backend: `services/probability.py`, `services/probability_engine.py` (já existentes).
- Frontend: `static/src/42-probability.js`.
- Guard: copy revisada contra `docs/PROBABILITY_LANGUAGE_AUDIT.md`.

**Experimento.** Exibir o mesmo cenário em dois enquadramentos (média da janela vs razão
histórica) e verificar que nenhum dos dois implica prazo.

**Métrica.** Zero ocorrência de linguagem temporal/preditiva no bloco (teste de copy).

**Critério de parada.** Parar se a única forma de tornar a tela útil for introduzir linguagem
preditiva — a regra do projeto vence a conveniência de UX.

**Fontes:** S2 · S13 · S14 ✅ (3 fontes primárias, o mínimo exigido) · S1 (alternativa pool) ·
evidência interna (`docs/PROBABILITY_LANGUAGE_AUDIT.md`, `C65-R001`) ✅

**Gap fechado em 2026-09-16.** A rev. 1 declarou este item com 2 fontes primárias. S13 e S14
fecham o gap com evidência independente: S13 é um **segundo operador** de solo, e S14 é uma
**fonte acadêmica** que dá o mecanismo, não apenas a descrição comercial. Ver §6 (histórico
preservado).

---

### P3 — Risco de entrega e não-reembolsabilidade no aluguel de hashrate

**Afirmação (P).** O recurso contratual do renter é fino: transação final, sem proteção de
preço, reembolso só via ticket.

Evidência literal (S8): "All transactions, including rentals, are final and non-refundable.
Fees paid for rental services are non-refundable unless otherwise specified on a case by case
basis." e "Mining Rig Rentals does not provide price protection or refunds". Do S10: "We will
not answer refund requests via email. To request refunds or to request rental reviews, please
login and use our ticket system."

Contraponto (S9): a home afirma "Built-in safeguards and escrow-backed transactions help
ensure renters receive the hashrate they purchase and rig owners are paid for the service they
provide." — note que isso é **afirmação de marketing na home**, enquanto a obrigação contratual
está no ToS, que é **mais restritivo** e datado de julho de 2017.

**Dor.** Quando o hashrate entregue fica abaixo do contratado, o renter precisa: (a) detectar,
(b) provar, (c) abrir ticket. Nenhuma dessas etapas é suportada por uma ferramenta de
observabilidade neutra — o registro fica do lado de quem vende.

**MVP proposto.** **Trilha de evidência de entrega**: registrar hashrate contratado vs
observado, com timestamp, fonte e janela, além de alerta quando a entrega fica abaixo do
contratado por um período declarado.
- Backend: `services/rental_performance.py` (já existe), `services/hashrate_market.py`,
  `services/poll_compute.py`.
- Frontend: `static/src/46-rentals.js` (já tem fluxo de overpay alert / concentration).
- Regra: usar o contrato de degradação de `BE-05` — `stale` é declarado, nunca vira `0`.

**Experimento.** Replay de uma janela telemetria vs contrato, medindo se o alerta dispara e se
a evidência é exportável.

**Métrica.** Proporção da janela com evidência rastreável (alvo: 100% dos pontos com fonte e
timestamp). **Não** é métrica de lucro.

**Critério de parada.** Parar se a detecção exigir dado do fornecedor que não temos — o valor
está em medir do nosso lado.

**Nota de escopo.** Isto é uma **funcionalidade nova proposta**, não um reparo. Requer Issue
própria com label `new-feature` antes de qualquer código.

**Fontes:** S8 · S9 · S10 ✅ (3 fontes primárias)

---

### P4 — Risco de contraparte e custódia no trilho BTC

**Afirmação (P).** Custo de confiar é assimétrico entre trilhos.

- No **marketplace de hashrate** (S8), a plataforma é "a 'mining' service rental agent" e o
  cripto enviado fica com ela: "Cryptocurrency sent to Mining Rig Rentals ... are never sent to
  third parties and are only withdrawn to a cryptocurrency address specified as being valid by
  the original account holder" — custódia, com saque apenas para endereço da conta original.
- No **trilho de pagamento** (S3/S4/S5), BTCPay é explícito: non-custodial, "Your private keys
  are never required to receive payments".

**Dor.** O operador que escolhe "não custodiar" assume trabalho operacional (runbook, backup,
disponibilidade, reconciliação). O que escolhe custódia troca trabalho por confiança.

**MVP proposto.** Não é feature — é **documentação de decisão**: explicitar o tradeoff no
runbook do operador antes de ativar o canal BTC (Issue #330).
- Docs: `docs/DEPLOYMENT_OPS.md`, `docs/OPERATOR_QUICKSTART.md`,
  `docs/MONETIZATION_BTC_PROGRAMS.md`, `docs/btcpay` (module `services/btcpay.py`).
- Gate existente: checkout só depois de reconciliação (`BTCPAY_RECONCILIATION_VERIFIED=1` é
  estado pós-validação, não atalho).

**Experimento.** Nenhum — é decisão documental. O "experimento" é a validação de reconciliação
já prevista.

**Métrica.** Runbook cobre os três estados de custódia (self-hosted · forwarding · endereço
de referência) sem ambiguidade.

**Critério de parada.** Não ativar o canal BTC antes de reconciliação validada — inalterado.

**Fontes:** S3 · S4 · S5 · S6 · S7 · S8 ✅ (6 fontes primárias)

---

### P5 — Custo de operação é estimativa por construção

**Afirmação (P).** Qualquer número de custo/consumo de energia da rede é uma **faixa**, não um
valor.

Evidência literal (S11): o modelo usa lower-bound (floor), upper-bound (ceiling) e best-guess;
assume "mining nodes ('miners') are rational economic agents that only use profitable
hardware"; trata **electricity cost** como "Static: estimate (assumption)"; e a partir da
v1.2.0 exclui hardware "exótico" e impõe vida econômica máxima de 5 anos. O parâmetro de
eficiência (J/TH) é derivado de especificações de mais de 100 modelos.

**Dor.** Um único número de custo/energia apresentado ao operador é falsa precisão. A própria
metodologia de referência publica três.

**MVP proposto.** Onde o produto exibe custo/consumo derivado, exibir **faixa com o rótulo de
estimativa** e a premissa de custo de energia declarada.
- Backend: `services/poll_compute.py`, `helpers.py` (`_num`, `build_decision_matrix`).
- Frontend: `static/src/45-market.js`, `static/src/39b-dashboard.js`.
- Regra: `BE-04` — indisponível continua indisponível.

**Experimento.** Comparar o valor exibido hoje com a faixa floor/ceiling quando ambos existem.

**Métrica.** Todo campo de custo com rótulo de estimativa e premissa visível.

**Critério de parada.** Parar se o cálculo exigir assumir custo de energia do operador — nesse
caso pedir o input, não estimar.

**Nota de escopo.** Depende de nós fornecermos os valores floor/ceiling do CBECI, que **não
conseguimos capturar** (§6). Sem eles, o MVP fica bloqueado até haver fonte de dados
consumível. **Isto é um bloqueio, não uma suposição.**

**Fontes:** S11 · S12 · S1 ✅ (3 fontes primárias, com a limitação de S12 registrada)

---

## 4. BTCPay: custódia e forwarding (seção exigida pelo critério de aceite)

Regra central, sustentada por fonte primária:

> **Um endereço de referência fixo não é liquidação de invoice nem forwarding.**

Por quê, com evidência literal:

| Ponto | Evidência | Implicação para o produto |
|---|---|---|
| Sem reuso de endereço | S3: "no address re-use since each invoice uses a new address for receiving payments to your wallet"; S3 ainda responde "Why can't I just give my Bitcoin address to a buyer?" como problema de privacidade | Um endereço fixo **não** consegue liquidar invoice: cada invoice precisa de endereço derivado |
| Só xpub é necessário | S4: "By default BTCPay Server only requires an extended public key" | Receber é não-custodial; a chave privada nunca é exigida para receber |
| Gerenciamento de fundos é separado | S4: você **não** é obrigado a usar a wallet interna; S7: wallet interna é opcional e verificada pelo próprio full node | Custódia do recebimento ≠ custódia do saldo |
| Payout/forwarding não é automático | S5: "BTCPay Server does not approve and pay a payout automatically"; S6: status `Awaiting Approval`, e "a future release ... presumably will have automation options" | Forwarding automático é trabalho a construir (Greenfield API), não um switch |
| Automação só via API | S5: "Since our API exposes the full capability of pull payments, a sender can automate payments" | Automatizar forwarding = integrar a API, com os riscos operacionais que isso traz |

| Postura de custódia | Ganho | Custo/risco operacional |
|---|---|---|
| BTCPay self-hosted (non-custodial) | Chave com o operador; sem terceiro | Operador é o processador: runbook, backup, disponibilidade, reconciliação |
| Forwarding automático | Reduz exposição de saldo no hot wallet | Exige automação via API; superfície de falha nova; erro de forwarding é irreversível |
| Endereço de referência fixo | Simples de exibir | **Não** liquida invoice, **não** faz forwarding, não permite reconciliar pagamento com pedido |

Estado atual do produto, para referência: o canal BTC está **off por padrão** — sem
`BTCPAY_URL`/`BTCPAY_API_KEY`/`BTCPAY_STORE_ID` (ou `LN_INVOICE_ENDPOINT`), o checkout BTC
retorna `503` e a aba não aparece. Rastreio: Issue **#330**.

---

## 5. Dores não investigadas nesta rodada

Declaradas para não parecerem cobertas:

- **Custo de energia por jurisdição** e estrutura tarifária real do operador.
- **Ruído, calor e restrição física** de instalação doméstica.
- **Falha de componente** (fonte, hashboard) e ciclo de RMA.
- **Firmware** como dor (bloqueio de vendor, taxa de dev fee).
- **Regulação/localização** por país.

Nenhuma delas recebeu fonte primária nesta rodada. Nenhuma deve ser citada como pesquisada.

---

## 6. Limitações e fontes não obtidas

Registrado por honestidade — o critério de aceite exige ≥3 fontes primárias por dor principal,
e **P2 não atingiu esse número**.

| Alvo | Resultado 2026-09-16 | Impacto |
|---|---|---|
| `braiins.com/hashpower` | `404 Not Found` | Sem fonte primária de SLA de entrega do fornecedor de hashrate |
| `academy.braiins.com/braiins-hashpower/` | `404 Not Found` | idem |
| `academy.braiins.com/{braiins-pool,hashpower}/` | `404 Not Found` | sem página índice de esquema de recompensa |
| `nicehash.com/support` · `/help` · `/legal` | shell JS, sem conteúdo | NiceHash não pôde ser usado como fonte |
| `help.nicehash.com` | DNS não resolve | idem |
| `bitcoin.org/bitcoin.pdf` | tipo de conteúdo não suportado (PDF) | Sem o *whitepaper* em PDF. **Contornado** em 2026-09-16 pela via HTML de S14, que trata Poisson e variância de solo mining de forma direta |
| `ccaf.io/cbnsi/cbeci` (landing) | valores numéricos renderizam no cliente | Sem número de consumo/energia — apenas a nota metodológica |
| Web search | sem resultados em todas as consultas | Fontes obtidas só por URL direta |
| `miningrigrentals.com/api/v2/docs` | `{"success": false, "data": "No endpoint: docs"}` | Sem contrato de API para automação |

**Histórico da rev. 1:** P2 tinha **2 fontes primárias + 1 evidência interna**, abaixo do mínimo
de 3, e isso ficou declarado em vez de arredondado para cima.

**Resolução (rev. 2, 2026-09-16):** o gap de P2 foi **fechado** com duas fontes obtidas por
acesso direto à URL — S13 (`solo.ckpool.org`) e S14 (`arxiv.org/html/1112.4980v1`). P2 passa a
ter **3 fontes primárias**. Nenhuma outra dor mudou de contagem.

**O que continua não obtido, e por quê:** as falhas de `braiins.com/hashpower` (404) e do
NiceHash (shell JS / DNS) permanecem. Elas afetam **P3** (SLA de entrega do fornecedor) e não
são cobertas por S13/S14 — P3 segue com 3 fontes (S8/S9/S10), mas **sem** fonte primária que
prometa um SLA de entrega. Não tratar essa ausência como resolvida.

---

## 7. Achados de código (reparo vs proposta)

Distinção exigida pelo critério de aceite.

### Reparo (higiene, sem comportamento novo)

| Achado | Evidência | Ação |
|---|---|---|
| ~~Arquivo órfão `services/rental_performance.py.bak` versionado no repo~~ | **Correção (rev. 2):** `git ls-files` e `git log --all -- <path>` voltam **vazios** — o arquivo **nunca foi versionado**. É artefato local, já coberto por `.gitignore:29` (`*.py.bak`) | Nenhuma ação de versionamento necessária. A premissa da rev. 1 estava errada; ver §8 |
| ~~Artefato temporário na raiz: `.tmp-extract-pr6.cjs`~~ | **Correção (rev. 2):** igualmente **nunca versionado**; coberto por `.gitignore:26` (`.tmp-*`) | Nenhuma ação de versionamento necessária |

### Já rastreado (sem nova Issue)

| Achado | Onde |
|---|---|
| Divergência doc × runtime (bind `0.0.0.0` descrito como loopback; blacklist descrita como se passasse pelo gate de comando) | Issue **#566** |
| Canal BTC off por padrão, sem env vars | Issue **#330** |
| Matriz física sem evidência real | Issue **#386** |

### Proposta (funcionalidade nova — requer Issue `new-feature` antes de código)

| Proposta | Origem |
|---|---|
| Valor líquido por trilho de payout (P1) | §3 P1 |
| Trilha de evidência de entrega contratado vs observado (P3) | §3 P3 |
| Faixa de estimativa em campos de custo/energia (P5) | §3 P5 |

**Nenhum bug de runtime foi descoberto nesta pesquisa.** Esta foi desk research sobre fontes
externas e leitura de código para mapeamento de MVP; não foi auditoria de código.

---

## 8. Próximas ações (menor ação verificável por item)

| # | Ação | Dono | Critério de aceite |
|---|---|---|---|
| 1 | ~~Issue `correction` para os dois artefatos~~ — **concluído com correção:** Issue #597 aberta e depois fechada como **premissa incorreta**; os arquivos não eram versionados e as regras de `.gitignore` já existiam (linhas 26 e 29) | `OPS-04` | ✅ ver §7 |
| 2 | Abrir Issue `new-feature` para valor líquido por trilho (P1) | `RS-04` → `BE-04` | Issue com métrica e critério de parada |
| 3 | ~~Obter a 3ª fonte primária de P2~~ — **concluído (rev. 2):** S13 + S14 adicionadas, P2 com 3 fontes datadas | `RS-02` | ✅ ver §3 P2 |
| 4 | Abrir Issue `new-feature` para trilha de evidência de entrega (P3) | `RS-04` → `FW-05` | contrato de dados definido |
| 5 | Bloquear P5 até haver fonte consumível de floor/ceiling | `RS-03` | fonte registrada em `RESEARCH_LOG.md` |
| 6 | Registrar este brief no `docs/RESEARCH_LOG.md` como `C65-RNNN` | `RS-01` | entrada criada com risco e status |

---

## 9. Declaração de não-fabricação

Conforme o critério de aceite da Issue #567, este documento **não** contém:

- economia, savings ou profitability estimados;
- uptime ou desempenho de campo de qualquer fornecedor;
- prevalência de mercado de qualquer dor;
- transação, invoice ou pagamento real;
- mudança de deploy, env var aplicada ou feature já implementada.

Todos os números presentes vêm de fonte primária citada em §2 e são apresentados como **o que
a fonte declara**, não como medição do nosso produto.
