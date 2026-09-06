# CYPHER65 Research Log

Registro de descobertas técnicas, operacionais e de produto relevantes para o CYPHER65 War Room.

## Regras do registro

- Registre somente informações necessárias para pesquisa, decisão e validação.
- **Nunca registre secrets, credenciais, tokens, cookies, chaves, dados de pagamento ou dados pessoais.** Redija exemplos e evidências antes de adicioná-los.
- Diferencie o que foi observado historicamente do comportamento do código atual. Uma fonte antiga não comprova que o problema ainda existe.
- Não reutilize código, texto ou assets externos sem identificar e validar a licença.
- Quando a licença não puder ser confirmada, use `Não identificada` e não incorpore o material ao produto.
- Use URLs permanentes ou suficientemente específicas. Para fontes do repositório, prefira o arquivo versionado no GitHub.
- Registre uma nova descoberta com o próximo ID `C65-RNNN`. Atualizações podem mudar decisão, próxima ação e status, preservando a fonte original.

## Status permitidos

| Status | Significado |
|---|---|
| `descoberto` | Achado registrado, ainda sem validação suficiente no código ou ambiente atual. |
| `validado` | Evidência reproduzida e conclusão confirmada no escopo declarado. |
| `protótipo` | Hipótese validada parcialmente em experimento isolado, sem integração de produção. |
| `implementado` | Mudança correspondente está no código; ainda deve manter testes e observabilidade. |
| `rejeitado` | Descoberta, proposta ou fonte descartada com justificativa registrada. |

## Escala de risco

- `CRÍTICO`: pode causar perda material, comando inseguro, exposição de secrets ou decisão operacional gravemente incorreta.
- `ALTO`: compromete confiança, disponibilidade, integridade de dados ou interpretação financeira/probabilística.
- `MÉDIO`: degrada diagnóstico, UX, compatibilidade ou manutenção sem risco imediato grave.
- `BAIXO`: impacto limitado, documental ou cosmético.

---

## C65-R001 — Linguagem probabilística pode ser interpretada como prazo ou progresso

- **Data:** 2026-08-27
- **Fonte:** Auditoria interna de linguagem de probabilidade, blocos e economia
- **URL:** https://github.com/0xjc65eth/cypher65-war-room/blob/master/docs/PROBABILITY_LANGUAGE_AUDIT.md
- **Categoria:** Probabilidade · Solo mining · Rentabilidade · UX
- **Problema observado:** Termos como expected time, proximity, cumulative progression, luck e ROI podiam transformar médias estatísticas, razões históricas ou cenários econômicos em prazo, progresso causal ou promessa de lucro.
- **Relevância para o CYPHER65:** Interpretação errada pode levar o operador a decisões financeiras ou operacionais incompatíveis com a independência dos hashes e com a incerteza dos inputs.
- **Licença:** MIT — documentação do próprio projeto; marcas excluídas conforme `LICENSE` e `TRADEMARKS.md`.
- **Risco:** ALTO
- **Decisão:** Manter contratos legados quando necessários para compatibilidade, mas usar linguagem não preditiva, premissas explícitas e métricas avançadas fora do Overview.
- **Próxima ação:** Manter testes de compreensão e regressão de copy; revalidar toda nova superfície que exiba probabilidade, luck, ROI, break-even ou forecast.
- **Status:** implementado

## C65-R002 — Saúde operacional estava dispersa entre múltiplas superfícies

- **Data:** 2026-08-26
- **Fonte:** Auditoria interna de UX/UI operacional
- **URL:** https://github.com/0xjc65eth/cypher65-war-room/blob/master/docs/OPERATIONAL_UX_AUDIT.md
- **Categoria:** UX operacional · Telemetria · Fleet · Dados stale/offline
- **Problema observado:** Saúde, exceções, hashrate perdido, custo e freshness não formavam uma decisão única no primeiro viewport; métricas analíticas competiam com incidentes operacionais.
- **Relevância para o CYPHER65:** O operador precisa identificar rapidamente se deve agir, quais ASICs exigem atenção, qual impacto existe e se os dados ainda são atuais.
- **Licença:** MIT — documentação do próprio projeto; marcas excluídas conforme `LICENSE` e `TRADEMARKS.md`.
- **Risco:** ALTO
- **Decisão:** Priorizar uma visão exception-first, distinguir zero de indisponível e manter ações do resumo como navegação para diagnóstico, sem executar comandos.
- **Próxima ação:** Validar a compreensão em desktop e mobile com operadores reais e medir tempo para identificar saúde, perda, freshness e próxima ação segura.
- **Status:** implementado

## C65-R003 — Integrações de Hash Market exigem validação individual de schema, autenticação e unidade

