"""
CYPHER65 // Pool detection REACHES the served payload (Issue #576)
=================================================================
The #574 wired `pool_detection`/`pool_worker` into
`services.snapshot_assembly._build_snapshot()` — the path behind
`/api/session-snapshot` and `POST /api/connect-wallet`. The dashboard does not
poll that path: `fetchSnapshot()` in `static/src/39b-dashboard.js` polls
`/api/snapshot`, which serves `state.latest_snapshot`, assembled by
`app.py::_do_poll()` with its own key list.

Measured in production with the #575 bundle already live: 35 top-level keys,
neither `pool_detection` nor `pool_worker` among them — so `poolDetectionView()`
returned `None` and the panel stayed hidden. Every test was green: the schema
test looked at the session builder, and the e2e **injected** the keys into its
mocked `/api/snapshot`.

These tests pin the delivery, which is what a user actually sees:

- the served `/api/snapshot` carries both keys for the default tenant;
- a NAMED tenant does NOT receive the operator's detection (it is built from the
  operator's fleet telemetry — serving it would leak the owner's pool, host and
  ASIC hashrate);
- every dict literal in `app.py` that builds the global snapshot carries both
  keys, so a new key can never again be added to one producer and forgotten in
  the others.
"""

import ast
import pathlib

import pytest

from app import app as _app
from services.auth import create_token

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_PY = ROOT / "app.py"

DETECTION = {
    "provider_id": "ocean",
    "label": "OCEAN",
    "kind": "pool",
    "chain": "btc",
    "chain_source": "provider_registry",
    "host": "ocean.xyz",
    "has_stats_api": False,
}
WORKER = {"provider_id": "ocean", "label": "OCEAN", "chain": "btc", "source": "asic"}


# The JWT secret is pinned to ONE value for env and app.config on purpose:
# `create_token` (no request context) reads env, while `verify_token` (in the
# request) prefers `app.config["JWT_SECRET_KEY"]`. A test elsewhere in the suite
# that sets the config without restoring it makes a token minted here fail
# verification — the request then falls back to the `default` tenant and the
# named-tenant assertion silently stops testing anything (measured: this test
# passed alone and failed in the full suite before the pin).
_SECRET = "delivery-test-secret-0123456789abcdef"


@pytest.fixture
def client(monkeypatch):
    _app.config["TESTING"] = True
    monkeypatch.setenv("SECRET_KEY", _SECRET)
    saved = _app.config.get("JWT_SECRET_KEY")
    _app.config["JWT_SECRET_KEY"] = _SECRET
    yield _app.test_client()
    if saved is not None:
        _app.config["JWT_SECRET_KEY"] = saved
    else:
        _app.config.pop("JWT_SECRET_KEY", None)


def _snapshot():
    """The smallest dict the enrichment path accepts."""
    return {
        "ts": 1,
        "btc_address": "bc1qexampleaddress000000000000000000000",
        "pool": {"hashrate": 1.0},
        "network": {"hashrate": 6e20, "difficulty": 8e13, "height": 840000},
        "worker": {"hashrate": 1.5e14},
        "pool_detection": DETECTION,
        "pool_worker": WORKER,
    }


@pytest.fixture
def served(monkeypatch):
    """Point the dashboard route at a deterministic global snapshot.

    Fase 6 · PR2: `/api/snapshot` is served by `dashboard_bp`, which reads
    `services.state.latest_snapshot` — not the `app` module global.
    """
    monkeypatch.setattr("services.state.latest_snapshot", _snapshot(), raising=False)
    monkeypatch.setattr(
        "services.snapshot_enrichment._get_hashrate_market_offers", lambda s: [], raising=False
    )
    monkeypatch.setattr(
        "services.hashrate_market.build_highlights", lambda *a, **k: [], raising=False
    )


class TestServedSnapshotCarriesPoolDetection:
    def test_default_tenant_receives_both_keys(self, client, served):
        resp = client.get("/api/snapshot")

        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["pool_detection"] == DETECTION
        assert payload["pool_worker"] == WORKER

    def test_both_keys_survive_as_none_without_a_report(self, client, served, monkeypatch):
        """The panel hides on `None`; a missing key is the bug being fixed."""
        snap = _snapshot()
        snap["pool_detection"] = None
        snap["pool_worker"] = None
        monkeypatch.setattr("services.state.latest_snapshot", snap, raising=False)

        payload = client.get("/api/snapshot").get_json()

        assert "pool_detection" in payload and payload["pool_detection"] is None
        assert "pool_worker" in payload and payload["pool_worker"] is None

    def test_named_tenant_never_receives_the_operator_detection(self, client, served):
        """Fail-closed: the global dict is the INSTANCE OWNER's fleet.

        A named tenant gets its own detection through `/api/session-snapshot`,
        which runs `_build_snapshot` with that tenant's id. Handing them the
        operator's here would disclose the owner's pool, host and hashrate.
        """
        token = create_token(subject="acme", extra_claims={"role": "admin"})

        resp = client.get("/api/snapshot", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200
        payload = resp.get_json()
        # Asserted FIRST: if the token did not resolve, the route served the
        # default-tenant payload and the two assertions below would be vacuous.
        assert payload.get("tenant_scope") == "acme", (
            "o token não resolveu para o tenant 'acme' — o teste estaria medindo "
            f"o caminho do tenant default ({sorted(payload)[:6]}…)"
        )
        assert "pool_detection" not in payload
        assert "pool_worker" not in payload
        # The scoped payload still serves public context — the filter is narrow,
        # not a blanket denial.
        assert payload.get("network")


class TestGlobalSnapshotProducersCarryTheKeys:
    """The bug class, not just the instance: a key added to one producer only.

    Static and format-independent on purpose — `pool_detection` started life in
    exactly this shape (present in the session builder, absent from the global
    ones) and no runtime test could see it.
    """

    KEY = "pool_detection"
    WORKER_KEY = "pool_worker"

    def _snapshot_literals(self):
        tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = {
                k.value
                for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
            # A global snapshot literal is recognised by the two keys every
            # producer has carried since long before this issue.
            if {"btc_address", "pool"} <= keys:
                found.append((node.lineno, keys))
        return found

    def test_module_default_carries_the_keys_from_boot(self):
        """Boot state: the first `/api/snapshot`, served before any poll, has them."""
        import app as app_module

        assert "pool_detection" in app_module.latest_snapshot
        assert "pool_worker" in app_module.latest_snapshot

    def test_every_global_snapshot_literal_shares_the_schema(self):
        literals = self._snapshot_literals()

        assert len(literals) >= 3, (
            "expected at least the module default, reset_memory_state() and "
            f"_do_poll() literals; found {[line for line, _ in literals]}"
        )
        missing = [
            line for line, keys in literals if not {self.KEY, self.WORKER_KEY} <= keys
        ]
        assert not missing, (
            "estes dicts constroem o snapshot global e/ou o seu default mas não "
            f"carregam {{{self.KEY!r}, {self.WORKER_KEY!r}}} (app.py linhas "
            f"{missing}) — o /api/snapshot serviria sem as chaves e a faixa da "
            "pool ficaria oculta (Issue #576)"
        )
