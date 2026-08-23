# 🛡️ TRADEMARK POLICY — proteção da marca "CYPHER65 WAR ROOM"

> **Marca ≠ código.** A licença MIT protege o código-fonte; a **marca** protege
> nome, logotipo e identidade. Um fork pode usar todo o código MIT, mas não
> pode se apresentar como "CYPHER65 War Room" sem autorização.
>
> Regra de ouro CFO: começar com o **mínimo viável** (Brasil, classes 9 + 42,
> custo ~R$ 880–1.760) e expandir para EU/UE/USA conforme tração.

---

## 1. Por que registrar (e por que marca ≠ copyright)

O caso concreto que motivou este documento: o repositório
`bladept696/centro-de-comando-v3` (auditado em 23/08/2026) tem **código 100%
original**, então **não viola a licença MIT** — mas tem sobreposição forte de
conceito (dashboard de mineração, porta 8765, best share, probabilidade solo,
MRR, alertas). A lição:

| Proteção | O que cobre | O que NÃO cobre |
|---|---|---|
| **Licença MIT** (copyright) | Código-fonte, textos, assets | Ideias, features, nome, identidade visual |
| **Marca registrada** | Nome, logotipo, slogan, identidade | Código, funcionalidades |

Ou seja: hoje, qualquer terceiro pode criar um "clone" com nome confuso
(ex.: *"Cypher65 Command Center"*) usando código próprio — e não haveria base
legal para impedir. **O registro da marca fecha exatamente essa brecha.**

---

## 2. O que registrar (ativos de marca)

| Ativo | Força distintiva | Prioridade | Observação |
|---|---|---|---|
| **CYPHER65** (wordmark) | Alta — termo arbitrário/coined | ⭐ 1º | Registro mais amplo; protege o núcleo do nome |
| **CYPHER65 WAR ROOM** (composto) | Média-alta | 2º | Protege o nome completo do produto |
| **Logotipo** (⚡ + wordmark) | Alta (design) | 3º | Só quando houver versão final estável (ver DESIGN_SYSTEM_V2) |
| **Slogan** ("Built for the cypherpunks") | Baixa | Opcional | Slogans são protegíveis, mas fracos isoladamente |

**Recomendação:** registrar o wordmark **CYPHER65** primeiro — ele é o ativo
mais forte e mais amplo. O registro do composto e do logotipo pode ser feito
no mesmo pedido (figurativa mista) ou depois.

> **Uso imediato (custo $0):** passe a usar o símbolo **™** ao lado do nome
> (README, rodapé da UI, docs). Não é registro, mas cria registro público de
> uso e desencoraja terceiros. O **®** só pode ser usado após a concessão.

---

## 3. Classes Nice recomendadas

O produto é uma plataforma de monitoramento/analytics (SaaS + app), então:

| Classe Nice | Cobre | Aplicável? |
|---|---|---|
| **9** | Software (desktop/app download) | ✅ Sim — ex. `.exe`, app mobile |
| **42** | SaaS, plataforma web, hosting, serviços de TI | ✅ Sim — o core (dashboard web + API) |
| **36** | Serviços financeiros/pagamentos | ⚪ Futuro — só se virar processadora de pagamentos |
| **35** | Publicidade/gestão de negócios | ❌ Não é o core do produto |

**Custo mínimo:** 2 classes (9 + 42) no INPI = ~R$ 880–1.760 (ver §4).

---

## 4. Jurisdições, custos e prazos (valores 2026 — confirmar na fonte oficial)

| Jurisdição | Órgão | Custo (1ª classe + extra) | Prazo médio | Cobertura |
|---|---|---|---|---|
| **Brasil** | INPI | R$ 440–1.760/classe (pré-aprovada vs livre; PF/ME têm desconto) | ~2–3 anos | Brasil |
| **EUA** | USPTO | US$ 350/classe (tarifa única desde 2025) | ~8–14 meses | EUA |
| **União Europeia** | EUIPO | € 850 (1ª) + € 50 (2ª) + € 150 (3+); 2 classes = **€ 900** | ~4–6 meses | 27 países |
| **Internacional** | Madrid Protocol | Taxa base + taxas por país designado | varia | multi-país num pedido só |

