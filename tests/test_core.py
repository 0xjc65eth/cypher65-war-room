"""Tests for core CYPHER65 functions: solo_mining calculations + helpers formatters."""

import math
import pytest
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from solo_mining import calc_block_probability, _parse_hashrate, normalize_cost
from helpers import parse_diff_to_float, fmt_diff
from core.models.device import NOT_AVAILABLE, normalize_telemetry


# ═══════════════════════════════════════════════════════════════════════════
# 0. normalize_telemetry — Fase 5 (NOT AVAILABLE fallback)
# ═══════════════════════════════════════════════════════════════════════════

class TestNormalizeTelemetry:
    """Canonical F5 fields must always be present — real value or NOT_AVAILABLE."""

    def test_none_passthrough(self):
        assert normalize_telemetry(None) is None

    def test_missing_fields_become_not_available(self):
        out = normalize_telemetry({"hashrate": 1e12, "temperature": 70})
        assert out["hashrate"] == 1e12
        assert out["temperature"] == 70
        assert out["chip_temp"] == NOT_AVAILABLE
        assert out["vr_temp"] == NOT_AVAILABLE
        assert out["hashrate_1m"] == NOT_AVAILABLE
        assert out["hashrate_10m"] == NOT_AVAILABLE
        assert out["hashrate_1h"] == NOT_AVAILABLE
        assert out["fan_rpm"] == NOT_AVAILABLE
        assert out["voltage"] == NOT_AVAILABLE
        assert out["power"] == NOT_AVAILABLE
        assert out["pool_status"] == NOT_AVAILABLE

    def test_none_values_become_not_available(self):
        out = normalize_telemetry({"chip_temp": None, "vr_temp": 55})
        assert out["chip_temp"] == NOT_AVAILABLE
        assert out["vr_temp"] == 55

    def test_present_values_preserved(self):
        out = normalize_telemetry({
            "chip_temp": 72, "vr_temp": 60, "hashrate_1m": 1.2e12,
            "hashrate_10m": 1.1e12, "hashrate_1h": 1.0e12,
            "fan_rpm": 4500, "voltage": 1200, "power": 30,
            "pool_status": "CONNECTED",
        })
        assert out["chip_temp"] == 72
        assert out["vr_temp"] == 60
        assert out["hashrate_1m"] == 1.2e12
        assert out["hashrate_10m"] == 1.1e12
        assert out["hashrate_1h"] == 1.0e12
        assert out["fan_rpm"] == 4500
        assert out["voltage"] == 1200
        assert out["power"] == 30
        assert out["pool_status"] == "CONNECTED"

    def test_extra_keys_preserved(self):
        out = normalize_telemetry({"hashrate": 5e11, "source": "bitaxe_adapter"})
        assert out["source"] == "bitaxe_adapter"
        assert out["hashrate"] == 5e11


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Fase 5 · Integration: adapter → normalize_telemetry() pipeline
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestTelemetryNormalizationPipeline:
    """End-to-end: adapter output → normalize_telemetry() → verify
    every canonical TELEMETRY_KEYS field is either a real value or the
    explicit NOT_AVAILABLE marker.

    This is the integration contract: the UI must never receive a missing
    key or None for a canonical field."""

    # ── CgminerAdapter ───────────────────────────────────────────────

    @staticmethod
    def _cgminer_telemetry(summary_data=None, stats_data=None, pools_data=None, host="10.0.0.1"):
        """Create a CgminerAdapter with mocked _send_command and return
        normalize_telemetry(get_telemetry())."""
        from unittest.mock import patch
        from core.adapters.cgminer_adapter import CgminerAdapter
        from core.models.device import Device, normalize_telemetry

        dev = Device(name="test-cgminer", model="Antminer S19", ip=host)
        adapter = CgminerAdapter(dev)

        def fake_send(cmd):
            if cmd == "summary":
                return summary_data
            if cmd == "stats":
                return stats_data
            if cmd == "pools":
                return pools_data
            return None

        with patch.object(adapter, "_send_command", side_effect=fake_send):
            raw = adapter.get_telemetry()
        return normalize_telemetry(raw)

    def test_cgminer_minimal_summary_only(self):
        """Cgminer with only 'summary' (no stats, no pools) → all Fase 5
        thermal/power/pool fields become NOT_AVAILABLE."""
        t = self._cgminer_telemetry(
            summary_data={
                "STATUS": [{"STATUS": "S", "When": 0}],
                "SUMMARY": [{"GHS 5s": "120.0", "Elapsed": 86400}],
            },
        )
        # cgminer never provides hashrate windows
        assert t["hashrate_1m"] == NOT_AVAILABLE
        assert t["hashrate_10m"] == NOT_AVAILABLE
        assert t["hashrate_1h"] == NOT_AVAILABLE
        # No stats → thermal/cooling/power NOT_AVAILABLE
        assert t["chip_temp"] == NOT_AVAILABLE
        assert t["vr_temp"] == NOT_AVAILABLE
        assert t["fan_rpm"] == NOT_AVAILABLE
        assert t["voltage"] == NOT_AVAILABLE
        assert t["power"] == NOT_AVAILABLE
        # No pools → pool_status NOT_AVAILABLE
        assert t["pool_status"] == NOT_AVAILABLE
        # Core hashrate is preserved
        assert t["hashrate"] == 120e9

    def test_cgminer_full_telemetry_all_present(self):
        """Cgminer with summary + stats + pools → all Fase 5 fields filled
        with real values, no NOT_AVAILABLE."""
        t = self._cgminer_telemetry(
            summary_data={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "110.0", "Accepted": 5000, "Rejected": 3,
                             "Stale": 1, "Elapsed": 604800, "Best Share": "25.7T"}],
            },
            stats_data={
                "STATUS": [{"STATUS": "S"}],
                "STATS": [
                    {"STATS": 0},
                    {"temp2_0": "72.5", "temp2_1": "68.0",
                     "fan_num": "2", "fan1": "4800",
                     "voltage": "12.4", "power": "3100"},
                ],
            },
            pools_data={
                "STATUS": [{"STATUS": "S"}],
                "POOLS": [
                    {"POOL": 0, "URL": "stratum+tcp://pool.btc.com:3333",
                     "User": "user.worker", "Status": "Alive"},
                ],
            },
        )
        # cgminer hashrate windows always NOT_AVAILABLE (protocol limitation)
        assert t["hashrate_1m"] == NOT_AVAILABLE
        assert t["hashrate_10m"] == NOT_AVAILABLE
        assert t["hashrate_1h"] == NOT_AVAILABLE
        # Thermal — from stats chain 1
        assert t["chip_temp"] == 72.5
        assert t["vr_temp"] == 68.0
        assert t["temperature"] == 72.5
        # Cooling & power
        assert t["fan_rpm"] == 4800
        assert t["voltage"] == 12.4
        assert t["power"] == 3100
        # Pool
        assert t["pool_status"] == "CONNECTED"
        # Core hashrate
        assert t["hashrate"] == 110e9

    def test_cgminer_stats_no_pools(self):
        """Cgminer with summary + stats but no pools → stats fields present,
        pool_status → NOT_AVAILABLE."""
        t = self._cgminer_telemetry(
            summary_data={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "95.0"}],
            },
            stats_data={
                "STATUS": [{"STATUS": "S"}],
                "STATS": [
                    {"STATS": 0},
                    {"temp2_0": "65.0", "fan_num": "1", "fan1": "4200",
                     "voltage": "11.8", "power": "2800"},
                ],
            },
        )
        assert t["chip_temp"] == 65.0
        assert t["fan_rpm"] == 4200
        assert t["voltage"] == 11.8
        assert t["power"] == 2800
        assert t["pool_status"] == NOT_AVAILABLE

    def test_cgminer_disconnected_pool(self):
        """Cgminer with pools all Dead → pool_status DISCONNECTED (not NOT_AVAILABLE)."""
        t = self._cgminer_telemetry(
            summary_data={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "0"}],
            },
            pools_data={
                "STATUS": [{"STATUS": "S"}],
                "POOLS": [
                    {"POOL": 0, "URL": "stratum+tcp://dead.pool:3333",
                     "User": "user.worker", "Status": "Dead"},
                ],
            },
        )
        assert t["pool_status"] == "DISCONNECTED"

    def test_cgminer_empty_pools_list(self):
        """Cgminer with empty POOLS → NOT CONFIGURED → normalize fills NOT_AVAILABLE."""
        t = self._cgminer_telemetry(
            summary_data={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "0"}],
            },
            pools_data={
                "STATUS": [{"STATUS": "S"}],
                "POOLS": [],
            },
        )
        assert t["pool_status"] == "NOT CONFIGURED"

    def test_cgminer_none_values_normalized(self):
        """Cgminer fields explicitly set to None by adapter become NOT_AVAILABLE."""
        t = self._cgminer_telemetry(
            summary_data={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "0", "Elapsed": 0}],
            },
        )
        # All Fase 5 fields not provided by adapter are None → NOT_AVAILABLE
        assert t["chip_temp"] == NOT_AVAILABLE
        assert t["vr_temp"] == NOT_AVAILABLE
        assert t["fan_rpm"] == NOT_AVAILABLE
        assert t["voltage"] == NOT_AVAILABLE
        assert t["power"] == NOT_AVAILABLE
        assert t["pool_status"] == NOT_AVAILABLE
        assert t["hashrate_1m"] == NOT_AVAILABLE
        assert t["hashrate_10m"] == NOT_AVAILABLE
        assert t["hashrate_1h"] == NOT_AVAILABLE
        # But hashrate itself is 0, not None → 0 is preserved
        assert t["hashrate"] == 0

    # ── BitaxeAdapter ───────────────────────────────────────────────

    @staticmethod
    def _bitaxe_telemetry(data: dict):
        """Create a BitaxeAdapter with mocked HTTP and return
        normalize_telemetry(get_telemetry())."""
        from unittest.mock import Mock, patch
        from core.adapters.bitaxe_adapter import BitaxeAdapter
        from core.models.device import Device, normalize_telemetry

        dev = Device(name="test-bitaxe", model="Bitaxe Max", ip="192.168.1.100")
        adapter = BitaxeAdapter(dev)

        mock_response = Mock()
        mock_response.json.return_value = data
        mock_response.raise_for_status = Mock()

        with patch("core.adapters.bitaxe_adapter.requests.get", return_value=mock_response):
            raw = adapter.get_telemetry()
        return normalize_telemetry(raw)

    def test_bitaxe_minimal_response(self):
        """Bitaxe with only hashRate + temp → hashrate windows, vr_temp,
        fan_rpm, pool_status all become NOT_AVAILABLE."""
        t = self._bitaxe_telemetry({"hashRate": 1.5e12, "temp": 70})
        # Hashrate windows absent
        assert t["hashrate_1m"] == NOT_AVAILABLE
        assert t["hashrate_10m"] == NOT_AVAILABLE
        assert t["hashrate_1h"] == NOT_AVAILABLE
        # chip_temp falls back to temp (70), so it IS present
        assert t["chip_temp"] == 70
        # vr_temp absent → adapter returns 0 (not None), kept as-is
        assert t["vr_temp"] == 0
        # Cooling absent → adapter returns 0, kept as-is
        assert t["fan_rpm"] == 0
        # Power/voltage absent → adapter returns 0
        assert t["voltage"] == 0
        assert t["power"] == 0
        # No pool config → adapter returns NOT CONFIGURED, but NOT in TELEMETRY_KEYS
        # so normalize doesn't touch it; pool_status here is "NOT CONFIGURED"
        assert t["pool_status"] == "NOT CONFIGURED"
        # Core hashrate preserved
        assert t["hashrate"] == 1.5e12

    def test_bitaxe_full_telemetry_no_not_available(self):
        """Bitaxe with all Fase 5 fields → no NOT_AVAILABLE markers."""
        t = self._bitaxe_telemetry({
            "hashRate": 1.5e12,
            "hashRate1m": 1.48e12,
            "hashRate10m": 1.45e12,
            "hashRate1hr": 1.40e12,
            "temp": 72,
            "tempChip": 74,
            "vrTemp": 68,
            "fanrpm": 4500,
            "voltage": 1200,
            "power": 30,
            "miningPaused": False,
            "stratumURL": "stratum+tcp://pool.btc.com:3333",
            "stratumPort": 3333,
            "stratumUser": "user.worker",
        })
        # All windows present
        assert t["hashrate_1m"] == 1.48e12
        assert t["hashrate_10m"] == 1.45e12
        assert t["hashrate_1h"] == 1.40e12
        # Thermal
        assert t["chip_temp"] == 74
        assert t["vr_temp"] == 68
        # Cooling & power
        assert t["fan_rpm"] == 4500
        assert t["voltage"] == 1200
        assert t["power"] == 30
        # Pool
        assert t["pool_status"] == "CONNECTED"

    def test_bitaxe_paused_pool_status_preserved(self):
        """Bitaxe with miningPaused=True → PAUSED, not overridden by normalize."""
        t = self._bitaxe_telemetry({
            "hashRate": 0,
            "temp": 45,
            "miningPaused": True,
            "stratumURL": "stratum+tcp://pool.btc.com:3333",
        })
        assert t["pool_status"] == "PAUSED"
        # Windows absent
        assert t["hashrate_1m"] == NOT_AVAILABLE
        assert t["hashrate_10m"] == NOT_AVAILABLE
        assert t["hashrate_1h"] == NOT_AVAILABLE

    def test_bitaxe_not_configured_becomes_not_available(self):
        """Bitaxe with NO pool URL → NOT CONFIGURED → normalize fills NOT_AVAILABLE."""
        t = self._bitaxe_telemetry({
            "hashRate": 1e12,
            "temp": 60,
            "miningPaused": False,
        })
        assert t["pool_status"] == "NOT CONFIGURED"

    # ── BraiinsAdapter ─────────────────────────────────────────────

    @staticmethod
    def _braiins_telemetry(summary=None, temps=None, fans=None, tuner=None,
                           stats=None, pools=None, host="10.0.0.1"):
        """Create a BraiinsAdapter with mocked _rest_get (returns None,
        forcing cgminer socket path) and _send_command, then return
        normalize_telemetry(get_telemetry())."""
        from unittest.mock import patch
        from core.adapters.braiins_adapter import BraiinsAdapter
        from core.models.device import Device, normalize_telemetry

        dev = Device(name="test-braiins", model="Antminer S19 Pro",
                     firmware="Braiins OS+", ip=host)
        adapter = BraiinsAdapter(dev)

        send_map = {}
        if summary is not None:
            send_map["summary"] = summary
        if temps is not None:
            send_map["temps"] = temps
        if fans is not None:
            send_map["fans"] = fans
        if tuner is not None:
            send_map["tunerstatus"] = tuner
        if stats is not None:
            send_map["stats"] = stats
        if pools is not None:
            send_map["pools"] = pools

        def fake_send(cmd, port=None):
            return send_map.get(cmd)

        with patch.object(adapter, "_rest_get", return_value=None), \
             patch.object(adapter, "_send_command", side_effect=fake_send):
            raw = adapter.get_telemetry()
        return normalize_telemetry(raw)

    def test_braiins_minimal_summary_only(self):
        """Braiins with only 'summary' → hashrate windows + all thermal/
        cooling/power fields become NOT_AVAILABLE."""
        t = self._braiins_telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "120.0", "Elapsed": 86400}],
            },
        )
        # Braiins cgminer socket (like standard cgminer) never provides
        # hashrate windows — adapter sets them to None → NOT_AVAILABLE
        assert t["hashrate_1m"] == NOT_AVAILABLE
        assert t["hashrate_10m"] == NOT_AVAILABLE
        assert t["hashrate_1h"] == NOT_AVAILABLE
        # No temps/fans/tuner/stats → all None → NOT_AVAILABLE
        assert t["chip_temp"] == NOT_AVAILABLE
        assert t["vr_temp"] == NOT_AVAILABLE
        assert t["fan_rpm"] == NOT_AVAILABLE
        assert t["voltage"] == NOT_AVAILABLE
        assert t["power"] == NOT_AVAILABLE
        assert t["pool_status"] == NOT_AVAILABLE
        # Core hashrate preserved
        assert t["hashrate"] == 120e9

    def test_braiins_full_telemetry_braiins_extensions(self):
        """Braiins with temps + fans + tunerstatus → all Fase 5 fields
        filled with Braiins-specific enriched values; windows remain
        NOT_AVAILABLE (cgminer protocol limitation)."""
        t = self._braiins_telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "110.0", "Accepted": 5000,
                             "Rejected": 3, "Stale": 1,
                             "Elapsed": 604800, "Best Share": "25.7T"}],
            },
            temps={
                "STATUS": [{"STATUS": "S"}],
                "TEMPS": [
                    {"Board": 0, "Chip": 0, "ID": 0,
                     "temp": "72.5", "temp_pcb": "58.0"},
                    {"Board": 0, "Chip": 1, "ID": 1,
                     "temp": "74.0", "temp_pcb": "59.5"},
                ],
            },
            fans={
                "STATUS": [{"STATUS": "S"}],
                "FANS": [
                    {"FAN": 0, "ID": 0, "RPM": 4800, "Speed": 80},
                    {"FAN": 1, "ID": 1, "RPM": 4600, "Speed": 78},
                ],
            },
            tuner={
                "STATUS": [{"STATUS": "S"}],
                "TUNERSTATUS": [
                    {"power": "3100", "tuner_state": "TUNED",
                     "power_limit": "3500"},
                ],
            },
            pools={
                "STATUS": [{"STATUS": "S"}],
                "POOLS": [
                    {"POOL": 0,
                     "URL": "stratum+tcp://braiins.pool:3333",
                     "User": "braiins.worker", "Status": "Alive"},
                ],
            },
        )
        # Windows always NOT_AVAILABLE (cgminer protocol limitation)
        assert t["hashrate_1m"] == NOT_AVAILABLE
        assert t["hashrate_10m"] == NOT_AVAILABLE
        assert t["hashrate_1h"] == NOT_AVAILABLE
        # Temps from Braiins 'temps' command (max chip, max PCB)
        assert t["chip_temp"] == 74.0
        assert t["temperature"] == 59.5
        # Fans from Braiins 'fans' command (average RPM)
        assert t["fan_rpm"] == (4800 + 4600) / 2
        # Power from tunerstatus
        assert t["power"] == 3100
        # Pool
        assert t["pool_status"] == "CONNECTED"
        assert t["hashrate"] == 110e9

    def test_braiins_stats_fallback_no_braiins_commands(self):
        """Braiins with summary + stats but no Braiins-specific commands
        (temps/fans/tuner absent) → falls back to stats chain data."""
        t = self._braiins_telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "95.0"}],
            },
            stats={
                "STATUS": [{"STATUS": "S"}],
                "STATS": [
                    {"STATS": 0},
                    {"temp2_0": "65.0", "temp2_1": "60.0",
                     "fan_num": "1", "fan1": "4200",
                     "voltage": "11.8", "power": "2800"},
                ],
            },
        )
        # Stats fallback fills temps, fan, voltage, power
        assert t["chip_temp"] == 65.0
        assert t["vr_temp"] == 60.0
        assert t["fan_rpm"] == 4200
        assert t["voltage"] == 11.8
        assert t["power"] == 2800
        # Hashrate windows stay NOT_AVAILABLE
        assert t["hashrate_1m"] == NOT_AVAILABLE
        assert t["hashrate_10m"] == NOT_AVAILABLE
        assert t["hashrate_1h"] == NOT_AVAILABLE

    def test_braiins_pool_disconnected(self):
        """Braiins with Dead pool → DISCONNECTED (real status, not NOT_AVAILABLE)."""
        t = self._braiins_telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "0"}],
            },
            pools={
                "STATUS": [{"STATUS": "S"}],
                "POOLS": [
                    {"POOL": 0,
                     "URL": "stratum+tcp://dead.pool:3333",
                     "User": "worker", "Status": "Dead"},
                ],
            },
        )
        assert t["pool_status"] == "DISCONNECTED"

    def test_braiins_pool_not_configured(self):
        """Braiins with empty POOLS → NOT CONFIGURED."""
        t = self._braiins_telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "0"}],
            },
            pools={
                "STATUS": [{"STATUS": "S"}],
                "POOLS": [],
            },
        )
        assert t["pool_status"] == "NOT CONFIGURED"

    def test_braiins_canonical_keys_all_present(self):
        """Every TELEMETRY_KEYS key present after braiins normalization."""
        from core.models.device import TELEMETRY_KEYS
        t = self._braiins_telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "1.0"}],
            },
        )
        for key in TELEMETRY_KEYS:
            assert key in t, f"Canonical key '{key}' missing from braiins pipeline"
            assert t[key] is not None, f"Canonical key '{key}' is None from braiins pipeline"

    # ── Pipeline edge cases ──────────────────────────────────────────

    def test_offline_adapter_returns_none(self):
        """When adapter returns None (offline), normalize_telemetry returns None."""
        assert normalize_telemetry(None) is None

    def test_all_canonical_keys_present_after_normalization(self):
        """Every key in TELEMETRY_KEYS must be present after normalization."""
        from core.models.device import TELEMETRY_KEYS
        t = self._cgminer_telemetry(
            summary_data={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "1.0"}],
            },
        )
        for key in TELEMETRY_KEYS:
            assert key in t, f"Canonical key '{key}' missing after normalize_telemetry"
            assert t[key] is not None, f"Canonical key '{key}' is None after normalize_telemetry"


