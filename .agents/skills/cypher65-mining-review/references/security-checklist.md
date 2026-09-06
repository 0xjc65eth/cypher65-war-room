# Checklist de segurança

Use este checklist em revisões que envolvam integrações, credenciais, comandos, webhooks ou self-hosting. Marque cada item como comprovado, falhou, não aplicável ou sem evidência.

## Credenciais e configuração

- [ ] Nenhum valor de secret foi lido, impresso, copiado ou incluído no relatório.
- [ ] APIs de configuração retornam apenas estado configurado/redigido, não plaintext.
- [ ] Campos de secret são write-only e vazio não apaga valor existente sem intenção explícita.
- [ ] Precedência entre environment, tenant e banco é explícita.
- [ ] Rotação ou perda da chave de criptografia falha de forma clara e segura.
- [ ] Logs, exceptions, audit log e analytics redigem tokens e assinaturas.
- [ ] Ausência ou rejeição de credencial não é exibida como integração vazia bem-sucedida.

## Integrações

- [ ] Timeout total e por tentativa são limitados.
- [ ] Retry usa backoff e respeita rate limit; operações mutáveis não são repetidas cegamente.
- [ ] Respostas inválidas, parciais, atrasadas e incompatíveis têm estado explícito.
- [ ] Cache informa origem, idade e stale.
- [ ] Webhooks recebidos são autenticados, deduplicados e idempotentes.
- [ ] Webhooks enviados têm timeout, assinatura quando prevista e payload mínimo.
- [ ] Falha de um provedor não apaga dados válidos de outro nem produz recomendação falsa.

## Comandos e automações

- [ ] Read-only é o padrão global e por device.
- [ ] Autorização é verificada no backend, não apenas na UI.
- [ ] Alvo, tenant, firmware e capacidade são validados imediatamente antes do envio.
- [ ] Dry-run usa as mesmas validações do caminho real e não produz efeito colateral.
- [ ] Confirmação humana está vinculada ao alvo, ação e parâmetros exibidos.
- [ ] Existe timeout/cancelamento e estado inequívoco para ausência de ACK.
- [ ] Repetição e concorrência são protegidas por idempotência/locking apropriado.
- [ ] Device offline ou telemetria stale bloqueia comando quando a segurança exigir.
- [ ] Estado pós-comando é reconciliado com firmware e, quando aplicável, pool.
- [ ] Ações destrutivas têm rollback/contenção, aprovação e ambiente de teste.

## Audit log

- [ ] Registra ator, tenant, alvo canônico, intenção, timestamp e resultado.
- [ ] Distingue dry-run, confirmação, envio, ACK, timeout, reconciliação e rollback.
- [ ] Parâmetros sensíveis são redigidos.
- [ ] Tentativas rejeitadas e duplicadas também são auditadas.
- [ ] Persistência após reinício e ordenação temporal foram testadas.
- [ ] O usuário consegue encontrar o evento e entender o resultado operacional.

## Dados e UX

- [ ] Loading, empty, stale, offline e error não são colapsados no mesmo estado.
- [ ] Zero real não é confundido com dado ausente.
- [ ] Métricas exibem unidade, timestamp/idade, janela e origem.
- [ ] Alertas não dependem apenas de cor e oferecem próxima ação segura.
- [ ] Probabilidade não é mostrada como progresso, prazo ou garantia.
- [ ] Rentabilidade modelada não é apresentada como lucro observado ou promessa.
- [ ] Desktop e mobile preservam informações críticas e confirmação segura.
