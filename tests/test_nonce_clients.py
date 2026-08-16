"""Issue #150 — todos os clientes HMAC com nonce usam o gerador monotônico.

Cobre o helper compartilhado ``helpers.next_monotonic_nonce_ms`` (sequencial,
concorrência e clock parado/voltando) e o ``solo_mining.get_mrr_listings``
(nonce monotônico nos headers + assinatura HMAC-SHA1 pinada).

``services/tuya_adapter.py`` foi auditado e NÃO se aplica: a Tuya usa nonce
vazio por design (valida a recência do ``t``, não a unicidade) — ver os
comentários no adapter (veredito documentado, anti-regressão).
"""

import hashlib
import hmac
import threading

import pytest

import helpers
import solo_mining


@pytest.fixture(autouse=True)
def _reset_nonce_counter():
    """Hermeticidade: o contador é singleton do processo (helpers)."""
    helpers._nonce_last_ms = 0
    yield
    helpers._nonce_last_ms = 0


# ── helpers.next_monotonic_nonce_ms ────────────────────────────────────────


def test_sequential_nonces_strictly_increasing():
    seen = [int(helpers.next_monotonic_nonce_ms()) for _ in range(5)]
    assert all(b > a for a, b in zip(seen, seen[1:]))


def test_concurrent_nonces_all_unique():
    out = []
    barrier = threading.Barrier(10)

    def worker():
        barrier.wait()
        out.extend([int(helpers.next_monotonic_nonce_ms()) for _ in range(5)])

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(out) == 50
    assert len(set(out)) == 50  # nenhuma colisão sob concorrência


def test_frozen_clock_still_increasing(monkeypatch):
    # Clock parado → o bump last+1 garante monotonicidade (mesmo ms).
    frozen = 1_700_000_000.0
    monkeypatch.setattr(helpers.time, "time", lambda: frozen)
    seen = [int(helpers.next_monotonic_nonce_ms()) for _ in range(3)]
    assert len(set(seen)) == 3
    assert all(b > a for a, b in zip(seen, seen[1:]))


def test_clock_backwards_still_increasing(monkeypatch):
    # Clock voltando atrás também não pode regredir o nonce.
    monkeypatch.setattr(helpers.time, "time", lambda: 1_700_000_000.0)
    first = int(helpers.next_monotonic_nonce_ms())
    monkeypatch.setattr(helpers.time, "time", lambda: 1_600_000_000.0)
    second = int(helpers.next_monotonic_nonce_ms())
    assert second > first


# ── solo_mining.get_mrr_listings (mesmo esquema de assinatura do MRR) ──────


class _FakeResp:
    ok = True

    def json(self):
        return {"success": True, "data": []}


def test_get_mrr_listings_uses_monotonic_nonce(monkeypatch):
    captured = []

    def fake_get(url, headers=None, timeout=0, **kw):
        captured.append((url, headers))
        return _FakeResp()

    monkeypatch.setattr(solo_mining.requests, "get", fake_get)

    solo_mining.get_mrr_listings(api_key="k1", api_secret="s1")
    solo_mining.get_mrr_listings(api_key="k1", api_secret="s1")

    assert len(captured) == 2
    nonces = [h["x-api-nonce"] for _, h in captured]
    # Estritamente crescente mesmo em execução consecutiva (mesmo ms possível).
    assert all(int(b) > int(a) for a, b in zip(nonces, nonces[1:]))

    # Assinatura pinada: HMAC-SHA1(key + nonce + endpoint sem base URL).
    ep = "/rig?type=sha256&order=price"
    url, headers = captured[0]
    assert url.endswith(ep)
    expected = hmac.new(b"s1", f"k1{nonces[0]}{ep}".encode(), hashlib.sha1).hexdigest()
    assert headers["x-api-sign"] == expected
    assert headers["x-api-key"] == "k1"


def test_get_mrr_listings_missing_credentials_no_request(monkeypatch):
    called = []

    def fake_get(url, headers=None, timeout=0, **kw):
        called.append(url)
        return _FakeResp()

    monkeypatch.setattr(solo_mining.requests, "get", fake_get)
    monkeypatch.delenv("MRR_API_KEY", raising=False)
    monkeypatch.delenv("MRR_API_SECRET", raising=False)

    out = solo_mining.get_mrr_listings()
    assert out.get("needs_auth") is True
    assert called == []
