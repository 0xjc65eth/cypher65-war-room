# 01 · Code Map — Fleet subsystem

Auditoria Fleet (Issue #627) · mapa real de arquivos e dependências (verificado por leitura de código, não por suposição).

## Módulos Python

| Arquivo | Papel | Notas da auditoria |
|---|---|---|
| `axe_fleet/routes.py` (3770 l.) | Blueprint `/api/axe-fleet/*` + `agent_bp` (`/api/agent/*`) | devices CRUD, telemetry ingest, scan, diagnose, test-devices (DEBUG_MOCK), power-plugs, agent register/telemetry/commands |
| `axe_fleet/scanner.py` | LAN scan (AxeOS :80, cgminer :4028, HTTPS :443), diagnose por host, sugestão de subnets, hint de topologia cloud-vs-LAN | `is_private_ip`, `private_ip_hint()`, `MAX_HOSTS_PER_SCAN=1024` |
| `axe_fleet/connector.py` | `AxeOSConnector` — HTTP :80 (`/api/system/info` etc.), `extract_telemetry` normalizado | best_diff agora via `best_diff_from_value` (#627) |
| `axe_fleet/models.py` | Schemas de device/telemetry, capacidades, `derive_device_status`, `best_diff_from_value` (novo), `is_telemetry_stale` (novo), `STATUS_STALE` (novo) | fonte de verdade dos estados |
| `axe_fleet/registry.py` | SQLite: devices, telemetry, agent commands, tombstones, upsert agent, `save_agent_telemetry` (máquina de estados honesta) | `_latest_measured_telemetry` (novo, ordem de chegada via rowid) |
| `agent/agent.py` (665 l., stdlib-only) | Agente local: scan LAN → register → push telemetria → pull/ack comandos → re-scan a cada 10 ciclos | `_best_diff` espelha o normalizador do server (testado) |
| `core/registry/detector.py` | `detect_firmware()` — AxeOS → Braiins REST → cgminer; marcadores `_AXEOS_MARKERS` rejeitam routers com JSON catch-all | porta fixa :80 no probe (limitação conhecida) |
| `core/adapters/{base,bitaxe,braiins,cgminer}_adapter.py` | Interfaces normalizadas por firmware (hashrate, temp, shares, `best_difficulty`, pool config) | `bitaxe_adapter` já fazia o normalizador certo |
| `services/pool_intelligence/` | Registry de pools (~30+4 novos), `detect_provider`, `stratum_host`, stats adapters, unknown honesto | AtlasPool + 3 solo pools adicionados (#627) |
| `services/pool_detection.py` | Cola ASIC→pool: `detected_pool_for`, `attach_to_snapshot` (chaves sempre presentes) | sem rede por iniciativa própria |
| `config.py` | `is_cloud_deploy()` — guard SaaS que muda a UX (scan/manual/agent) | lido no call-time |

## Frontend

| Arquivo | Papel |
|---|---|
| `static/src/49-axe-fleet.js` (1502 l.) | Fleet UI: grid de devices, wizard de add (3 steps), scan LAN, detail, agent panel |
| `static/src/48-fleet-cc.js` | Fleet Command Center (linhas por worker) |
| `static/src/40-app-logic.js` | Navegação de módulos, skeleton loading, boot |
| `static/src/10-core-fmt.js` | `fmt.diff()` — K/M/G/T/P/E para o P Share, `0 → "0"`, null → "—" |
| `static/app.js` | **Artefato gerado** — `node scripts/build_app_js.cjs` |

## Fluxo principal (call graph)

```
UI (49-axe-fleet.js)                     BACKEND                          DADOS
openAxeWizard()  ──POST /api/axe-fleet/devices──▶ add_device()
scanNetwork()    ──POST /api/network/scan───────▶ _lan_scanner (cloud guard)      SQLite axe_devices
                 ──POST /api/axe-fleet/scan─────▶ scan_subnet() (thread)          axe_telemetry
agent (LAN)      ──POST /api/agent/register─────▶ upsert_agent_device() ────────▶ (upsert por IP+tenant)
agent (LAN)      ──POST /api/agent/telemetry────▶ save_agent_telemetry() ───────▶ status honesto:
                                                                                   PAUSED > STALE(ts antigo) >
                                                                                   ONLINE/IDLE > STALE(heartbeat) > OFFLINE
UI polling       ──GET /api/axe-fleet/devices───▶ list_devices(with_telemetry) ──▶ degrada ONLINE velho → STALE
```

## Simuladores (nível de rede, não mocks de função)

- `tests/virtual_hardware/nerdqaxe.py` — AxeOS HTTP real (ThreadingHTTPServer), payload agora no contrato canônico (`hashrate`, `uptime`, `bestDiff`) (#627)
- `tests/virtual_pool/stratum_v1_lab.py` / `stratum_v2_lab.py` — servidores Stratum determinísticos
