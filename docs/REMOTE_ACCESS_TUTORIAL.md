# 🔗 Tutorial de Acesso Remoto — CYPHER65 Axe Fleet

**Controle seus miners de qualquer lugar, com segurança e sem abrir portas públicas.**

---

## 📋 Sumário

1. [O que você vai precisar](#1-o-que-você-vai-precisar)
2. [Passo 1 — Instalar Tailscale no host de casa](#passo-1--instalar-tailscale-no-host-de-casa)
3. [Passo 2 — Conectar celular e notebook ao mesmo tailnet](#passo-2--conectar-celular-e-notebook-ao-mesmo-tailnet)
4. [Passo 3 — Verificar o acesso remoto no Axe Fleet](#passo-3--verificar-o-acesso-remoto-no-axe-fleet)
5. [Passo 4 — Configurar tomadas Tuya](#passo-4--configurar-tomadas-tuya)
6. [Passo 5 — Associar tomada a um miner](#passo-5--associar-tomada-a-um-miner)
7. [Passo 6 — Ligar/desligar miner remotamente](#passo-6--ligardesligar-miner-remotamente)
8. [Passo 7 — Power-cycle (desligar, esperar, ligar)](#passo-7--power-cycle-desligar-esperar-ligar)
9. [Passo 8 — Diagnóstico de conectividade](#passo-8--diagnóstico-de-conectividade)
10. [Segurança importante](#-segurança-importante)

---

## 1) O que você vai precisar

| Item | Onde conseguir |
|------|---------------|
| **Computador em casa** rodando o CYPHER65 War Room | Já deve ter — é onde o dashboard está instalado |
| **Conta Tailscale** (gratuita) | [signup.tailscale.com](https://signup.tailscale.com) |
| **Tailscale instalado** no host, celular e notebook | [tailscale.com/download](https://tailscale.com/download) |
| **Conta Tuya Smart / Smart Life** | App no celular (Google Play / App Store) |
| **Smart plugs compatíveis** | Qualquer tomada Wi-Fi que funcione com o app Tuya Smart ou Smart Life |
| **Credenciais Tuya Cloud** (Access ID + Secret) | [developer.tuya.com](https://developer.tuya.com) — veja Passo 4 |

> ⏱ **Tempo estimado:** 15–30 minutos para configurar tudo.

---

## Passo 1 — Instalar Tailscale no host de casa

### 1.1 Crie uma conta Tailscale

Acesse [https://login.tailscale.com](https://login.tailscale.com) e faça login com Google, Microsoft ou GitHub. É gratuito para até 3 dispositivos e 1 usuário.

### 1.2 Instale no seu computador (host)

**Linux (Ubuntu/Debian):**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

**macOS:**
Baixe de [tailscale.com/download](https://tailscale.com/download) e instale. Clique no ícone na barra de menus e faça login.

**Windows:**
Baixe de [tailscale.com/download](https://tailscale.com/download) e instale. Faça login pelo systray.

### 1.3 Confirme que está conectado

```bash
tailscale status
```

Você deve ver algo como:
```
100.x.x.x    seu-hostname           linux   -
```

Anote o IP **100.x.x.x** — você vai usar ele para acessar o dashboard de qualquer lugar.

---

## Passo 2 — Conectar celular e notebook ao mesmo tailnet

### 2.1 Instale Tailscale no celular

- **Android:** [Google Play](https://play.google.com/store/apps/details?id=com.tailscale.ipn)
- **iOS:** [App Store](https://apps.apple.com/app/tailscale/id1470499037)

Abra o app e faça login **com a mesma conta** que você usou no Passo 1.

### 2.2 Instale no notebook

Repita o passo 1.2 no notebook, usando a mesma conta.

### 2.3 Verifique

No terminal do host de casa:
```bash
tailscale status
```

Você deve ver 3 dispositivos:
```
100.x.x.x    host-casa              linux   active
100.y.y.y    seu-celular            ios     active  
100.z.z.z    seu-notebook           macOS   active
```

> ✅ **Seu tailnet está pronto!** Agora você pode acessar o dashboard de qualquer dispositivo.

---

## Passo 3 — Verificar o acesso remoto no Axe Fleet

### 3.1 Abra o dashboard

No seu celular ou notebook (fora de casa), abra o navegador e acesse:

```
http://100.x.x.x:8765
```

(Substitua `100.x.x.x` pelo IP do host que você anotou no Passo 1.3)

### 3.2 Veja o status remoto

No painel **Axe Fleet**, procure a seção **🔗 REMOTE ACCESS**. Ela mostra:

| Indicador | O que significa |
|-----------|----------------|
| 🟢 Conectado | Tailscale ativo, host acessível |
| 🟡 Degradado | Tailscale conectado mas algo falhou |
| 🔴 Offline | Tailscale não está rodando |

### 3.3 Faça o teste de conexão

Clique no botão **"Test Connection"** no painel Remote Access. O sistema vai testar:

1. ✅ Tailscale daemon rodando
2. ✅ Dashboard reachable via tailnet
3. ✅ Miners registrados respondendo
4. ✅ Conectividade geral

> 💡 **Dica:** Se o dashboard abrir mas mostrar "Tailscale not connected", verifique se o Tailscale está ativo no host (`tailscale status`).

---

## Passo 4 — Configurar tomadas Tuya

### 4.1 Prepare os smart plugs

1. Conecte os smart plugs na tomada
2. Baixe o app **Tuya Smart** ou **Smart Life** no celular
3. Adicione cada plug pelo app (siga as instruções do fabricante)
4. Dê nomes fáceis de identificar: "Bitaxe Garage", "S19 Basement", etc.

### 4.2 Obtenha as credenciais Tuya Cloud

1. Acesse [https://developer.tuya.com](https://developer.tuya.com)
2. Crie uma conta (use o mesmo email do app Tuya Smart)
3. No painel, clique em **"Cloud" → "Create Cloud Project"**
   - Nome: `cypher65-war-room` (ou qualquer nome)
   - Tipo: **Smart Home**
   - Data Center: escolha sua região (US, EU, CN, IN)
4. No projeto criado, vá em **"Devices" → "Link Tuya App"** → escaneie o QR code com o app Tuya Smart
5. Vá em **"API Management"** e anote:
   - **Access ID** (Client ID)
   - **Access Secret** (Client Secret)
6. Anote também a **região** que você escolheu (us, eu, cn, in)

### 4.3 Configure no dashboard

1. No Axe Fleet, vá em **Settings** (botão `::`)
2. Encontre os campos Tuya (ou use variáveis de ambiente):
   - `TUYA_ACCESS_ID`: seu Access ID
   - `TUYA_ACCESS_SECRET`: seu Access Secret  
   - `TUYA_REGION`: us / eu / cn / in
3. Salve

**Alternativa via .env:**

Edite o arquivo `.env` na raiz do projeto:
```bash
TUYA_ACCESS_ID=seu_access_id_aqui
TUYA_ACCESS_SECRET=seu_access_secret_aqui
TUYA_REGION=us
```

### 4.4 Valide as credenciais

No painel Axe Fleet, clique em **"Power Plugs"**. Se as credenciais estiverem corretas, você verá a lista de plugs encontrados.

---

## Passo 5 — Associar tomada a um miner

### 5.1 Na lista de dispositivos

Cada miner no Axe Fleet pode ser associado a uma tomada:

1. No painel **Axe Fleet**, encontre o miner
2. Clique no ícone ⚡ (energia) ao lado do miner
3. No seletor, escolha a tomada Tuya correspondente
4. Confirme

### 5.2 Visualize a associação

Após associar:
- O card do miner mostra um badge 🔌 com o nome da tomada
- O estado da tomada aparece em tempo real (🟢 ligada / 🔴 desligada)

---

## Passo 6 — Ligar/desligar miner remotamente

### 6.1 Ações individuais

No card de cada miner, você pode:

| Ação | Botão | Precisa confirmação? |
|------|-------|---------------------|
| Ligar tomada | ✅ ON | Não |
| Desligar tomada | ⭕ OFF | Sim (1 clique) |
| Ver status | 🔍 STATUS | Não |

### 6.2 Confirmação

Ações de **desligamento** sempre pedem confirmação para evitar desligamento acidental.

---

## Passo 7 — Power-cycle (desligar, esperar, ligar)

O **power-cycle** é útil quando um miner trava e você precisa reiniciá-lo pela tomada.

### 7.1 Como fazer

1. No card do miner, clique em **"Power Cycle"**
2. Confirme a ação (caixa de diálogo, marque "confirm")
3. Defina o tempo que a tomada ficará desligada (5–60s, padrão 10s)
4. Confirme

### 7.2 O que acontece

O sistema:

1. Desliga a tomada ✅
2. Aguarda os segundos configurados ⏳
3. Liga a tomada novamente ✅

Como a operação é **assíncrona**, você pode fechar o diálogo e continuar usando o dashboard. O status aparece na seção "Power Tasks".

---

## Passo 8 — Diagnóstico de conectividade

No painel **Remote Access**, use os diagnósticos:

### Teste rápido
Clique em **"Test Connection"** — executa todos os testes em sequência:

| Teste | O que verifica |
|-------|---------------|
| Tailscale daemon | O Tailscale está instalado e rodando |
| Dashboard reachable | O próprio dashboard responde na tailnet |
| Miners na tailnet | Cada miner responde via tailnet |
| Tuya Cloud | Credenciais Tuya são válidas |

### Diagnóstico individual
Clique em **"Diagnose"** ao lado de cada miner para ver latência e status HTTP.

---

## ⚠ Segurança importante

### ✅ Faça

- Mantenha o **Tailscale sempre ativo** no host de casa
- Use **senha forte** na conta Tailscale
- Associe **apenas tomadas que você possui fisicamente**
- Confirme ações de desligamento antes de executar
- Mantenha o sistema atualizado

### ❌ NÃO faça

- **Nunca** abra a porta 80/8765 do seu roteador para os miners — para quê, se você tem Tailscale?
- **Nunca** compartilhe suas credenciais Tuya
- **Nunca** faça power-cycle em lote sem verificar cada miner antes
- **Nunca** desligue a energia de um miner que está encontrando um bloco (você perderia o share)

### 🔒 Modelo de segurança

```
Internet 🌐
    │
    ▼
[Servidor Tailscale] ─── criptografia ponta a ponta ─── [Seu celular]
    │                                                       │
    ▼                                                       ▼
[Host em casa] ←── tailnet privado (100.x.x.x) ──→ [Notebook]
    │
    ▼
[LAN doméstica] ── miners nunca expostos à internet
    │
    ▼
[Smart plugs Tuya] ── controlados via Tuya Cloud API
```

**Nenhum miner fica exposto à internet.** Toda comunicação passa pelo tailnet criptografado ou pela API oficial da Tuya.

---

## 🆘 Troubleshooting

| Problema | Causa provável | Solução |
|----------|---------------|---------|
| Dashboard não abre no celular | Tailscale não está conectado no celular | Abra o app Tailscale e verifique se está online |
| "Tailscale not connected" no painel | Tailscale não está rodando no host | `sudo tailscale up` no host |
| "Tuya credentials not configured" | Credenciais não foram salvas | Configure TUYA_ACCESS_ID e TUYA_ACCESS_SECRET |
| Plug não aparece na lista | Plug não foi adicionado no app Tuya Smart | Adicione o plug no app primeiro |
| "Command failed" ao ligar/desligar | Plug offline ou sem energia | Verifique se o plug está ligado na tomada |
| Power-cycle travou | Timeout na Tuya Cloud | Espere 30s e tente novamente |

---

## 📚 Referências

- [Documentação Tailscale](https://tailscale.com/docs/)
- [Tuya IoT Developer Platform](https://developer.tuya.com)
- [ESP-Miner / AxeOS API](https://github.com/bitaxeorg/ESP-Miner)
- [CYPHER65 War Room](https://github.com/0xjc65eth/cypher65-war-room)

---

*Última atualização: Julho 2026 • Versão 1.0*
