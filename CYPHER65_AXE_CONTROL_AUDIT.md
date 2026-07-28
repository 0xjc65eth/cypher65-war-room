# 🔍 CYPHER65 — AXE FLEET CONTROL AUDIT

**Data:** 27 Jul 2026  
**Propósito:** Auditoria de integração do módulo AXE FLEET REMOTE CONTROL no CYPHER65 War Room  
**Feature:** Additiva e isolada — não substitui o Master Upgrade

---

## 1. ARQUITETURA ATUAL DO CYPHER65 (relevante para integração)

```
Stack:        Python/Flask + Vanilla JS + SQLite
App principal: app.py (~2.390 linhas)
Frontend:     static/app.js + templates/dashboard.html + static/style.css
Estado:       services/state.py (single source of truth)
Polling:      app.py → poll_once() → parasite.space + blockchain.info + Coingecko
DB:           data/war_room.sqlite (snapshots, alerts, settings, events)
Background:   Daemon thread via threading.Thread (poll_loop)
```

### Módulos existentes que podem ser REUTILIZADOS

| Módulo | Função | Reutilizável para AXE? |
|--------|--------|------------------------|
| `services/state.py` | Estado global compartilhado | ✅ SIM — Device state cache |
| `services/proximity.py` | Cálculo de best-diff, quantum lock | ✅ SIM — Health scoring |
| `app.py` (poll_once) | Polling de APIs externas | ✅ SIM — Axe polling loop |
| `templates/dashboard.html` | 24 painéis existentes | ✅ SIM — Novo painel AXE FLEET |
| `static/app.js` | Renderização + polling frontend | ✅ SIM — Axe telemetry display |
| `static/style.css` | Design system (CSS vars) | ✅ SIM — Mesma identidade visual |
| `helpers.py` | Formatação (hashrate, diff, uptime) | ✅ SIM — Axe data formatting |
| `data/war_room.sqlite` | Persistência SQLite | ✅ SIM — Device registry + telemetry |

### O que NÃO existe e precisa ser criado

| Necessidade | Por quê |
|-------------|---------|
| `axe-fleet/connectors/axeos.py` | Connector REST para API AxeOS |
| `axe-fleet/discovery/` | Descoberta de dispositivos na rede |
| `axe-fleet/commands/` | Command Engine (restart, pause, config) |
| `axe-fleet/safety.py` | Safety Engine (limites de temp/freq/voltagem) |
| `axe-fleet/models.py` | Modelos de dados (Device, Capability, Telemetry) |
| Rotas Flask `/api/axe-fleet/*` | API REST para o frontend |
| Frontend: painel AXE FLEET | UI para monitorar/controlar devices |
| Frontend: Device Detail modal | UI para ver métricas individuais |

### API AxeOS — Endpoints confirmados