Fontes: `gov.br/inpi` (Tabela de Retribuições), `uspto.gov/trademark-fee-information`,
`euipo.europa.eu` (Fees and payments). **Sempre confira os valores na fonte
oficial antes de pagar** — tabelas mudam (o INPI reajusta periodicamente).

**Caminho recomendado (custo total mínimo):**

1. **INPI** — classes 9 + 42 (~R$ 880–1.760) — comunidade principal é BR.
2. **EUIPO** — 1 pedido cobre UE inteira (€ 900 p/ 2 classes) — barato e rápido.
3. **USPTO** — quando houver tração US (US$ 700 p/ 2 classes).
4. **Madrid** — apenas se precisar de vários países extra de uma vez.

---

## 5. Passo a passo — registro no INPI (primeiro)

1. **Busca de anterioridade (grátis):**
   - INPI: `busca.inpi.gov.br/pePI` (Marcas) — buscar "cypher65", "cypher",
     "war room" nas classes 9 e 42, incluindo fonética (CYPHER65 / CIPHER65).
   - USPTO: `tmsearch.uspto.gov` · EUIPO: `euipo.europa.eu/eSearch`.
2. **Definir titular:** pessoa física (0xjc65eth) ou jurídica (recomendado
   quando houver empresa — facilita licenciamento e PRO §R1). PF paga menos.
3. **Pedido:** sistema e-Marcas do INPI; especificação de produtos/serviços
   (prefira **especificação pré-aprovada** — mais barata e menos passível de
   exigência).
4. **Acompanhar:** o pedido é examinado (~2–3 anos); se publicado, terceiros
   têm **60 dias para oposição** (e você terá os mesmos 60 dias para opor
   contra marcas conflitantes — ver §7).
5. **Concessão:** vigência de **10 anos**, renovável por mais 10.

---

## 6. Marca vs MIT — política de uso da identidade

As regras da licença MIT (uso do **código**) e as regras de **marca** (uso do
**nome/logotipo**) são independentes. Resumo para terceiros:

### ✅ Uso permitido (sem pedir permissão)

