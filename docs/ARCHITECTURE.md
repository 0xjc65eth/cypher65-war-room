# CYPHER65 — ARCHITECTURE (MILESTONE 1)

**Version:** 1.0  
**Status:** Foundation  
**Date:** 2026-07-27  
**Gatekeeper:** Approved for implementation

---

## 1. PRINCIPLES

- **Modularidade real** — Nada de arquivo único de 108k linhas.
- **Separação clara** entre Core, Adapters, Services e UI.
- **Device como cidadão de primeira classe**.
- **Capability-driven** — A UI e a IA só podem usar o que o device realmente suporta.
- **Safety-first** — Toda ação passa por Safety Engine.
- **Auditabilidade** — Todo comando e mudança de estado é registrado.
- **Extensibilidade** — Novos adapters podem ser adicionados sem tocar no core.

---

## 2. MACRO ARCHITECTURE

```
CYPHER65
│
├── core/                      ← Foundation (imutável na maior parte)
│   ├── models/                ← Device, Capability, Telemetry, Command
│   ├── registry/              ← DeviceRegistry (fonte única de verdade)
│   ├── adapters/              ← BaseAdapter + implementações concretas
│   └── safety/                ← SafetyEngine
│
├── services/                  ← Lógica de negócio (já existe parcialmente)
│   ├── polling.py
│   ├── state.py
│   ├── proximity.py
│   └── ...
│
├── adapters/                  ← Implementações concretas de devices
│   ├── bitaxe_adapter.py
│   ├── nerdqaxe_adapter.py
│   ├── braiins_adapter.py
│   └── ...
│
├── routes/                    ← Flask blueprints (refatorar)
├── agents/                    ← AI tools
├── static/ + templates/       ← Frontend atual (será evoluído)
│
└── app.py                     ← Apenas orquestração (deve encolher)
```

---

## 3. DEVICE LAYER (Core)

### 3.1 Device Model

Todo device no sistema é representado por uma instância de `Device`.

Campos obrigatórios:
- `id` (uuid)
- `name`
- `model` (Bitaxe, NerdQaxe, NerdQaxe+, etc.)
- `firmware`
- `ip` / `hostname`
- `status` (online, offline, warning, critical)
- `capabilities` (lista de Capability)
- `last_seen`
- `metadata` (json)

### 3.2 Capability System

Cada device declara o que ele suporta:

```python
class Capability:
    name: str
    supported: bool
    requires_confirmation: bool
    risk_level: RiskLevel
```

Exemplos de capabilities:
- `telemetry`
- `restart`
- `set_frequency`
- `set_voltage`
- `change_pool`
- `firmware_update`
- `identify`

### 3.3 Adapter Pattern

```
BaseAdapter (interface)
    ├── get_telemetry()
    ├── execute_command(cmd)
    ├── get_capabilities()
    ├── health_check()
    └── ...
```

Cada família de minerador terá seu próprio adapter.

---

## 4. REGISTRY

`DeviceRegistry` é a única fonte de verdade para devices.

Responsabilidades:
- Adicionar / remover devices
- Persistir em SQLite
- Manter estado em memória
- Notificar listeners quando device muda de estado
- Fornecer queries (por status, model, site, etc.)

---

## 5. SAFETY ENGINE

Toda ação que modifica o device deve passar por:

```python
SafetyEngine.validate(device, command) → (allowed, reason)
```

Regras configuráveis:
- Temperatura máxima
- Taxa de rejeição máxima
- Frequência / voltagem máxima
- Cooldown entre restarts
- Rate limit de comandos

Se violado → `COMMAND_BLOCKED` ou `CONFIRMATION_REQUIRED`

---

## 6. FLUXO DE COMANDO (futuro)

```
User / AI → Intent
    → Command Engine
        → Capability Check
        → Safety Engine
            → Confirmation (se necessário)
                → Execute via Adapter
                    → Audit Log
```

---

## 7. PRÓXIMOS PASSOS (MILESTONE 1)

1. Definir `core/models/device.py`
2. Definir `core/models/capability.py`
3. Implementar `core/registry/device_registry.py`
4. Criar `core/adapters/base_adapter.py`
5. Criar esqueleto do `core/safety/safety_engine.py`
6. Migrar dados existentes do `app.py` para o novo registry (gradualmente)

---

**Gatekeeper Note:**  
Esta arquitetura foi projetada para eliminar o problema do arquivo gigante e permitir evolução segura do sistema. Qualquer desvio desta estrutura deve ser justificado e aprovado.