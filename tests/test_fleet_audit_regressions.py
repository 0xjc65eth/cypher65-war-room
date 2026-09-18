"""CYPHER65 // Fleet audit regressions (Issue #627).

Real production reports turned into permanent regression tests:

  BUG A — agentless dead-end: with no agent and a failing scan the operator
          MUST still see the manual-add path (wizard method card + empty-state
          button). The old wiring bailed on a missing header chip and left the
          empty-state button dead.
  BUG B — "miner online but no P Share": the P Share of THIS repo is the
          Best Share (``best_diff`` lineage: cgminer ``Best Share`` / AxeOS
          ``bestDiff`` / Braiins ``best_share``). Two defects:
            * `str(x or "")` collapsed a VERIFIED 0 into "" (fake unsupported);
            * an empty agent heartbeat ({}) kept devices IDLE + fresh
              last_seen forever — an ONLINE-looking state with no telemetry.
  BUG C — unknown/new pools must not crash and must stay usable as generic
          stratum endpoints (AtlasPool verified live via passive probe).

Every network-facing test runs against either the in-process Flask test
client or a scratch SQLite registry — never against a real miner, and the
pool tests are pure string/registry checks (no DNS, no sockets).
"""

import json
import sqlite3
import time
from unittest.mock import patch

import pytest

from app import app as _app
from services.auth import create_token
from axe_fleet.connector import AxeOSConnector
from axe_fleet.models import (
    STATUS_OFFLINE,
    STATUS_ONLINE,
    STATUS_STALE,
    best_diff_from_value,
    derive_device_status,
    is_telemetry_stale,
)
from axe_fleet.registry import DeviceRegistry
from services.pool_intelligence import Chain, PoolKind, detect_provider


# ══════════════════════════════════════════════════════════════════════════
#  Fixtures — hermetic scratch SQLite + Flask test client (test_agent_api)
# ══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def registry(tmp_path):
    """Real DeviceRegistry on a scratch SQLite file (no network)."""
    db_path = str(tmp_path / "fleet_audit.sqlite")

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    r = DeviceRegistry(get_db)
    r.ensure_tables()
    return r


@pytest.fixture
def client(monkeypatch):
    _app.config["TESTING"] = True
    saved = _app.config.get("JWT_SECRET_KEY")
    secret = "fleet-audit-secret-0123456789abcdef"
    _app.config["JWT_SECRET_KEY"] = secret
    # app.config + env in sync (same pattern as tests/test_agent_api.py) —
    # create_token() reads the env when called outside an app context.
    monkeypatch.setenv("SECRET_KEY", secret)
    with _app.test_client() as c:
        yield c
    if saved is not None:
        _app.config["JWT_SECRET_KEY"] = saved
    else:
        _app.config.pop("JWT_SECRET_KEY", None)


@pytest.fixture
def user_token():
    return create_token(subject="acme", extra_claims={"role": "admin"})


@pytest.fixture
def agent_token():
    return create_token(
        subject="acme",
        ttl=365 * 86400,
        extra_claims={"agent": True, "role": "agent"},
    )


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


# ══════════════════════════════════════════════════════════════════════════
#  P Share (Best Share) lineage — BUG B part 1
# ══════════════════════════════════════════════════════════════════════════


class TestBestShareNormalization:
    """The ONE normalizer every producer must use (models.best_diff_from_value).

    Fixtures per the audit contract: positive numeric, 0, null/undefined,
    string numeric, magnitudes, scientific notation, bool garbage.
    """

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, ""),  # null/undefined → "—" in the UI, NEVER 0
            (0, "0"),  # verified zero stays zero
            (0.0, "0"),
            ("0", "0"),
            ("0.0", "0"),
            ("1.23M", "1.23M"),  # magnitude strings pass through
            (482000000, "482000000"),  # scientific-notation-capable floats
            (5e8, "500000000.0"),
            ("42.8T", "42.8T"),
            (" 1234 ", "1234"),  # trimmed
            (True, ""),  # bool garbage → unsupported, not a number
        ],
    )
    def test_fixtures(self, raw, expected):
        assert best_diff_from_value(raw) == expected

    def test_legacy_idiom_is_dead(self):
        """The bug being pinned: `str(x or "")` collapsed 0 into ""."""
        assert best_diff_from_value(0) == "0"
        assert str(0 or "") != best_diff_from_value(0)

    def test_connector_preserves_zero_best_diff(self):
        """Server-side poll path: extract_telemetry must keep a real 0."""
        conn = AxeOSConnector("127.0.0.1", port=1, timeout=1)
        tel = conn.extract_telemetry({"hashrate": 0, "bestDiff": 0})
        assert tel["best_diff"] == "0"

    def test_connector_none_best_diff_stays_empty(self):
        conn = AxeOSConnector("127.0.0.1", port=1, timeout=1)
        tel = conn.extract_telemetry({"hashrate": 1000})
        assert tel["best_diff"] == ""


