# Wave 1 — Fleet Telemetry Lineage / Provenance Contract

Este documento é a base contratual antes da implementação (PR A backend e PR B frontend) da Wave 1 do trabalho de honestidade da telemetria Fleet.

Wave 1 mantém o escopo restrito a:
- melhorar a distinção entre momento de medição e momento de ingestão no servidor;
- preservar proveniência de forma honesta e somente quando tecnicamente derivável;
- evitar que amostra antiga substitua estado mais recente;
- preservar diferenças semânticas já comprovadas: UNKNOWN != 0, STALE != OFFLINE, AGENT_ONLINE != MINER_ONLINE, LAST_KNOWN != CURRENT, CACHE != LIVE;
- expor proveniência/frescura de forma honesta na UI Fleet, sem grande redesenho.

Não entra na Wave 1:
- envelope universal de telemetria;
- SLO novo, gate de performance, OpenTelemetry, Supabase, PostHog mining, AI anomalia, pool/device ratio, ML, comandos físicos, reescrita de banco, grande redesenho de frontend.

---

## 0. Definições de clock

O sistema tem pelo menos três relógios conceitualmente distintos:

1. **Device clock**  
   Relógio da ASIC/miner. Pode estar errado, sofrer drift, ATR ou ser ajustado pelo firmware. Não é fonte confiável de "agora" sem validação extra.

2. **Agent clock**  
   Relógio do agente local que empacota e envia a telemetria. Pode ser usado como referência intermediária, mas ainda pode ter skew em relação ao servidor.

3. **Server clock**  
   Relógio do backend no momento da ingestão. É a única fonte razoável para "quando o servidor recebeu" quando a própria plataforma é a observadora, ou quando se quer registrar a recepção de forma comparável entre solicitações.

Regra prática: downstream jamais deve tratar `server_received_at - source_observed_at` como "latência de rede exata" sem confiança explícita de relógio. Se algo desse tipo existir no futuro, precisa de nome honesto ou de mecanismo de clock confidence. Isso não está em escopo nesta Wave.

---

## 1. Campos propostos e semântica

Os quatro nomes abaixo são observados na Wave 1 como candidatos conceituais. A regra é menor mudança: o campo só é populado quando há evidência honesta de que representa aquilo que o nome diz. Caso contrário, permanece nulo/unknown e a UI/API trata isso como indisponível, nunca como zero.

### 1.1 `source_observed_at`

- **O que é (conceitual):** instante em que a fonte de origem observou ou gerou a medição.
- **Source of truth:** o produtor que efetivamente mediu (miner/AxeOS/stratum/agent).
- **Clock owner:** normalmente o dispositivo ou o agente que executa a medição.
- **Can be trusted?** Só quando há evidência prática de que o timestamp carregado reflete a observação da fonte e não foi inventado, copiado cegamente ou preenchido no servidor para "preencher o campo".
- **Fallback / null semantics:** `null` quando não há evidência de observação na fonte. O servidor não replica `time.time()` aqui só porque o campo existe.
- **Wave 1 guidance:** se o produtor local for capaz de entregar um timestamp de medição honesto, ele pode ser preservado; se não for, este campo não é forçado. O importante é não transformar "não temos timestamp da fonte" em "medição recente".

### 1.2 `agent_observed_at`

- **O que é (conceitual):** instante em que o agente observou/capturou a telemetria do dispositivo (por exemplo, quando efetuou a consulta ou leu a resposta).
- **Source of truth:** agente local.
- **Clock owner:** agente.
- **Can be trusted?** Quando o agente pode fornecer um carimbo honesto da observação. Útil quando se quer separar o que o miner relatou do que o agente efetivamente pegou.
- **Fallback / null semantics:** `null` quando o agente não entrega esse carimbo ou quando o contexto não suporta distinguir observação do agente da medição do dispositivo.
- **Wave 1 guidance:** este campo só ganha valor quando existe diferença real e comprovável entre observação da fonte e recepção/empacotamento pelo agente. Não criar campo só por existir.

