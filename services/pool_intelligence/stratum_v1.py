"""Bounded, read-only Stratum V1 health probe over pinned IP addresses."""

from dataclasses import dataclass
import ipaddress
import json
import socket
import ssl
import time
from typing import Callable

from .models import CapabilityState, PoolProtocol
from .resolver import PoolResolution

DEFAULT_PROBE_TIMEOUT_SECONDS = 3.0
MAX_CONNECT_ATTEMPTS = 4
MAX_STRATUM_RESPONSE_BYTES = 64 * 1024
_SUBSCRIBE_REQUEST = {
    "id": 1,
    "method": "mining.subscribe",
    "params": ["CYPHER65-War-Room/1.0"],
}


class StratumV1ProbeError(ValueError):
    """The validated destination or probe configuration is unusable."""


class _ProtocolFailure(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class StratumV1ProbeResult:
    endpoint: str
    connected_address: str | None
    healthy: bool
    protocol: PoolProtocol
    capability: CapabilityState
    dns_latency_ms: float
    tcp_latency_ms: float | None
    tls_latency_ms: float | None
    stratum_latency_ms: float | None
    total_latency_ms: float
    failure_code: str | None = None


def _round_ms(seconds: float) -> float:
    return round(max(0.0, seconds * 1000), 3)


def _numeric_socket_target(address: str, port: int) -> tuple[int, tuple]:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise StratumV1ProbeError(
            "validated destination must contain numeric IP addresses"
        ) from exc
    if isinstance(parsed, ipaddress.IPv6Address):
        return socket.AF_INET6, (parsed.compressed, port, 0, 0)
    return socket.AF_INET, (parsed.compressed, port)


def _read_response_line(connection, *, maximum_bytes: int) -> bytes:
    buffer = bytearray()
    while True:
        remaining = maximum_bytes - len(buffer)
        chunk = connection.recv(min(4096, remaining + 1))
        if not chunk:
            raise _ProtocolFailure("connection_closed")
        newline = chunk.find(b"\n")
        if newline >= 0:
            buffer.extend(chunk[:newline])
            return bytes(buffer).rstrip(b"\r")
        buffer.extend(chunk)
        if len(buffer) > maximum_bytes:
            raise _ProtocolFailure("response_too_large")


def _validate_subscribe_response(raw_line: bytes) -> None:
    try:
        message = json.loads(raw_line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _ProtocolFailure("invalid_json") from exc
    if not isinstance(message, dict) or message.get("id") != 1:
        raise _ProtocolFailure("invalid_response")
    if message.get("error") is not None:
        raise _ProtocolFailure("subscribe_rejected")
    result = message.get("result")
    if not isinstance(result, list) or len(result) < 3:
        raise _ProtocolFailure("invalid_subscribe_result")
    subscriptions, extra_nonce, extra_nonce_size = result[:3]
    if not isinstance(subscriptions, list):
        raise _ProtocolFailure("invalid_subscribe_result")
    if not isinstance(extra_nonce, str) or not 1 <= len(extra_nonce) <= 256:
        raise _ProtocolFailure("invalid_subscribe_result")
    if (
        isinstance(extra_nonce_size, bool)
        or not isinstance(extra_nonce_size, int)
        or not 1 <= extra_nonce_size <= 32
    ):
        raise _ProtocolFailure("invalid_subscribe_result")


def probe_stratum_v1(
    resolution: PoolResolution,
    *,
    timeout_seconds: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
    maximum_response_bytes: int = MAX_STRATUM_RESPONSE_BYTES,
    socket_factory: Callable[..., socket.socket] = socket.socket,
    tls_context_factory: Callable[[], ssl.SSLContext] = ssl.create_default_context,
    clock: Callable[[], float] = time.perf_counter,
) -> StratumV1ProbeResult:
    """Probe ``mining.subscribe`` without credentials or worker authorization.

    DNS is never called here. Every connection target is a numeric address from
    the already validated ``PoolResolution``. TLS keeps the original hostname
    solely for SNI and certificate verification.
    """
    if isinstance(timeout_seconds, bool) or not 0 < timeout_seconds <= 30:
        raise StratumV1ProbeError("timeout must be greater than 0 and at most 30s")
    if not 256 <= maximum_response_bytes <= MAX_STRATUM_RESPONSE_BYTES:
        raise StratumV1ProbeError("response limit must be between 256 and 65536 bytes")

    destination = resolution.destination
    endpoint = destination.endpoint
    targets = [
        (address, *_numeric_socket_target(address, endpoint.port))
        for address in destination.addresses[:MAX_CONNECT_ATTEMPTS]
    ]
    if not targets:
        raise StratumV1ProbeError("validated destination contains no addresses")

    total_started = clock()
    last_address: str | None = None
    last_failure = "connection_failed"
    last_tcp_ms: float | None = None
    last_tls_ms: float | None = None
    last_stratum_ms: float | None = None

    for address, family, target in targets:
        last_address = address
        raw_connection = None
        connection = None
        try:
            raw_connection = socket_factory(family, socket.SOCK_STREAM)
            raw_connection.settimeout(timeout_seconds)
            tcp_started = clock()
            raw_connection.connect(target)
            last_tcp_ms = _round_ms(clock() - tcp_started)
            connection = raw_connection

            if endpoint.tls:
                tls_started = clock()
                context = tls_context_factory()
                connection = context.wrap_socket(
                    raw_connection,
                    server_hostname=endpoint.host,
                )
                last_tls_ms = _round_ms(clock() - tls_started)

            request = (
                json.dumps(
                    _SUBSCRIBE_REQUEST, separators=(",", ":"), sort_keys=True
                ).encode("ascii")
                + b"\n"
            )
            stratum_started = clock()
            connection.sendall(request)
            response = _read_response_line(
                connection,
                maximum_bytes=maximum_response_bytes,
            )
            _validate_subscribe_response(response)
            last_stratum_ms = _round_ms(clock() - stratum_started)
            return StratumV1ProbeResult(
                endpoint=endpoint.normalized_url,
                connected_address=address,
                healthy=True,
                protocol=PoolProtocol.STRATUM_V1,
                capability=CapabilityState.SUPPORTED,
                dns_latency_ms=resolution.dns_latency_ms,
                tcp_latency_ms=last_tcp_ms,
                tls_latency_ms=last_tls_ms,
                stratum_latency_ms=last_stratum_ms,
                total_latency_ms=_round_ms(clock() - total_started)
                + resolution.dns_latency_ms,
            )
        except _ProtocolFailure as exc:
            last_failure = exc.code
        except (socket.timeout, TimeoutError):
            last_failure = "timeout"
        except ssl.SSLError:
            last_failure = "tls_failed"
        except OSError:
            last_failure = "connection_failed"
        finally:
            try:
                if connection is not None:
                    connection.close()
                elif raw_connection is not None:
                    raw_connection.close()
            except OSError:
                pass

    return StratumV1ProbeResult(
        endpoint=endpoint.normalized_url,
        connected_address=last_address,
        healthy=False,
        protocol=PoolProtocol.UNKNOWN,
        capability=CapabilityState.ERROR,
        dns_latency_ms=resolution.dns_latency_ms,
        tcp_latency_ms=last_tcp_ms,
        tls_latency_ms=last_tls_ms,
        stratum_latency_ms=last_stratum_ms,
        total_latency_ms=_round_ms(clock() - total_started) + resolution.dns_latency_ms,
        failure_code=last_failure,
    )
