# Fleet Audit — CYPHER65 (Issue #627)

Auditoria de produção do subsistema **Fleet** com organização multi-agente
(Orchestrator + 13 agentes especializados). Base: branch `fix/627-fleet-audit`
a partir de `master` (squash do PR #625, wave W3).

## Documentos

| Documento | Conteúdo |
|---|---|
| [`01-code-map.md`](./01-code-map.md) | Mapa de código: módulos, rotas, frontend, grafo de dependências |
| [`agent-ledger.md`](./agent-ledger.md) | Ledger de achados (F1–F10) com evidência, teste e status |
| [`pool-matrix.md`](./pool-matrix.md) | Matriz de pools verificada + veredito sobre os pools citados no relato |
| [`test-matrix.md`](./test-matrix.md) | Matriz de testes T01–T28 com automação e lacunas |

## Arquitetura (antes → depois)

### Antes (3 causas-raiz dos relatos de produção)

1. **BUG A (agentless dead-end)** — dupla falha no frontend:
   - `_axeDetectTimer` declarado com `let` dentro de `initAxeFleetControls()`
     mas usado por `resetAxeWizard()` em escopo de módulo → `ReferenceError`
     **em todo clique** que abre o wizard. O manual add **nunca funcionou**
     nesta build (introduzido quando o timer de auto-detect entrou).
   - `renderAxeFleet()` reescreve `#axe-grid` em runtime com um empty-state
     **sem botão** — o `#axe-empty-add` estático morria no primeiro render.
   - Resultado: usuário sem agente + scan falho = tela morta, exatamente o
     relato "não aparece a opção manualmente".

2. **BUG B ("online" sem P Share)** — três camadas:
   - `agent/agent.py` + `axe_fleet/connector.py` colapsavam best_diff **0
     legítimo** para `""` (`str(x or "")`), e heartbeat **vazio** do agente
     mantinha o device `IDLE` com `last_seen` fresco para sempre — "miner on"
     sem telemetria alguma.
   - A rota de telemetria re-derivava status do payload (`IDLE` fake) em vez
     de ecoar o status persistido pelo registry.
   - Leitura não tinha horizonte de staleness: `ONLINE` envelhecido ficava
     verde indefinidamente.

3. **BUG C (pools)** — AtlasPool e pools solo recentes ausentes; prompt
   original com leads não-verificados (SoloMining.de = loja, Noderunners =
   blog, satoshiradio.xyz = DNS inexistente). Arquitetura correta já existia:
   `detect_provider()` + fallback genérico — faltavam registros honestos.

### Depois

- **Manual add estruturalmente inquebrável**: `openAxeWizard()` em escopo de
  módulo, empty-state renderizado **com** botão funcional, e2e que falha se
  qualquer `pageerror` ocorrer.
- **Máquina de estados honesta**: `{}` heartbeat = presença, não saúde →
  OFFLINE (sem leitura) / STALE (leitura velha) / mantém vivo; PAUSED (desejo
  do operador) nunca expira; `STALE` não conta como online nos resumos.
- **Best Share com semântica única**: `best_diff_from_value()` — `0` é dado,
  `null` é vazio, lixo degrada para vazio; UI mostra "—" em vez de inventar 0.
- **Pools**: 4 providers `stratum_only` novos (AtlasPool solo verificado por
  probe passivo de protocolo em 2026-09-17) + fallback genérico documentado.

## Modos de operação (o que funciona sem agente)

| Modo | Sem agente? | Notas |
|---|---|---|
| Manual add por IP/host | ✅ | Backend alcança o miner diretamente (NAT: requer mesma rede/VPN); Test Connection distinguindo DNS/timeout/refused/auth |
| Scan LAN automático | ⚠️ | Executa no **servidor** — só enxerga a rede do servidor; sem agente, redes domésticas atrás de NAT não são escaneáveis (arquitetura documentada, não simulada) |
| Descoberta por pool | ✅ (parcial) | workers visíveis no pool ≠ device físico; identidade só após correlação |
| Telemetria contínua | via agente | heartbeat vazio agora é honesto (não mantém verde) |

## Evidência registrada na auditoria #627

```
pytest regressões Fleet ......... 34 passed (nova suíte)
Suíte Fleet completa ............ 470 passed
JS core ......................... 1525 passed + drift check ok
e2e Playwright (BUG A) .......... 6 passed (desktop + mobile)
Black/flake8 .................... clean
```

## Continuação Stratum (Issue #635)

Validação local das suítes de componentes em 2026-09-19:

```
Componentes SV2 (#630/#631) ...... 23 passed
Componentes V1 (#635) ........... 34 passed
Suítes Stratum relacionadas ..... 120 passed
Black/flake8 + git diff --check .. clean
```

Os 120 testes incluem as duas suítes acima, `test_stratum_v1_probe.py`,
`test_stratum_v1_fuzz_redteam.py` e `test_stratum_v2_adapter.py`.
O follow-up V1 testa resposta parcial seguida de EOF com erro
`connection_closed`, registra todos os envios do probe para exigir somente
`mining.subscribe` e verifica capabilities e observações de protocolo.

As suítes compõem funções de `pool_intelligence` com URLs sintéticas e labs
TCP locais. DNS e latência são fixtures; o socket redireciona o endereço para
loopback. SSL/TLS têm cobertura de parsing, sem handshake nestas duas suítes.
Os resultados não demonstram ingestão/rotas/persistência Fleet, conexão com ASIC
físico ou pool público, nem comportamento no cloud. Não há mudança de produção.
Os resultados históricos de #627 acima não foram reexecutados neste follow-up.

## Regras permanentes extraídas

1. Nunca `str(x or "")` para métricas — usar os normalizadores do módulo.
2. Heartbeat = presença; saúde vem de leitura do dispositivo com timestamp.
3. Toda re-renderização de DOM deve renderizar suas próprias ações (botões).
4. Pool do prompt ≠ pool real: verificar antes de registrar; `stratum_only`
   para pools sem REST confirmado.