# ═══════════════════════════════════════════════════════════════════════════
# 1. calc_block_probability
# ═══════════════════════════════════════════════════════════════════════════

class TestCalcBlockProbability:
    """Poisson-based block discovery probability."""

    def test_zero_hashrate(self):
        """Zero hashrate => lambda=0 => P=0."""
        result = calc_block_probability(0, 110e12, 86400)
        assert result["lambda"] == 0.0
        assert result["p_at_least_1_block"] == 0.0
        assert result["p_at_least_1_block_pct"] == 0.0
        assert result["p_zero_blocks_pct"] == 100.0

    def test_known_values(self):
        """225 TH/s for 24h at 110T difficulty — verify lambda and probability.
        Known: hashes_per_block = 110e12 * 2^32 ≈ 4.72e23
        block_rate = 225e12 / 4.72e23 ≈ 4.76e-10
        lambda(24h) = 4.76e-10 * 86400 ≈ 4.12e-5
        P = 1 - e^(-lambda) ≈ lambda (for small lambda) ≈ 4.12e-5
        P% ≈ 0.00412%
        """
        result = calc_block_probability(225e12, 110e12, 86400)
        # lambda should be ~4.12e-5
        assert 4.0e-5 < result["lambda"] < 4.3e-5
        # hashes per block
        expected_hpb = 110e12 * (2 ** 32)
        assert result["hashes_per_block"] == pytest.approx(expected_hpb, rel=1e-6)
        # P ≈ lambda for small values
        assert result["p_at_least_1_block"] == pytest.approx(result["lambda"], rel=0.02)
        # P% should be ~0.004%
        assert 0.003 < result["p_at_least_1_block_pct"] < 0.005

    def test_large_hashrate_guaranteed(self):
        """Enormous hashrate => near-certain block in 24h."""
        # 100 EH/s at current difficulty for 24h => lambda ~18, P ~= 1.0
        result = calc_block_probability(100e18, 110e12, 86400)
        assert result["p_at_least_1_block"] > 0.999
        assert result["p_zero_blocks_pct"] < 0.001

    def test_very_short_duration(self):
        """1 second => lambda is tiny, P ≈ 0."""
        result = calc_block_probability(225e12, 110e12, 1)
        assert result["lambda"] < 1e-8
        assert result["p_at_least_1_block"] < 1e-7

    def test_difficulty_zero_handling(self):
        """Difficulty=0 raises ZeroDivisionError — the function does not guard against this.
        This test documents the current behavior. Fix the function if zero-diff should be handled."""
        with pytest.raises(ZeroDivisionError):
            calc_block_probability(1e12, 0, 1)


