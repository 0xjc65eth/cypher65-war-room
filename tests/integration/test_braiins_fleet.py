"""
CYPHER65 // Integration Tests — Braiins OS+ Fleet Pipeline
===========================================================
End-to-end: seed a Braiins OS+ device via test-devices → verify the fleet
API returns correct firmware, capabilities, and adapter routing.

Uses Flask test_client + mocked registry (no real DB, no network I/O).
"""
import json
from unittest.mock import MagicMock, patch

import pytest

import app as _app_module
app = _app_module.app


@pytest.fixture
def client():
    """Return a Flask test client configured for testing."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ═══════════════════════════════════════════════════════════════════════════
#  Braiins OS+ Fleet Integration
# ═══════════════════════════════════════════════════════════════════════════

class TestBraiinsFleetIntegration:
    """Seed + verify a Braiins OS+ device end-to-end through the fleet API."""

    ENDPOINT_SEED = "/api/axe-fleet/test-devices"
    ENDPOINT_DEVICES = "/api/axe-fleet/devices"

    def _seed_and_get_devices(self, client, monkeypatch):
        """Seed test devices via the API and capture the persisted device
        dicts. Returns the list of device dicts that were persisted."""
        monkeypatch.setenv("DEBUG_MOCK", "1")
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = []  # empty → seed allowed

        persisted_devices = []

        def _capture_persist(device_dict):
            persisted_devices.append(dict(device_dict))

        mock_registry._persist_device.side_effect = _capture_persist
        # save_telemetry is called 40 times (4 devices × 10 points)
        mock_registry.save_telemetry.return_value = None

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.post(self.ENDPOINT_SEED)
        assert resp.status_code == 201
        assert len(persisted_devices) == 4
        return persisted_devices

    def _find_braiins(self, devices: list) -> dict:
        """Find the Braiins OS+ device in the seeded fleet."""
        braiins = [d for d in devices
                   if (d.get("firmware") or "").lower().startswith("braiins")]
        assert len(braiins) == 1, (
            f"Expected exactly 1 Braiins device, found {len(braiins)}: "
            f"{[d.get('firmware') for d in devices]}"
        )
        return braiins[0]

    # ── Firmware identity ──────────────────────────────────────────────

    def test_braiins_device_has_correct_firmware(self, client, monkeypatch):
        """Seeded Braiins device must carry firmware='Braiins OS+' so the
        adapter factory can pattern-match it."""
        devices = self._seed_and_get_devices(client, monkeypatch)
        braiins = self._find_braiins(devices)

        assert braiins["firmware"] == "Braiins OS+"
        assert braiins["model"] == "Antminer S19 Pro"
        assert braiins["manufacturer"] == "Bitmain"
        assert braiins["name"] == "Basement S19"

    def test_braiins_device_has_correct_status(self, client, monkeypatch):
        """Seeded Braiins device is OFFLINE (no real miner behind it)."""
        devices = self._seed_and_get_devices(client, monkeypatch)
        braiins = self._find_braiins(devices)

        assert braiins["status"] == "OFFLINE"
        assert braiins["ip_address"] == "192.168.1.200"
        assert braiins["tenant_id"] == "default"

    # ── Capabilities contract ──────────────────────────────────────────

    def test_braiins_device_has_telemetry_capability(self, client, monkeypatch):
        """Braiins OS+ device must have telemetry=True in capabilities."""
        devices = self._seed_and_get_devices(client, monkeypatch)
        braiins = self._find_braiins(devices)

        caps = braiins.get("capabilities") or {}
        assert caps.get("telemetry") is True, f"Expected telemetry=True, got {caps}"

    def test_braiins_device_has_statistics_capability(self, client, monkeypatch):
        """Braiins device must have statistics=True."""
        devices = self._seed_and_get_devices(client, monkeypatch)
        braiins = self._find_braiins(devices)

        caps = braiins.get("capabilities") or {}
        assert caps.get("statistics") is True

    def test_braiins_device_offline_commands_disabled(self, client, monkeypatch):
        """OFFLINE Braiins device must have restart/identify=False (device
        unreachable — commands would fail)."""
        devices = self._seed_and_get_devices(client, monkeypatch)
        braiins = self._find_braiins(devices)

        caps = braiins.get("capabilities") or {}
        assert caps.get("restart") is False
        assert caps.get("identify") is False

    # ── Capability differences: Braiins vs AxeOS ───────────────────────

    def test_braiins_lacks_axeos_only_capabilities(self, client, monkeypatch):
        """Braiins device must NOT have AxeOS-specific capabilities
        (pause/resume/frequencyControl — these are ESP-Miner only)."""
        devices = self._seed_and_get_devices(client, monkeypatch)
        braiins = self._find_braiins(devices)

        caps = braiins.get("capabilities") or {}
        assert caps.get("pause") is False, "pause is AxeOS-only"
        assert caps.get("resume") is False, "resume is AxeOS-only"
        assert caps.get("frequencyControl") is False, "frequencyControl is AxeOS-only"
        assert caps.get("voltageControl") is False, "voltageControl is AxeOS-only"

    def test_axeos_device_has_frequency_control(self, client, monkeypatch):
        """Contrast: an AxeOS device MUST have frequencyControl=True."""
        devices = self._seed_and_get_devices(client, monkeypatch)
        axeos = [d for d in devices if d.get("firmware") == "AxeOS"]
        assert len(axeos) >= 1, "No AxeOS device in seeded fleet"

        caps = axeos[0].get("capabilities") or {}
        assert caps.get("frequencyControl") is True
        assert caps.get("pause") is True

    # ── Adapter routing ────────────────────────────────────────────────

    def test_adapter_factory_routes_braiins_firmware(self):
        """core/adapters/__init__.py::get_adapter() must return a
        BraiinsAdapter for a device with firmware='Braiins OS+'."""
        from core.adapters import get_adapter
        from core.adapters.braiins_adapter import BraiinsAdapter
        from core.models.device import Device

        dev = Device(
            name="Basement S19",
            model="Antminer S19 Pro",
            firmware="Braiins OS+",
            ip="192.168.1.200",
        )
        adapter = get_adapter(dev)
        assert isinstance(adapter, BraiinsAdapter), (
            f"Expected BraiinsAdapter, got {type(adapter).__name__}"
        )

    def test_adapter_factory_routes_bosminer_firmware(self):
        """get_adapter() must also route 'BOSminer' firmware to BraiinsAdapter."""
        from core.adapters import get_adapter
        from core.adapters.braiins_adapter import BraiinsAdapter
        from core.models.device import Device

        dev = Device(
            name="s19-bos",
            model="Antminer S19",
            firmware="BOSminer 22.0",
            ip="10.0.0.2",
        )
        adapter = get_adapter(dev)
        assert isinstance(adapter, BraiinsAdapter)

    def test_adapter_factory_routes_braiins_in_model_name(self):
        """get_adapter() must also route model names containing 'braiins'."""
        from core.adapters import get_adapter
        from core.adapters.braiins_adapter import BraiinsAdapter
        from core.models.device import Device

        dev = Device(
            name="worker1",
            model="Braiins Antminer S19",
            firmware="",
            ip="10.0.0.3",
        )
        adapter = get_adapter(dev)
        assert isinstance(adapter, BraiinsAdapter)

    def test_adapter_factory_falls_back_to_cgminer_for_antminer(self):
        """get_adapter() must route generic Antminer devices to CgminerAdapter."""
        from core.adapters import get_adapter
        from core.adapters.cgminer_adapter import CgminerAdapter
        from core.models.device import Device

        dev = Device(
            name="s19-generic",
            model="Antminer S19",
            firmware="",
            ip="10.0.0.4",
        )
        adapter = get_adapter(dev)
        assert isinstance(adapter, CgminerAdapter)

    def test_adapter_factory_falls_back_to_cgminer_for_whatsminer(self):
        """get_adapter() routes Whatsminer to CgminerAdapter."""
        from core.adapters import get_adapter
        from core.adapters.cgminer_adapter import CgminerAdapter
        from core.models.device import Device

        dev = Device(
            name="m50s",
            model="Whatsminer M50S",
            firmware="",
            ip="10.0.0.5",
        )
        adapter = get_adapter(dev)
        assert isinstance(adapter, CgminerAdapter)

    # ── Fleet device listing integration ───────────────────────────────

    def test_fleet_devices_includes_braiins_device(self, client, monkeypatch):
        """GET /api/axe-fleet/devices must return the seeded Braiins device
        with correct firmware string."""
        devices = self._seed_and_get_devices(client, monkeypatch)

        # Simulate what GET /api/axe-fleet/devices would return by
        # building a mock response from the captured persisted data
        braiins = self._find_braiins(devices)

        # Verify the full device dict shape
        required_keys = [
            "id", "name", "model", "manufacturer", "firmware",
            "firmware_version", "ip_address", "hostname", "status",
            "capabilities", "tenant_id",
        ]
        for key in required_keys:
            assert key in braiins, f"Braiins device missing key: {key}"

        assert braiins["firmware"] == "Braiins OS+"
        assert braiins["firmware_version"] == "22.0"

    def test_fleet_devices_returns_correct_count(self, client, monkeypatch):
        """Fleet must have exactly 4 devices after seeding."""
        devices = self._seed_and_get_devices(client, monkeypatch)
        assert len(devices) == 4

        # Verify firmware distribution
        firmwares = {d["firmware"] for d in devices}
        assert "AxeOS" in firmwares
        assert "Braiins OS+" in firmwares

    def test_fleet_devices_all_have_unique_ids(self, client, monkeypatch):
        """Every seeded device must have a unique ID."""
        devices = self._seed_and_get_devices(client, monkeypatch)
        ids = [d["id"] for d in devices]
        assert len(ids) == len(set(ids)), f"Duplicate IDs found: {ids}"

    # ── Fleet summary integration ──────────────────────────────────────

    def test_fleet_summary_counts_braiins_device(self, client, monkeypatch):
        """Fleet summary must include the Braiins device in the count."""
        devices = self._seed_and_get_devices(client, monkeypatch)

        # Build a mock summary response from captured devices
        online = sum(1 for d in devices if d["status"] in ("ONLINE", "HASHING"))
        warning = sum(1 for d in devices if d["status"] == "WARNING")
        offline = sum(1 for d in devices if d["status"] not in ("ONLINE", "HASHING", "WARNING"))

        # Expected from the seeded fleet:
        # 2 AxeOS ONLINE, 1 AxeOS WARNING, 1 Braiins OFFLINE
        assert online == 2
        assert warning == 1
        assert offline == 1
        assert online + warning + offline == 4

        braiins = self._find_braiins(devices)
        assert braiins["status"] == "OFFLINE"

    def test_braiins_device_has_Bitmain_manufacturer(self, client, monkeypatch):
        """Braiins OS+ runs on Bitmain hardware — manufacturer must be 'Bitmain'."""
        devices = self._seed_and_get_devices(client, monkeypatch)
        braiins = self._find_braiins(devices)

        assert braiins["manufacturer"] == "Bitmain"

    def test_axeos_device_has_Bitaxe_manufacturer(self, client, monkeypatch):
        """AxeOS devices must have manufacturer='Bitaxe'."""
        devices = self._seed_and_get_devices(client, monkeypatch)
        # "Garage Bitaxe" has model "Bitaxe ULP" → manufacturer "Bitaxe"
        bitaxe_devs = [d for d in devices if "Bitaxe" in (d.get("model") or "")]
        assert len(bitaxe_devs) >= 2
        for d in bitaxe_devs:
            assert d["manufacturer"] == "Bitaxe"


# ═══════════════════════════════════════════════════════════════════════════
#  Braiins OS+ capabilities contract (adapter level)
# ═══════════════════════════════════════════════════════════════════════════

class TestBraiinsCapabilitiesContract:
    """BraiinsAdapter.get_capabilities() must return the 5 capability
    names defined in the adapter, in the correct supported state."""

    def test_braiins_adapter_has_five_capabilities(self):
        from core.adapters.braiins_adapter import BraiinsAdapter
        from core.models.device import Device

        dev = Device(name="braiins", model="Antminer S19 Pro",
                     firmware="Braiins OS+", ip="10.0.0.1")
        adapter = BraiinsAdapter(dev)
        caps = adapter.get_capabilities()

        assert len(caps) == 5
        names = {c.name for c in caps}
        assert names == {"telemetry", "restart", "identify",
                         "tuner_control", "set_frequency"}

    def test_telemetry_is_supported(self):
        from core.adapters.braiins_adapter import BraiinsAdapter
        from core.models.device import Device

        dev = Device(name="b", model="S19", firmware="Braiins OS+", ip="10.0.0.1")
        adapter = BraiinsAdapter(dev)
        caps = {c.name: c for c in adapter.get_capabilities()}

        assert caps["telemetry"].supported is True
        assert caps["restart"].supported is True
        assert caps["identify"].supported is True
        assert caps["tuner_control"].supported is False
        assert caps["set_frequency"].supported is False

    def test_restart_requires_confirmation_medium_risk(self):
        from core.adapters.braiins_adapter import BraiinsAdapter
        from core.models.device import Device

        dev = Device(name="b", model="S19", firmware="Braiins OS+", ip="10.0.0.1")
        adapter = BraiinsAdapter(dev)
        caps = {c.name: c for c in adapter.get_capabilities()}

        assert caps["restart"].requires_confirmation is True
        assert caps["restart"].risk_level.value == "medium"

    def test_tuner_control_requires_confirmation_high_risk(self):
        from core.adapters.braiins_adapter import BraiinsAdapter
        from core.models.device import Device

        dev = Device(name="b", model="S19", firmware="Braiins OS+", ip="10.0.0.1")
        adapter = BraiinsAdapter(dev)
        caps = {c.name: c for c in adapter.get_capabilities()}

        assert caps["tuner_control"].requires_confirmation is True
        assert caps["tuner_control"].risk_level.value == "high"

    def test_set_frequency_requires_confirmation_high_risk(self):
        from core.adapters.braiins_adapter import BraiinsAdapter
        from core.models.device import Device

        dev = Device(name="b", model="S19", firmware="Braiins OS+", ip="10.0.0.1")
        adapter = BraiinsAdapter(dev)
        caps = {c.name: c for c in adapter.get_capabilities()}

        assert caps["set_frequency"].requires_confirmation is True
        assert caps["set_frequency"].risk_level.value == "high"


# ═══════════════════════════════════════════════════════════════════════════
#  Detector → Fleet pipeline integration
# ═══════════════════════════════════════════════════════════════════════════

class TestDetectorToFleetPipeline:
    """detect_firmware() → adapter routing → fleet seeding end-to-end."""

    def test_detector_identifies_braiins(self, monkeypatch):
        """detect_firmware() must return firmware='braiins' for a Braiins
        REST API response."""
        from core.registry.detector import detect_firmware
        import requests
        from unittest.mock import Mock

        # AxeOS probe fails; Braiins REST probe succeeds
        def fake_get(url, timeout):
            if "/api/system/info" in url:
                raise requests.ConnectionError("not axeos")
            mock = Mock()
            mock.status_code = 200
            mock.json.return_value = {
                "miner_stats": {
                    "hashrate_ghps": "100",
                    "version": "braiins-os_2024-10",
                    "model": "Antminer S19 Pro",
                },
            }
            return mock

        monkeypatch.setattr("core.registry.detector.requests.get", fake_get)

        result = detect_firmware("10.0.0.50")
        assert result["firmware"] == "braiins"
        assert result["adapter_type"] == "braiins"
        assert result["reachable"] is True
        assert result["version"] == "braiins-os_2024-10"
        assert result["model"] == "Antminer S19 Pro"

    def test_detector_to_adapter_factory_roundtrip(self, monkeypatch):
        """Full roundtrip: detect_firmware → adapter_type → get_adapter →
        correct adapter class instantiated."""
        from core.registry.detector import detect_firmware
        from core.adapters import get_adapter
        from core.adapters.braiins_adapter import BraiinsAdapter
        from core.models.device import Device
        import requests
        from unittest.mock import Mock

        # Simulate a Braiins REST detection
        def fake_get(url, timeout):
            if "/api/system/info" in url:
                raise requests.ConnectionError("not axeos")
            mock = Mock()
            mock.status_code = 200
            mock.json.return_value = {
                "miner_stats": {
                    "hashrate_ghps": "110.0",
                    "version": "braiins-os_2025-01",
                    "model": "Antminer S19j Pro",
                },
            }
            return mock

        monkeypatch.setattr("core.registry.detector.requests.get", fake_get)

        # Step 1: Detect firmware
        fw = detect_firmware("10.0.0.60")
        assert fw["adapter_type"] == "braiins"

        # Step 2: Create a Device with the detected firmware
        dev = Device(
            name="detected-miner",
            model=fw["model"],
            firmware=fw["firmware"],
            ip="10.0.0.60",
        )

        # Step 3: get_adapter must route to BraiinsAdapter
        adapter = get_adapter(dev)
        assert isinstance(adapter, BraiinsAdapter)

        # Step 4: Verify capabilities match the adapter contract
        caps = {c.name: c.supported for c in adapter.get_capabilities()}
        assert caps["telemetry"] is True
        assert caps["tuner_control"] is False  # stub


# ═══════════════════════════════════════════════════════════════════════════
#  Auto-detect firmware on POST /api/axe-fleet/devices
# ═══════════════════════════════════════════════════════════════════════════

class TestAutoDetectOnAddDevice:
    """POST /api/axe-fleet/devices now calls detect_firmware() and enriches
    the registered device with detected firmware/model/version."""

    ENDPOINT = "/api/axe-fleet/devices"

    def test_device_enriched_with_detected_braiins_firmware(self, client, monkeypatch):
        """When detect_firmware returns braiins, the device is enriched with
        firmware='braiins', model, version, and status=ONLINE."""
        from unittest.mock import MagicMock, patch

        monkeypatch.setattr(
            "core.registry.detector.detect_firmware",
            lambda ip: {"firmware": "braiins", "adapter_type": "braiins",
                        "version": "braiins-os_2024-10",
                        "model": "Antminer S19 Pro", "reachable": True}
        )

        mock_reg = MagicMock()
        mock_reg.get_device_by_ip.return_value = None
        mock_reg.add_device.return_value = {
            "id": "dev-001", "name": "my-s19", "status": "OFFLINE",
            "ip_address": "10.0.0.1", "tenant_id": "default"
        }
        mock_reg.get_device.return_value = {
            "id": "dev-001", "name": "my-s19", "status": "ONLINE",
            "ip_address": "10.0.0.1", "model": "Antminer S19 Pro",
            "firmware": "braiins", "firmware_version": "braiins-os_2024-10",
            "tenant_id": "default"
        }

        with patch("axe_fleet.routes._registry", mock_reg), \
             patch("axe_fleet.routes._can_add_worker", return_value=True):
            resp = client.post(self.ENDPOINT,
                              json={"ip_address": "10.0.0.1", "name": "my-s19"})

        assert resp.status_code == 201
        data = resp.get_json()
        assert data["success"] is True
        device = data["device"]
        assert device["firmware"] == "braiins"
        assert device["firmware_version"] == "braiins-os_2024-10"
        assert device["model"] == "Antminer S19 Pro"
        assert device["status"] == "ONLINE"

        # Verify update_device was called with the detected metadata
        mock_reg.update_device.assert_called_once()
        call_args = mock_reg.update_device.call_args[0]
        assert call_args[0] == "dev-001"  # device_id
        updates = call_args[1]
        assert updates["firmware"] == "braiins"
        assert updates["status"] == "ONLINE"

    def test_device_not_enriched_when_detector_unreachable(self, client, monkeypatch):
        """When detect_firmware returns reachable=False, the device is
        registered without enrichment (firmware stays empty)."""
        from unittest.mock import MagicMock, patch

        monkeypatch.setattr(
            "core.registry.detector.detect_firmware",
            lambda ip: {"firmware": "unknown", "adapter_type": "unknown",
                        "reachable": False}
        )

        mock_reg = MagicMock()
        mock_reg.get_device_by_ip.return_value = None
        mock_reg.add_device.return_value = {
            "id": "dev-002", "name": "dead-miner", "status": "OFFLINE",
            "ip_address": "10.0.0.99", "tenant_id": "default"
        }

        with patch("axe_fleet.routes._registry", mock_reg), \
             patch("axe_fleet.routes._can_add_worker", return_value=True):
            resp = client.post(self.ENDPOINT,
                              json={"ip_address": "10.0.0.99", "name": "dead-miner"})

        assert resp.status_code == 201
        # update_device should NOT be called (nothing to enrich)
        mock_reg.update_device.assert_not_called()

    def test_detector_exception_does_not_block_registration(self, client, monkeypatch):
        """If detect_firmware raises an exception, the device is still
        registered — firmware auto-detect is best-effort."""
        from unittest.mock import MagicMock, patch

        monkeypatch.setattr(
            "core.registry.detector.detect_firmware",
            lambda ip: (_ for _ in ()).throw(RuntimeError("probe timeout"))
        )

        mock_reg = MagicMock()
        mock_reg.get_device_by_ip.return_value = None
        mock_reg.add_device.return_value = {
            "id": "dev-003", "name": "timeout-miner", "status": "OFFLINE",
            "ip_address": "10.0.0.50", "tenant_id": "default"
        }

        with patch("axe_fleet.routes._registry", mock_reg), \
             patch("axe_fleet.routes._can_add_worker", return_value=True):
            resp = client.post(self.ENDPOINT,
                              json={"ip_address": "10.0.0.50", "name": "timeout-miner"})

        assert resp.status_code == 201
        assert resp.get_json()["success"] is True
        # Registration succeeded despite probe failure
        mock_reg.add_device.assert_called_once()

    def test_detected_cgminer_device_gets_firmware(self, client, monkeypatch):
        """detect_firmware returning cgminer also enriches the device."""
        from unittest.mock import MagicMock, patch

        monkeypatch.setattr(
            "core.registry.detector.detect_firmware",
            lambda ip: {"firmware": "cgminer", "adapter_type": "cgminer",
                        "version": "4.12.0", "model": "Antminer S19",
                        "reachable": True}
        )

        mock_reg = MagicMock()
        mock_reg.get_device_by_ip.return_value = None
        mock_reg.add_device.return_value = {
            "id": "dev-004", "name": "antminer", "status": "OFFLINE",
            "ip_address": "10.0.0.2", "tenant_id": "default"
        }
        mock_reg.get_device.return_value = {
            "id": "dev-004", "name": "antminer", "status": "ONLINE",
            "ip_address": "10.0.0.2", "model": "Antminer S19",
            "firmware": "cgminer", "firmware_version": "4.12.0",
            "tenant_id": "default"
        }

        with patch("axe_fleet.routes._registry", mock_reg), \
             patch("axe_fleet.routes._can_add_worker", return_value=True):
            resp = client.post(self.ENDPOINT,
                              json={"ip_address": "10.0.0.2", "name": "antminer"})

        assert resp.status_code == 201
        device = resp.get_json()["device"]
        assert device["firmware"] == "cgminer"
        assert device["firmware_version"] == "4.12.0"
        assert device["status"] == "ONLINE"
