# Feature flags de alto risco

Estas flags controlam capacidades que podem alterar hardware ou movimentar
dinheiro. Todas são independentes e permanecem desabilitadas por padrão. A
interface não é uma fronteira de segurança: os gates devem ser aplicados pelo
backend em todos os caminhos de execução, inclusive APIs, jobs e automações.

```env
ENABLE_PHYSICAL_COMMANDS=false
ENABLE_AUTONOMOUS_COMMANDS=false
ENABLE_REAL_HASHRATE_PURCHASES=false
ENABLE_REAL_PAYMENTS=false
```

Não inclua chaves, tokens, endereços de carteira ou outros segredos neste
arquivo. Os únicos valores de ativação aceitos, sem diferenciar maiúsculas e
minúsculas, são `1`, `true`, `yes` e `on`; qualquer outro valor é desabilitado.
Os gates leem o ambiente a cada operação. Se a plataforma só propaga mudanças
de ambiente durante um deploy, reinicie o serviço; em todos os casos, valide o
estado efetivo antes de aceitar tráfego.

## Matriz de implantação

| Flag | Capacidade protegida | Beta de 30 dias | Produção pública | Gate mínimo para habilitar |
|---|---|---:|---:|---|
| `ENABLE_PHYSICAL_COMMANDS` | Comandos que alteram o estado de ASICs | `false` | `false` até validação | Matriz física aprovada, dry-run, confirmação humana, timeout, idempotência, ACK, reconciliação pós-comando e audit log persistente |
| `ENABLE_AUTONOMOUS_COMMANDS` | Execução física sem confirmação humana por ação | `false` | `false` até validação adicional | Gate de comandos físicos aprovado, kill switch testado, limites operacionais, rollback, testes de concorrência e evidência em hardware suportado |
| `ENABLE_REAL_HASHRATE_PURCHASES` | Ordens ou bids que podem gastar saldo em provedores de hashrate | `false` | `false` até validação | Sandbox/provedor validado, dry-run padrão, confirmação server-side vinculada aos parâmetros, ledger idempotente, reconciliação e audit log fail-closed |
| `ENABLE_REAL_PAYMENTS` | Checkout e ativação de licença por pagamento | `false` | `false` até validação | BTCPay configurado, webhook autenticado, invoice conhecida, deduplicação, reconciliação ponta a ponta, persistência após reinício e procedimento de revogação |

`Produção pública` não é sinônimo de `true`. A recomendação inicial é publicar
o núcleo read-only com as quatro flags em `false` e habilitar cada capacidade
separadamente somente quando sua evidência de aprovação estiver registrada.

## Dependências entre flags

- `ENABLE_AUTONOMOUS_COMMANDS=true` exige também
  `ENABLE_PHYSICAL_COMMANDS=true`. Sem essa combinação, a autonomia deve
  permanecer bloqueada.
- `ENABLE_REAL_HASHRATE_PURCHASES` não depende de pagamentos de licença e não
  deve ser habilitada junto com `ENABLE_REAL_PAYMENTS` por conveniência.
- Licença, papel de administrador, configuração salva no frontend ou modo beta
  não substituem nenhuma destas flags.
- Desabilitar uma flag deve impedir novas execuções sem apagar histórico,
  configuração ou audit logs existentes.

## Verificação operacional

Antes de habilitar uma flag:

1. Registre a aprovação do gate e as evidências sem credenciais ou dados
   pessoais.
2. Ative somente uma capacidade por mudança de configuração.
3. Reinicie o serviço e confirme que endpoints bloqueados continuam falhando de
   forma segura quando as demais flags estão desligadas.
4. Execute um dry-run e verifique timestamp, alvo, origem e audit log.
5. Tenha rollback documentado: retorne a flag para `false`, reinicie o serviço
   e confirme que novas ações foram bloqueadas.

Em incidentes ou estado desconhecido, defina imediatamente as quatro flags como
`false`. A desativação não substitui a reconciliação de ações já enviadas a
hardware ou provedores externos.

## ACK, reconciliação e idempotência

- Um `ack.state=acknowledged` confirma somente que o adaptador ou provedor
  aceitou a requisição. Ele não comprova o estado físico ou financeiro final.
- Comandos físicos retornam `operation_id` e começam com
  `reconciliation.state=pending`. Consulte
  `GET /api/devices/<device_id>/commands/<operation_id>`; somente telemetria
  coletada depois do ACK pode produzir `confirmed`.
- Dispositivo offline, telemetria antiga ou firmware sem estado comparável
  resultam em `unknown` ou `pending`, nunca em sucesso presumido.
- Sem telemetria nova dentro de `COMMAND_RECONCILIATION_TIMEOUT_SECONDS`
  (padrão: 120 segundos), a reconciliação muda para `unknown`; o comando não é
  reenviado.
- `POST /api/rentals/braiins/bid` é dry-run por padrão. O dry-run devolve um
  token de confirmação curto e vinculado ao payload exato.
- A execução real exige `dry_run=false`, o token retornado e o header
  `Idempotency-Key` (8–64 caracteres), idêntico a `cl_order_id` para permitir
  correlação com o provedor. Reutilizar a chave devolve a operação persistida
  e nunca cria uma segunda ordem.
- Timeout ou falha de transporte após iniciar o POST Braiins é registrado como
  `unknown` com `retry_allowed=false`. Reconcilie no provedor antes de criar
  uma nova idempotency key; não repita automaticamente.
- O ledger persiste somente hashes, estados, timestamps e referências
  sanitizadas. API keys, URL Stratum e identidade do worker não são guardadas.
