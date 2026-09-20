# Fleet no Render — continuação da auditoria

Issues #636, #637 e #638. Base inspecionada: `master` em `8f69742`.

## Veredito

**Confirmado pelo código:** o dashboard cloud depende de um agente dentro da
rede do usuário. `axe_fleet/routes.py` bloqueia scan LAN e cadastro direto de
IP privado no cloud. O agente envia registro e telemetria por HTTPS; não existe
um túnel que permita ao servidor Render consultar qualquer IP da LAN.

## Correções desta entrega (#636)

| Falha confirmada | Correção | Evidência automatizada |
|---|---|---|
| Comando Docker continha `\\n` literal em três linhas | Gerador usa uma continuação shell real e protege os argumentos | JS core executa gerador real com comandos inertes; Playwright verifica painel e cópia |
| Instalador perdia `CYPHER65_SCAN_CIDR` e `CYPHER65_DEVICES` | Configuração preservada em launchd, systemd e fallback | Preflight/serializadores reais, parsing plist/unit e execução de fallback com agente inerte |
| HTTP 410 removia entrada de `known` durante sua iteração | Iteração sobre snapshot permite continuar a coleta | Dois ciclos, dois miners, rescan e recusa de registro do miner removido |
| Runner de instalações antigas podia continuar legível por outros usuários | Arquivos são restritos antes de gravar credenciais; runner executável só pelo proprietário | Teste de geração sobre arquivos antigos com modo 0755 |

O arquivo `agent.env` é cópia protegida da configuração, não configuração
recarregada pelo agente. Alterações exigem executar novamente o instalador.
Veja as instruções de IP/faixa explícitos em [agent/README.md](../../agent/README.md).

## Pendências confirmadas

- **#637 — fluxo cloud e recuperação:** o wizard ainda oferece caminhos
  bloqueados no servidor e perde detalhes de erro. Um miner privado removido
  mantém tombstone, mas o add manual que o restauraria é bloqueado no cloud.
  A correção deverá preservar isolamento entre tenants e proteção de IP privado.
- **#638 — descoberta após offline:** um IP explícito indisponível no startup
  recebe identidade Bitaxe provisória que não é corrigida no rescan. Um miner
  cgminer que surge depois pode continuar sendo consultado como AxeOS.
- **#638 — expansão de rede:** `_expand_cidr` materializa os hosts antes do
  corte; uma faixa muito grande pode exaurir memória. A descoberta automática
  deriva `/24` de rota/hostname, sem comprovar a máscara ou interface do miner.
- **#629/#638 — diagnóstico:** sem miners não há heartbeat independente com
  resultado do scan que diferencie agente desconectado de descoberta vazia.

## Limites da evidência

**Inferido:** interface VPN/container, faixa incorreta ou identidade provisória
podem explicar o relato do usuário, dependendo de como o agente foi instalado.
Não há log redigido do agente do usuário que identifique qual hipótese ocorreu.

**Precisa ser validado:** instalação real por supervisor, conectividade da LAN,
autenticação no Render e telemetria com hardware físico. Testes locais usam
contratos, simuladores e configurações temporárias. Nenhum serviço foi instalado
na máquina do usuário e nenhum comando foi enviado a um ASIC nesta entrega.

Os testes de Stratum #635 são uma entrega independente de integração entre
componentes `pool_intelligence`; não comprovam a operação do Fleet no Render.

## Validação local (2026-09-20)

- **216 passed**: `test_agent_install_config`, `test_agent_main_loop`,
  `test_agent_api`, `test_agent_protocol`, `test_fleet_audit_regressions`,
  `test_axe_fleet_scanner`, `test_fleet_pause_status`, `test_axeos_connector_http`.
- **1.533 verificações JS core** passaram; os comandos gerados são executados
  por shell com funções Docker/curl/bash inertes que capturam argumentos.
- **16 Playwright** passaram em desktop/mobile (`agent-revoke.spec.js`);
  emissão de token do teste de cópia é uma resposta simulada explicitamente.
- Black, flake8, sintaxe shell/JS, drift do bundle, guards DOM/mobile e
  consistência do lockfile passaram no escopo afetado.
- Prova negativa em memória: o teste de dois miners rejeita o loop anterior
  com `RuntimeError: dictionary changed size during iteration`.

O CI do master base tem falha no job mobile (Issue #626), independente desta
alteração. A validação local acima não substitui os checks do SHA do PR nem
a aprovação exigida pelo workflow.
