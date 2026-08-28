# Matriz de validação física — gate do beta

Status em 28-08-2026: **PENDENTE — não libera comandos físicos publicamente**.
Este documento define o ensaio; não afirma que qualquer execução ocorreu.

## Escopo mínimo

- Dispositivos: Bitaxe, NerdQaxe e um ASIC de farm (Antminer ou equivalente).
- Firmware: ESP-Miner/AxeOS e cgminer/BMMiner ou Braiins OS.
- Volume: 200 dry-runs e 50 comandos humanos controlados.
- Todo comando real exige alvo validado, `dry_run=false` explícito, confirmação
  humana, ACK, estado pós-comando, audit log e reconciliação com pool e firmware.
- Somente laboratório segmentado, janela aprovada e rollback documentado.
  Não testar troca destrutiva de pool, firmware ou energia em produção.

## Matriz

| Cenário | Preparação | Ação | Resultado esperado | Evidência | Risco | Critério de aprovação |
|---|---|---|---|---|---|---|
| ASIC online | Telemetria estável por 15 min | Coletar 3 ciclos | online, timestamp/origem/unidade presentes | payloads + firmware | baixo | 3/3 coerentes |
| ASIC offline | Isolar LAN no laboratório | Coletar até timeout | offline/stale, sem zero fictício | timeline + captura LAN | baixo | estado em até 2 ciclos |
| Reboot parcial | Janela e rollback aprovados | dry-run; confirmar; reboot | ACK, offline transitório, retorno e uptime reiniciado | audit + antes/depois | médio | alvo correto e reconciliação |
| Timeout de LAN | Firewall temporário | dry-run e tentativa controlada | timeout limitado, sem retry infinito | duração + log | médio | nenhuma duplicação |
| Resposta atrasada | Proxy de laboratório adiciona latência | coletar/comandar | stale/timeout explícito | timestamps | médio | UI não mostra sucesso prematuro |
| Firmware incompatível | Dispositivo sem capability | consultar e tentar dry-run | read-only/unsupported | capabilities + audit | baixo | nenhum POST físico |
| Alteração de hashrate | Perfil seguro conhecido | mudar perfil com rollback | unidade H/s, ACK e nova telemetria | firmware/pool | alto | limites térmicos preservados |
| Stale shares | Pool de teste/telemetria gravada | interromper submissões | alerta stale com idade/origem | pool + alerta | baixo | sem confundir com offline |
| Queda de temperatura | Reduzir carga com segurança | observar | tendência real, sem alerta de alta | série temporal | baixo | coerente com firmware |
| Aumento de temperatura | Carga limitada e supervisionada | observar limiar | alerta antes do limite de rollback | termal + audit | alto | abort automático/manual funciona |
| Perda de conectividade | Desconectar rede | observar/reconectar | offline → reconnect sem duplicar ASIC | eventos + IDs | médio | mesmo device_id após retorno |
| Dois comandos simultâneos | Mesmo alvo, dois clientes | consumir mesmo token | só um consume; outro 409/403 | audit + respostas | alto | uma ação física |
| Repetição de comando | Reenviar mesma confirmação | replay | rejeitado; sem segundo dispatch | audit + firmware | alto | contagem física = 1 |
| Comando após offline | Preparar token e derrubar LAN | executar | bloqueado por estado/freshness | audit + timestamp | alto | nenhum dispatch |

## Registro de evidência

Cada execução é um objeto JSON sem IP público, credencial, wallet ou dado
pessoal. Campos obrigatórios: `run_id`, `timestamp` UTC, `mode`,
`device_family`, `firmware_family`, `scenario`, `target_validated`, `passed` e
`evidence_ref`. Comandos humanos também exigem `confirmed`, `ack`,
`post_state_verified`, `audit_log_id`, `pool_reconciled` e
`firmware_reconciled`.

Validação do gate:

```bash
python scripts/validate_physical_evidence.py caminho/evidence.json
```

O arquivo real de evidências deve ficar fora do Git se contiver endereços LAN
ou identificadores operacionais. Publique apenas artefatos sanitizados.

## Kill criteria

- Qualquer comando no alvo errado, duplicado ou sem audit log: interromper lote.
- ACK sem estado pós-comando coerente: não liberar a família/firmware.
- Mais de 2% de divergência de classificação online/offline ou stale na matriz:
  corrigir antes de continuar.
- Timeout superior ao limite documentado ou retry não limitado: manter read-only.
- Menos de 200 dry-runs, 50 comandos controlados, três famílias de dispositivo
  ou duas famílias de firmware: beta permanece sem comandos reais.