- **Data:** 2026-08-01
- **Fonte:** Pesquisa forense interna do pipeline Fênix
- **URL:** https://github.com/0xjc65eth/cypher65-war-room/blob/master/docs/FENIX_PIPELINE_RESEARCH.md
- **Categoria:** Hash Market · Integrações · Unidades · Supply chain de dados
- **Problema observado:** A baseline histórica encontrou diferenças entre endpoints Braiins, NiceHash e MRR, além de risco de apresentar TH/s como H/s. Parte das integrações exigia parâmetros ou autenticação específicos.
- **Relevância para o CYPHER65:** Schema ou unidade incorreta pode alterar preço efetivo, liquidez, comparação de ofertas e recomendação econômica.
- **Licença:** MIT — documentação do próprio projeto; termos e licenças das APIs externas devem ser verificados separadamente antes de reutilizar respostas, schemas ou SDKs.
- **Risco:** ALTO
- **Decisão:** Não tratar uma integração como operacional apenas porque a UI ou um mock funciona. Exigir contrato por provedor, unidade explícita, timestamp, origem, freshness e teste opt-in contra a API real.
- **Próxima ação:** Reproduzir a matriz no código atual sem registrar credenciais; documentar status por endpoint, rate limit, autenticação, unidade e comportamento de erro parcial.
- **Status:** descoberto

## C65-R004 — Testes podem contaminar dados operacionais se o banco não estiver isolado

- **Data:** 2026-08-01
- **Fonte:** Pesquisa forense interna do pipeline Fênix
- **URL:** https://github.com/0xjc65eth/cypher65-war-room/blob/master/docs/FENIX_PIPELINE_RESEARCH.md
- **Categoria:** Testes · Persistência · Integridade de dados
- **Problema observado:** A baseline histórica registrou fixtures e alertas de teste persistidos no banco operacional por caminhos que inicializavam a aplicação com o DB padrão.
- **Relevância para o CYPHER65:** Dados sintéticos podem produzir alertas falsos, distorcer histórico, reduzir confiança e esconder incidentes reais.
- **Licença:** MIT — documentação do próprio projeto; marcas excluídas conforme `LICENSE` e `TRADEMARKS.md`.
- **Risco:** CRÍTICO
- **Decisão:** Todo teste que persiste dados deve usar banco temporário explicitamente isolado; a ausência de alteração no banco operacional deve ser critério de aceite.
- **Próxima ação:** Revalidar no branch atual comparando hash e contagem das tabelas operacionais antes/depois da suíte, sem expor o conteúdo dos registros.
- **Status:** descoberto

## C65-R005 — Dados offline não podem ser tratados como zero nem como telemetria atual

- **Data:** 2026-08-26
- **Fonte:** Auditoria interna de UX/UI operacional
- **URL:** https://github.com/0xjc65eth/cypher65-war-room/blob/master/docs/OPERATIONAL_UX_AUDIT.md
- **Categoria:** Telemetria ASIC · Uptime · Freshness · Alertas
- **Problema observado:** O último valor conhecido pode ser útil como baseline de perda, mas se torna enganoso quando apresentado como produção atual; ausência de baseline também não equivale a zero perdido.
- **Relevância para o CYPHER65:** A distinção influencia hashrate agregado, impacto financeiro, priorização de ASICs e confiança nos alertas.
- **Licença:** MIT — documentação do próprio projeto; marcas excluídas conforme `LICENSE` e `TRADEMARKS.md`.
- **Risco:** ALTO
- **Decisão:** Separar estado offline, idade do dado, último valor conhecido, valor ativo e indisponibilidade; usar baseline apenas com rótulo e janela explícitos.
- **Próxima ação:** Manter testes para ASIC offline com e sem baseline, snapshot stale, reconexão e agregação de fleet após reinício.
- **Status:** implementado

---

## Modelo para nova descoberta

Copie o bloco abaixo e substitua todos os campos. Não deixe valores hipotéticos parecendo fatos.

```markdown
## C65-RNNN — Título objetivo

- **Data:** AAAA-MM-DD
- **Fonte:** Nome da fonte, autor ou organização
- **URL:** https://...
- **Categoria:** Categoria principal · Categoria secundária
- **Problema observado:** O que foi efetivamente observado e em qual contexto.
- **Relevância para o CYPHER65:** Impacto técnico, operacional, financeiro ou de produto.
- **Licença:** Licença confirmada, `Não identificada` ou `Não aplicável`, com justificativa.
- **Risco:** CRÍTICO | ALTO | MÉDIO | BAIXO
- **Decisão:** Adotar, validar, prototipar, adiar ou rejeitar, com motivo.
- **Próxima ação:** Menor ação verificável, responsável quando conhecido e critério de aceite.
- **Status:** descoberto | validado | protótipo | implementado | rejeitado
```
