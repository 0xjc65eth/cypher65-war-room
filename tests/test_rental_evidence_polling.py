"""Real cache metadata and tenant-poll evidence handoff regressions (#599)."""

from services import snapshot_assembly as sa
from services import user_polling as up
from services import rental_evidence as evidence


def test_cached_response_preserves_original_retrieval_interval(monkeypatch):
    key = "user_bc1q" + "x" * 30
    monkeypatch.setattr(sa, "_global_cache", {})
    calls = []
    clock = [1000.0]
    monkeypatch.setattr(sa.time, "time", lambda: clock[0])

    def fetch():
        calls.append(1)
        clock[0] = 1002.0
        return {"workerData": [{"id": "exact", "hashrate": 0}]}

    first = sa._cached_user_fetch(key, fetch)
    meta = dict(sa._global_cache[key])
    clock[0] = 1005.0
    assert sa._cached_user_fetch(key, fetch) is first
    assert calls == [1]
    assert sa._global_cache[key] == meta
    assert meta["collection_started_at"] == 1000.0
    assert meta["collection_completed_at"] == 1002.0


def test_private_metadata_collected_once_without_publishing(monkeypatch):
    calls = []
    monkeypatch.setattr(
        evidence, "collect", lambda *a, **kw: calls.append((a, kw)) or []
    )
    worker = up.UserPollingWorker(
        "session", None, "bc1q" + "x" * 30, tenant_id="tenant-a"
    )
    raw = {"workerData": [{"id": "exact", "hashrate": 0}]}
    snapshot = {
        "btc_address": worker.address,
        "_rental_pool_observation": {
            "payload": raw,
            "collection_started_at": 1000.0,
            "collection_completed_at": 1002.0,
        },
    }
    worker._collect_rental_evidence(snapshot)
    worker._collect_rental_evidence(snapshot)
    assert len(calls) == 1
    assert calls[0][0] == ("tenant-a", worker.address)
    assert calls[0][1]["payload"] is raw
    assert "_rental_pool_observation" not in snapshot


def test_collector_failure_keeps_snapshot_and_logs_without_payload(monkeypatch):
    worker = up.UserPollingWorker(
        "session", None, "bc1q" + "x" * 30, tenant_id="tenant-a"
    )

    def fail(*a, **kw):
        raise RuntimeError("simulated database unavailable")

    monkeypatch.setattr(evidence, "collect", fail)
    logged = []
    monkeypatch.setattr(up.log, "exception", lambda message: logged.append(message))
    snapshot = {
        "btc_address": worker.address,
        "_rental_pool_observation": {
            "payload": {"private": "do-not-log-payload"},
            "collection_started_at": 1000.0,
            "collection_completed_at": 1002.0,
        },
    }
    worker._collect_rental_evidence(snapshot)
    assert snapshot == {"btc_address": worker.address}
    assert logged == ["rental_evidence_collection_failed"]
    assert "do-not-log-payload" not in str(logged)


def test_new_evidence_alert_is_mirrored_to_tenant_feed(monkeypatch):
    worker = up.UserPollingWorker(
        "session", None, "bc1q" + "x" * 30, tenant_id="tenant-a"
    )
    event = {
        "provider": "mrr",
        "rental_id": "1",
        "revision": 2,
        "observed_at": 1002,
        "threshold_pct": 90,
        "duration_s": 30,
        "max_gap_s": 15,
    }
    monkeypatch.setattr(evidence, "collect", lambda *a, **kw: [event])
    snapshot = {
        "btc_address": worker.address,
        "_rental_pool_observation": {
            "payload": {},
            "collection_started_at": 1000,
            "collection_completed_at": 1002,
        },
    }
    worker._collect_rental_evidence(snapshot)
    message = evidence.alert_message(event)
    assert "90%" in message and "30 s" in message and "15 s" in message
    assert snapshot["alerts_recent"][0]["category"] == "rental_delivery"
