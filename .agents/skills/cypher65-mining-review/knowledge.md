# Conhecimento de revisão de mineração CYPHER65

Este arquivo é a base técnica obrigatória da skill. Ele orienta a revisão; não substitui a evidência do código, da configuração e das fontes realmente usadas pelo projeto.

## Contrato mínimo de qualquer métrica

Uma métrica só é operacionalmente confiável quando informa ou permite provar:

- **valor** e estado de disponibilidade;
- **unidade** e escala, sem conversões implícitas;
- **observed_at** ou timestamp equivalente;
- **janela** de amostragem ou agregação;
- **origem**: firmware, pool, rede, mercado, banco, cache ou cálculo;
- **premissas** e fórmula, quando derivada;
- **freshness** e critério configurado de stale;
- **precisão** compatível com a fonte.

Não invente limiares. Descubra no código ou na configuração o que significa stale, offline, degradado, febre térmica ou perda de hashrate. Se não existir regra explícita, registre a ausência.

## Unidades SHA-256

- `1 TH/s = 10^12 H/s`
- `1 PH/s = 10^15 H/s = 1.000 TH/s`
- `1 EH/s = 10^18 H/s = 1.000 PH/s`
- Potência: W ou kW. Energia: kWh. Não trate potência como energia.
- Eficiência normalmente usa `J/TH = W / (TH/s)`. Hashrate zero torna a razão indefinida; exiba indisponível, não zero ou infinito.

Verifique se cada conversão usa a escala declarada pela fonte. Um campo chamado `hashrate` sem unidade é uma falha de contrato até que produtor e consumidor sejam rastreados.

## Shares, dificuldade e probabilidade

Para dificuldade de rede `D`, hashrate constante `H` em H/s e janela `t` em segundos:

- hashes médios para um bloco no modelo: `D × 2^32`;
- valor médio modelado de blocos na janela: `λ = H × t / (D × 2^32)`;
- probabilidade modelada de pelo menos um bloco: `P(X ≥ 1) = 1 - exp(-λ)`.

Esses resultados dependem de hashrate e dificuldade constantes e de tentativas independentes. O intervalo médio não é prazo, contagem regressiva ou promessa.

Para uma share com dificuldade efetiva `d`, a equivalência probabilística de atingir o target da rede é aproximadamente `min(1, d / D)`. Essa relação descreve aquela dificuldade de share; o melhor share histórico não representa a chance da próxima tentativa e não mede progresso acumulado.

Luck passada, cumulative work e proximidade histórica não alteram a distribuição do próximo hash. Procure e sinalize textos como “perto”, “progresso para o bloco”, “quantum lock”, “previsão”, “garantia” ou datas implícitas.

## Pool e solo mining

Separe claramente:

- hashrate do dispositivo, hashrate aceito/estimado pela pool e hashrate da rede;
- workers cadastrados, alcançáveis, hashing e reconhecidos pela pool;
- shares accepted, stale, rejected e unknown;
- pagamento observado, receita estimada e valor esperado modelado;
- pool luck histórica e probabilidade futura.

A taxa de stale precisa declarar numerador, denominador e janela. Uma forma possível é `stale / (accepted + stale + rejected)`, mas a revisão deve usar a definição real do projeto ou registrar que ela não está definida.

Reconcilie firmware e pool com tolerância e janela explícitas. Divergência pode resultar de smoothing, latência, intervalo de reporte, unidade ou dispositivo offline; não conclua defeito de hardware sem evidência.

## Uptime, offline e freshness

Não confunda:

- aplicação/API alcançável;
- coletor executando;
- ASIC alcançável na LAN;
- ASIC hashing;
- worker visto recentemente pela pool;
- dado apenas disponível em cache.

Uptime deve indicar entidade, janela e fonte. Dados antigos devem manter o último valor apenas se rotulados como stale, com idade visível. Offline não deve ser apresentado como zero operacional quando “sem dado” for a interpretação correta.

