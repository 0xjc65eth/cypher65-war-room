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
| UI (token + comandos) | Fleet → CONNECT AGENT (`dashboard.html` + `app.js`) |

## Limitações conhecidas

- O usuário precisa de uma **máquina ligada** na rede dos miners (Raspberry
  Pi/NAS/PC). Enquanto ela estiver desligada, o fleet dele fica offline.
- Descoberta cobre AxeOS :80 e cgminer :4028 (padrão de mercado); miners com
  API não padrão podem precisar de IP explícito (`CYPHER65_DEVICES`).
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
