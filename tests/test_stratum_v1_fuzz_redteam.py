"""Deterministic parser fuzzing and hermetic connector red-team cases."""

import json
import random
import socket

import pytest

from services.pool_intelligence import (
    DestinationPolicy,
    PolicyError,
    PoolResolution,
    StratumV1ProbeError,
    StratumV1ResponseError,
    ValidatedDestination,
    parse_pool_endpoint,
    probe_stratum_v1,
    resolve_pool_destination,
    validate_stratum_v1_subscribe_response,
)


CONTROLLED_RESPONSE_CODES = {
    "invalid_json",
    "invalid_response",
    "subscribe_rejected",
    "invalid_subscribe_result",
    "response_too_large",
}
VALID_RESPONSE = (
    b'{"id":1,"result":[[["mining.notify","session"]],"01",4],' b'"error":null}'
)


class _ProbeSocket:
    def __init__(self, response=VALID_RESPONSE):
        self.response = response
        self.targets = []

    def settimeout(self, timeout):
        assert 0 < timeout <= 30

    def connect(self, target):
        self.targets.append(target)

    def sendall(self, payload):
        assert b"mining.subscribe" in payload

    def recv(self, size):
        chunk, self.response = self.response[:size], self.response[size:]
        return chunk + (b"\n" if self.response == b"" else b"")

    def close(self):
        return None


def _dns_record(address):
    return (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 3333))


def test_public_validator_accepts_only_a_strict_subscribe_shape():
    assert validate_stratum_v1_subscribe_response(VALID_RESPONSE) is None


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (
            b'{"id":true,"result":[[["mining.notify","s"]],"01",4],"error":null}',
            "invalid_response",
        ),
        (
            b'{"id":1,"id":1,"result":[[["mining.notify","s"]],"01",4],"error":null}',
            "invalid_json",
        ),
        (b'{"id":1,"result":[[["mining.notify","s"]],"01",4]}', "invalid_response"),
        (b'{"id":1,"result":[[],"01",4],"error":null}', "invalid_subscribe_result"),
        (
            b'{"id":1,"result":[[["other","s"]],"01",4],"error":null}',
            "invalid_subscribe_result",
        ),
        (
            b'{"id":1,"result":[[[1,2]],"01",4],"error":null}',
            "invalid_subscribe_result",
        ),
        (
            b'{"id":1,"result":[[["mining.notify","s"]],"0",4],"error":null}',
            "invalid_subscribe_result",
        ),
        (
            b'{"id":1,"result":[[["mining.notify","s"]],"zz",4],"error":null}',
            "invalid_subscribe_result",
        ),
        (
            b'{"id":1,"result":[[["mining.notify","s"]],"01",true],"error":null}',
            "invalid_subscribe_result",
        ),
        (
            b'{"id":1,"result":null,"error":[20,"remote-secret",null]}',
            "subscribe_rejected",
        ),
        (b"[" * 2_000 + b"0" + b"]" * 2_000, "invalid_response"),
        (b"x" * 65_537, "response_too_large"),
    ],
)
def test_adversarial_subscribe_corpus_fails_with_controlled_codes(payload, code):
    with pytest.raises(StratumV1ResponseError) as exc_info:
        validate_stratum_v1_subscribe_response(payload)

    assert exc_info.value.code == code
    assert str(exc_info.value) == code
    assert "remote-secret" not in str(exc_info.value)


def test_seeded_byte_fuzzer_never_escapes_an_uncontrolled_exception():
    generator = random.Random(0xC65)

    for _ in range(5_000):
        payload = generator.randbytes(generator.randrange(0, 4_097))
        try:
            validate_stratum_v1_subscribe_response(payload)
        except StratumV1ResponseError as exc:
            assert exc.code in CONTROLLED_RESPONSE_CODES


