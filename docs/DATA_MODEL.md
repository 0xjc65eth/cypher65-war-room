# CYPHER65 — DATA MODEL (MILESTONE 1)

**Version:** 1.1
**Status:** Foundation
**Date:** 2026-08-23

---

## 1. DEVICE

```python
@dataclass
class Device:
    id: str                          # UUID
    name: str
    model: str                       # Bitaxe, NerdQaxe, NerdQaxe+, etc.
    firmware: str
    ip: Optional[str]
    hostname: Optional[str]
    mac: Optional[str]
    status: DeviceStatus             # online | offline | warning | critical
    capabilities: List[Capability]
    last_seen: datetime
    created_at: datetime
    updated_at: datetime
    metadata: Dict[str, Any]         # site, rack, room, tags, notes, etc.
    current_telemetry: Optional[Telemetry]
```

---

## 2. CAPABILITY

```python
@dataclass
class Capability:
    name: str
    supported: bool
    requires_confirmation: bool = False
    risk_level: RiskLevel = RiskLevel.LOW
    constraints: Dict[str, Any] = field(default_factory=dict)
```

**RiskLevel:** `LOW | MEDIUM | HIGH | CRITICAL`

---

## 3. TELEMETRY

```python
@dataclass
class Telemetry:
    timestamp: datetime
    hashrate: float
    hashrate_5m: Optional[float]
    temperature: float
    fan_speed: Optional[int]
    power: Optional[float]
    voltage: Optional[float]
    frequency: Optional[int]
    accepted_shares: int
    rejected_shares: int
    stale_shares: int
    hw_errors: int
    best_difficulty: Optional[int]
    uptime: Optional[int]
    pool: Optional[str]
    worker: Optional[str]
    source: str                      # "adapter", "polling", "manual"
    freshness: float                 # seconds since last update
```

---

## 4. COMMAND

```python
@dataclass
class Command:
    id: str
    device_id: str
    command_type: CommandType
    parameters: Dict[str, Any]
    requested_by: str                # user_id or "ai" or "automation"
    requested_at: datetime
    status: CommandStatus            # pending | approved | executing | completed | failed | blocked
    result: Optional[Dict[str, Any]]
    safety_check: Optional[SafetyResult]
    audit_id: Optional[str]
```

---

## 5. SAFETY RESULT

```python
@dataclass
class SafetyResult:
    allowed: bool
    reason: Optional[str]
    risk_level: RiskLevel
    requires_confirmation: bool
    violations: List[str]
```

---

## 6. AUDIT LOG

```python
@dataclass
class AuditLog:
    id: str
    timestamp: datetime
    actor: str
    action: str
    device_id: Optional[str]
    command_id: Optional[str]
    before: Optional[Dict]
    after: Optional[Dict]
    result: str
    ip: Optional[str]
```

---

## 7. DEVICE STATUS

```python
class DeviceStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    WARNING = "warning"
    CRITICAL = "critical"
    MAINTENANCE = "maintenance"
```

---

## 8. PERSISTENCE

- Dispositivos e telemetria histórica → SQLite (`data/war_room.sqlite`)
- Telemetria em tempo real → memória (DeviceRegistry) + flush periódico
- Audit logs → tabela dedicada `audit_logs`
- Schema versionado via `schema_version` (`app.py`) — evolução aditiva com
  `CREATE TABLE IF NOT EXISTS` + migrações explícitas

---

## 9. LEDGERS & PAYMENTS (SQLite)

Tabelas reais de receita e auditoria adicionadas nas fases de monetização
(Issues #248/#249) — a versão 1.0 deste documento cobria só o modelo de domínio:

### `donations` — cypherpunk support (BTC / Lightning / hashrate)
`id` · `ts` · `method` (`lightning` \| `btc` \| `hashpower`) · `amount_sat` ·
`txid` · `preimage` · `note` · `source` (`webln` \| `onchain` \| `manual`)

### `pro_licenses` — chaves PRO/PREMIUM emitidas (`services/licensing.py`)
`key` (PK) · `plan` (default `pro`) · `email` · `source` (`manual` default,
`lemon_squeezy` \| `btcpay` \| `webln`) · `created_at` · `expires_at` · `revoked_at`

### `btcpay_invoice_plans` — checkout BTC → plano (`services/btcpay.py`)
`invoice_id` (PK) · `plan` · `created_ts`

### `processed_invoices` — webhooks BTCPay idempotentes (`services/btcpay.py`)
`invoice_id` (PK) · `event` (default `invoice_settled`) · `license_key` · `processed_ts`

### `conversion_events` — funil paywall→paid (`services/conversion.py`)
`id` · `ts` · `event` · `tenant_id` · `meta` (JSON) · `created_at`

### `subscription_events` — assinaturas (`services/conversion.py`)
`id` · `subscription_id` · `event` · `ts` · `renews_at` · `created_at` ·
`created_at_ts` · `UNIQUE(subscription_id, event, renews_at)`

### `audit_logs` — auditoria operacional (`app.py`)
`id` · `ts` · `tenant_id` · `user_id` · `action` · `target` · `details` (JSON) ·
índice `(tenant_id, ts)`

---

**Gatekeeper Note:**  
Este modelo é a base para todo o sistema. Mudanças devem ser feitas via migração controlada.