"""Security and protocol tests for the pinned Stratum V1 probe."""

import json
import socket
import ssl

import pytest

from services.pool_intelligence import (
    CapabilityState,
    DestinationPolicy,
    PolicyError,
    PoolProtocol,
    PoolResolution,
    ResolutionError,
    StratumV1ProbeError,
    ValidatedDestination,
    parse_pool_endpoint,
    probe_stratum_v1,
    resolve_pool_destination,
)
from tests.virtual_pool.stratum_v1_lab import StratumV1Lab


def _record(address: str) -> tuple:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr = (address, 3333, 0, 0) if family == socket.AF_INET6 else (address, 3333)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)


def _resolution(address: str, port: int, *, tls: bool = False) -> PoolResolution:
    scheme = "stratum+tls" if tls else "stratum+tcp"
    endpoint = parse_pool_endpoint(f"{scheme}://pool.example.test:{port}")
    return PoolResolution(
        destination=ValidatedDestination(
            endpoint=endpoint,
            addresses=(address,),
            local_pool_mode=False,
        ),
        dns_latency_ms=1.25,
    )


def test_resolver_runs_once_and_returns_policy_validated_addresses():
    calls = []

    def resolver(*args, **kwargs):
        calls.append((args, kwargs))
        return [_record("8.8.8.8"), _record("1.1.1.1"), _record("8.8.8.8")]

    endpoint = parse_pool_endpoint("pool.example.test:3333")
    result = resolve_pool_destination(
        endpoint,
        DestinationPolicy(),
        resolver=resolver,
    )

    assert len(calls) == 1
    assert result.destination.addresses == ("8.8.8.8", "1.1.1.1")
    assert result.dns_latency_ms >= 0


def test_mixed_public_private_dns_answer_fails_before_probe():
    endpoint = parse_pool_endpoint("pool.example.test:3333")

    with pytest.raises(PolicyError):
        resolve_pool_destination(
            endpoint,
            DestinationPolicy(),
            resolver=lambda *args, **kwargs: [
                _record("8.8.8.8"),
                _record("127.0.0.1"),
            ],
        )


def test_resolver_caps_answers_and_sanitizes_dns_failures():
    endpoint = parse_pool_endpoint("pool.example.test:3333")
    too_many = [_record(f"8.8.8.{index}") for index in range(1, 18)]
    with pytest.raises(PolicyError, match="too many"):
        resolve_pool_destination(
            endpoint,
            DestinationPolicy(),
            resolver=lambda *args, **kwargs: too_many,
        )

    def failed_resolver(*args, **kwargs):
        raise socket.gaierror("resolver-internal-secret")

    with pytest.raises(ResolutionError, match="did not resolve") as exc_info:
        resolve_pool_destination(
            endpoint,
            DestinationPolicy(),
            resolver=failed_resolver,
        )
    assert "internal-secret" not in str(exc_info.value)

    with pytest.raises(ResolutionError, match="invalid record"):
        resolve_pool_destination(
            endpoint,
            DestinationPolicy(),
            resolver=lambda *args, **kwargs: [(socket.AF_INET,)],
        )


def test_virtual_lab_is_stateful_and_probe_reports_v1_health():
    with StratumV1Lab() as lab:
        socket_factory = _lab_socket_factory(lab.port)
        first = probe_stratum_v1(
            _resolution("8.8.8.8", lab.port), socket_factory=socket_factory
        )
        second = probe_stratum_v1(
            _resolution("8.8.8.8", lab.port), socket_factory=socket_factory
        )

    assert first.healthy is True
    assert first.protocol is PoolProtocol.STRATUM_V1
    assert first.capability is CapabilityState.SUPPORTED
    assert first.connected_address == "8.8.8.8"
    assert first.failure_code is None
    assert first.tcp_latency_ms is not None
    assert first.stratum_latency_ms is not None
    assert first.total_latency_ms >= first.dns_latency_ms
    assert second.healthy is True
    assert lab.request_count == 2
    request = json.loads(lab.last_request.decode("ascii"))
    assert request["method"] == "mining.subscribe"
    assert "worker" not in lab.last_request.decode("ascii").lower()


