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

    The get_db callable is injected at init time to match the CYPHER65
    pattern (app.py's get_db or a test mock).
    """

    def __init__(self, get_db_callable):
        self._get_db = get_db_callable

    # ── Schema management ─────────────────────────────────────────────

    def ensure_tables(self):
        """Create axe_fleet tables if they don't exist.
        Called once at startup from init_db()."""
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
        conn.commit()
        conn.close()

    # ── CRUD ──────────────────────────────────────────────────────────

    def add_device(self, ip_address: str, name: str = "") -> dict:
        """Register a new device by IP. Attempts to connect and auto-detect.
        Returns the device dict with detected info, or basic info if connection failed."""
        device_id = uuid.uuid4().hex[:12]
        now = int(time.time())
        device = new_device(ip_address, name)
        device["id"] = device_id
        device["added_at"] = now
        device["updated_at"] = now

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

    def remove_device(self, device_id: str) -> bool:
        """Remove a device from the registry. Returns True if removed."""
        conn = self._get_db()
        c = conn.cursor()
        c.execute("DELETE FROM axe_devices WHERE id=?", (device_id,))
        deleted = c.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def list_devices(self) -> list:
        """Return all registered devices."""
        conn = self._get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM axe_devices ORDER BY name")
        rows = c.fetchall()
        conn.close()
        return [self._row_to_device(r) for r in rows]

    def get_device(self, device_id: str) -> dict:
        """Get a single device by ID."""
        conn = self._get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM axe_devices WHERE id=?", (device_id,))
        r = c.fetchone()
        conn.close()
        return self._row_to_device(r) if r else {}

    def get_device_by_ip(self, ip_address: str) -> dict:
        """Get a device by IP address."""
        conn = self._get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM axe_devices WHERE ip_address=?", (ip_address,))
        r = c.fetchone()
        conn.close()
        return self._row_to_device(r) if r else {}

    def update_device(self, device_id: str, updates: dict) -> bool:
        """Update device fields. Keys in 'updates' overwrite stored values.
        Returns True if device exists and was updated."""
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

        vals.append(device_id)
        sql = f"UPDATE axe_devices SET {', '.join(set_parts)}, updated_at=? WHERE id=?"
        vals.append(int(time.time()))
        vals.append(device_id)

        conn = self._get_db()
        c = conn.cursor()
        c.execute(sql, tuple(vals))
        updated = c.rowcount > 0
        conn.commit()
        conn.close()
        return updated

    # ── Telemetry persistence ─────────────────────────────────────────

    def save_telemetry(self, device_id: str, telemetry: dict):
        """Persist a telemetry snapshot."""
        conn = self._get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO axe_telemetry (ts, device_id, payload) VALUES (?, ?, ?)",
            (telemetry.get("ts", int(time.time())), device_id, json.dumps(telemetry)),
        )
        conn.commit()
        conn.close()

    def get_recent_telemetry(self, device_id: str, limit: int = 120) -> list:
        """Get recent telemetry entries for a device."""
        conn = self._get_db()
        c = conn.cursor()
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

    # ── Polling support ───────────────────────────────────────────────

    def poll_device(self, device_id: str) -> dict:
        """Poll a single device: fetch telemetry, update status, persist.
        Returns the telemetry dict (or empty dict on failure)."""
        device = self.get_device(device_id)
        if not device:
            return {}

        try:
            conn_ax = AxeOSConnector(device["ip_address"])
            telemetry = conn_ax.extract_telemetry()
            telemetry["device_id"] = device_id

            # Update device status
            now = int(time.time())
            self.update_device(device_id, {
                "last_seen": now,
                "status": STATUS_ONLINE if telemetry.get("hashrate_hs", 0) > 0
                          else "IDLE",
            })

            # Persist telemetry
            self.save_telemetry(device_id, telemetry)
            return telemetry

        except AxeOSConnectorError:
            self.update_device(device_id, {"last_seen": int(time.time()), "status": STATUS_OFFLINE})
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
             last_seen, status, group_id, capabilities, added_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def _row_to_device(row) -> dict:
        """Convert a SQLite Row to a device dict."""
        d = dict(row)
        # Parse capabilities JSON
        caps_raw = d.get("capabilities", "{}")
        if isinstance(caps_raw, str):
            try:
                d["capabilities"] = json.loads(caps_raw)
            except (json.JSONDecodeError, TypeError):
                d["capabilities"] = {}
        return d