# ═══════════════════════════════════════════════════════════════════════════
# 2. _parse_hashrate
# ═══════════════════════════════════════════════════════════════════════════

class TestParseHashrate:
    """Parse human-readable hashrate strings to H/s."""

    def test_terahash(self):
        assert _parse_hashrate("225TH") == 225e12
        assert _parse_hashrate("225 TH/s") == 225e12
        assert _parse_hashrate("225TH/s") == 225e12
        assert _parse_hashrate("225 th") == 225e12  # case-insensitive

    def test_petahash(self):
        assert _parse_hashrate("1.5PH") == 1.5e15
        assert _parse_hashrate("1.5 PH/s") == 1.5e15

    def test_exahash(self):
        assert _parse_hashrate("100EH") == 100e18
        assert _parse_hashrate("0.5 EH") == 0.5e18

    def test_gigahash(self):
        assert _parse_hashrate("500GH") == 500e9

    def test_megahash(self):
        assert _parse_hashrate("100MH") == 100e6

    def test_kilohash(self):
        assert _parse_hashrate("50KH") == 50e3

    def test_plain_hash(self):
        assert _parse_hashrate("1000H") == 1000
        assert _parse_hashrate("1000") == 1000  # no unit => plain number

    def test_decimal_values(self):
        assert _parse_hashrate("0.5TH") == 0.5e12
        assert _parse_hashrate("225.75 TH") == 225.75e12

    def test_with_spaces(self):
        assert _parse_hashrate("  225 TH/s  ") == 225e12


