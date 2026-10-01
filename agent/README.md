# CYPHER65 LOCAL AGENT (SaaS)

O dashboard na nuvem (Render) **não consegue** varrer a sua LAN — `192.168.x.x`
não é roteável a partir da nuvem. Por isso o modelo é o inverso: um **agente
leve roda na sua rede** (Raspberry Pi, NAS, mini-PC, ou qualquer máquina que
fique ligada) e **conecta para fora**, empurrando telemetria para o dashboard.
Sem abrir porta no roteador, funciona atrás de NAT/CGNAT.

```
┌─ SUA REDE ────────────────┐        ┌─ RENDER (dashboard) ────┐
│  Miner 1 (192.168.1.50)   │        │  /api/agent/telemetry ←─┐ │
│  Miner 2 (192.168.1.60)   │        │  /api/agent/commands  ──┘ │
│        │ poll direto      │ HTTPS │  (multi-tenant)           │
│  ┌──────────────┐         │────────▶│                          │
│  │ AGENT LOCAL  │  conexão│  saída │                          │
│  └──────────────┘  iniciada│        └──────────────────────────┘
└──────────────────────────┘
```

## 1 · Gerar o token do agente

No dashboard (já logado) → **Fleet → + ADD → Connect Agent** → *Generate token*.
O token é um JWT scoped ao SEU tenant — não compartilhe.

## 2 · Instalar na máquina da rede local

Requer `python3` e `curl` instalados. O agente usa apenas a biblioteca padrão
do Python: não precisa de `pip install`. Copie o comando do painel **Connect
Agent** e execute em uma máquina que consiga alcançar os miners. O instalador
configura launchd (macOS), systemd (Linux) ou um loop de fallback.

Se souber os IPs dos miners, informe-os no comando de instalação:

```bash
curl -fsSL https://SEU-APP.onrender.com/agent/install.sh \
  | CYPHER65_SERVER_URL=https://SEU-APP.onrender.com \
    CYPHER65_AGENT_TOKEN=SEU_TOKEN \
    CYPHER65_DEVICES='192.168.1.50,192.168.1.60' bash
```

Para descobrir miners em uma faixa conhecida, substitua `CYPHER65_DEVICES`
por `CYPHER65_SCAN_CIDR='192.168.1.0/24'` (ou `192.168.1.50-80`). Use os IPs
ou a faixa reais da sua rede, consultando o roteador ou a interface do miner.
O instalador preserva essa escolha quando o serviço reinicia. Para mudar a
configuração, execute novamente o comando com os novos valores; `agent.env`
é uma cópia protegida da configuração, não um arquivo recarregado pelo serviço.

Sem essas variáveis, o agente tenta CIDRs IPv4 obtidos das interfaces locais
quando suportado; em sistemas sem esse recurso, deriva faixas `/24` dos IPs do
host. Isso pode não identificar a rede dos miners, outras VLANs ou o roteamento
de containers. Se a descoberta não encontrar os devices, confira a conectividade
local e informe os IPs ou a faixa correta.

## 3 · Rodar com Docker

```bash
docker run -d --restart unless-stopped --name cypher65-agent --network host \
  -e CYPHER65_SERVER_URL=https://SEU-APP.onrender.com \
  -e CYPHER65_AGENT_TOKEN=SEU_TOKEN \
  -e CYPHER65_POLL_INTERVAL=30 \
  -e CYPHER65_DEVICES=192.168.1.50,192.168.1.60 \
  ghcr.io/0xjc65eth/cypher65-agent
```

`--network host` compartilha a rede do host no Docker Engine Linux. No Docker
Desktop (macOS/Windows), o container roda numa VM e host networking não garante
acesso transparente à LAN nem broadcast/descoberta das sub-redes físicas; o
comportamento depende da versão e da configuração. Prefira instalar o agente
nativamente no host macOS/Windows. Se usar Docker Desktop, confirme primeiro
que o container alcança o IP/porta do miner; use `CYPHER65_DEVICES` ou
`CYPHER65_SCAN_CIDR` para seleção explícita de hosts — isso não contorna uma
rota/firewall inacessível.

No Linux, host networking também não escolhe a máscara/rede certa por si só.
A descoberta automática usa CIDRs obtidos das interfaces quando suportado e
pode recorrer a `/24` derivado do IPv4 local; não detecta outras VLANs nem
prova qual rede contém os miners. Prefira a faixa real, por exemplo
`CYPHER65_SCAN_CIDR='192.168.1.0/24'`, e note que a varredura é limitada a
1.024 hosts por faixa.

O instalador reporta que configurou/iniciou o serviço, não que a nuvem aceitou
o token ou que encontrou miners. Verifique `~/.cypher65-agent/agent.log` (fallback),
`journalctl --user -u cypher65-agent` (Linux) ou
`~/Library/Logs`/o caminho de log informado pelo serviço (macOS), procure por
`FLEET_REGISTER`/`FLEET_SCAN` e confira **Fleet** no dashboard. Erros de rede,
token inválido, faixa incorreta e limite do plano precisam de diagnóstico à parte.

O comando Docker precisa receber também `-e CYPHER65_SCAN_CIDR=...` ou
`-e CYPHER65_DEVICES=...` se você não estiver usando a descoberta padrão; essas
variáveis não vêm do instalador nativo.

## 4 · Rodar diretamente com Python

```bash
CYPHER65_SERVER_URL=https://SEU-APP.onrender.com \
CYPHER65_AGENT_TOKEN=SEU_TOKEN \
CYPHER65_DEVICES=192.168.1.50,192.168.1.60 \
python3 agent/agent.py
```

## Variáveis de ambiente

| Var | Default | Descrição |
|---|---|---|
| `CYPHER65_SERVER_URL` | `http://localhost:8765` | URL base do dashboard (Render) |
| `CYPHER65_AGENT_TOKEN` | — (obrigatório) | Token JWT gerado no dashboard |
| `CYPHER65_POLL_INTERVAL` | `30` | Intervalo do push de telemetria (s) |
| `CYPHER65_SCAN_CIDR` | CIDRs das interfaces (ou fallback /24) | CIDR/faixa local conhecida; no máximo 1.024 hosts são sondados por faixa |
| `CYPHER65_DEVICES` | — | IPs separados por vírgula; limita descoberta e coleta a eles, com prioridade sobre `SCAN_CIDR` |

## O que o agente faz

1. **Descobre** miners na LAN (AxeOS :80, cgminer :4028 — mesmo motor tolerante
   do scanner do servidor).
2. **Registra** os devices no seu tenant (`/api/agent/register`).
3. **Poll de telemetria** (hashrate, temp, shares, power…) a cada 30s e push por
   device (`/api/agent/telemetry`).
4. **Puxa comandos** enfileirados (restart/identify) e executa localmente
   (`/api/agent/commands/pull` + `ack`).

Devices agent-managed **não** são pollados pelo servidor (não haveria como
alcançá-los) — o skip é automático no `_do_poll`.

No modo cloud, adicionar um IP privado pede ao agente uma única sondagem
read-only por IP literal na rede privada. Ela não altera o miner nem herda
permissões de restart/configuração; loopback, link-local, IPv6 e IPs públicos
são recusados antes de qualquer conexão. O resultado só é registrado quando o
agente local reconhece um firmware suportado.

## Segurança

- Autenticação por JWT de agente (claims `agent_tenant_id`), validado em todas
  as rotas `/api/agent/*`.
- Telemetria/registro são estritamente **tenant-scoped**.
- O agente só fala com o seu tenant; um token vazado não expõe outros tenants.
- Comandos dependem do protocolo: restart/identify e, em AxeOS, pause/resume.