- **Referência nominativa:** citar "CYPHER65 War Room" em texto para dizer que
  o software roda com/sobre/compatível com ele (ex.: "compatible with CYPHER65
  War Room").
- **Forks com nome diferente:** copiar o código (MIT) e lançar com **outro
  nome** — desde que mantenha o aviso de copyright MIT e não dê a entender que
  é o projeto oficial.
- **Atribuição:** creditar "© 2026 0xjc65eth — licença MIT" como a licença exige.

### 🚫 Uso proibido (violação de marca)

- Usar **CYPHER65**, **CYPHER65 WAR ROOM** ou logotipo parecido como nome de
  produto, repo, pacote, domínio, conta ou app **derivado/comercial** de forma
  a confundir com o projeto oficial.
- **Passing off:** apresentar fork/derivado como se fosse o produto oficial.
- **Cybersquatting:** registrar domínios/nomes de usuário com o nosso nome para
  desviar tráfego ou revender.
- Usar o **logotipo** (⚡ + wordmark) sem autorização em material comercial.

### ✍️ Como pedir permissão

Email/proposta via GitHub (`0xjc65eth/cypher65-war-room`) ou pelo canal de
suporte do painel. Usos comerciais de marca (white-label, merch) são avaliados
caso a caso — ver `docs/BUSINESS_PLAN.md` (ENTERPRISE white-label).

### 📌 Nota opcional na LICENSE

Para deixar explícito que a MIT **não** cobre a marca, é prática comum adicionar
um parágrafo ao arquivo LICENSE ou um arquivo `NOTICE`:

> *"MIT License does not extend to the trademarks 'CYPHER65', 'CYPHER65 WAR
> ROOM' or associated logos, which remain the property of 0xjc65eth."*

(Alterar a LICENSE é decisão sua — posso aplicar se quiser.)

---

## 7. Enforcement — escada de escalação

| Nível | Ação | Custo | Quando |
|---|---|---|---|
| 1 | **Contato amigável** (comunidade) | $0 | Uso confuso por membros da comunidade (ex.: apoiadores) |
| 2 | **Carta de cessação** (cease & desist) | $0–baixo | Ignorou o nível 1 ou uso comercial deliberado |
| 3 | **Reclamação na plataforma** (GitHub/lojas) | $0 | Repo/conta com nome confuso — GitHub tem política de marcas própria |
| 4 | **Oposição administrativa** (INPI/EUIPO) | taxa | Pedido de terceiro conflitante publicado no boletim |
| 5 | **Ação judicial** | alto | Último recurso; uso comercial doloso |

**Lembrete do caso auditado:** nível 1 é o caminho natural para o
`centro-de-comando-v3` — código original + autor é apoiador da comunidade
(Filipe Silva, bitminer33). Não há violação a exigir níveis 2–5; há convivência.

---

## 8. Vigilância contínua (custo $0)

- **Trimestral:** buscar "cypher65"/"cypher" em `busca.inpi.gov.br/pePI`,
  `tmsearch.uspto.gov`, `euipo.europa.eu/eSearch`.
- **Contínuo:** GitHub (repos/packages com o nome), npm/PyPI, domínios
  (`cypher65.*`), Google Alerts.
- **GitHub:** monitorar novos repos que combinem "cypher + mining/war room".
- Registrar **domínios e handles** oficiais antes de precisar deles
  (cypher65.com, GitHub org `cypher65`, PyPI/npm names).

---

## 9. Plano de ação imediato

| # | Ação | Custo | Prazo |
|---|---|---|---|
| 1 | Busca de anterioridade INPI/USPTO/EUIPO (grátis) | $0 | 1 semana |
| 2 | Começar a usar **™** no README/UI/docs | $0 | hoje |
| 3 | Registrar **CYPHER65** classes 9+42 no **INPI** | ~R$ 880–1.760 | 1 mês |
| 4 | Registrar domínios/handles oficiais | ~R$ 50–150/ano | 1 mês |
| 5 | Publicar `TRADEMARKS.md` + nota na LICENSE | $0 | 1 semana |
| 6 | EUIPO (2 classes) quando consolidar | € 900 | após INPI |
| 7 | USPTO quando houver tração US | US$ 700 | após tração |

**Total mínimo para fechar a proteção do núcleo (passos 1–5): ~R$ 950–1.950.**

---

## 10. Caso concreto: `bladept696/centro-de-comando-v3`

| Pergunta | Resposta |
|---|---|
| Copiou código? | **Não** — arquitetura, funções, classes, assets e textos 100% originais (Jaccard 16,8%; 0 marcas distintivas compartilhadas) |
| Violou a MIT? | **Não** — a obrigação de atribuição só existiria se houvesse cópia substancial |
| Usou a nossa marca? | **Não** — nome, logotipo e identidade são próprios ("Centro de Comando", não "CYPHER65...") |
| Risco residual? | Sobreposição de **conceito** (porta 8765, features) — não é violação; o registro da marca (§3–§9) é o que protege contra um futuro clone com nome confuso |
| Ação recomendada | Nível 1 (convivência/contato amigável) — autor é apoiador com acesso FULL & FREE |

---

*Documento de estratégia interna. Não substitui assessoria jurídica — para
decisões de registro o ideal é validar com um agente de propriedade industrial
ou advogado (INPI/EUIPO/USPTO aceitam procurador).*