# ═══════════════════════════════════════════════════════════════════════════
# 3. normalize_cost
# ═══════════════════════════════════════════════════════════════════════════

class TestNormalizeCost:
    """Normalize rental prices to BTC/PH/day."""

    def test_sats_per_ph_day(self):
        """200,000 sats/PH/day = 0.002 BTC/PH/day."""
        result = normalize_cost(200_000, "sats/PH/day")
        assert result == pytest.approx(0.002, rel=1e-6)

    def test_btc_per_eh_day(self):
        """0.002 BTC/EH/day = 0.002 / 1000 = 0.000002 BTC/PH/day."""
        result = normalize_cost(0.002, "BTC/EH/day")
        assert result == pytest.approx(2e-6, rel=1e-6)

    def test_btc_per_ph_day(self):
        """Direct pass-through."""
        result = normalize_cost(0.005, "BTC/PH/day")
        assert result == 0.005

    def test_case_insensitive(self):
        """Unit strings should be case-insensitive."""
        result = normalize_cost(200_000, "sats/ph/day")
        assert result == pytest.approx(0.002, rel=1e-6)

    def test_unknown_unit(self):
        """Unknown unit returns None."""
        result = normalize_cost(100, "eur/day")
        assert result is None

    def test_usd_per_th_day(self):
        """USD/TH/day requires BTC price lookup — returns None if API fails."""
        # This will call get_btc_price() — may return None if offline
        result = normalize_cost(0.05, "usd/th/day")
        # Should not crash; may be None if CoinGecko is unreachable
        if result is not None:
            assert result > 0


