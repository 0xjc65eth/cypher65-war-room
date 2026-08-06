# Nota técnica: por que o agente local? (arquitetura do fleet SaaS)

> Leitura recomendada para quem opera o deploy. O guia do usuário está em
> [`AGENT_SETUP_GUIDE.md`](./AGENT_SETUP_GUIDE.md).

## O problema

O CYPHER65 roda no **Render (nuvem)** e cada usuário entra pela URL do deploy.
O painel tem um scanner de rede e polling de telemetria que funcionam bem
**quando o servidor está na mesma rede dos miners** (self-host). Mas na
arquitetura SaaS:

```
Render (nuvem)  ──► 192.168.1.50  (miner do usuário)  ✗ IMPOSSÍVEL
```

A nuvem **não roteia** para endereços privados (`192.168.x.x`, `10.x.x.x`).
Um `scan 192.168.1.0/24` a partir do Render só varre a rede do próprio Render
— sempre retorna `0 miners found`, mesmo com o miner ligado e saudável. Isso
**não é bug do scanner**: é física de rede (RFC 1918 + NAT/CGNAT dos
provedores domésticos).

Antes desta feature, o painel explicava o problema no wizard ("IP privado
(LAN)") mas **não tinha como resolver** — o usuário ficava sem fleet.

## A solução: o padrão de mercado (HiveOS, Awesome Miner)

A única arquitetura que funciona para SaaS multi-tenant é o **agente na casa
do usuário conectando para fora**:

```
Casa do usuário                          Render (nuvem)
┌─────────────────────────────┐         ┌──────────────────────────┐
│  miner ← poll local (agente)│         │  POST /api/agent/*       │
│  ┌───────────┐              │  HTTPS  │  (JWT por tenant)        │
│  │  AGENT    │─────────────▶│────────▶│  registry + fila comandos│
│  └───────────┘              │ saída   └──────────────────────────┘
└─────────────────────────────┘
```

- **Quem inicia a conexão é o agente** (de dentro da LAN para fora) → nada de
  abrir porta no roteador, funciona sob NAT/CGNAT.
- **O agente é quem alcança os miners** (está na mesma rede) → usa o mesmo
  motor de descoberta/protocolo do scanner (AxeOS :80, cgminer :4028 com
  parsing tolerante a Avalon/Whatsminer).
- **O servidor só recebe e exibe** → telemetria em batch, fila de comandos
  (restart/identify) que o agente executa localmente.
- **Isolamento por tenant** → o token do agente é um JWT com claim
  `agent:true` e `sub = tenant_id`; cada rota `/api/agent/*` valida e filtra
  por esse tenant. O agente do usuário A nunca enxerga o fleet do usuário B.

## Por que o instalador de 1 linha (e não só Docker)

O Docker exige que o usuário tenha Docker instalado — barreira real para
muitos. O agente é **100% stdlib Python** (urllib, zero dependências), então o
`curl | bash` funciona em **qualquer máquina com python3** (macOS, Linux,
Raspberry Pi OS — todos já trazem). O instalador:

1. baixa `agent.py` do próprio servidor (`/agent/agent.py`);
2. grava o token em `~/.cypher65-agent/agent.env` (permissão 600);
3. instala como **serviço** (launchd no macOS / systemd user com `enable-linger`
   no Linux / loop `nohup` + crontab `@reboot` como fallback) — sobrevive a
   reboot, sem o usuário precisar fazer mais nada;
4. re-escaneia a LAN periodicamente (miners novos aparecem sozinhos).

## Componentes

| Peça | Onde |
|---|---|
| Agente (stdlib) | `agent/agent.py` |
| Instalador 1-linha | `agent/install.sh` (servido em `/agent/install.sh`) |
| Agente baixável | `/agent/agent.py` (rota pública `agent_assets_bp`) |
| API do agente | `/api/agent/*` (`axe_fleet/routes.py`) |
| Fila de comandos + coluna `agent_managed` | `axe_fleet/registry.py` |
| Skip de poll no servidor | `app.py::_poll_axe_fleet` (nunca polla device agent-managed) |
| Tombstone de device removido | `axe_fleet/registry.py` (`removed_at` + `gc_tombstones`) |
| UI (token + comandos) | Fleet → CONNECT AGENT (`dashboard.html` + `app.js`) |

## Comandos: do clique no painel ao miner (fluxo corrigido)

O usuário clica em **Restart/Identify** no card do device. Para um device
agent-managed o caminho é (o servidor na nuvem não alcança o miner):

```
Dashboard ──POST /devices/<id>/restart──► servidor
                                            │ enfileira (axe_agent_commands)
Agente ──POST /api/agent/commands/pull────► servidor
     ◄──── {id, ip_address, command} ────── servidor   ← IP resolvido AQUI
Agente ── executa no miner da LAN ──►  AxeOS HTTP :80 / cgminer TCP :4028
Agente ──POST /commands/<id>/ack─────────► servidor (done/failed)
```

Dois detalhes que já foram fonte de bug e agora são garantidos por teste:

- **O payload do pull carrega o `ip_address` do device**, não o UUID do
  registry. Antes o agente recebia o UUID e tentava abrir um socket para uma
  string não resolvível — o comando era enfileirado, puxado e ackado como
  `failed` sem nunca tocar o miner. O E2E (`scripts/e2e_agent_local.py`, etapa
  7) prova a execução real: os miners mock contam os restarts recebidos.
- **O protocolo segue o tipo do device** (o agente conhece o tipo pela própria
  descoberta): AxeOS/Bitaxe usa `POST /api/system/{restart|identify}` em :80;
  cgminer usa o comando `restart` do JSON-over-TCP em :4028 (a API cgminer não
  tem `identify` — por isso o card de um Antminer não oferece esse botão).
- **Nota de contrato — `restart`/`identify` exigem sessão de tenant (ou
  localhost)** (`@_require_local_or_session` no servidor): o guard aceita
  localhost (127.0.0.1/::1/mesmo host), sessão Flask autenticada, Bearer JWT
  de access válido, X-API-Key configurada — ou, em open-mode self-host sem
  auth, o header leniente legado. Sem nenhum desses, responde **401
  `"authentication required — device control restricted to localhost or
  authenticated session"`**. É o motivo pelo qual o botão do dashboard usa
  `authFetch` (Bearer do tenant): antes de corrigir, o card postava para a
  rota core `/api/devices/<id>/command`, que respondia **404 "device not
  found"** (o device não existe no core registry) — o erro honesto agora é
  401, e o fluxo legítimo (browser logado / agente na LAN) passa sem mudança.

## Device removido: tombstone, sem zumbis

Quando o operador remove um device, a linha **não é apagada** — recebe um
carimbo `removed_at` (soft delete / tombstone):

- Todas as leituras (`list_devices`, `get_device`, `get_device_by_ip`) filtram
  tombstoned rows — o card some do dashboard imediatamente.
- O caminho do **agente não consegue ressuscitá-lo**: `register` retorna o IP
  no bloco `blocked` e `telemetry` responde `410 removed`. O agente então
  **remove o IP do próprio poll set** — nunca mais empurra telemetria para um
  device que o operador removeu (zero 403-spam, provado pelo
  `scripts/e2e_agent_plan_cap.py`).
- `count_tenant_workers` ignora tombstones — o device removido **libera a
  vaga** no plano imediatamente.
- O **`+ ADD` manual revive**: o operador que removeu por engano (ou quer
  re-adicionar) usa o wizard; o caminho manual limpa o tombstone e cria uma
  linha ativa nova.
- Tombstones antigos (> 30 dias) são purgados fisicamente no boot por
  `gc_tombstones()` (linha + telemetria), então o soft delete nunca cresce o
  DB para sempre.

## Limitações conhecidas

- O usuário precisa de uma **máquina ligada** na rede dos miners (Raspberry
  Pi/NAS/PC). Enquanto ela estiver desligada, o fleet dele fica offline.
- Descoberta cobre AxeOS :80 e cgminer :4028 (padrão de mercado); miners com
  API não padrão podem precisar de IP explícito (`CYPHER65_DEVICES`).
- `identify` só é oferecido para AxeOS/Bitaxe — a API cgminer não tem esse
  comando (o card do Antminer mostra só Restart).
- A imagem Docker (`ghcr.io/0xjc65eth/cypher65-agent`, publicada por CI a
  cada push em `master`) é oferecida como alternativa; o caminho principal (1
  linha) não depende dela.

## Operação: tornar o pacote GHCR público (uma vez)

O workflow `agent-image.yml` publica no GHCR com `GITHUB_TOKEN`, e pacotes
criados assim nascem **privados** — o `docker run ghcr.io/0xjc65eth/cypher65-agent`
dos usuários falharia com `unauthorized`. **Uma vez**, após o primeiro push em
`master`, trocar a visibilidade para pública:

1. Abrir
   `https://github.com/users/0xjc65eth/packages/container/package/cypher65-agent`
2. **Package settings** → **Danger Zone** → **Change visibility** → **Public**

(Alternativa via CLI com PAT `write:packages`:
`gh api --method POST /user/packages/container/cypher65-agent/visibility -f visibility=public`.)