# ══════════════════════════════════════════════════════════════════════════
#  Online-state semantics — BUG B part 2 (fleet_online_requires_recent_signal)
# ══════════════════════════════════════════════════════════════════════════


class TestOnlineStateSemantics:
    def test_stale_helper_pure(self):
        now = 1_800_000_000
        assert is_telemetry_stale(now - 16 * 60, now=now) is True
        assert is_telemetry_stale(now - 60, now=now) is False
        assert is_telemetry_stale(None, now=now) is True
        assert is_telemetry_stale(0, now=now) is True

    def test_empty_heartbeat_never_says_online(self, registry):
        """A device that never produced a measurement is OFFLINE, not IDLE."""
        dev = registry.upsert_agent_device("192.168.77.10", tenant_id="acme")
        registry.save_agent_telemetry(dev["id"], {}, tenant_id="acme")
        stored = registry.get_device(dev["id"], tenant_id="acme")
        assert stored["status"] == STATUS_OFFLINE
        # Presence WAS recorded (heartbeat works), only the state is honest.
        assert stored["last_seen"] > 0

    def test_empty_heartbeat_after_horizon_is_stale(self, registry):
        """fleet_stale_telemetry_transitions_state — measured data gone old."""
        dev = registry.upsert_agent_device("192.168.77.11", tenant_id="acme")
        old = int(time.time()) - 16 * 60
        registry.save_agent_telemetry(
            dev["id"], {"hashrate_hs": 1000, "ts": old}, tenant_id="acme"
        )
        registry.save_agent_telemetry(dev["id"], {}, tenant_id="acme")
        stored = registry.get_device(dev["id"], tenant_id="acme")
        assert stored["status"] == STATUS_STALE

    def test_fresh_measured_reading_keeps_live_status(self, registry):
        """A healthy miner with a recent reading is NOT degraded."""
        dev = registry.upsert_agent_device("192.168.77.12", tenant_id="acme")
        registry.save_agent_telemetry(
            dev["id"], {"hashrate_hs": 4800000000000}, tenant_id="acme"
        )
        # Even a later empty heartbeat (one failed poll) keeps the live status.
        registry.save_agent_telemetry(dev["id"], {}, tenant_id="acme")
        stored = registry.get_device(dev["id"], tenant_id="acme")
        assert stored["status"] == STATUS_ONLINE

    def test_stale_status_is_not_online_for_summaries(self):
        """device_status_is_online must treat STALE as not-reachable."""
        from core.models.device import device_status_is_online

        assert device_status_is_online(STATUS_STALE) is False
        assert device_status_is_online(STATUS_ONLINE) is True

    def test_list_devices_degrades_old_online_rows(self, registry):
        """The read path: an ONLINE row with old telemetry reads STALE."""
        dev = registry.upsert_agent_device("192.168.77.13", tenant_id="acme")
        old = int(time.time()) - 3600
        registry.save_agent_telemetry(
            dev["id"], {"hashrate_hs": 999, "ts": old}, tenant_id="acme"
        )
        # Force the row back to ONLINE as an old producer would have left it.
        registry.update_device(dev["id"], {"status": STATUS_ONLINE}, tenant_id="acme")
        devices = registry.list_devices(tenant_id="acme", with_telemetry=True)
        assert devices[0]["status"] == STATUS_STALE

    def test_derive_device_status_unchanged_for_measured_payloads(self):
        """Existing contract preserved: measured payloads decide ONLINE/IDLE."""
        assert derive_device_status({"hashrate_hs": 10}) == STATUS_ONLINE
        assert derive_device_status({"hashrate_hs": 0}) == "IDLE"