### 1.3 `server_received_at`

- **O que é:** instante em que o servidor registrou a ingestão da amostra.
- **Source of truth:** relógio do servidor na ingestão.
- **Clock owner:** servidor.
- **Can be trusted?** Sim, para o que o campo diz: recebeção, não medição.
- **Fallback / null semantics:** quando aplicável, deve ser o relógio do servidor no momento da persistência/processamento da amostra, não o timestamp enviado pelo produtor.
- **Wave 1 guidance:** este é o campo mais defensável como timestamp de linhagem no lado do servidor, porque é o único que o backend realmente conhece. Não confundir com "quando foi medido".

### 1.4 `persisted_at`

- **O que é:** instante em que a amostra foi efetivamente persistida/confirmada no armazenamento.
- **Source of truth:** relógio do servidor no momento da escrita/committed.
- **Clock owner:** servidor.
- **Can be trusted?** Sim, para rastreamento de escrita.
- **Fallback / null semantics:** pode ser próximo de `server_received_at`, mas deve representar persistência, não ingestão lógica nem medição. Se não houver razão para separar, não se cria campo artificial.
- **Wave 1 guidance:** útil para auditoria de escrita e para distinguir ingestão de confirmação, mas não deve ser usado como "tempo da medição".

Resumo operacional da Wave 1:

- `server_received_at` e `persisted_at` são campos do lado do servidor e devem usar relógio do servidor.
- `source_observed_at` e `agent_observed_at` são campos do lado do observador e só devem ser preenchidos quando o observador pode entregar algo honesto.
- Nunca preencher um campo de tempo com `time.time()` só para ele não ser nulo, quando isso muda o significado contrato.
- Nulo/unknown é estado válido e semântica correta para linhagem desconhecida.

---

## 2. Ordem de ingestão e boot duro

A política de ordem da Wave 1 é: "mais novo por evidência ganha, mas amostra mais antiga chegar depois não pode derrubar estado mais recente silenciosamente".

Cinco casos explícitos:

- **Caso A — amostra nova chega depois e tem timestamp maior**  
  Resultado: a amostra nova vence, porque há evidência de que é mais recente.

- **Caso B — amostra atrasada chega depois com timestamp menor**  
  Resultado: não pode substituir silenciosamente o estado corrente. A telemetria mais recente já registrada tem precedência.

- **Caso C — timestamps iguais**  
  Resultado: política determinística e documentada. No estado atual do código, o desempate usa `ts` e `rowid` como critério de arrivo quando timestamps são iguais. A Wave 1 não muda isso sem razão; apenas deixa a regra explícita e coberta por teste.

- **Caso D — timestamp futuramente absurdo**  
  Resultado: o timestamp futuro não pode manter o dispositivo permanentemente LIVE. A frescura side do servidor continua segura mesmo que o produtor envie um carimbo equivocado.

- **Caso E — clock do miner errado**  
  Resultado: a frescura side do servidor deve continuar funcional mesmo quando o produtor tem clock errado. O servidor não pode Delegar verdicts de "atualidade" a um relógio não confiável.

Regra transversal: onde o servidor não consegue determinar "quem é o mais recente" com confiança, ele não deve fingir certeza. O comportamento honesto pode ser manter o estado existente e/ou marcar linhagem como limitada.

---

## 3. Contrato de idempotência

Preservar o comportamento existente do `idempotency_key`, com cobertura explícita para os cenários:

- mesma chave + mesmo payload: replay legítimo não duplica.
- mesma chave + payload diferente: conflito, não nova observação silenciosa.
- retry duplicado: idempotente.
- duplicata concorrente: segura.
- duplicata out-of-order: não pode criar duplicação ou derrubar estado mais recente.

A Wave 1 trata isso como contrato a preservar, não como algo para reinventar.

---

## 4. Empty heartbeat

Contrato comprovado: `telemetry: {}` é presença do agente, não nova medição do miner.

Empty heartbeat não pode, sequer indiretamente:

