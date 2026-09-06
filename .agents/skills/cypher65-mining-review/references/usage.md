# Uso da skill

## Quando usar

Use a skill para auditorias, diagnósticos e revisões adversariais do CYPHER65 War Room. Ela é deliberadamente somente leitura: entrega evidências, hipóteses, recomendações, testes propostos e critérios de aceite, mas não implementa mudanças.

## Exemplos de chamada

### Revisão completa

```text
Use $cypher65-mining-review para auditar o CYPHER65 inteiro. Priorize telemetria ASIC, dados stale/offline, segurança de comandos e UX operacional. Não altere arquivos.
```

### Métricas e probabilidade

```text
Use $cypher65-mining-review para revisar Block Model, solo mining e rentabilidade. Confirme fórmulas, unidades, origem, janela e timestamp e identifique linguagem que possa prometer bloco ou lucro.
```

### Integrações de rentals

```text
Use $cypher65-mining-review para diagnosticar MRR e Braiins em modo somente leitura. Não leia credenciais. Separe falha de configuração, autenticação, transporte e schema e proponha testes de aceite.
```

### Comandos remotos

```text
Use $cypher65-mining-review para auditar os comandos de ASIC. Verifique read-only, dry-run, confirmação humana, timeout, idempotência, ACK, estado pós-comando e audit log. Não envie comandos.
```

### UX operacional

```text
Use $cypher65-mining-review para revisar Overview, Fleet e Live Mining em desktop e mobile. Avalie se o operador identifica saúde, ASICs críticos, hashrate perdido, custo, freshness e próxima ação segura em poucos segundos.
```

## Saída esperada

O relatório será escrito em português e marcará conclusões como **FATO**, **HIPÓTESE** ou **RECOMENDAÇÃO**. Resultados de fixtures e mocks serão separados de integrações ou hardware reais.

## Remoção

Para remover a skill do repositório, faça a alteração em uma tarefa autorizada e siga o workflow local de Issue/branch/PR. Remova somente este diretório:

```text
.agents/skills/cypher65-mining-review/
```

Antes de remover, procure referências pelo nome:

```bash
rg -n "cypher65-mining-review" . --glob '!node_modules/**' --glob '!.git/**'
```

Não remova `.agents/skills/`, outras skills ou arquivos compartilhados. Após a remoção, confirme que o diretório não existe e que nenhuma documentação ativa ainda recomenda `$cypher65-mining-review`.
