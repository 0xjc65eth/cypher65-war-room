"""Bound the fixed pool-user API response before JSON decoding (#599)."""

import json

import pytest

from services import snapshot_assembly as sa


class Response:
    def __init__(self, chunks, status=200):
        self.chunks = chunks
        self.status_code = status
        self.closed = False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        assert chunk_size == 8192
        yield from self.chunks

    def close(self):
        self.closed = True


def _fetch(monkeypatch, response):
    calls = []
    monkeypatch.setattr(
        sa.requests, "get", lambda url, **kwargs: calls.append(kwargs) or response
    )
    monkeypatch.setattr(sa.time, "sleep", lambda duration: None)
    result = sa._fetch_json(sa.PARASITE_API + "/user/bc1q" + "x" * 30)
    assert response.closed
    assert all(
        call["timeout"] == 10 and call["stream"] and call["allow_redirects"] is False
        for call in calls
    )
    return result, calls


def test_bounded_pool_read_preserves_raw_zero_and_selector(monkeypatch):
    payload = {"workerData": [{"id": "exact", "name": "raw.name", "hashrate": 0}]}
    response = Response([json.dumps(payload).encode()])
    result, calls = _fetch(monkeypatch, response)
    assert result == payload
    assert len(calls) == 1


def test_oversized_decompressed_body_is_not_decoded_or_retried(monkeypatch):
    monkeypatch.setattr(sa, "MAX_USER_RESPONSE_BYTES", 8)
    response = Response([b"1234", b"56789", b"must-not-be-read"])
    result, calls = _fetch(monkeypatch, response)
    assert result == {"_rental_quality": "oversized"}
    assert len(calls) == 1


def test_worker_limit_does_not_return_a_partial_catalog(monkeypatch):
    payload = {"workerData": [{"id": str(i), "hashrate": 0} for i in range(251)]}
    result, calls = _fetch(monkeypatch, Response([json.dumps(payload).encode()]))
    assert result == {"_rental_quality": "oversized"}
    assert len(calls) == 1


def test_read_deadline_is_bounded(monkeypatch):
    moments = iter([1, 12])
    monkeypatch.setattr(sa.time, "monotonic", lambda: next(moments))
    result, calls = _fetch(monkeypatch, Response([b"{}"]))
    assert result == {"_rental_quality": "oversized"}
    assert len(calls) == 1


@pytest.mark.parametrize("chunks,status", [([b"not-json"], 200), ([b"{}"], 302)])
def test_invalid_json_or_redirect_returns_no_reading_with_bounded_retries(
    monkeypatch, chunks, status
):
    result, calls = _fetch(monkeypatch, Response(chunks, status))
    assert result is None
    assert len(calls) == sa.FETCH_MAX_RETRIES + 1
