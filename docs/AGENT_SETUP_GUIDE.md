# 🤖 Conectando seus miners ao CYPHER65 (guia do usuário)

> **Tempo total: ~2 minutos.** Você só precisa de um computador que fique ligado
> na **mesma rede Wi-Fi/LAN dos seus miners** (um PC, notebook, Raspberry Pi ou
> NAS). O resto é copiar e colar.

---

## Como funciona (30 segundos)

O CYPHER65 roda na nuvem — **a nuvem não consegue "enxergar" a sua casa**
(endereços `192.168.x.x` não são acessíveis pela internet). Por isso, um
pequeno **agente** roda na sua máquina, descobre os miners da sua rede e
**conecta para fora**, mandando os dados para o seu painel. Você **não precisa
abrir porta no roteador** — é seguro e funciona atrás de NAT/CGNAT.

```
Sua casa                          Nuvem (CYPHER65)
┌──────────────────────┐          ┌──────────────────────┐
│  Miner 1 (192.168.x) │          │  Seu painel          │
│  Miner 2 (192.168.x) │          │  ┌────────────────┐  │
│         │ poll local │          │  │ fleet atualiza │  │
│  ┌───────────────┐   │  HTTPS   │  └────────────────┘  │
│  │ AGENT (1 cmd) │───┼─────────▶│                      │
│  └───────────────┘   │  saída   │                      │
└──────────────────────┘          └──────────────────────┘
```

---

## Passo a passo (copie e cole)

### Passo 1 · Crie sua conta e entre

Abra o link do CYPHER65 que você recebeu, crie sua conta e faça login.

### Passo 2 · Gere o token do agente

1. No menu lateral, clique em **Fleet**.
2. Clique no botão **🤖 CONNECT AGENT**.
3. Clique em **🔑 GENERATE AGENT TOKEN**.
4. Clique em **⧉ COPY COMMAND** (copia o comando de instalação já com o seu
   token). *O token é secreto — não compartilhe.*

### Passo 3 · Rode o agente na máquina da sua rede

Abra o **Terminal** (macOS/Linux) no computador que fica na mesma rede dos
miners e **cole o comando copiado** — ele é mais ou menos assim
(substitua pela URL e token que aparecem no seu painel):

```bash
curl -sSL "https://SEU-APP.onrender.com/agent/install.sh" \
  | CYPHER65_SERVER_URL=https://SEU-APP.onrender.com CYPHER65_AGENT_TOKEN=SEU_TOKEN bash
```

Pressione **Enter** e aguarde. Você vai ver:

```
[cypher65] downloading agent from https://SEU-APP.onrender.com...
[cypher65] installed as macOS service (com.cypher65.agent)
[cypher65] ✅ AGENT INSTALLED & RUNNING
[cypher65]    The fleet will appear in the dashboard within ~1 min.
```

> ✅ **Pronto.** O agente já está instalado como **serviço** — ele inicia
> sozinho quando a máquina liga, re-escaneia a rede periodicamente (miner novo
> aparece sozinho) e envia telemetria a cada 30s.

### Passo 4 · Veja seus miners

Volte ao painel → **Fleet**. Em ~1 minuto seus miners aparecem com hashrate,
temperatura, status e mais. Se algo não aparecer, confira:

| Problema | Causa provável |
|---|---|
| Nenhum miner aparece | O agente está numa rede diferente da dos miners (mesma Wi-Fi? mesmo cabo?) |
| Algum miner não aparece | O miner está desligado, ou é um modelo que o agente não conhece ainda |
| `AGENT INSTALLED` mas fleet vazio | Espere mais 1-2 minutos e recarregue a página |

### Passo 5 · Conecte sua conta de aluguel (painel RENTALS) — MRR + Braiins

O painel **RENTALS** lê **as SUAS contas** de hashrate alugado (MiningRigRentals
e Braiins Hashpower). **Cada usuário configura a própria chave** — não existe
chave global/compartilhada. Sem chave, o painel mostra `🔑 credentials missing`.

#### MRR (MiningRigRentals) — key + secret

1. Acesse `miningrigrentals.com` → **My Account → API Access** → **gere** (ou
   regenerar) a **API key** + **API secret** do site (o par que aparece AGORA).
2. No painel CYPHER65: **Settings (⚙) → MRR credentials** → cole a **API key**
   e o **API secret** → **Salvar**.
3. Volte em **RENTALS**: os cards MRR mostram as **contagens reais** (sem
   `🔑`/`⚠`).

#### Braiins (Braiins Hashpower) — owner token

1. Acesse `hashpower.braiins.com` → **API Tokens** → copie o **owner token**
   (mostrado uma vez no registro; se perder, regenere).
2. No painel CYPHER65: **Settings (⚙) → Braiins credentials** → cole o token →
   **Salvar**.