@pytest.mark.parametrize(
    ("mode", "maximum_bytes", "failure_code"),
    [
        ("invalid_json", 65536, "invalid_json"),
        ("oversized", 256, "response_too_large"),
        ("silent", 65536, "timeout"),
        ("rejected", 65536, "subscribe_rejected"),
    ],
)
def test_virtual_lab_failures_are_bounded_and_sanitized(
    mode, maximum_bytes, failure_code
):
    with StratumV1Lab(mode=mode, oversized_bytes=1024) as lab:
        result = probe_stratum_v1(
            _resolution("8.8.8.8", lab.port),
            timeout_seconds=0.05,
            maximum_response_bytes=maximum_bytes,
            socket_factory=_lab_socket_factory(lab.port),
        )

    assert result.healthy is False
    assert result.protocol is PoolProtocol.UNKNOWN
    assert result.failure_code == failure_code
    assert result.capability is CapabilityState.ERROR
    assert "remote-secret-detail" not in repr(result)


class _FakeSocket:
    def __init__(self, response: bytes):
        self.response = response
        self.targets = []
        self.timeout = None
        self.sent = b""

    def settimeout(self, timeout):
        self.timeout = timeout

    def connect(self, target):
        self.targets.append(target)

    def sendall(self, payload):
        self.sent += payload

    def recv(self, size):
        response, self.response = self.response[:size], self.response[size:]
        return response

    def close(self):
        return None


class _LabRedirectSocket:
    """Test-only transport that keeps the virtual lab on loopback."""

    def __init__(self, port):
        self._port = port
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def settimeout(self, timeout):
        self._socket.settimeout(timeout)

    def connect(self, target):
        assert target == ("8.8.8.8", self._port)
        self._socket.connect(("127.0.0.1", self._port))

    def sendall(self, payload):
        self._socket.sendall(payload)

    def recv(self, size):
        return self._socket.recv(size)

    def close(self):
        self._socket.close()


def _lab_socket_factory(port):
    return lambda family, kind: _LabRedirectSocket(port)


class _FailingSocket(_FakeSocket):
    def connect(self, target):
        self.targets.append(target)
        raise OSError("refused")


class _CloseFailingSocket(_FakeSocket):
    def close(self):
        raise OSError("close failed")


class _ChunkedSocket(_FakeSocket):
    def __init__(self, chunks):
        super().__init__(b"")
        self.chunks = list(chunks)

    def recv(self, size):
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        assert len(chunk) <= size
        return chunk


def _valid_response() -> bytes:
    return b'{"id":1,"result":[[["mining.notify","s"]],"01",4],"error":null}\n'


def test_connector_uses_numeric_pinned_address_without_second_dns_lookup():
    fake_socket = _FakeSocket(_valid_response())

    def socket_factory(family, kind):
        assert family == socket.AF_INET
        assert kind == socket.SOCK_STREAM
        return fake_socket

    result = probe_stratum_v1(
        _resolution("8.8.8.8", 3333),
        socket_factory=socket_factory,
    )

    assert result.healthy is True
    assert fake_socket.targets == [("8.8.8.8", 3333)]
    assert b"pool.example.test" not in fake_socket.sent


def test_connector_caps_numeric_address_attempts():
    endpoint = parse_pool_endpoint("pool.example.test:3333")
    resolution = PoolResolution(
        destination=ValidatedDestination(
            endpoint=endpoint,
            addresses=(
                "1.1.1.1",
                "8.8.8.8",
                "9.9.9.9",
                "208.67.222.222",
                "208.67.220.220",
            ),
            local_pool_mode=False,
        ),
        dns_latency_ms=0,
    )
    sockets = []

    def socket_factory(*args):
        created = _FailingSocket(b"")
        sockets.append(created)
        return created

    result = probe_stratum_v1(resolution, socket_factory=socket_factory)

    assert result.healthy is False
    assert result.failure_code == "connection_failed"
    assert len(sockets) == 4


