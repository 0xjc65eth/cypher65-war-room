import json
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from core.models.device import Device, DeviceStatus
from core.models.capability import Capability


def _utc_now():
    return datetime.now(timezone.utc)


class DeviceRegistry:
    """
    Fonte única de verdade para todos os dispositivos do CYPHER65.
    Responsável por CRUD, persistência e estado em memória.
    """

    def __init__(self, db_path: str = "data/war_room.sqlite"):
        self.db_path = db_path
        self.devices: Dict[str, Device] = {}
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                name TEXT,
                model TEXT,
                firmware TEXT,
                ip TEXT,
                hostname TEXT,
                mac TEXT,
                status TEXT,
                last_seen TEXT,
                metadata TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        conn.commit()
        conn.close()

    def add_device(self, device: Device) -> Device:
        device = self._ensure_capabilities(device)
        self.devices[device.id] = device
        self._save_to_db(device)
        return device

    def get_device(self, device_id: str) -> Optional[Device]:
        return self.devices.get(device_id)

    def list_devices(self, status: Optional[DeviceStatus] = None) -> List[Device]:
        if status:
            return [d for d in self.devices.values() if d.status == status]
        return list(self.devices.values())

    def update_device(self, device: Device):
        device.updated_at = _utc_now()
        self.devices[device.id] = device
        self._save_to_db(device)

    def remove_device(self, device_id: str):
        if device_id in self.devices:
            del self.devices[device_id]
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
        conn.commit()
        conn.close()

    def _save_to_db(self, device: Device):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO devices
            (id, name, model, firmware, ip, hostname, mac, status, last_seen, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            device.id,
            device.name,
            device.model,
            device.firmware,
            device.ip,
            device.hostname,
            device.mac,
            device.status.value,
            device.last_seen.isoformat() if device.last_seen else None,
            json.dumps(device.metadata) if device.metadata else "{}",
            device.created_at.isoformat(),
            device.updated_at.isoformat()
        ))
        conn.commit()
        conn.close()

    def load_from_db(self):
        """Carrega todos os devices do banco para memória"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM devices")
        rows = cursor.fetchall()
        conn.close()

        for row in rows:
            metadata = {}
            try:
                metadata = json.loads(row[9]) if row[9] else {}
            except (json.JSONDecodeError, TypeError):
                metadata = {}

            device = Device(
                id=row[0],
                name=row[1],
                model=row[2],
                firmware=row[3],
                ip=row[4],
                hostname=row[5],
                mac=row[6],
                status=DeviceStatus(row[7]),
                last_seen=datetime.fromisoformat(row[8]) if row[8] else None,
                metadata=metadata,
                created_at=datetime.fromisoformat(row[10]),
                updated_at=datetime.fromisoformat(row[11]),
            )
            device = self._ensure_capabilities(device)
            self.devices[device.id] = device

    def count_by_status(self) -> Dict[str, int]:
        result = {s.value: 0 for s in DeviceStatus}
        for d in self.devices.values():
            result[d.status.value] += 1
        return result

    def _ensure_capabilities(self, device: Device) -> Device:
        """Populate device capabilities from the adapter if not already set."""
        if device.capabilities:
            return device
        try:
            # Lazy import to avoid circular dependencies.
            from core.adapters import get_adapter
            adapter = get_adapter(device)
            device.capabilities = adapter.get_capabilities()
        except Exception:
            # Unknown/unsupported devices keep empty capabilities.
            pass
        return device
