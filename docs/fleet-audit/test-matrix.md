# Test Matrix — Fleet audit (Issue #627)

Cobertura automatizada por cenário. Fontes: `tests/test_fleet_audit_regressions.py`
(34 testes), `tests/e2e/fleet-agentless-manual-add.spec.js`,
`tests/test_fleet_stratum_v1_pipeline.py` (34 testes),
`tests/test_fleet_stratum_v2_pipeline.py` (23 testes), suítes existentes.
O follow-up Stratum V1 é rastreado pela Issue #635.

| ID | Cenário | Agente | Miner | Pool | Protocolo | Esperado | Automatizado | Resultado | Evidência / Teste |
|---|---|---|---|---|---|---|---|---|---|
| T01 | Manual add visível sem agent e com chip ausente | ❌ | — | — | — | Botão sempre alcançável | ✅ e2e desktop | ✅ | `fleet_agentless_manual_add_visible_without_header_chip` |
| T02 | Manual add visível em mobile (drawer) | ❌ | — | — | — | Botão sempre alcançável | ✅ e2e mobile | ✅ | `fleet_agentless_manual_add_visible_on_mobile` |
| T03 | Empty-state sem devices tem botão funcional | ❌ | — | — | — | `#axe-empty-add` renderizado em runtime | ✅ e2e | ✅ | `fleet_empty_state_add_button_renders_after_devices_render` |
| T04 | Scan falho sem agent não vira dead-end | ❌ | — | — | — | Wizard aberto após clique | ✅ e2e | ✅ | `fleet_agentless_scan_explains_limitations_and_manual_add_reachable` |
| T05 | Wizard abre sem `ReferenceError` | ❌ | — | — | — | Zero page errors no clique | ✅ e2e | ✅ | todas as specs (assert `pageerror`) |
| T06 | Heartbeat vazio ≠ ONLINE | ✅ | — | — | — | OFFLINE (sem leitura) | ✅ unit/API | ✅ | `test_empty_heartbeat_never_says_online` |
| T07 | Heartbeat vazio + leitura velha | ✅ | ✅ | — | — | STALE | ✅ unit/API | ✅ | `test_empty_heartbeat_does_not_hide_a_dead_miner` |
| T08 | Heartbeat vazio + leitura fresca | ✅ | ✅ | — | — | mantém status vivo (IDLE/ONLINE) | ✅ unit/API | ✅ | `test_empty_heartbeat_preserves_fresh_live_reading` |
| T09 | Device novo, só heartbeat → OFFLINE | ✅ | — | — | — | Nunca "online" sem sinal do miner | ✅ unit/API | ✅ | `test_agent_register_then_stale_heartbeat` / `test_new_device_with_only_heartbeat_is_offline` |
| T10 | Leitura online envelhecida (>15min) degrada | — | ✅ | — | — | STALE na listagem | ✅ unit/API | ✅ | `test_list_devices_degrades_old_online_rows` |
| T11 | STALE não conta como online no resumo | — | ✅ | — | — | counts honestos | ✅ unit | ✅ | `test_stale_status_is_not_online_for_summaries` |
| T12 | PAUSED não expira por staleness | — | ✅ | — | — | Intenção do operador vence | ✅ unit | ✅ | `test_fleet_pause_status` (atualizado) |
| T13 | best_diff `"0"` (cgminer) preservado | — | ✅ | — | cgminer API | `"0"` ≠ `""` | ✅ unit | ✅ | `test_best_diff_from_value` + `test_legacy_idiom_is_dead` |
| T14 | best_diff 0 (AxeOS numérico) preservado | — | ✅ | — | AxeOS | `"0"` | ✅ unit | ✅ | `TestBestShareNormalization::test_zero_number` |
| T15 | best_diff null/ausente → vazio, nunca `"0"` | — | ✅ | — | AxeOS | `""` (UI: "—") | ✅ unit | ✅ | `TestBestShareNormalization::test_none`/`test_missing_key` |
| T16 | best_diff string numérica normalizada | — | ✅ | — | ambos | número canônico | ✅ unit | ✅ | `TestBestShareNormalization::test_numeric_string` |
| T17 | best_diff lixo (NaN/inf/objeto) → vazio | — | ✅ | — | ambos | degradação honesta | ✅ unit | ✅ | `TestBestShareNormalization::test_nan_inf_garbage` |
| T18 | best_diff gigante (1e300, notação científica) | — | ✅ | — | ambos | preservado | ✅ unit | ✅ | `TestBestShareNormalization::test_huge_values` |
| T19 | Telemetria sem best_diff: contraste presença/ausência | — | ✅ | — | AxeOS | chave presente com "" ≠ ausente sem inventar "0" | ✅ API | ✅ | `test_telemetry_without_best_diff_leaves_no_fabricated_zero` |
| T20 | Telemetria velha não perde para nova no empate de `ts` | — | ✅ | — | — | ordem de chegada (rowid) | ✅ API | ✅ | `test_telemetry_same_ts_last_write_wins` |
| T21 | Pool desconhecido não crasha | — | ✅ | genérico | Stratum V1 | `generic-stratum` editável | ✅ unit | ✅ | `test_fleet_unknown_pool_does_not_crash` |
| T22 | AtlasPool detectado | — | ✅ | AtlasPool | Stratum V1 | SOLO/BTC + stratum_only | ✅ unit | ✅ | `test_fleet_atlas_pool_detected` |
| T23 | Novos solo pools registrados | — | ✅ | Braiins Solo/SoloHash/Satoshi Radio/EU CK | Stratum V1 | detectados, sem REST prometido | ✅ unit | ✅ | `test_new_solo_pools_are_registered` |
| T24 | Simulador AxeOS serve payload canônico | — | ✅ (virtual) | — | HTTP | hashRate→hashrate, bestDiff:0 | ✅ e2e/fixture | ✅ | `test_validate_physical_evidence` + e2e scan |
| T25 | Rota ecoa status persistido (não re-deriva) | ✅ | — | — | — | OFFLINE ecoado | ✅ API | ✅ | `TestEmptyHeartbeatAccepted` |
| T26 | Regressão: suítes Fleet completas | ✅ | ✅ | ✅ | — | 470 passed | ✅ pytest | ✅ | `pytest tests/test_fleet_audit_regressions.py tests/test_agent_api.py tests/test_axe_fleet_scanner.py tests/test_fleet_pause_status.py tests/test_axeos_connector.py` |
| T27 | Componentes V1: parsing `stratum+tcp/ssl/tls`, detecção de provider, probe TCP local e capability `protocol.stratum_v1.subscribe` | — | — (URL fixture) | V1 lab | Stratum V1 | SUPPORTED/ERROR; todos os envios do caso read-only contêm só `mining.subscribe`; EOF retorna `connection_closed` | ✅ pytest | ✅ | `tests/test_fleet_stratum_v1_pipeline.py` (34 testes, #635) |
| T28 | Scheme ≠ versão nos probes: `stratum2+tcp` contra lab V1 observa V1; probe V2 com `stratum+tcp` contra lab V2 observa V2 (probe V1 não declara V1) | — | — (URL fixture) | V1+V2 lab | ambos | observação vence o scheme | ✅ pytest | ✅ | `TestSchemeIsNotVersionEvidence` |

## Cobertura e2e (Playwright)

- Desktop 1280×720 + Mobile 390×844 (drawer da sidebar).
- Assert de `pageerror` em **todos** os testes (regressão do F1 é impossível quebrar sem falhar).
- Scan real contra o simulador virtual (`virtual_hardware`) via `DEBUG_MOCK`.
- **Marker `data-axe-rendered`** na `#axe-grid` (todos os 3 pontos de pintura):
  sinal explícito de "pintado por JS" usado pelos specs (dashboard, braiins-detector).
  O probe antigo — ausência de `#axe-empty-add` — tornou-se ambíguo quando o
  empty-state runtime passou a carregar legitimamente esse botão (F2). Specs
  atualizados nesta branch; dashboard 58/58 local.

## Cobertura Stratum e limites (Issues #630 e #635)

- **V2 (#630/PR #631):** 23 testes em `test_fleet_stratum_v2_pipeline.py`
  exercitam parsing, detecção, probe TCP local e capability. O adaptador já tinha
  sua própria suíte (`test_stratum_v2_adapter.py`); não estava ausente.
- **V1 (#635, T27/T28):** 34 testes em `test_fleet_stratum_v1_pipeline.py`
  exercitam os componentes equivalentes, normalização de endpoint
  (`host:port` ≡ `stratum+tcp://host:port`), registro de todos os `sendall` do
  caso read-only, falhas sanitizadas e resposta parcial seguida de EOF.
  A normalização não prova deduplicação de dispositivos no registry Fleet.
  O lab V1 já existia; este follow-up não altera produção.
- **Protocolo observado:** probes V1/V2 são chamados explicitamente nos testes;
  T28 verifica os dois sentidos da regra scheme ≠ versão. Isso não demonstra
  seleção automática de protocolo no Fleet.
- **Limites do ambiente:** DNS e latência são fixtures. Os sockets redirecionam
  o destino numérico para labs TCP em loopback; não validam DNS real, pinning do
  destino ou alcance de pools públicos. `ssl/tls` têm cobertura de parsing e
  roundtrip, sem handshake TLS nestas duas suítes. Ingestão de telemetria,
  scanner, rotas, persistência Fleet, ASIC físico e cloud ficam fora deste teste
  de integração entre componentes.
- **Execução local em 2026-09-19:** 120 testes passaram nas duas suítes Fleet
  Stratum, `test_stratum_v1_probe.py`, `test_stratum_v1_fuzz_redteam.py` e
  `test_stratum_v2_adapter.py`; Black, flake8 e `git diff --check` passaram.
  A evidência histórica T01–T26 não foi reexecutada neste follow-up.

## Lacunas conhecidas (não automatizadas por este follow-up)

- Integração Fleet completa com ingestão de telemetria até observação de
  protocolo/capability, incluindo seleção do probe e persistência.
- Handshake TLS e operação com ASIC/pool reais ou implantação cloud.
- Chaos matrix completa (reboot do miner, troca de IP/MAC, DNS failure) — parcialmente coberta pelos testes de staleness T06–T11; cenários de rede real exigem ambiente físico.
- Eventos estruturados `fleet.*` (R7 do review) — Issue #629.
