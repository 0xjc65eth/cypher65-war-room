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

Sem essas variáveis, o agente tenta faixas `/24` derivadas dos endereços IPv4
do host. Isso não identifica automaticamente a máscara real, outras VLANs
ou a rede dos miners em um container. Se a descoberta não encontrar os
devices, confira a conectividade local e informe os IPs ou a faixa correta.

## 3 · Rodar com Docker

```bash
docker run -d --name cypher65-agent --network host \
  -e CYPHER65_SERVER_URL=https://SEU-APP.onrender.com \
  -e CYPHER65_AGENT_TOKEN=SEU_TOKEN \
  -e CYPHER65_POLL_INTERVAL=30 \
  -e CYPHER65_DEVICES=192.168.1.50,192.168.1.60 \
  ghcr.io/0xjc65eth/cypher65-agent
```

O comando usa a rede do host e exige suporte a esse modo na instalação do
Docker. O container precisa alcançar os IPs dos miners; estar na mesma máquina
não garante que a descoberta automática use a faixa correta. Informe IPs
explícitos ou `CYPHER65_SCAN_CIDR`. No macOS, a instalação nativa acima evita
depender da configuração de rede do Docker.

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
| `CYPHER65_SCAN_CIDR` | tentativa de /24 por IPv4 do host | CIDR/faixa local conhecida para descobrir miners |
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

## Segurança

- Autenticação por JWT de agente (claims `agent_tenant_id`), validado em todas
  as rotas `/api/agent/*`.
- Telemetria/registro são estritamente **tenant-scoped**.
- O agente só fala com o seu tenant; um token vazado não expõe outros tenants.
- Comandos dependem do protocolo: restart/identify e, em AxeOS, pause/resume.
