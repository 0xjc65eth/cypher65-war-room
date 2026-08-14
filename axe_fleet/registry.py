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

from .models import (
    new_device, infer_capabilities, STATUS_ONLINE, STATUS_OFFLINE,
    derive_device_status,
)
from .connector import AxeOSConnector, AxeOSConnectorError

log = logging.getLogger("cypher65.axe.registry")


def _caps_for_type(info: dict) -> dict:
    """Capabilities derived from the agent's discovery info (type + firmware).

    Single source of truth for agent-managed device capabilities, used by
    both the create and update branches of upsert_agent_device so a device
    whose type is only learned on a LATER register still gets honest caps
    (cgminer must never advertise an identify button it cannot execute).

    - bitaxe/AxeOS: restart+identify+pause+resume over HTTP :80 (ESP-Miner
      /api/system/miningPause|miningResume), configure for AxeOS.
    - cgminer-family: restart over JSON-over-TCP :4028, NO identify/pause/
      resume (the cgminer API has no such commands).
    - type unknown (telemetry-only re-upsert): conservative — restart yes,
      identify only if the firmware looks like AxeOS."""
    dev_type = str(info.get("type") or "").lower()
    is_cgminer = dev_type == "cgminer"
    is_axeos = bool(info.get("firmware")) and "axe" in str(info.get("firmware", "")).lower()
    return {
        "telemetry": True,
        "restart": True,
        "identify": not is_cgminer,
        "pause": is_axeos and not is_cgminer,
        "resume": is_axeos and not is_cgminer,
        "configure": is_axeos,
    }


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
        # ── Agent-managed migration: devices polled by the user's LOCAL
        #    agent (SaaS: cloud dashboard can't reach the home LAN) must be
        #    marked so the server-side poll never touches them. ──
        self._migrate_add_agent_managed(c)
        # ── Tombstone migration: soft-delete marker so a removed device
        #    can't be re-created by the agent's next push (zombie fix). ──
        self._migrate_add_removed_at(c)
        # ── Agent command queue (restart/identify routed through the agent) ──
        c.execute(
            """CREATE TABLE IF NOT EXISTS axe_agent_commands (
                id TEXT PRIMARY KEY,
                tenant_id TEXT DEFAULT 'default',
                device_id TEXT NOT NULL,
                command TEXT NOT NULL,
                params TEXT DEFAULT '{}',
                status TEXT DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                pulled_at INTEGER DEFAULT 0,
                acked_at INTEGER DEFAULT 0,
                result TEXT DEFAULT ''
            )"""
        )
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

    def _migrate_add_agent_managed(self, c):
        """Add agent_managed column to axe_devices if missing (SaaS agent
        model: 1 = polled by the user's local agent, never by this server)."""
        c.execute("PRAGMA table_info(axe_devices)")
        cols = {row[1] for row in c.fetchall()}
        if "agent_managed" not in cols:
            try:
                c.execute("ALTER TABLE axe_devices ADD COLUMN agent_managed INTEGER DEFAULT 0")
                log.info("[migrate] added agent_managed to axe_devices")
            except Exception as e:
                log.warning("[migrate] could not add agent_managed: %s", e)

    def _migrate_add_removed_at(self, c):
        """Add removed_at (tombstone) column to axe_devices if missing.

        Soft-delete marker: when the operator removes a device, the row is
        NOT physically deleted — removed_at is stamped so the agent's next
        telemetry push / register can't silently re-create a device the
        operator explicitly removed (the "zombie" reappearing card). All
        reads filter tombstoned rows out."""
        c.execute("PRAGMA table_info(axe_devices)")
        cols = {row[1] for row in c.fetchall()}
        if "removed_at" not in cols:
            try:
                c.execute("ALTER TABLE axe_devices ADD COLUMN removed_at INTEGER DEFAULT 0")
                log.info("[migrate] added removed_at to axe_devices")
            except Exception as e:
                log.warning("[migrate] could not add removed_at: %s", e)

    # ── CRUD ──────────────────────────────────────────────────────────

    def add_device(self, ip_address: str, name: str = "", tenant_id: str = "default") -> dict:
        """Register a new device by IP. Attempts to connect and auto-detect.
        Returns the device dict with detected info, or basic info if connection failed.

        Manual operator add UN-TOMBSTONES the IP: the operator explicitly
        re-adding a device they previously removed must get a fresh active
        row (the agent path refuses tombstones, the manual path clears them)."""
        # Revive: purge any tombstoned row for this IP+tenant so the manual
        # add is authoritative (a removed device the operator explicitly
        # wants back must not stay blocked by the agent-side tombstone).
        conn = self._get_db()
        c = conn.cursor()
        if tenant_id:
            c.execute(
                "DELETE FROM axe_devices WHERE ip_address=? AND tenant_id=? AND COALESCE(removed_at,0)>0",
                (ip_address, tenant_id),
            )
        else:
            c.execute(
                "DELETE FROM axe_devices WHERE ip_address=? AND COALESCE(removed_at,0)>0",
                (ip_address,),
            )
        conn.commit()
        conn.close()
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

    def remove_device(self, device_id: str, tenant_id: str = "default",
                      hard: bool = False) -> bool:
        """Remove a device from the registry. Returns True if removed.
        Only removes if the device belongs to the given tenant.

        SOFT DELETE (tombstone) by default: the row stays with removed_at
        stamped so the agent's next telemetry push / register can't re-create
        a device the operator explicitly removed (zombie fix). All reads
        filter tombstoned rows out.

        hard=True physically deletes the row (used by the seed/test purges,
        which must not accumulate tombstones)."""
        conn = self._get_db()
        c = conn.cursor()
        if hard:
            c.execute("DELETE FROM axe_devices WHERE id=? AND tenant_id=?",
                      (device_id, tenant_id))
        else:
            c.execute(
                "UPDATE axe_devices SET removed_at=?, status='OFFLINE' "
                "WHERE id=? AND tenant_id=? AND COALESCE(removed_at,0)=0",
                (int(time.time()), device_id, tenant_id),
            )
        deleted = c.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def gc_tombstones(self, max_age_days: int = 30) -> int:
        """Physically purge tombstoned rows older than max_age_days (and
        their telemetry) so soft-deleted devices don't grow the DB forever.
        Returns the number of tombstoned rows removed. Never raises."""
        cutoff = int(time.time()) - max_age_days * 86400
        removed = 0
        try:
            conn = self._get_db()
            c = conn.cursor()
            c.execute("SELECT id FROM axe_devices WHERE COALESCE(removed_at,0)>0 AND removed_at<?",
                      (cutoff,))
            ids = [r["id"] for r in c.fetchall()]
            if ids:
                placeholders = ",".join("?" * len(ids))
                # placeholders are generated ?-markers only — no user input.
                c.execute(f"DELETE FROM axe_telemetry WHERE device_id IN ({placeholders})", ids)  # nosec B608
                c.execute(f"DELETE FROM axe_devices WHERE id IN ({placeholders})", ids)  # nosec B608
                removed = len(ids)
                conn.commit()
                if removed:
                    log.info("[gc] purged %d old tombstoned devices", removed)
            conn.close()
        except Exception as e:
            log.warning("[gc] tombstone gc failed: %s", e)
        return removed

    def _tombstone_query(self):
        """SQL fragment excluding soft-deleted (tombstoned) rows."""
        return "COALESCE(removed_at,0)=0"

    def get_removed_by_ip(self, ip_address: str, tenant_id: str = "") -> dict:
        """Return the tombstoned (removed) row for an IP, or {}.
        Used to REFUSE re-registration of a device the operator removed —
        the agent must not resurrect it on the next scan/telemetry."""
        conn = self._get_db()
        c = conn.cursor()
        if tenant_id:
            c.execute(
                "SELECT * FROM axe_devices WHERE ip_address=? AND tenant_id=? AND COALESCE(removed_at,0)>0",
                (ip_address, tenant_id),
            )
        else:
            c.execute(
                "SELECT * FROM axe_devices WHERE ip_address=? AND COALESCE(removed_at,0)>0",
                (ip_address,),
            )
        r = c.fetchone()
        conn.close()
        return self._row_to_device(r) if r else {}

    def list_devices(self, tenant_id: str = "", with_telemetry: bool = False) -> list:
        """Return all registered devices, optionally filtered by tenant.
        If tenant_id is empty, returns all devices (admin). Tombstoned
        (removed) rows are never returned.

        with_telemetry=True joins each device's latest TRUSTED telemetry
        (one pass, no N+1) so list views carry live hashrate — previously
        the list endpoint returned devices with hashrate_hs=None even after
        the agent pushed rich telemetry."""
        conn = self._get_db()
        c = conn.cursor()
        if tenant_id:
            # _tombstone_query() is an internal fixed expression — no user input.
            c.execute(f"SELECT * FROM axe_devices WHERE tenant_id=? AND {self._tombstone_query()} ORDER BY name", (tenant_id,))  # nosec B608
        else:
            c.execute(f"SELECT * FROM axe_devices WHERE {self._tombstone_query()} ORDER BY name")  # nosec B608
        rows = c.fetchall()
        conn.close()
        devices = [self._row_to_device(r) for r in rows]
        if with_telemetry:
            latest = self._latest_telemetry_by_device(tenant_id)
            for d in devices:
                tel = latest.get(d["id"])
                if tel:
                    d["telemetry"] = tel
                    d["hashrate_hs"] = tel.get("hashrate_hs")
        return devices

    def _latest_telemetry_by_device(self, tenant_id: str = "") -> dict:
        """Latest TRUSTED telemetry payload per device in a single query.
        Only payloads carrying hashrate_hs count as trusted (mirrors the
        route layer's _is_trusted_payload); heartbeat-only {} pushes never
        replace the last real reading."""
        conn = self._get_db()
        c = conn.cursor()
        if tenant_id:
            c.execute(
                "SELECT device_id, payload FROM axe_telemetry WHERE tenant_id=? ORDER BY ts DESC",
                (tenant_id,),
            )
        else:
            c.execute("SELECT device_id, payload FROM axe_telemetry ORDER BY ts DESC")
        rows = c.fetchall()
        conn.close()
        latest = {}
        for r in rows:
            did = r["device_id"]
            if did in latest:
                continue
            try:
                payload = json.loads(r["payload"])
            except (json.JSONDecodeError, TypeError):
                payload = {}
            if isinstance(payload, dict) and payload.get("hashrate_hs") is not None:
                latest[did] = payload
        return latest

    def get_device(self, device_id: str, tenant_id: str = "") -> dict:
        """Get a single device by ID, scoped to tenant if provided.
        Tombstoned rows are never returned."""
        conn = self._get_db()
        c = conn.cursor()
        if tenant_id:
            # internal fixed _tombstone_query() expression — no user input.
            c.execute(f"SELECT * FROM axe_devices WHERE id=? AND tenant_id=? AND {self._tombstone_query()}", (device_id, tenant_id))  # nosec B608
        else:
            c.execute(f"SELECT * FROM axe_devices WHERE id=? AND {self._tombstone_query()}", (device_id,))  # nosec B608
        r = c.fetchone()
        conn.close()
        return self._row_to_device(r) if r else {}

    def get_device_by_ip(self, ip_address: str, tenant_id: str = "") -> dict:
        """Get a device by IP address, scoped to tenant if provided.
        Tombstoned rows are never returned."""
        conn = self._get_db()
        c = conn.cursor()
        if tenant_id:
            # internal fixed _tombstone_query() expression — no user input.
            c.execute(f"SELECT * FROM axe_devices WHERE ip_address=? AND tenant_id=? AND {self._tombstone_query()}", (ip_address, tenant_id))  # nosec B608
        else:
            c.execute(f"SELECT * FROM axe_devices WHERE ip_address=? AND {self._tombstone_query()}", (ip_address,))  # nosec B608
        r = c.fetchone()
        conn.close()
        return self._row_to_device(r) if r else {}

    def upsert_agent_device(self, ip_address: str, name: str = "",
                            tenant_id: str = "default", info: dict = None) -> dict:
        """Register (or refresh) a device reported by the user's LOCAL agent.

        SaaS model: the cloud dashboard cannot reach the home LAN, so devices
        arrive here from the agent instead of a server-side probe. Upserts by
        (ip_address, tenant_id) WITHOUT connecting to the miner; telemetry
        arrives separately via save_agent_telemetry. Marks agent_managed=1 so
        the server-side poll never touches it. Returns the device dict.

        REFUSES tombstoned IPs: a device the operator removed must not be
        resurrected by the agent — returns {} so callers treat it as blocked.
        """
        info = info or {}
        now = int(time.time())
        # Zombie fix: operator removed this IP → agent re-scan must NOT bring
        # it back. The tombstone is checked BEFORE the upsert so both the
        # register and telemetry paths refuse it.
        if self.get_removed_by_ip(ip_address, tenant_id=tenant_id):
            log.info("[agent] refusing upsert of removed device %s (tombstoned)", ip_address)
            return {}
        existing = self.get_device_by_ip(ip_address, tenant_id=tenant_id)
        if existing:
            updates = {
                "model": str(info.get("model") or existing.get("model", "")),
                "firmware": str(info.get("firmware") or existing.get("firmware", "")),
                "firmware_version": str(info.get("version") or existing.get("firmware_version", "")),
                "hostname": str(info.get("hostname") or existing.get("hostname", "")),
                "agent_managed": 1,
                "last_seen": now,
            }
            # Recompute capabilities whenever the agent reports a type or
            # firmware — a device first seen via telemetry-only upsert (no
            # type) must still get honest caps once register carries it.
            if info.get("type") or info.get("firmware"):
                updates["capabilities"] = _caps_for_type(info)
            if name:
                updates["name"] = name
            self.update_device(existing["id"], updates, tenant_id=tenant_id)
            return self.get_device(existing["id"], tenant_id=tenant_id)

        device_id = uuid.uuid4().hex[:12]
        caps = _caps_for_type(info)
        device = {
            "id": device_id,
            "name": name or str(info.get("hostname") or info.get("model") or ip_address),
            "model": str(info.get("model") or ""),
            "manufacturer": str(info.get("manufacturer") or ""),
            "firmware": str(info.get("firmware") or ""),
            "firmware_version": str(info.get("version") or ""),
            "api_version": "",
            "ip_address": ip_address,
            "hostname": str(info.get("hostname") or ""),
            "mac_address": str(info.get("mac") or ""),
            "last_seen": now,
            "status": STATUS_OFFLINE,  # telemetry decides ONLINE/IDLE
            "group_id": "",
            "capabilities": caps,
            "added_at": now,
            "updated_at": now,
            "tenant_id": tenant_id,
            "agent_managed": 1,
        }
        self._persist_device(device)
        return device

    def save_agent_telemetry(self, device_id: str, telemetry: dict,
                             tenant_id: str = "default") -> None:
        """Persist telemetry pushed by the user's local agent and update the
        device status (ONLINE when hashrate > 0, IDLE otherwise)."""
        now = int(time.time())
        payload = dict(telemetry or {})
        payload["ts"] = payload.get("ts") or now
        payload["device_id"] = device_id
        self.save_telemetry(device_id, payload, tenant_id=tenant_id)
        self.update_device(device_id, {
            "last_seen": now,
            "status": derive_device_status(payload),
            "agent_managed": 1,
        }, tenant_id=tenant_id)

    def update_device(self, device_id: str, updates: dict, tenant_id: str = "") -> bool:
        """Update device fields. Keys in 'updates' overwrite stored values.
        Returns True if device exists and was updated.
        If tenant_id is provided, only updates devices belonging to that tenant."""
        fields = ["name", "model", "ip_address", "hostname", "group_id", "status",
                  "last_seen", "agent_managed", "firmware", "firmware_version",
                  "manufacturer", "mac_address", "api_version"]
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

        # set_parts is built from the fixed allowlist of update fields.
        sql = f"UPDATE axe_devices SET {', '.join(set_parts)}, updated_at=? WHERE id=?"  # nosec B608
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
            # Trust only well-formed telemetry (must contain hashrate_hs) —
            # legacy broken stubs would otherwise render as a 0-H/s point.
            if not (isinstance(p, dict) and "hashrate_hs" in p):
                continue
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
            if not telemetry:
                # extract_telemetry() swallows the connector error internally and
                # returns {} — treat that as unreachable. Never persist or cache
                # a broken {"device_id": ...} stub, which zeroed the whole fleet.
                raise AxeOSConnectorError("empty telemetry (device unreachable)")

            telemetry["device_id"] = device_id

            now = int(time.time())
            self.update_device(device_id, {
                "last_seen": now,
                "status": derive_device_status(telemetry),
            }, tenant_id=tenant_id)

            self.save_telemetry(device_id, telemetry, tenant_id=tenant_id)
            return telemetry

        except AxeOSConnectorError:
            self.update_device(device_id, {"last_seen": int(time.time()), "status": STATUS_OFFLINE},
                              tenant_id=tenant_id)
            # Return a FALSY dict so the background poll loop never caches
            # error stubs into axe_telemetry_cache / the /api/snapshot payload.
            return {}

    # ── Internals ─────────────────────────────────────────────────────

    def _persist_device(self, device: dict):
        """Insert or replace a device record."""
        conn = self._get_db()
        c = conn.cursor()
        c.execute(
            """INSERT OR REPLACE INTO axe_devices
            (id, name, model, manufacturer, firmware, firmware_version,
             api_version, ip_address, hostname, mac_address,
             last_seen, status, group_id, capabilities, added_at, updated_at,
             tenant_id, agent_managed)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                int(device.get("agent_managed", 0) or 0),
            ),
        )
        conn.commit()
        conn.close()

    # ── Agent command queue (SaaS: commands routed through the local agent) ─

    def enqueue_agent_command(self, device_id: str, command: str,
                              params: dict = None, tenant_id: str = "default") -> dict:
        """Queue a command for a device polled by the user's local agent.
        Returns {"id": ..., "status": "pending"} or {} when the device is
        not agent-managed / unknown. Never raises."""
        cmd_id = uuid.uuid4().hex[:12]
        now = int(time.time())
        conn = self._get_db()
        c = conn.cursor()
        try:
            c.execute(
                "INSERT INTO axe_agent_commands "
                "(id, tenant_id, device_id, command, params, status, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (cmd_id, tenant_id, device_id, command,
                 json.dumps(params or {}), "pending", now),
            )
            conn.commit()
        except Exception as e:
            log.warning("[agent-cmd] enqueue failed: %s", e)
            cmd_id = ""
        finally:
            conn.close()
        if not cmd_id:
            return {}
        return {"id": cmd_id, "command": command, "status": "pending"}

    def pending_agent_commands(self, tenant_id: str = "default",
                               requeue_after: int = 60) -> list:
        """Pending commands for a tenant (for the agent's pull). Commands
        pulled but never acked within `requeue_after` seconds are returned
        again so a crashed agent doesn't lose the command forever."""
        now = int(time.time())
        conn = self._get_db()
        c = conn.cursor()
        try:
            c.execute(
                "SELECT * FROM axe_agent_commands WHERE tenant_id=? "
                "AND (status='pending' OR (status='pulled' AND ? - pulled_at > ?)) "
                "ORDER BY created_at LIMIT 20",
                (tenant_id, now, requeue_after),
            )
            rows = [dict(r) for r in c.fetchall()]
        except Exception as e:
            log.warning("[agent-cmd] pull failed: %s", e)
            rows = []
        finally:
            conn.close()
        for r in rows:
            try:
                r["params"] = json.loads(r.get("params") or "{}")
            except (json.JSONDecodeError, TypeError):
                r["params"] = {}
        return rows

    def mark_command_pulled(self, command_id: str, tenant_id: str = "default") -> bool:
        """Mark a command as pulled (agent will ack after executing)."""
        conn = self._get_db()
        c = conn.cursor()
        try:
            c.execute(
                "UPDATE axe_agent_commands SET status='pulled', pulled_at=? "
                "WHERE id=? AND tenant_id=?",
                (int(time.time()), command_id, tenant_id),
            )
            conn.commit()
            return c.rowcount > 0
        except Exception as e:
            log.warning("[agent-cmd] mark pulled failed: %s", e)
            return False
        finally:
            conn.close()

    def ack_agent_command(self, command_id: str, tenant_id: str, success: bool,
                          result: str = "") -> bool:
        """Ack a command result (agent executed it). Idempotent.
        A duplicate ack (agent network retry) returns True as long as the
        command belongs to the tenant — an already-acked command must not
        surface as a 404 to the agent."""
        conn = self._get_db()
        c = conn.cursor()
        try:
            c.execute(
                "UPDATE axe_agent_commands SET status=?, result=?, acked_at=? "
                "WHERE id=? AND tenant_id=? AND status='pulled'",
                ("done" if success else "failed", result[:2000],
                 int(time.time()), command_id, tenant_id),
            )
            conn.commit()
            if c.rowcount > 0:
                return True
            # Not currently 'pulled' — either unknown/wrong tenant (False)
            # or already acked (idempotent True).
            c.execute(
                "SELECT status FROM axe_agent_commands WHERE id=? AND tenant_id=?",
                (command_id, tenant_id),
            )
            row = c.fetchone()
            return bool(row and row["status"] in ("done", "failed"))
        except Exception as e:
            log.warning("[agent-cmd] ack failed: %s", e)
            return False
        finally:
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