- zerar hashrate;
- zerar temperatura;
- atualizar o timestamp de medição como se houvesse medição;
- transformar last-known em current;
- tornar o miner saudável apenas porque o agente está vivo.

A semântica correta é: o heartbeat pode renovar presença/last_seen, mas não deve derrubar o último valor bom nem fingir medição atual.

---

## 5. Proveniência: o que pode ser exposto

A Wave 1 deve expor proveniência somente quando for derivável de forma honesta e útil, sem duplicar informações já disponíveis nem criar cardinalidade desnecessária.

Campos candidatos para quando tecnicamente disponíveis e semanticamente corretos:

- `source` — de onde veio a telemetria (quando a origem é conhecida e útil).
- `protocol` — protocolo/subsistema quando relevante e não secreto.
- `agent_id` — quando útil e já existir, sem expor segredos.
- `received_at` — instante de recepção no servidor (se esse campo for introduzido).
- `measurement_at` — instante da medição na fonte (apenas quando houver evidência honesta, e não confundido com recepção).
- `freshness` — visto honestamente, com rótulos como LIVE/STALE/UNKNOWN/SYNCED a partir de critérios declarados, não fingidos.
- `last_valid_measurement_at` — quando houver distinção real entre medição atual e último valor bom conhecido.

O que não fazer:

- expor segredos;
- criar campos que duplicam o que já está disponível;
- adicionar dimensões desnecessárias em métricas globais.

---

## 6. Zero, null, unknown, missing

Comportamento explícito:

- **0 legítimo** é 0. Exemplo: hashrate 0 quando documentado/provado que é zero.
- **null** pode significar indisponível, não medido ou sem valor conhecido.
- **unknown** não é zero.
- **missing** não é zero.

Na UI e na API:

- Nunca tratamos `value || "-"` como padrão quando zero é valor legítimo.
- Use tratamento nullish/validity: distinga ausência de valor de valor zero.
- 0 deve aparecer como zero quando for zero real.
- Ausência deve aparecer como indisponível/unknown, não como 0.
- UNKNOWN deve continuar distinguível de 0.

---

## 7. Semânticas preservadas explicitamente

Sempre que um campo/estado existir ou for usado, a Wave 1 não pode colapsar:

- UNKNOWN != 0
- STALE != OFFLINE
- AGENT_ONLINE != MINER_ONLINE
- LAST_KNOWN != CURRENT
- CACHE != LIVE

Isso significa que código/nomes/UI não podem fingir que eles são iguais ou que um implica o outro sem evidência.

---

## 8. Backward compatibility

- Linhas históricas que não têm evidência de linhagem devem permanecer NULL/UNKNOWN nas colunas/nuances introduzidas.
- Não fazer migração destrutiva.
- Não inventar timestamps para linhas antigas.
- UI/API deve lidar corretamente com linhagem nula/unknown.
- Historical unknown provenance must remain unknown.

---

## 9. Escopo realista do PR A e PR B nesta Wave

- **PR A (backend):** timestamps de linhagem/proveniência onde tecnicamente justificados, política de ordenação e idempotência preservada/reforçada, comportamento de empty heartbeat preservado, e comportamento de linhas históricas nulas preservado; testes backend/integration cobrindo os casos do Passo 6 e do Passo 12.
- **PR B (frontend):** UI Fleet que distingue visualmente LIVE/STALE/UNKNOWN, mostra idade/fonte/proveniância quando disponível, e trata zero vs ausência de forma honesta; testes frontend/Playwright quando afetado.

---

## 10. Critérios de validade do contrato nesta Wave

Um campo/nuance é válido nesta Wave se:

1. o significado honesto do campo pode ser derivado;
2. a fonte do relógio/owner do clock está identificável;
3. há fallback definido para quando a informação não existe;
4. o valor nulo/unknown é aceito como estado legítimo;
5. não há invenção de tempo, nem falsa precisão de latência, nem colapso de semânticas distintas.

Se não passar nisso, Wave 1 não cria o campo.
