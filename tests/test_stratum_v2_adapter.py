"""Security and protocol tests for the bounded Stratum V2 adapter."""

import socket
import time

import pytest

from services.pool_intelligence import (
    CapabilityState,
    PoolProtocol,
    PoolResolution,
    StratumV2ProbeError,
    StratumV2ResponseError,
    ValidatedDestination,
    build_capability_graph,
    build_setup_connection,
    capability_from_v2_probe,
    encode_stratum_v2_frame,
    parse_pool_endpoint,
    probe_stratum_v2,
    validate_stratum_v2_setup_response,
)
from tests.virtual_pool.stratum_v2_lab import (
    LAB_RESPONSE_TIMEOUT_SECONDS,
    LAB_SILENCE_TIMEOUT_SECONDS,
    StratumV2Lab,
)


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


class _LabRedirectSocket:
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


def test_setup_connection_frame_has_no_credentials_or_worker():
    endpoint = parse_pool_endpoint("stratum+tcp://pool.example.test:3333")
    frame = build_setup_connection(endpoint)
    assert frame[2] == 0x00
    assert b"password" not in frame.lower()
    assert b"worker" not in frame.lower()
    assert b"@" not in frame
    assert b"CYPHER65" in frame


def test_encoder_rejects_non_setup_and_unsafe_strings():
    with pytest.raises(StratumV2ProbeError, match="only send SetupConnection"):
        encode_stratum_v2_frame(0x10, b"\x00")
    endpoint = parse_pool_endpoint("stratum+tcp://pool.example.test:3333")
    bad = endpoint.__class__(
        scheme=endpoint.scheme,
        host="user:secret@pool.example.test",
        port=endpoint.port,
        protocol=endpoint.protocol,
        tls=endpoint.tls,
        normalized_url=endpoint.normalized_url,
    )
    with pytest.raises(StratumV2ProbeError):
        build_setup_connection(bad)


def test_success_payload_is_version_only_and_discards_secrets():
    payload = (2).to_bytes(2, "little") + (0).to_bytes(4, "little")
    assert validate_stratum_v2_setup_response(0x01, payload) == 2
    with pytest.raises(StratumV2ResponseError, match="setup_rejected"):
        validate_stratum_v2_setup_response(0x02, b"secret-error-detail")
    with pytest.raises(StratumV2ResponseError, match="unsupported_message"):
        validate_stratum_v2_setup_response(0x10, payload)
    with pytest.raises(StratumV2ResponseError, match="invalid_setup_result"):
        validate_stratum_v2_setup_response(
            0x01, (1).to_bytes(2, "little") + (0).to_bytes(4, "little")
        )


def test_virtual_lab_probe_reports_v2_health_without_dns_rebinding():
    with StratumV2Lab() as lab:
        result = probe_stratum_v2(
            _resolution("8.8.8.8", lab.port),
            socket_factory=_lab_socket_factory(lab.port),
        )

    assert result.healthy is True
    assert result.protocol is PoolProtocol.STRATUM_V2
    assert result.capability is CapabilityState.SUPPORTED
    assert result.connected_address == "8.8.8.8"
    assert result.used_version == 2
    assert result.failure_code is None
    assert result.tcp_latency_ms is not None
    assertion = capability_from_v2_probe(result)
    assert assertion.name == "protocol.stratum_v2.setup"
    assert assertion.state is CapabilityState.SUPPORTED
    graph = build_capability_graph((assertion,))
    assert (
        graph.get("protocol.stratum_v2.setup").observed_state
        is CapabilityState.SUPPORTED
    )


@pytest.mark.parametrize(
    ("mode", "maximum_bytes", "failure_code"),
    [
        ("invalid_frame", 4096, "invalid_setup_result"),
        ("oversized", 64, "frame_too_large"),
        ("silent", 4096, "timeout"),
        ("rejected", 4096, "setup_rejected"),
        ("wrong_type", 4096, "unsupported_message"),
        ("noise", 4096, "noise_required"),
    ],
)
def test_virtual_lab_failures_are_bounded_and_sanitized(
    mode, maximum_bytes, failure_code
):
    with StratumV2Lab(mode=mode, oversized_bytes=8192) as lab:
        result = probe_stratum_v2(
            _resolution("8.8.8.8", lab.port),
            timeout_seconds=(
                LAB_SILENCE_TIMEOUT_SECONDS
                if mode == "silent"
                else LAB_RESPONSE_TIMEOUT_SECONDS
            ),
            maximum_frame_bytes=maximum_bytes,
            socket_factory=_lab_socket_factory(lab.port),
        )

    assert result.healthy is False
    assert result.protocol is PoolProtocol.UNKNOWN
    assert result.failure_code == failure_code
    assert result.capability is CapabilityState.ERROR
    assert "secret-error-detail" not in repr(result)


def test_probe_rejects_malformed_timeout_and_empty_resolution():
    with pytest.raises(StratumV2ProbeError):
        probe_stratum_v2(_resolution("8.8.8.8", 3333), timeout_seconds=0)
    with pytest.raises(StratumV2ProbeError):
        probe_stratum_v2(_resolution("8.8.8.8", 3333), timeout_seconds=True)
    with pytest.raises(StratumV2ProbeError, match="PoolResolution"):
        probe_stratum_v2("not-a-resolution")


@pytest.mark.parametrize(
    ("mode", "failure_code"), [("success", None), ("wrong_type", "unsupported_message")]
)
def test_delayed_lab_response_is_classified_without_a_silence_budget(
    mode: str, failure_code: str | None
) -> None:
    """A real delayed response must reach parsing, not become a scheduling timeout."""
    response_delay_seconds = 0.1
    with StratumV2Lab(mode=mode, response_delay_seconds=response_delay_seconds) as lab:
        probe_started = time.perf_counter()
        result = probe_stratum_v2(
            _resolution("8.8.8.8", lab.port),
            timeout_seconds=LAB_RESPONSE_TIMEOUT_SECONDS,
            socket_factory=_lab_socket_factory(lab.port),
        )
        probe_elapsed_seconds = time.perf_counter() - probe_started
        assert lab.request_count == 1

    assert result.failure_code == failure_code
    assert result.healthy is (failure_code is None)
    assert result.protocol is (
        PoolProtocol.STRATUM_V2 if failure_code is None else PoolProtocol.UNKNOWN
    )
    assert result.capability is (
        CapabilityState.SUPPORTED if failure_code is None else CapabilityState.ERROR
    )
    # Measure only probe time, not the fixture's server shutdown/join overhead.
    assert probe_elapsed_seconds >= response_delay_seconds
    assert "secret-error-detail" not in repr(result)


@pytest.mark.parametrize(
    "delay", [True, -0.1, 0.51, float("nan"), float("inf"), "0.1", 10**400, -(10**400)]
)
def test_lab_rejects_invalid_response_delay_before_opening_a_socket(
    delay: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fixture's explicit response wait must stay finite and bounded."""

    def unexpected_server(*args, **kwargs):
        raise AssertionError("invalid delay must fail before server creation")

    monkeypatch.setattr("tests.virtual_pool.stratum_v2_lab._Server", unexpected_server)
    with pytest.raises(ValueError, match="response delay"):
        StratumV2Lab(response_delay_seconds=delay)
