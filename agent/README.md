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
│        │ poll direto      │   WSS  │  (multi-tenant)           │
│  ┌──────────────┐         │────────▶│                          │
│  │ AGENT LOCAL  │  conexão│  saída │                          │
│  └──────────────┘  iniciada│        └──────────────────────────┘
└──────────────────────────┘
```

## 1 · Gerar o token do agente

No dashboard (já logado) → **Fleet → + ADD → Connect Agent** → *Generate token*.
O token é um JWT scoped ao SEU tenant — não compartilhe.

## 2 · Rodar com Docker (recomendado)

```bash
docker run -d --name cypher65-agent --network host \
  -e CYPHER65_SERVER_URL=https://SEU-APP.onrender.com \
  -e CYPHER65_AGENT_TOKEN=SEU_TOKEN \
  -e CYPHER65_POLL_INTERVAL=30 \
  ghcr.io/0xjc65eth/cypher65-agent
```

> `--network host` é essencial: o agente precisa alcançar os IPs da LAN
> (`192.168.x.x`). Em Mac/Windows, rode na máquina que está na mesma rede dos
> miners.

## 3 · Rodar sem Docker (Python)

```bash
pip install requests
CYPHER65_SERVER_URL=https://SEU-APP.onrender.com \
CYPHER65_AGENT_TOKEN=SEU_TOKEN \
python3 agent/agent.py
```

## Variáveis de ambiente

| Var | Default | Descrição |
|---|---|---|
| `CYPHER65_SERVER_URL` | `http://localhost:8765` | URL base do dashboard (Render) |
| `CYPHER65_AGENT_TOKEN` | — (obrigatório) | Token JWT gerado no dashboard |
| `CYPHER65_POLL_INTERVAL` | `30` | Intervalo do push de telemetria (s) |
| `CYPHER65_SCAN_CIDR` | auto (/24 da interface) | CIDR/range para descobrir miners |
| `CYPHER65_DEVICES` | — | IPs fixos (pula scan, polla só esses) |

## O que o agente faz

1. **Descobre** miners na LAN (AxeOS :80, cgminer :4028 — mesmo motor tolerante
   do scanner do servidor).
2. **Registra** os devices no seu tenant (`/api/agent/register`).
3. **Poll de telemetria** (hashrate, temp, shares, power…) a cada 30s e push em
   batch (`/api/agent/telemetry`).
4. **Puxa comandos** enfileirados (restart/identify) e executa localmente
   (`/api/agent/commands/pull` + `ack`).

Devices agent-managed **não** são pollados pelo servidor (não haveria como
alcançá-los) — o skip é automático no `_do_poll`.

## Segurança

- Autenticação por JWT de agente (claims `agent_tenant_id`), validado em todas
  as rotas `/api/agent/*`.
- Telemetria/registro são estritamente **tenant-scoped**.
- O agente só fala com o seu tenant; um token vazado não expõe outros tenants.
- Comandos são apenas restart/identify (sem comandos destrutivos remotos).