@pytest.mark.parametrize(
    ("response", "failure_code"),
    [
        (b"", "connection_closed"),
        (b'{"id":2,"result":[],"error":null}\n', "invalid_response"),
        (b'{"id":1,"result":null,"error":null}\n', "invalid_subscribe_result"),
        (b'{"id":1,"result":[{},"01",4],"error":null}\n', "invalid_subscribe_result"),
        (b'{"id":1,"result":[[],"",4],"error":null}\n', "invalid_subscribe_result"),
        (
            b'{"id":1,"result":[[],"01",true],"error":null}\n',
            "invalid_subscribe_result",
        ),
    ],
)
def test_protocol_response_shape_is_fail_closed(response, failure_code):
    result = probe_stratum_v1(
        _resolution("8.8.8.8", 3333),
        socket_factory=lambda *args: _FakeSocket(response),
    )
    assert result.healthy is False
    assert result.failure_code == failure_code


def test_response_without_newline_hits_the_size_limit():
    result = probe_stratum_v1(
        _resolution("8.8.8.8", 3333),
        maximum_response_bytes=256,
        socket_factory=lambda *args: _FakeSocket(b"x" * 257),
    )
    assert result.healthy is False
    assert result.failure_code == "response_too_large"


def test_exact_size_response_accepts_newline_in_the_next_tcp_segment():
    response = _valid_response().rstrip(b"\n")
    padded_response = response + b" " * (256 - len(response))
    result = probe_stratum_v1(
        _resolution("8.8.8.8", 3333),
        maximum_response_bytes=256,
        socket_factory=lambda *args: _ChunkedSocket([padded_response, b"\n"]),
    )
    assert result.healthy is True


def test_socket_close_failure_does_not_hide_a_valid_probe_result():
    result = probe_stratum_v1(
        _resolution("8.8.8.8", 3333),
        socket_factory=lambda *args: _CloseFailingSocket(_valid_response()),
    )
    assert result.healthy is True


def test_probe_configuration_and_empty_destination_are_rejected():
    resolution = _resolution("8.8.8.8", 3333)
    for timeout in (True, 0, 31):
        with pytest.raises(StratumV1ProbeError, match="timeout"):
            probe_stratum_v1(resolution, timeout_seconds=timeout)
    for limit in (255, 65537):
        with pytest.raises(StratumV1ProbeError, match="response limit"):
            probe_stratum_v1(resolution, maximum_response_bytes=limit)

    empty = PoolResolution(
        destination=ValidatedDestination(
            endpoint=resolution.destination.endpoint,
            addresses=(),
            local_pool_mode=False,
        ),
        dns_latency_ms=0,
    )
    with pytest.raises(StratumV1ProbeError, match="no addresses"):
        probe_stratum_v1(empty)


def test_ipv6_destination_is_connected_as_a_numeric_ipv6_tuple():
    fake_socket = _FakeSocket(_valid_response())
    result = probe_stratum_v1(
        _resolution("2001:4860:4860::8888", 3333),
        socket_factory=lambda family, kind: fake_socket,
    )
    assert result.healthy is True
    assert fake_socket.targets == [("2001:4860:4860::8888", 3333, 0, 0)]


def test_tls_uses_original_host_only_for_sni_and_certificate_verification():
    fake_socket = _FakeSocket(_valid_response())

    class FakeContext:
        server_hostname = None

        def wrap_socket(self, connection, *, server_hostname):
            self.server_hostname = server_hostname
            return connection

    context = FakeContext()
    result = probe_stratum_v1(
        _resolution("8.8.8.8", 443, tls=True),
        socket_factory=lambda *args: fake_socket,
        tls_context_factory=lambda: context,
    )

    assert result.healthy is True
    assert fake_socket.targets == [("8.8.8.8", 443)]
    assert context.server_hostname == "pool.example.test"
    assert result.tls_latency_ms is not None


def test_tls_failure_is_sanitized():
    fake_socket = _FakeSocket(_valid_response())

    class FailingContext:
        def wrap_socket(self, connection, *, server_hostname):
            raise ssl.SSLError("certificate detail")

    result = probe_stratum_v1(
        _resolution("8.8.8.8", 443, tls=True),
        socket_factory=lambda *args: fake_socket,
        tls_context_factory=FailingContext,
    )
    assert result.healthy is False
    assert result.failure_code == "tls_failed"
    assert "certificate detail" not in repr(result)


@pytest.mark.parametrize("address", ["pool.example.test", "127.1"])
def test_connector_rejects_non_numeric_validated_destinations(address):
    with pytest.raises(StratumV1ProbeError, match="connector policy"):
        probe_stratum_v1(_resolution(address, 3333))