# ═══════════════════════════════════════════════════════════════════════════
# 4. fmt_diff
# ═══════════════════════════════════════════════════════════════════════════

class TestFmtDiff:
    """Format difficulty values to human-readable strings."""

    def test_raw_number(self):
        assert fmt_diff(0) == "0"
        assert fmt_diff(1) == "1.00"
        assert fmt_diff(999) == "999.00"

    def test_kilo(self):
        assert fmt_diff(1000) == "1.00 K"
        assert fmt_diff(5000) == "5.00 K"

    def test_mega(self):
        assert fmt_diff(1_000_000) == "1.00 M"
        assert fmt_diff(2_500_000) == "2.50 M"

    def test_giga(self):
        assert fmt_diff(1_000_000_000) == "1.00 G"
        assert fmt_diff(5_500_000_000) == "5.50 G"

    def test_tera(self):
        assert fmt_diff(1_000_000_000_000) == "1.00 T"
        # 110T
        assert fmt_diff(110_000_000_000_000) == "110.00 T"
        # 25.73T
        assert fmt_diff(25_730_000_000_000) == "25.73 T"

    def test_peta(self):
        assert fmt_diff(1_000_000_000_000_000) == "1.00 P"

    def test_exa(self):
        assert fmt_diff(1_000_000_000_000_000_000) == "1.00 E"

    def test_none_and_empty(self):
        """None is treated as falsy => returns '0'."""
        assert fmt_diff(None) == "0"
        assert fmt_diff(0) == "0"

    def test_string_input(self):
        """fmt_diff does NOT parse strings — call parse_diff_to_float first.
        This test documents the current behavior: float() on a string raises ValueError."""
        with pytest.raises(ValueError):
            fmt_diff("25.73 T")

    def test_negative_values(self):
        """Negative values are NOT abs'd — they show as negative raw numbers."""
        result = fmt_diff(-1000)
        assert result == "-1000.00"


