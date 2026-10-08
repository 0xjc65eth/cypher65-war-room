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
import re
import time
import uuid

from .models import (
    new_device,
    infer_capabilities,
    STATUS_ONLINE,
    STATUS_OFFLINE,
    STATUS_STALE,
    derive_device_status,
    is_telemetry_stale,
    validate_agent_telemetry,
)
from .connector import AxeOSConnector, AxeOSConnectorError
from services.observability import emit_event

log = logging.getLogger("cypher65.axe.registry")


class TelemetryIdempotencyConflict(ValueError):
    """Raised when a telemetry event key is reused for another payload."""


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
    is_axeos = (
        bool(info.get("firmware")) and "axe" in str(info.get("firmware", "")).lower()
    )
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
                idempotency_key TEXT,
                FOREIGN KEY (device_id) REFERENCES axe_devices(id)
            )"""
        )
        # ── Multi-tenant migration: add tenant_id columns ──
        self._migrate_add_tenant_id(c)
        self._migrate_telemetry_idempotency(c)
        # ── Agent-managed migration: devices polled by the user's LOCAL
        #    agent (SaaS: cloud dashboard can't reach the home LAN) must be
        #    marked so the server-side poll never touches them. ──
        self._migrate_add_agent_managed(c)
        # ── Tombstone migration: soft-delete marker so a removed device
        #    can't be re-created by the agent's next push (zombie fix). ──
        self._migrate_add_removed_at(c)
        # ── Canonical physical identity aliases (MAC is tenant-scoped; IP is
        #    only a locator). Alias rows survive DHCP changes and tombstones. ──
        c.execute(
            """CREATE TABLE IF NOT EXISTS axe_device_identity_aliases (
                tenant_id TEXT NOT NULL,
                mac_normalized TEXT NOT NULL,
                device_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (tenant_id, mac_normalized)
            )"""
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_axe_device_identity_device "
            "ON axe_device_identity_aliases(tenant_id, device_id)"
        )
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
        c.execute(
            """CREATE TABLE IF NOT EXISTS axe_telemetry_quarantine (
                tenant_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                ts INTEGER NOT NULL,
                fields TEXT NOT NULL DEFAULT '[]',
                reasons TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY (tenant_id, device_id)
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
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_axe_devices_tenant ON axe_devices(tenant_id)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_axe_telemetry_tenant ON axe_telemetry(tenant_id)"
            )
        except Exception:
            pass

    @staticmethod
    def _migrate_telemetry_idempotency(c):
        """Add the optional sample key and enforce tenant/device uniqueness."""
        c.execute("PRAGMA table_info(axe_telemetry)")
        columns = {row[1] for row in c.fetchall()}
        if "idempotency_key" not in columns:
            c.execute("ALTER TABLE axe_telemetry ADD COLUMN idempotency_key TEXT")
        c.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS uq_axe_telemetry_idempotency
            ON axe_telemetry(tenant_id, device_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL"""
        )

    def _migrate_add_agent_managed(self, c):
        """Add agent_managed column to axe_devices if missing (SaaS agent
        model: 1 = polled by the user's local agent, never by this server)."""
        c.execute("PRAGMA table_info(axe_devices)")
        cols = {row[1] for row in c.fetchall()}
        if "agent_managed" not in cols:
            try:
                c.execute(
                    "ALTER TABLE axe_devices ADD COLUMN agent_managed INTEGER DEFAULT 0"
                )
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
                c.execute(
                    "ALTER TABLE axe_devices ADD COLUMN removed_at INTEGER DEFAULT 0"
                )
                log.info("[migrate] added removed_at to axe_devices")
            except Exception as e:
                log.warning("[migrate] could not add removed_at: %s", e)

    # ── CRUD ──────────────────────────────────────────────────────────

    def add_device(
        self, ip_address: str, name: str = "", tenant_id: str = "default"
    ) -> dict:
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
            from .axeos_contract import extract_axeos_telemetry, looks_like_axeos
            from .models import derive_device_status

            if not looks_like_axeos(info):
                raise AxeOSConnectorError("payload is not ESP-Miner")
            tel = extract_axeos_telemetry(info)
            device["model"] = str(
                tel.get("model") or info.get("model") or info.get("board", "")
            )
            device["firmware"] = str(info.get("firmware", ""))
            device["firmware_version"] = str(info.get("version", ""))
            device["hostname"] = str(info.get("hostname", ""))
            device["mac_address"] = str(
                tel.get("mac") or info.get("macAddr") or info.get("mac") or ""
            )
            device["last_seen"] = int(time.time())
            device["status"] = derive_device_status(tel)
            device["capabilities"] = conn.detect_capabilities()
        except AxeOSConnectorError:
            device["status"] = STATUS_OFFLINE
            device["capabilities"] = {}

        return self._persist_registered_device(device, allow_restore=True)

    def remove_device(
        self, device_id: str, tenant_id: str = "default", hard: bool = False
    ) -> bool:
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
            c.execute(
                "DELETE FROM axe_devices WHERE id=? AND tenant_id=?",
                (device_id, tenant_id),
            )
            deleted = c.rowcount > 0
        else:
            c.execute(
                "UPDATE axe_devices SET removed_at=?, status='OFFLINE' "
                "WHERE id=? AND tenant_id=? AND COALESCE(removed_at,0)=0",
                (int(time.time()), device_id, tenant_id),
            )
            deleted = c.rowcount > 0
        c.execute(
            "DELETE FROM axe_telemetry_quarantine WHERE device_id=? AND tenant_id=?",
            (device_id, tenant_id),
        )
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
            c.execute(
                "SELECT id, tenant_id FROM axe_devices WHERE COALESCE(removed_at,0)>0 AND removed_at<?",
                (cutoff,),
            )
            removed_devices = [dict(r) for r in c.fetchall()]
            ids = [row["id"] for row in removed_devices]
            if ids:
                # Quarantine metadata is scoped by both tenant and device ID.
                c.executemany(
                    "DELETE FROM axe_telemetry_quarantine WHERE tenant_id=? AND device_id=?",
                    [(row["tenant_id"], row["id"]) for row in removed_devices],
                )
                placeholders = ",".join("?" * len(ids))
                # placeholders are generated ?-markers only — no user input.
                c.execute(
                    f"DELETE FROM axe_telemetry WHERE device_id IN ({placeholders})",  # nosec B608
                    ids,
                )
                c.execute(
                    f"DELETE FROM axe_devices WHERE id IN ({placeholders})",  # nosec B608
                    ids,
                )
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

    def list_removed(self, tenant_id: str = "") -> list:
        """Tombstoned devices for this tenant (operator-intent restore list)."""
        if not tenant_id:
            return []
        conn = self._get_db()
        c = conn.cursor()
        c.execute(
            "SELECT * FROM axe_devices WHERE tenant_id=? AND COALESCE(removed_at,0)>0 ORDER BY removed_at DESC",
            (tenant_id,),
        )
        rows = [self._row_to_device(r) for r in c.fetchall()]
        conn.close()
        return rows

    def clear_tombstone(self, ip_address: str, tenant_id: str = "") -> dict:
        """Explicitly restore a tenant-scoped locator without deleting history.

        Does not create a device or probe the IP. The tombstoned row, MAC alias,
        telemetry and command ledger remain attached to the same canonical ID.
        """
        if not ip_address or not tenant_id:
            return {}
        conn = self._get_db()
        try:
            c = conn.cursor()
            c.execute("BEGIN IMMEDIATE")
            c.execute(
                "SELECT * FROM axe_devices WHERE ip_address=? AND tenant_id=? "
                "AND COALESCE(removed_at,0)>0 ORDER BY added_at DESC",
                (ip_address, tenant_id),
            )
            rows = c.fetchall()
            if len(rows) != 1:
                conn.rollback()
                return {}
            row = self._row_to_device(rows[0])
            c.execute(
                "UPDATE axe_devices SET removed_at=0, status='OFFLINE', updated_at=? "
                "WHERE id=? AND tenant_id=? AND COALESCE(removed_at,0)>0 "
                "AND mac_address=?",
                (int(time.time()), row["id"], tenant_id, row["mac_address"]),
            )
            if c.rowcount != 1:
                conn.rollback()
                return {}
            conn.commit()
            return row
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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
            c.execute(
                f"SELECT * FROM axe_devices WHERE tenant_id=? AND {self._tombstone_query()} ORDER BY name",  # nosec B608
                (tenant_id,),
            )
        else:
            c.execute(
                f"SELECT * FROM axe_devices WHERE {self._tombstone_query()} ORDER BY name"  # nosec B608
            )
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
                    # Fleet audit (Issue #627): a live-looking status backed by
                    # an OLD reading is STALE, not ONLINE — the stored row is
                    # the evidence, and no poll has refreshed it in time.
                    if is_telemetry_stale(tel.get("ts")) and d.get("status") in (
                        STATUS_ONLINE,
                        "IDLE",
                        "HASHING",
                    ):
                        d["status"] = STATUS_STALE
        return devices

    def _latest_telemetry_by_device(self, tenant_id: str = "") -> dict:
        """Latest TRUSTED telemetry payload per device in a single query.
        Only payloads carrying hashrate_hs count as trusted (mirrors the
        route layer's _is_trusted_payload); heartbeat-only {} pushes never
        replace the last real reading."""
        conn = self._get_db()
        c = conn.cursor()
        # rowid as the tiebreaker: two pushes in the same second must resolve
        # by ARRIVAL order, or the newest reading can be shadowed by the one
        # before it (Fleet audit #627 — a verified best_diff was shadowed).
        if tenant_id:
            c.execute(
                "SELECT device_id, payload FROM axe_telemetry "
                "WHERE tenant_id=? ORDER BY ts DESC, rowid DESC",
                (tenant_id,),
            )
        else:
            c.execute(
                "SELECT device_id, payload FROM axe_telemetry ORDER BY ts DESC, rowid DESC"
            )
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
            c.execute(
                f"SELECT * FROM axe_devices WHERE id=? AND tenant_id=? AND {self._tombstone_query()}",  # nosec B608
                (device_id, tenant_id),
            )
        else:
            c.execute(
                f"SELECT * FROM axe_devices WHERE id=? AND {self._tombstone_query()}",  # nosec B608
                (device_id,),
            )
        r = c.fetchone()
        conn.close()
        return self._row_to_device(r) if r else {}

    def get_device_by_mac(self, mac_address: str, tenant_id: str = "") -> dict:
        """Find one active device by canonical tenant-scoped MAC identity."""
        mac = normalize_device_mac(mac_address)
        if not mac:
            return {}
        conn = self._get_db()
        try:
            c = conn.cursor()
            if tenant_id:
                c.execute(
                    "SELECT device_id FROM axe_device_identity_aliases "
                    "WHERE mac_normalized=? AND tenant_id=?",
                    (mac, tenant_id),
                )
            else:
                c.execute(
                    "SELECT device_id FROM axe_device_identity_aliases "
                    "WHERE mac_normalized=?",
                    (mac,),
                )
            alias = c.fetchone()
            if alias:
                device = self.get_device(alias["device_id"], tenant_id=tenant_id)
                return device
            # Compatibility for legacy rows written before the alias table.
            rows = c.execute(
                "SELECT * FROM axe_devices WHERE "
                + ("tenant_id=? AND " if tenant_id else "")
                + self._tombstone_query(),
                (tenant_id,) if tenant_id else (),
            ).fetchall()
            matches = [
                row for row in rows
                if normalize_device_mac(row["mac_address"]) == mac
            ]
            if len(matches) > 1:
                raise DeviceIdentityConflict("MAC maps to multiple legacy device rows")
            return self._row_to_device(matches[0]) if matches else {}
        finally:
            conn.close()

    def get_device_by_ip(self, ip_address: str, tenant_id: str = "") -> dict:
        """Get a device by IP address, scoped to tenant if provided.
        Tombstoned rows are never returned."""
        conn = self._get_db()
        c = conn.cursor()
        if tenant_id:
            # internal fixed _tombstone_query() expression — no user input.
            c.execute(
                f"SELECT * FROM axe_devices WHERE ip_address=? AND tenant_id=? AND {self._tombstone_query()}",  # nosec B608
                (ip_address, tenant_id),
            )
        else:
            c.execute(
                f"SELECT * FROM axe_devices WHERE ip_address=? AND {self._tombstone_query()}",  # nosec B608
                (ip_address,),
            )
        r = c.fetchone()
        conn.close()
        return self._row_to_device(r) if r else {}

    def _matching_device_rows(self, c, tenant_id: str, ip_address: str):
        """Return active and tombstoned locator rows inside the caller's tx."""
        c.execute(
            "SELECT * FROM axe_devices WHERE tenant_id=? AND ip_address=? "
            "ORDER BY added_at, id",
            (tenant_id, ip_address),
        )
        return [self._row_to_device(row) for row in c.fetchall()]

    def _identity_device_tx(self, c, tenant_id: str, ip_address: str, mac: str):
        """Resolve one identity without ever treating IP as physical proof."""
        alias = None
        if mac:
            c.execute(
                "SELECT device_id FROM axe_device_identity_aliases "
                "WHERE tenant_id=? AND mac_normalized=?",
                (tenant_id, mac),
            )
            alias = c.fetchone()
        alias_id = alias["device_id"] if alias else None

        c.execute("SELECT * FROM axe_devices WHERE tenant_id=? ORDER BY id", (tenant_id,))
        tenant_rows = [self._row_to_device(row) for row in c.fetchall()]
        mac_rows = [
            row for row in tenant_rows
            if mac and normalize_device_mac(row.get("mac_address")) == mac
        ]
        mac_ids = {row["id"] for row in mac_rows}
        if len(mac_ids) > 1:
            raise DeviceIdentityConflict("MAC maps to multiple legacy device rows")
        if alias_id and mac_ids and alias_id not in mac_ids:
            raise DeviceIdentityConflict("MAC alias conflicts with registry rows")
        target_id = alias_id or (next(iter(mac_ids)) if mac_ids else None)
        target = next((row for row in tenant_rows if row["id"] == target_id), None)
        if alias_id and target is None:
            raise DeviceIdentityConflict("MAC alias points to a missing device row")

        ip_rows = [row for row in tenant_rows if row.get("ip_address") == ip_address]
        if len(ip_rows) > 1:
            raise DeviceIdentityConflict("IP locator maps to multiple registry rows")
        ip_row = ip_rows[0] if ip_rows else None
        if target is not None and ip_row is not None and target["id"] != ip_row["id"]:
            raise DeviceIdentityConflict("MAC identity and IP locator point to different devices")
        if target is None and ip_row is not None:
            stored_mac = normalize_device_mac(ip_row.get("mac_address"))
            if mac and stored_mac and stored_mac != mac:
                raise DeviceIdentityConflict("IP locator is already assigned to another MAC")
            target = ip_row
        return target

    @staticmethod
    def _write_device_tx(c, device: dict, *, insert: bool):
        fields = (
            "id", "name", "model", "manufacturer", "firmware", "firmware_version",
            "api_version", "ip_address", "hostname", "mac_address", "last_seen",
            "status", "group_id", "capabilities", "added_at", "updated_at",
            "tenant_id", "agent_managed", "removed_at",
        )
        values = [
            device.get("id", ""), device.get("name", ""), device.get("model", ""),
            device.get("manufacturer", ""), device.get("firmware", ""),
            device.get("firmware_version", ""), device.get("api_version", ""),
            device.get("ip_address", ""), device.get("hostname", ""),
            device.get("mac_address", ""), device.get("last_seen", 0),
            device.get("status", STATUS_OFFLINE), device.get("group_id", ""),
            json.dumps(device.get("capabilities", {})), device.get("added_at", int(time.time())),
            int(time.time()), device.get("tenant_id", "default"),
            int(device.get("agent_managed", 0) or 0), int(device.get("removed_at", 0) or 0),
        ]
        if insert:
            c.execute(
                "INSERT INTO axe_devices (" + ",".join(fields) + ") VALUES (" +
                ",".join("?" for _ in fields) + ")",
                values,
            )
            return
        c.execute(
            "UPDATE axe_devices SET " + ",".join(f"{field}=?" for field in fields[1:]) +
            " WHERE id=? AND tenant_id=?",
            values[1:] + [device["id"], device["tenant_id"]],
        )
        if c.rowcount != 1:
            raise DeviceIdentityConflict("canonical registry row disappeared during update")

    def _persist_registered_device(self, device: dict, *, allow_restore: bool) -> dict:
        """Atomically resolve and persist manual registration by MAC evidence."""
        tenant_id = str(device.get("tenant_id") or "default")
        ip_address = str(device.get("ip_address") or "").strip()
        mac = normalize_device_mac(device.get("mac_address"))
        conn = self._get_db()
        try:
            c = conn.cursor()
            c.execute("BEGIN IMMEDIATE")
            target = self._identity_device_tx(c, tenant_id, ip_address, mac)
            if target and int(target.get("removed_at", 0) or 0) and not allow_restore:
                conn.rollback()
                return {}
            if target:
                if mac and normalize_device_mac(target.get("mac_address")) not in (None, mac):
                    raise DeviceIdentityConflict("canonical row has a different MAC")
                merged = dict(target)
                for field in (
                    "name", "model", "manufacturer", "firmware", "firmware_version",
                    "api_version", "hostname", "status", "last_seen", "group_id",
                    "capabilities", "agent_managed",
                ):
                    if device.get(field) not in (None, ""):
                        merged[field] = device[field]
                merged["ip_address"] = ip_address
                merged["mac_address"] = mac or target.get("mac_address", "")
                merged["removed_at"] = 0 if allow_restore else int(target.get("removed_at", 0) or 0)
                self._write_device_tx(c, merged, insert=False)
            else:
                merged = dict(device)
                merged["tenant_id"] = tenant_id
                merged["mac_address"] = mac or ""
                merged["removed_at"] = 0
                self._write_device_tx(c, merged, insert=True)
            if mac:
                c.execute(
                    "INSERT OR IGNORE INTO axe_device_identity_aliases "
                    "(tenant_id, mac_normalized, device_id, created_at) VALUES (?,?,?,?)",
                    (tenant_id, mac, merged["id"], int(time.time())),
                )
                c.execute(
                    "SELECT device_id FROM axe_device_identity_aliases "
                    "WHERE tenant_id=? AND mac_normalized=?",
                    (tenant_id, mac),
                )
                alias = c.fetchone()
                if not alias or alias["device_id"] != merged["id"]:
                    raise DeviceIdentityConflict("MAC alias is already bound to another device")
            conn.commit()
            return self.get_device(merged["id"], tenant_id=tenant_id) or merged
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def upsert_agent_device(
        self,
        ip_address: str,
        name: str = "",
        tenant_id: str = "default",
        info: dict = None,
    ) -> dict:
        """Register Agent telemetry with tenant-scoped MAC identity.

        MAC is physical evidence; IP is only the current locator. SQLite's
        immediate write transaction serializes contenders across independent
        Agent connections. Ambiguous legacy rows fail closed; tombstoned
        identities are never auto-restored. Missing MAC remains unverified.
        """
        info = dict(info or {})
        now = int(time.time())
        mac = normalize_device_mac(info.get("mac"))
        caps = _caps_for_type(info)
        proposed = {
            "id": uuid.uuid4().hex[:12],
            "name": name or str(info.get("hostname") or info.get("model") or ip_address),
            "model": str(info.get("model") or ""),
            "manufacturer": str(info.get("manufacturer") or ""),
            "firmware": str(info.get("firmware") or ""),
            "firmware_version": str(info.get("version") or ""),
            "api_version": "",
            "ip_address": ip_address,
            "hostname": str(info.get("hostname") or ""),
            "mac_address": mac or "",
            "last_seen": now,
            "status": STATUS_OFFLINE,
            "group_id": "",
            "capabilities": caps,
            "added_at": now,
            "updated_at": now,
            "tenant_id": tenant_id,
            "agent_managed": 1,
            "removed_at": 0,
        }
        conn = self._get_db()
        try:
            c = conn.cursor()
            c.execute("BEGIN IMMEDIATE")
            target = self._identity_device_tx(c, tenant_id, ip_address, mac)
            if target and int(target.get("removed_at", 0) or 0):
                conn.rollback()
                log.info("[agent] refusing tombstoned device registration")
                return {}
            if target:
                if mac and normalize_device_mac(target.get("mac_address")) not in (None, mac):
                    raise DeviceIdentityConflict("canonical row has a different MAC")
                merged = dict(target)
                for field in (
                    "model", "manufacturer", "firmware", "firmware_version", "hostname",
                    "agent_managed", "last_seen", "capabilities",
                ):
                    if info.get({"firmware_version": "version"}.get(field, field)) not in (None, ""):
                        source = "version" if field == "firmware_version" else field
                        merged[field] = str(info[source]) if field not in ("agent_managed", "last_seen", "capabilities") else proposed[field]
                merged["ip_address"] = ip_address
                merged["mac_address"] = mac or target.get("mac_address", "")
                if name:
                    merged["name"] = name
                self._write_device_tx(c, merged, insert=False)
            else:
                merged = proposed
                self._write_device_tx(c, merged, insert=True)
            if mac:
                c.execute(
                    "INSERT OR IGNORE INTO axe_device_identity_aliases "
                    "(tenant_id, mac_normalized, device_id, created_at) VALUES (?,?,?,?)",
                    (tenant_id, mac, merged["id"], now),
                )
                c.execute(
                    "SELECT device_id FROM axe_device_identity_aliases "
                    "WHERE tenant_id=? AND mac_normalized=?",
                    (tenant_id, mac),
                )
                alias = c.fetchone()
                if not alias or alias["device_id"] != merged["id"]:
                    raise DeviceIdentityConflict("MAC alias is already bound to another device")
            conn.commit()
            return self.get_device(merged["id"], tenant_id=tenant_id) or merged
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _latest_measured_telemetry(
        self, device_id: str, tenant_id: str = ""
    ) -> dict | None:
        """Newest stored telemetry payload that actually carries measurements
        (a hashrate_hs key) — heartbeat-only {} rows are skipped. Used by the
        agent-heartbeat path to degrade status honestly (STALE/OFFLINE).
        Scans the newest 50 rows, which covers any sane heartbeat cadence.
        Returns None when no measured reading exists."""
        conn = self._get_db()
        c = conn.cursor()
        # ORDER BY rowid DESC: ARRIVAL order, not payload ts — a device with
        # clock skew (or an agent re-pushing cached readings) must not make a
        # stale measurement look like the newest one.
        if tenant_id:
            c.execute(
                "SELECT payload FROM axe_telemetry "
                "WHERE device_id=? AND tenant_id=? ORDER BY rowid DESC LIMIT 50",
                (device_id, tenant_id),
            )
        else:
            c.execute(
                "SELECT payload FROM axe_telemetry "
                "WHERE device_id=? ORDER BY rowid DESC LIMIT 50",
                (device_id,),
            )
        rows = c.fetchall()
        conn.close()
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict) and "hashrate_hs" in payload:
                return payload
        return None

    def save_agent_telemetry(
        self,
        device_id: str,
        telemetry: dict,
        tenant_id: str = "default",
        idempotency_key: str = "",
    ) -> str:
        """Persist telemetry pushed by the user's local agent and update the
        device status. Returns the persisted status so callers (routes) can
        echo the HONEST state instead of re-deriving from the raw payload.

        Fleet audit (Issue #627): an EMPTY heartbeat (``{}`` — the agent pushes
        one when the device answered nothing) is PRESENCE, not health. It
        refreshes last_seen but must NOT keep a device at IDLE forever: the
        status degrades to STALE when the newest MEASURED telemetry is older
        than the staleness horizon, and OFFLINE when no measured reading has
        ever been stored. Only a payload with real measurements can say
        ONLINE/IDLE/PAUSED.
        """
        errors = validate_agent_telemetry(telemetry)
        if errors:
            raise ValueError(f"invalid agent telemetry: {errors}")
        now = int(time.time())
        payload = dict(telemetry or {})
        payload["ts"] = payload.get("ts") or now
        payload["device_id"] = device_id
        share_fields = (
            "best_diff",
            "shares_accepted",
            "shares_rejected",
            "shares_stale",
        )
        has_measurements = any(
            payload.get(k) not in (None, "")
            for k in (
                "hashrate_hs",
                "temperature",
                "shares_accepted",
                "best_diff",
            )
        )
        if has_measurements:
            # Issue #13 precedence: PAUSED is explicit operator intent and
            # never expires — it beats staleness. Everything else with an OLD
            # ts is a stale reading even when it arrives now (agent backlog
            # after a reboot): ONLINE requires a RECENT signal.
            status = derive_device_status(payload)
            if status != "PAUSED" and is_telemetry_stale(payload.get("ts"), now=now):
                status = STATUS_STALE
        else:
            latest = self._latest_measured_telemetry(device_id, tenant_id=tenant_id)
            if latest is None:
                status = STATUS_OFFLINE
            elif is_telemetry_stale(latest.get("ts"), now=now):
                status = STATUS_STALE
            else:
                # Fresh-enough measured reading exists: keep its live status
                # (PAUSED survives a heartbeat; IDLE stays IDLE).
                status = derive_device_status(latest)
        # Compute status before inserting so concurrent replays can repair
        # denormalized device state even if a writer stopped after the event
        # row committed but before update_device completed.
        if idempotency_key:
            inserted = self.save_telemetry(
                device_id,
                payload,
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
            )
            if not inserted:
                latest = self._latest_measured_telemetry(device_id, tenant_id=tenant_id)
                if latest and latest.get("ts", 0) > payload.get("ts", 0):
                    status = derive_device_status(latest)
                    if status != "PAUSED" and is_telemetry_stale(
                        latest.get("ts"), now=now
                    ):
                        status = STATUS_STALE
        else:
            # Preserve the established call shape for legacy instrumentation
            # wrappers around save_telemetry.
            self.save_telemetry(device_id, payload, tenant_id=tenant_id)
        transition_events = []
        if status == STATUS_STALE and any(
            payload.get(key) not in (None, "") for key in share_fields
        ):
            transition_events.append(
                (
                    "share.stale",
                    {
                        "sample_ts": (
                            payload.get("ts")
                            if isinstance(payload.get("ts"), int)
                            else None
                        ),
                        "changed_fields": ",".join(
                            key
                            for key in share_fields
                            if payload.get(key) not in (None, "")
                        ),
                    },
                )
            )
        updated = self.update_device(
            device_id,
            {
                "last_seen": now,
                "status": status,
                "agent_managed": 1,
            },
            tenant_id=tenant_id,
            transition_events=transition_events,
        )
        if telemetry:
            self.clear_telemetry_quarantine(device_id, tenant_id=tenant_id)
        sample_ts = payload.get("ts")
        if updated and has_measurements and status != STATUS_STALE:
            emit_event(
                "miner.telemetry.received",
                tenant_id=tenant_id,
                device_id=device_id,
                sample_ts=sample_ts if isinstance(sample_ts, int) else None,
                status=status,
            )
        return status

    def record_telemetry_quarantine(
        self, device_id: str, fields: list, reasons: list, tenant_id: str = "default"
    ) -> bool:
        """Persist only metadata; return True on first/change, never store sample."""
        clean_fields = sorted({str(field)[:160] for field in fields})[:32]
        clean_reasons = sorted({str(reason)[:80] for reason in reasons})[:16]
        tenant = tenant_id or "default"
        conn = self._get_db()
        try:
            previous = conn.execute(
                "SELECT fields, reasons FROM axe_telemetry_quarantine "
                "WHERE tenant_id=? AND device_id=?",
                (tenant, device_id),
            ).fetchone()
            unchanged = False
            if previous:
                try:
                    unchanged = (
                        json.loads(previous["fields"] or "[]") == clean_fields
                        and json.loads(previous["reasons"] or "[]") == clean_reasons
                    )
                except (json.JSONDecodeError, TypeError):
                    unchanged = False
            conn.execute(
                "INSERT INTO axe_telemetry_quarantine "
                "(tenant_id, device_id, ts, fields, reasons) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(tenant_id, device_id) DO UPDATE SET "
                "ts=excluded.ts, fields=excluded.fields, reasons=excluded.reasons",
                (
                    tenant,
                    device_id,
                    int(time.time()),
                    json.dumps(clean_fields),
                    json.dumps(clean_reasons),
                ),
            )
            conn.commit()
            return not unchanged
        finally:
            conn.close()

    def get_telemetry_quarantines(self, tenant_id: str = "") -> dict:
        """Latest quarantined-sample metadata, scoped to a single tenant."""
        if not tenant_id:
            return {}
        conn = self._get_db()
        try:
            rows = conn.execute(
                "SELECT device_id, ts, fields, reasons FROM axe_telemetry_quarantine "
                "WHERE tenant_id=?",
                (tenant_id,),
            ).fetchall()
            result = {}
            for row in rows:
                try:
                    result[row["device_id"]] = {
                        "ts": row["ts"],
                        "fields": json.loads(row["fields"] or "[]"),
                        "reasons": json.loads(row["reasons"] or "[]"),
                    }
                except (json.JSONDecodeError, TypeError):
                    continue
            return result
        finally:
            conn.close()

    def clear_telemetry_quarantine(self, device_id: str, tenant_id: str = "") -> None:
        """Clear warning metadata only after a non-empty valid sample is saved."""
        if not tenant_id:
            return
        conn = self._get_db()
        try:
            conn.execute(
                "DELETE FROM axe_telemetry_quarantine WHERE tenant_id=? AND device_id=?",
                (tenant_id, device_id),
            )
            conn.commit()
        finally:
            conn.close()

    def update_device(
        self,
        device_id: str,
        updates: dict,
        tenant_id: str = "",
        transition_events=None,
    ) -> bool:
        """Update device fields. Keys in 'updates' overwrite stored values.
        Returns True if device exists and was updated.
        If tenant_id is provided, only updates devices belonging to that tenant."""
        fields = [
            "name",
            "model",
            "ip_address",
            "hostname",
            "group_id",
            "status",
            "last_seen",
            "agent_managed",
            "firmware",
            "firmware_version",
            "manufacturer",
            "mac_address",
            "api_version",
        ]
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
        if active_only:
            sql += " AND COALESCE(removed_at,0)=0"

        conn = self._get_db()
        c = conn.cursor()
        previous_status = None
        event_tenant_id = tenant_id
        try:
            if "status" in updates:
                # Serialize status transitions so concurrent pollers cannot
                # both observe the same previous value and emit duplicate edges.
                is_sqlite = type(conn).__module__.startswith("sqlite3")
                c.execute("BEGIN IMMEDIATE" if is_sqlite else "BEGIN")
                lookup = "SELECT status, tenant_id FROM axe_devices WHERE id=?"
                if not is_sqlite:
                    lookup += " FOR UPDATE"
                lookup_values = [device_id]
                if tenant_id:
                    lookup += " AND tenant_id=?"
                    lookup_values.append(tenant_id)
                c.execute(lookup, tuple(lookup_values))
                previous = c.fetchone()
                if previous is not None:
                    previous_status = str(previous["status"] or "").upper()
                    event_tenant_id = str(previous["tenant_id"] or tenant_id or "")
            c.execute(sql, tuple(vals))
            updated = c.rowcount > 0
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        current_status = str(updates.get("status") or "").upper()
        if updated and previous_status and previous_status != current_status:
            event_name = None
            if current_status == STATUS_OFFLINE:
                event_name = "miner.offline"
            elif current_status == STATUS_STALE:
                event_name = "miner.telemetry.stale"
            elif previous_status in {STATUS_OFFLINE, STATUS_STALE} and current_status:
                event_name = "miner.online"
            if event_name:
                emit_event(
                    event_name,
                    tenant_id=event_tenant_id,
                    device_id=device_id,
                    previous_status=previous_status,
                    status=current_status,
                )
            for extra_name, extra_fields in transition_events or ():
                emit_event(
                    extra_name,
                    tenant_id=event_tenant_id,
                    device_id=device_id,
                    status=current_status,
                    **extra_fields,
                )
        return updated

    # ── Telemetry persistence (tenant-aware) ──────────────────────────

    def save_telemetry(
        self,
        device_id: str,
        telemetry: dict,
        tenant_id: str = "default",
        idempotency_key: str = "",
    ) -> bool:
        """Persist one sample, ignoring identical keyed replays.

        Returns ``False`` when the event was already stored with an identical
        canonical payload. Reusing a key for another payload raises
        :class:`TelemetryIdempotencyConflict`. Legacy calls may omit the key.
        """
        serialized = json.dumps(telemetry, sort_keys=True, separators=(",", ":"))
        conn = self._get_db()
        c = conn.cursor()
        changed_share_fields = []
        share_fields = (
            "best_diff",
            "shares_accepted",
            "shares_rejected",
            "shares_stale",
        )
        try:
            c.execute("BEGIN IMMEDIATE")
            c.execute(
                "SELECT payload FROM axe_telemetry WHERE device_id=? AND tenant_id=? "
                "ORDER BY rowid DESC LIMIT 50",
                (device_id, tenant_id),
            )
            previous_sample = None
            for row in c.fetchall():
                try:
                    candidate = json.loads(row["payload"])
                except (TypeError, ValueError):
                    continue
                if (
                    isinstance(candidate, dict)
                    and any(
                        candidate.get(key) not in (None, "") for key in share_fields
                    )
                    and not is_telemetry_stale(candidate.get("ts"))
                ):
                    previous_sample = candidate
                    break
            changed_share_fields = [
                key
                for key in share_fields
                if telemetry.get(key) not in (None, "")
                and (previous_sample or {}).get(key) != telemetry.get(key)
            ]
            if idempotency_key:
                c.execute(
                    """INSERT OR IGNORE INTO axe_telemetry
                    (ts, device_id, payload, tenant_id, idempotency_key)
                    VALUES (?, ?, ?, ?, ?)""",
                    (
                        telemetry.get("ts", int(time.time())),
                        device_id,
                        serialized,
                        tenant_id,
                        idempotency_key,
                    ),
                )
                if c.rowcount == 0:
                    c.execute(
                        """SELECT payload FROM axe_telemetry
                        WHERE tenant_id=? AND device_id=? AND idempotency_key=?""",
                        (tenant_id, device_id, idempotency_key),
                    )
                    existing = c.fetchone()
                    if existing is None:
                        raise RuntimeError("telemetry insert was ignored unexpectedly")
                    if existing["payload"] != serialized:
                        raise TelemetryIdempotencyConflict(
                            "idempotency key already belongs to a different telemetry sample"
                        )
                    conn.commit()
                    return False
            else:
                c.execute(
                    """INSERT INTO axe_telemetry
                    (ts, device_id, payload, tenant_id, idempotency_key)
                    VALUES (?, ?, ?, ?, NULL)""",
                    (
                        telemetry.get("ts", int(time.time())),
                        device_id,
                        serialized,
                        tenant_id,
                    ),
                )
            conn.commit()
            inserted = True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        if (
            inserted
            and changed_share_fields
            and not is_telemetry_stale(telemetry.get("ts"))
        ):
            emit_event(
                "share.updated",
                tenant_id=tenant_id,
                device_id=device_id,
                sample_ts=(
                    telemetry.get("ts")
                    if isinstance(telemetry.get("ts"), int)
                    else None
                ),
                changed_fields=",".join(changed_share_fields),
            )
        return inserted

    def get_recent_telemetry(
        self, device_id: str, limit: int = 120, tenant_id: str = ""
    ) -> list:
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

    def get_telemetry_chart_data(
        self, device_id: str, limit: int = 120, tenant_id: str = ""
    ) -> dict:
        """Get chart-ready telemetry series for a device.
        Returns dict with arrays: ts, hashrate_hs, temperature, fan_rpm,
        power_watts, efficiency_jth, shares_accepted, shares_rejected."""
        raw = self.get_recent_telemetry(device_id, limit=limit, tenant_id=tenant_id)
        raw.reverse()  # chronological order
        series = {
            "ts": [],
            "hashrate_hs": [],
            "temperature": [],
            "fan_rpm": [],
            "power_watts": [],
            "efficiency_jth": [],
            "shares_accepted": [],
            "shares_rejected": [],
            "hw_error_pct": [],
            "voltage_mv": [],
            "frequency_mhz": [],
        }
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
            self.update_device(
                device_id,
                {
                    "last_seen": now,
                    "status": derive_device_status(telemetry),
                },
                tenant_id=tenant_id,
            )

            self.save_telemetry(device_id, telemetry, tenant_id=tenant_id)
            return telemetry

        except AxeOSConnectorError:
            self.update_device(
                device_id,
                {"last_seen": int(time.time()), "status": STATUS_OFFLINE},
                tenant_id=tenant_id,
            )
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

    def enqueue_agent_command(
        self,
        device_id: str,
        command: str,
        params: dict = None,
        tenant_id: str = "default",
    ) -> dict:
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
                (
                    cmd_id,
                    tenant_id,
                    device_id,
                    command,
                    json.dumps(params or {}),
                    "pending",
                    now,
                ),
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

    def pending_agent_commands(
        self, tenant_id: str = "default", requeue_after: int = 60
    ) -> list:
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

    def mark_command_pulled(
        self,
        command_id: str,
        tenant_id: str = "default",
        max_age: int = 300,
        requeue_after: int = 60,
    ) -> bool:
        """Atomically release a pending/retryable command to an agent.

        The age predicate closes the race between listing and marking: an
        expired command can never become executable while a pull is in flight.
        """
        conn = self._get_db()
        c = conn.cursor()
        try:
            now = int(time.time())
            c.execute(
                "UPDATE axe_agent_commands SET status='pulled', pulled_at=? "
                "WHERE id=? AND tenant_id=? AND created_at>=? "
                "AND (status='pending' OR "
                "(status='pulled' AND ? - pulled_at > ?))",
                (
                    now,
                    command_id,
                    tenant_id,
                    now - max(1, int(max_age)),
                    now,
                    max(1, int(requeue_after)),
                ),
            )
            conn.commit()
            return c.rowcount > 0
        except Exception as e:
            log.warning("[agent-cmd] mark pulled failed: %s", e)
            return False
        finally:
            conn.close()

    def terminalize_agent_command(
        self,
        command_id: str,
        tenant_id: str,
        status: str,
        reason: str,
    ) -> bool:
        """Move an undelivered command to an auditable terminal state."""
        if status not in ("expired", "blocked", "failed"):
            return False
        conn = self._get_db()
        c = conn.cursor()
        try:
            c.execute(
                "UPDATE axe_agent_commands SET status=?, result=?, acked_at=? "
                "WHERE id=? AND tenant_id=? AND status IN ('pending','pulled')",
                (
                    status,
                    str(reason or "")[:2000],
                    int(time.time()),
                    command_id,
                    tenant_id,
                ),
            )
            conn.commit()
            return c.rowcount > 0
        except Exception as e:
            log.warning("[agent-cmd] terminalize failed: %s", e)
            return False
        finally:
            conn.close()

    def ack_agent_command(
        self, command_id: str, tenant_id: str, success: bool, result: str = ""
    ) -> bool:
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
                (
                    "done" if success else "failed",
                    result[:2000],
                    int(time.time()),
                    command_id,
                    tenant_id,
                ),
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