Revisar boot, reconexão, backoff, timeout, persistência após reinício, timezone e ordenação por timestamps. Comparações devem normalizar timestamps para UTC internamente e deixar clara a zona exibida.

## Hashprice e rentabilidade

Hashprice precisa declarar moeda, unidade e período, por exemplo `USD/PH/dia`, `BTC/PH/dia` ou `sat/TH/dia`, além de fonte e timestamp. Confirme cada conversão; não compare valores em bases diferentes.

Rentabilidade deve separar:

- receita bruta observada ou modelada;
- pool fee, rental fee e demais taxas;
- energia: `potência_kW × horas × tarifa_por_kWh`;
- custos fixos e capex, se realmente fornecidos;
- receita líquida, margem, ROI e break-even;
- preço BTC, hashprice, dificuldade e janela usados.

ROI e break-even são inválidos sem investimento/custo correspondente e período. Cenários com inputs constantes não são forecast. Nunca prometa lucro e não apresente casas decimais além da qualidade das entradas.

## Telemetria ASIC

Rastreie o contrato por família de firmware e modelo. Verifique pelo menos:

- identidade estável do device e endereço normalizado;
- hashrate e sua janela;
- temperatura de chips/boards/VRM quando disponível;
- potência, eficiência e fans com unidade;
- pools configuradas e shares;
- boot time, last seen, versão de firmware e capacidade de comando;
- valores ausentes, extremos, negativos, `NaN`, infinito e divisão por zero;
- deduplicação e ordenação de amostras atrasadas.

Não atribua suporte a Antminer, Bitaxe ou firmware específico apenas porque existe um parser ou fixture. Exija teste de contrato e, para alegar suporte físico, evidência controlada em hardware real.

## Alertas e UX operacional

Um alerta útil identifica entidade, severidade, causa, evidência, idade do dado e ação segura. Verifique deduplicação, cooldown, resolução, reabertura, ordenação e persistência.

Em poucos segundos, a UX deve permitir responder:

- a operação está saudável?
- quais ASICs exigem atenção?
- quanto hashrate está sendo perdido e em qual janela?
- qual custo operacional foi observado ou modelado?
- os dados estão atuais?
- qual ação segura pode ser tomada e por quê?

Priorize exceções. Não use cor como único sinal. Verifique loading, empty, stale, offline e error separadamente em desktop e mobile.

## Integrações e self-hosting

Para pools, mercados, webhooks e provedores, verifique:

- autenticação e precedência entre environment e configuração persistida;
- secrets write-only, redaction e rotação;
- timeout, retry com backoff, rate limit e circuit breaker quando necessário;
- paginação, schema/versionamento, idempotência e deduplicação;
- cache, freshness e erro parcial por provedor;
- comportamento sem provedor configurado;
- persistência, backup, restore, migração e estabilidade da chave de criptografia;
- diferenças entre desenvolvimento, self-hosted e produção.

Nunca leia o valor de uma credencial. É suficiente verificar que existe um caminho seguro de armazenamento/uso e que testes cobrem ausência, rejeição, rotação e falha de descriptografia.

## Comandos seguros e audit log

Read-only deve ser o padrão. Para ações mutáveis, exija defesa em profundidade:

1. autorização e capacidade explícita do device;
2. alvo canônico e ainda online;
3. dry-run sem efeito colateral e baseado no mesmo validador do comando real;
4. confirmação humana contendo alvo, ação e parâmetros finais;
5. timeout e cancelamento;
6. idempotência e proteção contra concorrência/replay;
7. ACK verificável;
8. reconciliação do estado pós-comando;
9. audit log com ator, tenant, alvo, intenção, parâmetros redigidos, timestamps e resultado;
10. rollback ou contenção proporcional ao risco.

Logs não devem conter credenciais, tokens, dados de pagamento desnecessários ou payloads sensíveis. Falha de audit log em comando de risco deve impedir ou marcar claramente a execução, conforme a política observada do produto.