Fonte: [ESP-Miner openapi.yaml](https://github.com/bitaxeorg/ESP-Miner/blob/master/main/http_server/openapi.yaml) + [OSMU Wiki](https://osmu.wiki/bitaxe/api/)

| Método | Endpoint | Dados retornados |
|--------|----------|-----------------|
| GET | `/api/system/info` | System, miner, ASIC, network info |
| GET | `/api/system/asic` | ASIC model, frequency, voltage capabilities |
| GET | `/api/system/statistics` | Logging data (se statsFrequency > 0) |
| GET | `/api/system/statistics/dashboard` | Dashboard-optimized statistics |
| GET | `/api/system/logs` | Logs (melhor via WebSocket) |
| POST | `/api/system/restart` | Reboot |
| POST | `/api/system/identify` | Flash LED/screen |
| POST | `/api/system/OTA` | Firmware update |
| POST | `/api/system/OTAWWW` | Web UI update |
| PATCH | `/api/system` | Update settings (pool, fan, ASIC OC) |
| WS | `ws://{ip}/ws` | Real-time logs + events |

---

## 2. PONTOS DE INTEGRAÇÃO

### Backend (app.py)

```
app.register_blueprint(axe_fleet_bp, url_prefix='/api/axe-fleet')
```

Novo blueprint `axe_fleet_bp` em `axe-fleet/routes.py`. Adicionar após as registrações existentes.

### Estado compartilhado (services/state.py)

Adicionar ao `services/state.py`:
```python
# Axe Fleet state
axe_devices = {}       # {device_id: Device}
axe_telemetry = {}     # {device_id: Telemetry}
```

### Polling

Adicionar função `_poll_axe_fleet()` em app.py que roda junto com `poll_once()`, respeitando intervalos configuráveis (não fazer polling agressivo — máximo a cada 30s).

### Database (SQLite)

Novas tabelas em `init_db()`:
- `axe_devices`: registro de dispositivos
- `axe_telemetry`: histórico de telemetria
- `axe_commands`: log de comandos executados

### Frontend

Adicionar painel no `dashboard.html` (seguindo o grid de 4 colunas), conectado via `fetchAxeSnapshot()` em `app.js`.

---

## 3. POTENCIAIS CONFLITOS

| Conflito | Risco | Mitigação |
|----------|-------|-----------|
| Polling loop sobrecarregado | Médio | Axe polling em thread separada, intervalo mínimo 30s |
| Muitos dispositivos (15+) | Baixo | Polling sequencial com timeout por device |
| Conflito de nomes de estado | Baixo | Namespace `axe_` em services/state.py |
| Segurança (LAN access) | Médio | Credenciais criptografadas no DB; nunca expor no frontend |
| Regressão de testes | Baixo | Não modificar app.py existente além do registro do blueprint |

---

## 4. RECOMENDAÇÃO: MÓDULOS A CRIAR

```
axe-fleet/
├── __init__.py
├── routes.py              # Blueprint Flask: /api/axe-fleet/*
├── connector.py           # AxeOSConnector — REST + WS para device
├── registry.py            # Device registry (CRUD + persistência)
├── telemetry.py           # Coleta + cache de telemetria
├── commands.py            # Command Engine (restart, pause, config)
├── safety.py              # Safety Engine (limites, validação)
├── models.py              # Dataclasses/typed dicts (Device, Capability, Telemetry)
├── discovery.py           # Descoberta de devices na rede local
└── templates/
    └── dashboard.html     # (opcional) fragmentos HTML para injeção
```

---

## 5. PLANO DE IMPLEMENTAÇÃO (45 fases → reduzido para 7 entregas)

### Fase 1: Connector + Registry + DB (fundação)
- Criar `axe-fleet/models.py` — Device, Capability, Telemetry dataclasses
- Criar `axe-fleet/connector.py` — AxeOSConnector (fetch_info, fetch_asic, fetch_stats, capability detection)
- Criar `axe-fleet/registry.py` — CRUD de devices, SQLite persistence
- Adicionar tabelas `axe_devices` e `axe_telemetry` em `init_db()`
- Criar `axe-fleet/routes.py` — Blueprint com `/api/axe-fleet/devices` (GET), `/api/axe-fleet/devices/add` (POST)
- Registrar blueprint em `app.py`

### Fase 2: Telemetry + Polling
- Criar `axe-fleet/telemetry.py` — coleta periódica de métricas
- Adicionar `_poll_axe_fleet()` em app.py (thread separada, poll a cada 30-120s)
- Telemetry inclui: hashrate, temp, freq, voltage, power, shares, best-diff, HW errors

### Fase 3: Command Engine + Safety
- Criar `axe-fleet/commands.py` — restart, identify, pause/resume (se suportado), PATCH settings
- Criar `axe-fleet/safety.py` — validação de temperatura, frequência, voltagem
- Rotas: `POST /api/axe-fleet/devices/{id}/restart`, `POST /api/axe-fleet/devices/{id}/config`

### Fase 4: Frontend — Axe Fleet Dashboard
- Adicionar painel "AXE FLEET" no `dashboard.html`
- Cards de dispositivo com status, hashrate, temperatura, health
- Device Detail expand panel com todas as métricas
- Botões de ação (restart, identify, configure) — visíveis apenas se suportados

### Fase 5: Fleet Management + Auto-Tune
- Agrupamento de devices
- Operações em massa (restart all, pause all)
- Auto-Tune básico (gradual frequency sweep com safety limits)

### Fase 6: CYPHER AI Tools
- Adicionar tools para consultar/controlar axe fleet
- NLP para comandos naturais

### Fase 7: Testes + Segurança
- Testes unitários para connector, safety, commands
- Testes de integração
- Audit log + rate limiting

---

## 6. PRÓXIMO PASSO RECOMENDADO

Começar pela **Fase 1**: AxeOSConnector + Device Registry + DB schema + rotas Flask. Isso estabelece a fundação sem modificar o fluxo principal do CYPHER65. A implementação é puramente aditiva — nenhum código existente é alterado além do registro do blueprint em `app.py`.
