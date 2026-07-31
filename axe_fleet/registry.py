"""
CYPHER65 // AXE FLEET — Device Registry
========================================
CRUD operations for managing registered AxeOS devices.
Persistence via SQLite (reuses CYPHER65's existing get_db() pattern).

Usage:
    from axe_fleet.registry import DeviceRegistry
    registry = DeviceRegistry(get_db)
    registry.add_device("192.168.1.100", "Garage Bitaxe")
    devices = registry.list_devices()
"""
import json
import logging
import time
import uuid

from .models import new_device, infer_capabilities, STATUS_ONLINE, STATUS_OFFLINE
from .connector import AxeOSConnector, AxeOSConnectorError

log = logging.getLogger("cypher65.axe.registry")


class DeviceRegistry:
    """Manages the device registry with SQLite persistence.
    Supports multi-tenant isolation via tenant_id filtering.

    The get_db callable is injected at init time to match the CYPHER65
    pattern (app.py's get_db or a test mock).
    """

    def __init__(self, get_db_callable):
        self._get_db = get_db_callable

    # ── Schema management ─────────────────────────────────────────────

    def ensure_tables(self):
        """Create axe_fleet tables if they don't exist + run migrations."""
        conn = self._get_db()
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS axe_devices (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                model TEXT DEFAULT '',
                manufacturer TEXT DEFAULT '',
                firmware TEXT DEFAULT '',
                firmware_version TEXT DEFAULT '',
                api_version TEXT DEFAULT '',
                ip_address TEXT NOT NULL,
                hostname TEXT DEFAULT '',
                mac_address TEXT DEFAULT '',
                last_seen INTEGER DEFAULT 0,
                status TEXT DEFAULT 'OFFLINE',
                group_id TEXT DEFAULT '',
                capabilities TEXT DEFAULT '{}',
                added_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS axe_telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                device_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                FOREIGN KEY (device_id) REFERENCES axe_devices(id)
            )"""
        )
        # ── Multi-tenant migration: add tenant_id columns ──
        self._migrate_add_tenant_id(c)
        conn.commit()
        conn.close()

    def _migrate_add_tenant_id(self, c):
        """Add tenant_id column to axe_devices and axe_telemetry if missing."""
        tables = {
            "axe_devices": "TEXT DEFAULT 'default'",
            "axe_telemetry": "TEXT DEFAULT 'default'",
        }
        for table, col_def in tables.items():
            c.execute(f"PRAGMA table_info({table})")
            cols = {row[1] for row in c.fetchall()}
            if "tenant_id" not in cols:
                try:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN tenant_id {col_def}")
                    log.info("[migrate] added tenant_id to %s", table)
                except Exception as e:
                    log.warning("[migrate] could not add tenant_id to %s: %s", table, e)
        # Index for performance
        try:
            c.execute("CREATE INDEX IF NOT EXISTS idx_axe_devices_tenant ON axe_devices(tenant_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_axe_telemetry_tenant ON axe_telemetry(tenant_id)")
        except Exception:
            pass

    # ── CRUD ──────────────────────────────────────────────────────────

    def add_device(self, ip_address: str, name: str = "", tenant_id: str = "default") -> dict:
        """Register a new device by IP. Attempts to connect and auto-detect.
        Returns the device dict with detected info, or basic info if connection failed."""
        device_id = uuid.uuid4().hex[:12]
        now = int(time.time())
        device = new_device(ip_address, name)
        device["id"] = device_id
        device["added_at"] = now
        device["updated_at"] = now
        device["tenant_id"] = tenant_id

        # Try to detect capabilities by connecting
        try:
            conn = AxeOSConnector(ip_address)
            info = conn.fetch_info()
            device["model"] = str(info.get("model") or info.get("board", ""))
            device["firmware"] = str(info.get("firmware", ""))
            device["firmware_version"] = str(info.get("version", ""))
            device["hostname"] = str(info.get("hostname", ""))
            device["mac_address"] = str(info.get("mac", ""))
            device["last_seen"] = int(time.time())
            device["status"] = STATUS_ONLINE
            device["capabilities"] = conn.detect_capabilities()
        except AxeOSConnectorError:
            device["status"] = STATUS_OFFLINE
            device["capabilities"] = {}

        self._persist_device(device)
        return device

    def remove_device(self, device_id: str, tenant_id: str = "default") -> bool:
        """Remove a device from the registry. Returns True if removed.
        Only removes if the device belongs to the given tenant."""
        conn = self._get_db()
        c = conn.cursor()
        c.execute("DELETE FROM axe_devices WHERE id=? AND tenant_id=?", (device_id, tenant_id))
        deleted = c.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def list_devices(self, tenant_id: str = "") -> list:
        """Return all registered devices, optionally filtered by tenant.
        If tenant_id is empty, returns all devices (admin)."""
        conn = self._get_db()
        c = conn.cursor()
        if tenant_id:
            c.execute("SELECT * FROM axe_devices WHERE tenant_id=? ORDER BY name", (tenant_id,))
        else:
            c.execute("SELECT * FROM axe_devices ORDER BY name")
        rows = c.fetchall()
        conn.close()
        return [self._row_to_device(r) for r in rows]

    def get_device(self, device_id: str, tenant_id: str = "") -> dict:
        """Get a single device by ID, scoped to tenant if provided."""
        conn = self._get_db()
        c = conn.cursor()
        if tenant_id:
            c.execute("SELECT * FROM axe_devices WHERE id=? AND tenant_id=?", (device_id, tenant_id))
        else:
            c.execute("SELECT * FROM axe_devices WHERE id=?", (device_id,))
        r = c.fetchone()
        conn.close()
        return self._row_to_device(r) if r else {}

    def get_device_by_ip(self, ip_address: str, tenant_id: str = "") -> dict:
        """Get a device by IP address, scoped to tenant if provided."""
        conn = self._get_db()
        c = conn.cursor()
        if tenant_id:
            c.execute("SELECT * FROM axe_devices WHERE ip_address=? AND tenant_id=?", (ip_address, tenant_id))
        else:
            c.execute("SELECT * FROM axe_devices WHERE ip_address=?", (ip_address,))
        r = c.fetchone()
        conn.close()
        return self._row_to_device(r) if r else {}

    def update_device(self, device_id: str, updates: dict, tenant_id: str = "") -> bool:
        """Update device fields. Keys in 'updates' overwrite stored values.
        Returns True if device exists and was updated.
        If tenant_id is provided, only updates devices belonging to that tenant."""
        fields = ["name", "model", "ip_address", "hostname", "group_id", "status"]
        set_parts = []
        vals = []
        for k, v in updates.items():
            if k in fields:
                set_parts.append(f"{k}=?")
                vals.append(v)
        if not set_parts:
            return False

        if "capabilities" in updates:
            set_parts.append("capabilities=?")
            vals.append(json.dumps(updates["capabilities"]))

        sql = f"UPDATE axe_devices SET {', '.join(set_parts)}, updated_at=? WHERE id=?"
        vals.append(int(time.time()))
        vals.append(device_id)
        if tenant_id:
            sql += " AND tenant_id=?"
            vals.append(tenant_id)

        conn = self._get_db()
        c = conn.cursor()
        c.execute(sql, tuple(vals))
        updated = c.rowcount > 0
        conn.commit()
        conn.close()
        return updated

    # ── Telemetry persistence (tenant-aware) ──────────────────────────

    def save_telemetry(self, device_id: str, telemetry: dict, tenant_id: str = "default"):
        """Persist a telemetry snapshot for a device owned by the given tenant."""
        conn = self._get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO axe_telemetry (ts, device_id, payload, tenant_id) VALUES (?, ?, ?, ?)",
            (telemetry.get("ts", int(time.time())), device_id, json.dumps(telemetry), tenant_id),
        )
        conn.commit()
        conn.close()

    def get_recent_telemetry(self, device_id: str, limit: int = 120, tenant_id: str = "") -> list:
        """Get recent telemetry entries for a device, scoped to tenant."""
        conn = self._get_db()
        c = conn.cursor()
        if tenant_id:
            c.execute(
                "SELECT * FROM axe_telemetry WHERE device_id=? AND tenant_id=? ORDER BY ts DESC LIMIT ?",
                (device_id, tenant_id, limit),
            )
        else:
            c.execute(
                "SELECT * FROM axe_telemetry WHERE device_id=? ORDER BY ts DESC LIMIT ?",
                (device_id, limit),
            )
        rows = c.fetchall()
        conn.close()
        result = []
        for r in rows:
            entry = {"id": r["id"], "ts": r["ts"], "device_id": r["device_id"]}
            try:
                entry["payload"] = json.loads(r["payload"])
            except (json.JSONDecodeError, TypeError):
                entry["payload"] = {}
            result.append(entry)
        return result

    def get_telemetry_chart_data(self, device_id: str, limit: int = 120, tenant_id: str = "") -> dict:
        """Get chart-ready telemetry series for a device.
        Returns dict with arrays: ts, hashrate_hs, temperature, fan_rpm,
        power_watts, efficiency_jth, shares_accepted, shares_rejected."""
        raw = self.get_recent_telemetry(device_id, limit=limit, tenant_id=tenant_id)
        raw.reverse()  # chronological order
        series = {"ts": [], "hashrate_hs": [], "temperature": [], "fan_rpm": [],
                  "power_watts": [], "efficiency_jth": [], "shares_accepted": [],
                  "shares_rejected": [], "hw_error_pct": [], "voltage_mv": [],
                  "frequency_mhz": []}
        for entry in raw:
            p = entry["payload"]
            series["ts"].append(entry["ts"])
            series["hashrate_hs"].append(p.get("hashrate_hs", 0))
            series["temperature"].append(p.get("temperature"))
            series["fan_rpm"].append(p.get("fan_rpm"))
            series["power_watts"].append(p.get("power_watts"))
            series["efficiency_jth"].append(p.get("efficiency_jth"))
            series["shares_accepted"].append(p.get("shares_accepted", 0))
            series["shares_rejected"].append(p.get("shares_rejected", 0))
            series["hw_error_pct"].append(p.get("hw_error_pct", 0))
            series["voltage_mv"].append(p.get("voltage_mv"))
            series["frequency_mhz"].append(p.get("frequency_mhz"))
        return series

    # ── Polling support ───────────────────────────────────────────────

    def poll_device(self, device_id: str, tenant_id: str = "default") -> dict:
        """Poll a single device: fetch telemetry, update status, persist.
        Returns the telemetry dict (or empty dict on failure)."""
        device = self.get_device(device_id, tenant_id=tenant_id)
        if not device:
            return {}

        try:
            conn_ax = AxeOSConnector(device["ip_address"])
            telemetry = conn_ax.extract_telemetry()
            telemetry["device_id"] = device_id

            now = int(time.time())
            self.update_device(device_id, {
                "last_seen": now,
                "status": STATUS_ONLINE if telemetry.get("hashrate_hs", 0) > 0
                          else "IDLE",
            }, tenant_id=tenant_id)

            self.save_telemetry(device_id, telemetry, tenant_id=tenant_id)
            return telemetry

        except AxeOSConnectorError:
            self.update_device(device_id, {"last_seen": int(time.time()), "status": STATUS_OFFLINE},
                              tenant_id=tenant_id)
            return {"device_id": device_id, "ts": int(time.time()), "error": "device unreachable"}

    # ── Internals ─────────────────────────────────────────────────────

    def _persist_device(self, device: dict):
        """Insert or replace a device record."""
        conn = self._get_db()
        c = conn.cursor()
        c.execute(
            """INSERT OR REPLACE INTO axe_devices
            (id, name, model, manufacturer, firmware, firmware_version,
             api_version, ip_address, hostname, mac_address,
             last_seen, status, group_id, capabilities, added_at, updated_at, tenant_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                device.get("id", ""),
                device.get("name", ""),
                device.get("model", ""),
                device.get("manufacturer", ""),
                device.get("firmware", ""),
                device.get("firmware_version", ""),
                device.get("api_version", ""),
                device.get("ip_address", ""),
                device.get("hostname", ""),
                device.get("mac_address", ""),
                device.get("last_seen", 0),
                device.get("status", STATUS_OFFLINE),
                device.get("group_id", ""),
                json.dumps(device.get("capabilities", {})),
                device.get("added_at", int(time.time())),
                int(time.time()),
                device.get("tenant_id", "default"),
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def _row_to_device(row) -> dict:
        """Convert a SQLite Row to a device dict."""
        d = dict(row)
        caps_raw = d.get("capabilities", "{}")
        if isinstance(caps_raw, str):
            try:
                d["capabilities"] = json.loads(caps_raw)
            except (json.JSONDecodeError, TypeError):
                d["capabilities"] = {}
        return d