# ══════════════════════════════════════════════════════════════════════════
#  BUG A — agentless manual add must never be a dead end
# ══════════════════════════════════════════════════════════════════════════


class TestFleetAgentless:
    def test_agentless_manual_add_visible(self, client):
        """Both add entry points exist in the served shell: the wizard's
        manual method card and the empty-state button."""
        resp = client.get("/")
        assert resp.status_code == 200, "dashboard shell must serve"
        html = resp.get_data(as_text=True)
        assert 'data-wiz-method="manual"' in html, "manual method card missing"
        assert "Enter IP manually" in html
        assert 'id="axe-empty-add"' in html, "empty-state add button missing"
        assert "+ Add Device" in html

    def test_agentless_scan_explains_limitations(self, client, monkeypatch):
        """On a cloud deploy the scan refuses HONESTLY and names the
        alternative (local agent) instead of pretending to work."""
        monkeypatch.setenv("RENDER", "true")
        resp = client.post("/api/network/scan")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert data["is_cloud"] is True
        assert "AGENTE LOCAL" in data["message"]

    def test_manual_add_still_possible_with_private_ip_off_cloud(
        self, client, user_token, registry
    ):
        """Self-hosted: a private LAN IP add works (only the agent cap and
        duplicates reject), and the response is a 201 with the device."""
        with patch("axe_fleet.routes._registry", registry), patch(
            "config.is_cloud_deploy", return_value=False
        ):
            resp = client.post(
                "/api/axe-fleet/devices",
                headers=_headers(user_token),
                json={"ip_address": "192.168.1.77", "name": "garage"},
            )
        assert resp.status_code == 201
        assert resp.get_json()["success"] is True


# ══════════════════════════════════════════════════════════════════════════
#  BUG C — pools: unknown must not crash, AtlasPool must be recognised
# ══════════════════════════════════════════════════════════════════════════


class TestPoolSupport:
    def test_fleet_unknown_pool_does_not_crash(self):
        """An endpoint no registry entry matches degrades to an honest
        unknown — never an exception, never a fabricated provider."""
        detection = detect_provider("stratum+tcp://totally-unknown.example:5555")
        assert detection.provider_id == "unknown"
        assert detection.provider is None

    def test_fleet_atlas_pool_detected(self):
        """AtlasPool: verified live via passive mining.subscribe probe
        (2026-09-17) — recognised as a BTC solo stratum pool."""
        detection = detect_provider("stratum+tcp://solo.atlaspool.io:3333")
        assert detection.provider_id == "atlaspool"
        assert detection.provider.kind is PoolKind.SOLO
        assert detection.provider.chain is Chain.BTC

    def test_fleet_generic_stratum_pool_supported(self):
        """Custom host/port pools stay usable: host is extracted with the
        custom port intact so the operator can point a miner at anything."""
        from services.pool_intelligence import stratum_host

        assert stratum_host("stratum+tcp://my-own-box.lan:5555") == "my-own-box.lan"
        assert stratum_host("my-own-box.lan:5555") == "my-own-box.lan"

    def test_new_solo_pools_are_registered(self):
        """The audit additions exist as stratum_only entries (no fabricated
        stats APIs)."""
        from services.pool_intelligence.providers import provider_by_id

        for pid in ("atlaspool", "braiins_solo", "solohash", "satoshi_radio"):
            provider = provider_by_id(pid)
            assert provider is not None, pid
            assert not provider.has_stats_api, f"{pid} must be stratum_only"


# ══════════════════════════════════════════════════════════════════════════
#  End-to-end through the agent HTTP API (register → telemetry → read)
# ══════════════════════════════════════════════════════════════════════════


