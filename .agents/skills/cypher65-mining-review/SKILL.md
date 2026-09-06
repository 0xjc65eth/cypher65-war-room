---
name: cypher65-mining-review
description: Audite tecnicamente o CYPHER65 War Room quando a solicitação envolver mineração SHA-256, telemetria ASIC, pools, solo mining, hashprice, rentabilidade, comandos operacionais, integrações, self-hosting ou UX de operação. Produza diagnóstico somente leitura em português; não use para implementar correções.
---

# CYPHER65 Mining Review

Realize uma revisão adversarial, baseada em evidências, sem modificar o projeto ou sistemas conectados.

## Preparação obrigatória

1. Leia obrigatoriamente `@knowledge.md` ([knowledge.md](knowledge.md)) completamente antes de iniciar qualquer revisão.
2. Localize e respeite `AGENTS.md`, instruções do repositório e documentação de workflow aplicável.
3. Confirme o escopo solicitado e inspecione código, configuração não sensível, testes e documentação relacionados.
4. Consulte [references/security-checklist.md](references/security-checklist.md) sempre que houver comandos, credenciais, integrações, webhooks ou acesso remoto.
5. Consulte [references/validation-cases.md](references/validation-cases.md) ao propor ou avaliar testes.

## Limites de atuação

- Trabalhe em modo somente leitura. Não edite arquivos, banco de dados, configuração, issues, branches, PRs ou serviços externos.
- Não envie comandos a ASICs, pools, mercados, carteiras ou provedores, nem mesmo em dry-run. Avalie o fluxo pelo código, testes, logs fornecidos e endpoints explicitamente seguros e somente leitura.
- Não acesse, revele, copie ou valide valores de secrets. Inspecione apenas presença, precedência, formato esperado, redaction e caminhos de uso quando isso puder ser feito sem ler o valor.
- Não instale nem atualize dependências. Se uma ferramenta estiver ausente, registre a limitação e continue com evidência disponível.
- Execute somente scripts de teste já existentes e proporcionais ao escopo. Não afirme que passaram sem observar o resultado real.
- Preserve dados e funcionalidades. Se a solicitação também pedir correções, encerre primeiro o relatório e informe que a implementação exige uma tarefa separada e autorização explícita.

## Método de revisão

### 1. Inventário e fluxo dos dados

Mapeie, conforme o escopo:

- origem externa ou local;
- coleta, normalização, armazenamento e agregação;
- API e consumidor de UI;
- fallback, cache e reconexão;
- estados loading, empty, stale, offline e error;
- testes que exercitam o caminho real e testes que apenas usam fixtures ou interceptação.

Para toda métrica apresentada, exija: nome sem ambiguidade, valor, unidade, timestamp de observação, janela, origem, premissas e precisão compatível com a fonte. Se algum item faltar, trate a métrica como incompleta; não preencha lacunas por estimativa própria.

### 2. Evidência e classificação

Classifique cada afirmação explicitamente:

- **FATO**: sustentado por código, teste executado, resposta observada, log ou documentação identificável. Cite arquivo e linha quando possível e diferencie teste com fixture de integração real.
- **HIPÓTESE**: explicação plausível ainda não confirmada. Declare a evidência necessária para confirmá-la ou refutá-la.
- **RECOMENDAÇÃO**: ação proposta, com risco tratado, menor teste seguro e critério de aceite.

Não converta ausência de erro em prova de correção. Não trate dados de exemplo, seed, fixture, mock ou cache como telemetria real.

### 3. Revisão por domínio

Use as regras e fórmulas de [knowledge.md](knowledge.md) para verificar:

- telemetria ASIC, uptime, temperatura, potência, eficiência, shares e reconciliação entre firmware e pool;
- métricas SHA-256, pool mining, solo mining e Block Model;
- hashprice, custos, rentabilidade e premissas econômicas;
- alertas, deduplicação, severidade, freshness e estados stale/offline;
- integrações, autenticação, timeout, retry, rate limit, idempotência e self-hosting;
- UX operacional: saúde, prioridade, hashrate perdido, custo, atualidade do dado e próxima ação segura.

Detecte linguagem que transforme média estatística em prazo, melhor share histórico em progresso, luck passada em chance futura, cenário em previsão ou rentabilidade modelada em promessa de lucro. Recomende nomenclatura e tooltip corretivos sem alterar o código.

### 4. Comandos operacionais

Para cada comando ou automação, verifique no código e nos testes:

- read-only como padrão e autorização por função;
- seleção e validação inequívoca do alvo;
- dry-run fiel ao comando real;
- confirmação humana vinculada a alvo, ação e parâmetros;
- timeout, tratamento de ACK e estado pós-comando;
- chave de idempotência, concorrência e repetição;
- audit log imutável o suficiente, com ator, alvo, intenção, resultado e timestamp;
- bloqueio quando o dispositivo fica offline ou a telemetria está stale;
- rollback ou contenção para ação de risco.

Ausência de evidência para qualquer proteção deve aparecer como lacuna, nunca como proteção presumida.

## Testes e critérios de aceite

Priorize testes existentes. Quando rodá-los, registre comando, ambiente relevante sem secrets, duração, quantidade de testes, falhas e skips. Não use mocks para declarar que uma integração externa funciona; rotule-os como testes de contrato ou UI.

Para cada falha ou caminho não coberto, proponha o menor teste seguro contendo:

`ID | Tipo | Cenário | Entrada | Resultado esperado | Arquivo sugerido | Critério de aceite`

Inclua casos nominais e estados inválidos, offline, stale, timeout, duplicação, reconexão, timezone, zero, extremos e permissões quando aplicáveis. Não execute comandos físicos como parte da revisão.

## Formato da entrega

Entregue o relatório em português, nesta ordem:

1. Veredito e escopo efetivamente verificado.
2. Evidências observadas e limitações.
3. Achados priorizados por severidade, cada um separado em **FATO**, **HIPÓTESE** e **RECOMENDAÇÃO**.
4. Matriz de métricas com unidade, timestamp, janela, origem e premissas.
5. Segurança de comandos e integrações.
6. Testes executados e resultados reais.
7. Testes ausentes e critérios de aceite.
8. Correções obrigatórias antes de produção e melhorias posteriores.

Use [references/usage.md](references/usage.md) quando o usuário pedir exemplos de invocação, instalação local ou remoção da skill.
