# CYPHER65 — Ideal Customer Profiles (ICPs)

**Version:** 1.0
**Date:** 2026-08-23
**Status:** Draft — validates during beta (30 days, 10 testers)

---

## ICP 1: Solo Miner com Bitaxe/ASIC na LAN

### Dor
- Monitora 1-5 ASICs (Bitaxe, NerdQaxe, Antminer) via webUI do firmware ou planilha.
- Quando o miner cai às 3h da manhã, só descobre ao acordar — perdeu 6h de shares.
- Não tem visão consolidada de uptime, temperatura e eficiência ao longo do tempo.
- Usa CoinWarz ou calculadoras online para estimar rentabilidade, mas são genéricos.

### Oferta CYPHER65
- **AXE Fleet Command**: telemetria em tempo real (hashrate, temp, fan, efficiency, uptime).
- **Probability Engine**: entende quanto tempo falta para encontrar um bloco, dado o hashrate real.
- **Auto-Pilot (advisory)**: alertas de miner offline/overheating sem executar nada.
- **Alerts**: Discord/Telegram quando algo sai do normal.

### Mensagem comercial
> "Seu miner caiu de madrugada e você só viu de manhã. O CYPHER65 te avisa em 30 segundos."

### Canal preferido
- YouTube (tutoriais Bitaxe/NerdQaxe), Reddit r/BitcoinMining, Telegram groups SHA-256.

### Ticket esperado
- PRO: $9/mês ou BTC equivalente
- Upgrade path: Rental Hub quando escalar para 10+ rigs

---

## ICP 2: Pequena Farm (5-20 Antminers)

### Dor
- Opera 5-20 ASICs em 1-2 locais. Usa planilha + dashboard da pool + WhatsApp para coordination.
- Não sabe qual rig é menos eficiente (J/TH) nem qual está com mais shares rejeitados.
- Quando um rig fica lento, o técnico demora a perceber — perde produtividade.
- Precisa comparar custo de energia vs. hashprice para decidir se mantém ou desliga rigs.
- Não tem trilha de auditoria: quem mudou a configuração do Antminer X?

### Oferta CYPHER65
- **AXE Fleet Command**: ranking de rigs por eficiência, alerta de outlier.
- **Profitability (POOL/SOLO)**: cálculo de break-even com custo de energia real.
- **Rentals Hub**: compara alugar hash vs. manter rig próprio.
- **Auto-Pilot**: restart automático de rig offline (com consent, EULA assinado).
- **Audit Log**: trilha imutável de cada mudança em cada dispositivo.

### Mensagem comercial
> "Sua planilha não te avisa quando o Antminer S21 está consumindo 40W a mais que o normal. O CYPHER65 sim."

### Canal preferido
- Minerscale/Bitcoin mining conferences, mining farm operator forums, LinkedIn mining groups.

### Ticket esperado
- PRO: $9-29/mês (conforme número de rigs)
- Upgrade path: Auto-Pilot autônomo + consultoria de eficiência

---

## ICP 3: Operador de Hashrate Alugado (Rental/Lease)

### Dor
- Aluga hashrate no Braiins/MRR/NiceHash e não sabe se o preço pago é competitivo.
- Comprou hash a 70 sats/TH/d e agora o mercado caiu para 50 — precisa decidir: manter ou revender.
- Não consegue rastrear ROI por contrato de aluguel — tudo é média suja.
- Preocupa-se com concentração: 80% do hash em 1 provider = risco de single point of failure.
- Oportunidades de arbitragem (Braiins 49 vs MRR 66) passam batido porque não tem alerta.

### Oferta CYPHER65
- **Hash Market**: comparação ao vivo Braiins vs NiceHash vs MRR vs Parasite.
- **Rentals Hub**: P/L por contrato, custo vs. mercado, worst-rig leaderboard, arbitrage alerts.
- **One-click Braiins spot buy**: compra com balance guard e audit log.
- **Profitability (RENTAL/LEASE)**: cálculo de break-even com dados reais de mercado.

### Mensagem comercial
> "Você pagou 70 sats/TH/d por hash que hoje custa 50. O CYPHER65 te alertou 3 dias antes."

### Canal preferido
- Braiins/MRR Discord, hashrate marketplace forums, Twitter Bitcoin mining community.

### Ticket esperado
- PRO: $19-49/mês (volume de aluguel)
- Upgrade path: Auto-Pilot de arbitragem + rental automation

---

## Validação do beta (30 dias, 10 testers)

| ICP | Métrica de sucesso | Critério |
|---|---|---|
| Solo Miner | Time to first value | < 5 min do clone ao primeiro dado real |
| Small Farm | Daily active usage | ≥ 3/4 testers logam diariamente |
| Rental Op | Trial→paid conversion | ≥ 2/3 testers pagam no dia 31 |

**Se < 50% dos testers de qualquer ICP validarem a dor → pivotar ou reduzir escopo.**