3. Clique em **🔑 TESTAR CHAVE BRAIINS** — o painel valida na hora e responde
   **ok** (chave aceita) ou **rejected** (chave rejeitada pela API).
4. Em **RENTALS → aba Braiins**, seus contratos/bids aparecem.

#### Como ler o painel RENTALS

| Estado no card | Significado | Ação |
|---|---|---|
| `🔑` credentials missing | chave **não configurada** | Adicione em Settings (⚙) |
| `⚠` API key rejected | chave configurada mas **REJEITADA pela API** | Regenerar a chave no site do provider (ver abaixo) |
| número (ex.: `12`) | chave **OK** | conta real — nada a fazer |

#### Troubleshooting rápido

- **`Not Authenticated - Invalid Key - Bad Nonce.` (MRR):** a chave em si é
  **inválida/desatualizada** — não é bug do app. **Regenere** uma chave NOVA em
  `miningrigrentals.com → My Account → API Access` e salve o par novo (copiar a
  antiga não resolve).
- **Braiins sem contratos e o teste diz que o token não está configurado:**
  confirme que salvou o **owner token** (não o read-only) em Settings e use o
  botão **🔑 TESTAR CHAVE BRAIINS** — o verdict dele é a fonte da verdade
  (ok / rejected / não configurado).
- **Env var sobrescrevendo:** se o card de Settings mostrar *"⚠ env var
  SOBRESCREVE"*, há uma chave antiga configurada como variável de ambiente no
  deploy — remova-a (Render → Environment) para valer a do Settings.

---

### Desinstalar / reinstalar

- **Reinstalar** (mudou de máquina/token): rode o mesmo comando de novo.
- **Parar o agente**: macOS → `launchctl unload ~/Library/LaunchAgents/com.cypher65.agent.plist` · Linux → `systemctl --user stop cypher65-agent` · outros → `pkill -f run.sh`.

---

## Perguntas frequentes

**Preciso deixar o computador ligado?** Sim — enquanto o agente roda, os dados
chegam. É por isso que recomendamos um Raspberry Pi, NAS ou PC sempre ligado.

**E se eu não tiver nenhum computador sobrando?** Qualquer máquina que já fica
ligada na sua casa serve (inclusive o PC que você usa normalmente).

**Isso é seguro?** O agente só **envia** dados para o seu painel (conexão
iniciada por ele, criptografada via HTTPS, autenticada com o seu token). Nada
é aberto para a internet, e ninguém consegue acessar sua rede por causa dele.
O token só dá acesso ao **seu** fleet, não ao de outros usuários.

**Funciona com mineradores diferentes?** O agente detecta miners com API
AxeOS/ESP-Miner (Bitaxe, NerdAxe…) e protocolo cgminer (Antminer, Avalon,
Whatsminer e compatíveis) na porta padrão.

**Os botões Restart/Identify do painel funcionam mesmo com o CYPHER65 na
nuvem?** Sim. Você clica no card do miner, o servidor **enfileira o comando**
e o **agente executa de verdade na sua rede** (ele é quem alcança o miner).
O resultado volta para o painel. Detalhe honesto: `Identify` (piscar o LED)
só existe em miners AxeOS/Bitaxe — num Antminer o card mostra apenas
`Restart`, porque a API cgminer não tem o comando de identificar.

**Removi um miner por engano. Ele volta sozinho?** Não — o painel respeita a
sua remoção: o miner removido não reaparece, e a **vaga é liberada na hora**
no seu plano. Se você quer re-adicioná-lo, use o botão **+ ADD** no Fleet e
informe o IP (o agente volta a descobri-lo normalmente).

**Meu plano não aceitou um miner novo (limite de workers).** Se o agente
descobrir mais miners do que o seu plano permite, os excedentes **não são
registrados** — você vê um aviso no painel do operador, e o agente loga o
bloqueio (`plan worker limit`). Nada quebra: os miners já registrados
continuam enviando telemetria normalmente. Para liberar vaga, remova um
device (a vaga é liberada na hora) ou aumente o limite do plano.

**Uso Docker?** Também funciona, se você preferir: `docker run -d --name
cypher65-agent --network host -e CYPHER65_SERVER_URL=<URL> -e
CYPHER65_AGENT_TOKEN=<TOKEN> ghcr.io/0xjc65eth/cypher65-agent`. Mas o
comando de 1 linha acima
é o caminho mais simples (não precisa de Docker).

**O que é o painel RENTALS e por que ele pede a MINHA chave do MRR/Braiins?**
O painel **RENTALS** consolida seus aluguéis de hashrate nas **suas próprias**
contas (MiningRigRentals + Braiins Hashpower). Por segurança, **cada usuário
conecta a própria conta** — o app nunca usa chave de outro usuário nem chave
global. Veja o **Passo 5** acima: em ~2 minutos você conecta e aprende a ler os
estados do painel (🔑 missing · ⚠ rejected · número = conta OK).