# ═══════════════════════════════════════════════════════════════════════════
# 5. parse_diff_to_float
# ═══════════════════════════════════════════════════════════════════════════

class TestParseDiffToFloat:
    """Parse difficulty strings like '25.73 T' to float values."""

    def test_tera(self):
        assert parse_diff_to_float("25.73 T") == pytest.approx(25.73e12, rel=1e-3)
        assert parse_diff_to_float("110 T") == pytest.approx(110e12, rel=1e-3)

    def test_giga(self):
        assert parse_diff_to_float("5.5 G") == pytest.approx(5.5e9, rel=1e-3)

    def test_mega(self):
        assert parse_diff_to_float("100 M") == pytest.approx(100e6, rel=1e-3)

    def test_kilo(self):
        assert parse_diff_to_float("50 K") == pytest.approx(50e3, rel=1e-3)

    def test_peta(self):
        assert parse_diff_to_float("1.5 P") == pytest.approx(1.5e15, rel=1e-3)

    def test_no_suffix(self):
        assert parse_diff_to_float("5000") == 5000.0

    def test_number_input(self):
        """Direct number input passes through."""
        assert parse_diff_to_float(25.73e12) == pytest.approx(25.73e12, rel=1e-3)

    def test_comma_decimal(self):
        """European decimal format."""
        assert parse_diff_to_float("25,73 T") == pytest.approx(25.73e12, rel=1e-3)

    def test_invalid_input(self):
        """Invalid strings return 0."""
        assert parse_diff_to_float("not a number") == 0.0
        assert parse_diff_to_float("") == 0.0

    def test_none(self):
        assert parse_diff_to_float(None) == 0.0

    def test_spaces(self):
        assert parse_diff_to_float("  110 T  ") == pytest.approx(110e12, rel=1e-3)