class TestAgentTelemetryApiRegressions:
    def _register(self, client, agent_token, registry, ip):
        with patch("axe_fleet.routes._registry", registry):
            resp = client.post(
                "/api/agent/register",
                headers=_headers(agent_token),
                json={"devices": [{"ip": ip, "type": "bitaxe", "model": "NerdQaxe++"}]},
            )
        assert resp.status_code == 201

    def test_fleet_online_with_missing_share_does_not_display_zero(
        self, client, user_token, agent_token, registry
    ):
        """Miner hashing but firmware reports no bestDiff: the payload must
        carry best_diff="" (UI '—'), never an invented 0 — and with a
        VERIFIED 0 it must stay "0"."""
        self._register(client, agent_token, registry, "192.168.77.50")
        with patch("axe_fleet.routes._registry", registry):
            first = client.post(
                "/api/agent/telemetry",
                headers=_headers(agent_token),
                json={
                    "ip": "192.168.77.50",
                    "telemetry": {"hashrate_hs": 4800000000000, "temperature": 58.0},
                },
            )
            assert first.status_code == 200
            assert first.get_json()["status"] == STATUS_ONLINE
            devices = client.get(
                "/api/axe-fleet/devices", headers=_headers(user_token)
            ).get_json()["devices"]
            # best_diff ABSENT from the push stays absent — the UI renders an
            # honest '—' (never an invented 0).
            assert "best_diff" not in devices[0]["telemetry"]

            # A verified zero survives: "0" in, "0" stored.
            second = client.post(
                "/api/agent/telemetry",
                headers=_headers(agent_token),
                json={
                    "ip": "192.168.77.50",
                    "telemetry": {"hashrate_hs": 1, "best_diff": "0"},
                },
            )
            assert second.status_code == 200
            devices = client.get(
                "/api/axe-fleet/devices", headers=_headers(user_token)
            ).get_json()["devices"]
            assert devices[0]["telemetry"]["best_diff"] == "0"

    def test_empty_heartbeat_does_not_hide_a_dead_miner(
        self, client, user_token, agent_token, registry
    ):
        """Reproduces 'diz que o miner tá on' — heartbeat-only pushes must
        NOT keep the miner green when no measurement is coming in."""
        self._register(client, agent_token, registry, "192.168.77.51")
        with patch("axe_fleet.routes._registry", registry):
            # Dead miner: only empty heartbeats, no measured reading ever.
            client.post(
                "/api/agent/telemetry",
                headers=_headers(agent_token),
                json={"ip": "192.168.77.51", "telemetry": {}},
            )
            devices = client.get(
                "/api/axe-fleet/devices", headers=_headers(user_token)
            ).get_json()["devices"]
            assert devices[0]["status"] == STATUS_OFFLINE

    def test_agent_register_then_stale_heartbeat(
        self, client, user_token, agent_token, registry
    ):
        """Full timeline: healthy → measurements stop → STALE surfaces."""
        self._register(client, agent_token, registry, "192.168.77.52")
        with patch("axe_fleet.routes._registry", registry):
            healthy = client.post(
                "/api/agent/telemetry",
                headers=_headers(agent_token),
                json={
                    "ip": "192.168.77.52",
                    "telemetry": {"hashrate_hs": 1000, "temperature": 55.0},
                },
            )
            assert healthy.get_json()["status"] == STATUS_ONLINE
            # Miner died 16+ minutes ago (in payload time), heartbeats flow.
            old = int(time.time()) - 16 * 60
            client.post(
                "/api/agent/telemetry",
                headers=_headers(agent_token),
                json={
                    "ip": "192.168.77.52",
                    "telemetry": {"hashrate_hs": 1000, "ts": old},
                },
            )
            client.post(
                "/api/agent/telemetry",
                headers=_headers(agent_token),
                json={"ip": "192.168.77.52", "telemetry": {}},
            )
            devices = client.get(
                "/api/axe-fleet/devices", headers=_headers(user_token)
            ).get_json()["devices"]
            assert devices[0]["status"] == STATUS_STALE

    def test_summary_counts_stale_as_not_online(self, client, user_token, registry):
        dev = registry.upsert_agent_device("192.168.77.53", tenant_id="acme")
        registry.update_device(dev["id"], {"status": STATUS_STALE}, tenant_id="acme")
        with patch("axe_fleet.routes._registry", registry):
            resp = client.get("/api/axe-fleet/summary", headers=_headers(user_token))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["online"] == 0
