"""Auth, tenant context and response-header tests for rental evidence routes."""

import time

import pytest

import app as app_module
from services import rental_evidence as evidence
from services.auth import create_token
from services.bootstrap import init_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = str(tmp_path / "rental-evidence-routes.sqlite")
    monkeypatch.setenv("DB_PATH", path)
    monkeypatch.setenv("API_KEY", "evidence-test-key")
    app = app_module.app
    app.config["TESTING"] = True
    saved_secret = app.config.get("JWT_SECRET_KEY")
    app.config["JWT_SECRET_KEY"] = "rental-evidence-test-secret-0123456789"
    init_db()
    with app.test_client() as test_client:
        yield test_client
    if saved_secret is None:
        app.config.pop("JWT_SECRET_KEY", None)
    else:
        app.config["JWT_SECRET_KEY"] = saved_secret


def _headers(tenant="tenant-a", role="viewer"):
    with app_module.app.app_context():
        token = create_token(subject=tenant, extra_claims={"role": role})
    return {"Authorization": f"Bearer {token}"}


def _source(tenant="tenant-a"):
    now = time.time()
    evidence.collect(
        tenant,
        "bc1qroutetestaddress000",
        {"workerData": [{"id": "worker-api-1", "name": "rental", "hashrate": 80e12}]},
        now,
        now,
    )
    return evidence.read(tenant, "mrr", "rental-1")["sources"][0]["id"]


def _body(source_id):
    return {
        "source_id": source_id,
        "contract_th": 100,
        "threshold_pct": 90,
        "duration_s": 60,
        "max_gap_s": 30,
        "exclusive_worker": True,
    }


def test_read_route_requires_authenticated_viewer_and_disables_caching(client):
    anonymous = client.get(
        "/api/rentals/rental-1/evidence",
        environ_base={"REMOTE_ADDR": "203.0.113.7"},
    )
    assert anonymous.status_code == 403

    response = client.get(
        "/api/rentals/rental-1/evidence",
        headers=_headers(role="viewer"),
        environ_base={"REMOTE_ADDR": "203.0.113.7"},
    )
    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
    assert response.get_json()["success"] is True


def test_config_and_delete_require_member_role(client):
    source_id = _source()
    viewer = client.post(
        "/api/rentals/rental-1/evidence",
        json=_body(source_id),
        headers=_headers(role="viewer"),
        environ_base={"REMOTE_ADDR": "203.0.113.7"},
    )
    assert viewer.status_code == 403

    member = client.post(
        "/api/rentals/rental-1/evidence",
        json=_body(source_id),
        headers=_headers(role="member"),
        environ_base={"REMOTE_ADDR": "203.0.113.7"},
    )
    assert member.status_code == 200
    assert "no-store" in member.headers["Cache-Control"]
    assert member.get_json()["binding"]["exclusive_worker"] is True

    deleted = client.delete(
        "/api/rentals/rental-1/evidence",
        headers=_headers(role="member"),
        environ_base={"REMOTE_ADDR": "203.0.113.7"},
    )
    assert deleted.status_code == 200
    assert deleted.get_json()["binding"] is None


def test_tenant_is_resolved_from_token_and_read_export_are_scoped(client):
    source_id_a = _source("tenant-a")
    source_id_b = _source("tenant-b")
    with app_module.app.app_context():
        tenant_a = create_token("tenant-a", extra_claims={"role": "member"})
        tenant_b = create_token("tenant-b", extra_claims={"role": "member"})
    headers_a = {"Authorization": f"Bearer {tenant_a}"}
    headers_b = {"Authorization": f"Bearer {tenant_b}"}
    for headers, source_id in ((headers_a, source_id_a), (headers_b, source_id_b)):
        response = client.post(
            "/api/rentals/shared-id/evidence",
            json=_body(source_id),
            headers=headers,
            environ_base={"REMOTE_ADDR": "203.0.113.7"},
        )
        assert response.status_code == 200

    read_a = client.get(
        "/api/rentals/shared-id/evidence", headers=headers_a,
        environ_base={"REMOTE_ADDR": "203.0.113.7"},
    )
    assert read_a.status_code == 200
    source_ids = {s["id"] for s in read_a.get_json()["sources"]}
    assert source_id_a in source_ids
    assert source_id_b not in source_ids

    export_a = client.get(
        "/api/rentals/shared-id/evidence/export", headers=headers_a,
        environ_base={"REMOTE_ADDR": "203.0.113.7"},
    )
    assert export_a.status_code == 200
    assert export_a.mimetype == "text/csv"
    assert "no-store" in export_a.headers["Cache-Control"]
    assert export_a.headers["X-Content-Type-Options"] == "nosniff"
    assert export_a.headers["X-Evidence-Retention"]


@pytest.mark.parametrize(
    "path,method,kwargs",
    [
        ("/api/rentals/bad%20id/evidence", "get", {}),
        ("/api/rentals/rental-1/evidence?provider=unknown", "get", {}),
        ("/api/rentals/rental-1/evidence", "post", {"json": {"not": "valid"}}),
        ("/api/rentals/bad%20id/evidence/export", "get", {}),
    ],
)
def test_invalid_route_inputs_fail_with_client_error(client, path, method, kwargs):
    response = getattr(client, method)(
        path,
        headers=_headers(role="member"),
        environ_base={"REMOTE_ADDR": "203.0.113.7"},
        **kwargs,
    )
    assert response.status_code == 400
    assert response.get_json()["success"] is False