def test_seeded_structured_fuzzer_rejects_mutated_shapes_fail_closed():
    generator = random.Random(0x51A7)
    baseline = {
        "id": 1,
        "result": [[["mining.notify", "session"]], "01", 4],
        "error": None,
    }
    invalid_by_field = {
        "id": [None, True, False, -1, 0, 1.5, "", {}, []],
        "result": [None, True, False, -1, 0, 1.5, "", {}, []],
        "error": [True, False, -1, 0, 1, 1.5, "error", {}, []],
    }

    for _ in range(1_000):
        message = dict(baseline)
        field = generator.choice(("id", "result", "error"))
        message[field] = generator.choice(invalid_by_field[field])
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        with pytest.raises(StratumV1ResponseError) as exc_info:
            validate_stratum_v1_subscribe_response(payload)
        assert exc_info.value.code in CONTROLLED_RESPONSE_CODES


def test_rebinding_resolver_is_called_once_and_socket_uses_only_first_public_ip():
    calls = 0
    probe_socket = _ProbeSocket()

    def rebinding_resolver(*args, **kwargs):
        nonlocal calls
        calls += 1
        address = "8.8.8.8" if calls == 1 else "169.254.169.254"
        return [_dns_record(address)]

    endpoint = parse_pool_endpoint("pool.example.test:3333")
    resolution = resolve_pool_destination(
        endpoint,
        DestinationPolicy(),
        resolver=rebinding_resolver,
    )
    result = probe_stratum_v1(
        resolution,
        socket_factory=lambda *args: probe_socket,
    )

    assert result.healthy is True
    assert calls == 1
    assert probe_socket.targets == [("8.8.8.8", 3333)]


def test_mixed_dns_ssrf_answer_fails_before_any_socket_exists():
    socket_created = False

    def socket_factory(*args):
        nonlocal socket_created
        socket_created = True
        return _ProbeSocket()

    endpoint = parse_pool_endpoint("pool.example.test:3333")
    with pytest.raises(PolicyError):
        resolution = resolve_pool_destination(
            endpoint,
            DestinationPolicy(),
            resolver=lambda *args, **kwargs: [
                _dns_record("8.8.8.8"),
                _dns_record("169.254.169.254"),
            ],
        )
        probe_stratum_v1(resolution, socket_factory=socket_factory)

    assert socket_created is False


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "169.254.169.254", "::ffff:127.0.0.1"]
)
def test_forged_private_resolution_is_revalidated_before_socket_creation(address):
    endpoint = parse_pool_endpoint("pool.example.test:3333")
    forged = PoolResolution(
        destination=ValidatedDestination(
            endpoint=endpoint,
            addresses=(address,),
            local_pool_mode=False,
        ),
        dns_latency_ms=0,
    )
    socket_created = False

    def socket_factory(*args):
        nonlocal socket_created
        socket_created = True
        return _ProbeSocket()

    with pytest.raises(StratumV1ProbeError, match="connector policy"):
        probe_stratum_v1(forged, socket_factory=socket_factory)

    assert socket_created is False


@pytest.mark.parametrize(
    ("dns_latency", "local_pool_mode"),
    [
        (True, False),
        (-1, False),
        (float("nan"), False),
        ("1", False),
        (0, "authorized"),
    ],
)
def test_forged_resolution_metadata_fails_before_socket_creation(
    dns_latency, local_pool_mode
):
    endpoint = parse_pool_endpoint("pool.example.test:3333")
    forged = PoolResolution(
        destination=ValidatedDestination(
            endpoint=endpoint,
            addresses=("8.8.8.8",),
            local_pool_mode=local_pool_mode,
        ),
        dns_latency_ms=dns_latency,
    )

    with pytest.raises(StratumV1ProbeError, match="malformed"):
        probe_stratum_v1(forged, socket_factory=lambda *args: pytest.fail("socket"))


def test_validator_rejects_non_bytes_as_programmer_error():
    with pytest.raises(StratumV1ProbeError, match="must be bytes"):
        validate_stratum_v1_subscribe_response("not-bytes")


def test_public_error_and_resolution_types_reject_programmer_misuse():
    with pytest.raises(ValueError, match="failure code"):
        StratumV1ResponseError("remote-controlled-code")
    with pytest.raises(StratumV1ProbeError, match="PoolResolution"):
        probe_stratum_v1(object())
