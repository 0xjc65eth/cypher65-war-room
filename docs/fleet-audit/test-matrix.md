# Test Matrix — Fleet audit (Issue #627)

Cobertura automatizada por cenário. Fontes: `tests/test_fleet_audit_regressions.py`
(34 testes), `tests/e2e/fleet-agentless-manual-add.spec.js`, suítes existentes.

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

## Cobertura e2e (Playwright)

- Desktop 1280×720 + Mobile 390×844 (drawer da sidebar).
- Assert de `pageerror` em **todos** os testes (regressão do F1 é impossível quebrar sem falhar).
- Scan real contra o simulador virtual (`virtual_hardware`) via `DEBUG_MOCK`.
- **Marker `data-axe-rendered`** na `#axe-grid` (todos os 3 pontos de pintura):
  sinal explícito de "pintado por JS" usado pelos specs (dashboard, braiins-detector).
  O probe antigo — ausência de `#axe-empty-add` — tornou-se ambíguo quando o
  empty-state runtime passou a carregar legitimamente esse botão (F2). Specs
  atualizados nesta branch; dashboard 58/58 local.

## Lacunas conhecidas (não automatizadas)

- ~~Stratum V2 sem suíte consumidora no Fleet~~ — **fechada pelo PR #631** (Issue #630):
  `tests/test_fleet_stratum_v2_pipeline.py` cobre o pipeline ASIC → parsing
  (`stratum2+tcp/ssl/tls`) → detecção → probe passivo no lab → capability.
  A adaptação original da auditoria estava imprecisa: o adaptador SV2 já tinha
  suíte própria (`test_stratum_v2_adapter.py`). Stratum V1 segue com lacuna
  análoga (lab existe, sem consumidor end-to-end no Fleet).
- Chaos matrix completa (reboot do miner, troca de IP/MAC, DNS failure) — parcialmente coberta pelos testes de staleness T06–T11; cenários de rede real exigem ambiente físico.
- Eventos estruturados `fleet.*` (R7 do review) — Issue #629.
