"""Bounded, read-only Stratum V2 SetupConnection adapter.

This adapter speaks the Common-layer binary framing (extension 0) after an
already pinned TCP/TLS socket. It never implements Noise NX, mining channels,
worker authorization or share submission. A remote that starts a Noise
handshake is reported as ``noise_required`` and is not healthy.
"""

from dataclasses import dataclass
import ipaddress
import math
import re
import socket
import ssl
import time
from typing import Callable

from .models import CapabilityState, PoolEndpoint, PoolProtocol
from .policy import DestinationPolicy, PolicyError, ValidatedDestination
from .resolver import PoolResolution

DEFAULT_PROBE_TIMEOUT_SECONDS = 3.0
MAX_CONNECT_ATTEMPTS = 4
MAX_STRATUM_V2_FRAME_BYTES = 4 * 1024
HEADER_BYTES = 6
MSG_SETUP_CONNECTION = 0x00
MSG_SETUP_CONNECTION_SUCCESS = 0x01
MSG_SETUP_CONNECTION_ERROR = 0x02
MIN_PROTOCOL_VERSION = 2
MAX_PROTOCOL_VERSION = 2
_SAFE_ASCII = re.compile(r"^[A-Za-z0-9._+/-]{0,255}$")
_RESPONSE_FAILURE_CODES = frozenset(
    {
        "invalid_frame",
        "frame_too_large",
        "unsupported_message",
        "setup_rejected",
        "invalid_setup_result",
        "noise_required",
        "connection_closed",
    }
)


class StratumV2ProbeError(ValueError):
    """The validated destination or probe configuration is unusable."""


class StratumV2ResponseError(ValueError):
    """A bounded SetupConnection response failed with a controlled reason code."""

    def __init__(self, code: str):
        if code not in _RESPONSE_FAILURE_CODES:
            raise ValueError("invalid Stratum V2 response failure code")
        super().__init__(code)
        self.code = code


class _ProtocolFailure(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class StratumV2ProbeResult:
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
    used_version: int | None = None
    failure_code: str | None = None


def _round_ms(seconds: float) -> float:
    return round(max(0.0, seconds * 1000), 3)


def _numeric_socket_target(address: str, port: int) -> tuple[int, tuple]:
    parsed = ipaddress.ip_address(address)
    if isinstance(parsed, ipaddress.IPv6Address):
        return socket.AF_INET6, (parsed.compressed, port, 0, 0)
    return socket.AF_INET, (parsed.compressed, port)


def _u16le(value: int) -> bytes:
    return int(value).to_bytes(2, "little")


def _u24le(value: int) -> bytes:
    return int(value).to_bytes(3, "little")


def _u32le(value: int) -> bytes:
    return int(value).to_bytes(4, "little")


def _str0_255(value: str) -> bytes:
    if not isinstance(value, str) or not _SAFE_ASCII.fullmatch(value):
        raise StratumV2ProbeError("SetupConnection string must be safe ASCII")
    raw = value.encode("ascii")
    return bytes([len(raw)]) + raw


def encode_stratum_v2_frame(message_type: int, payload: bytes) -> bytes:
    """Encode one Common-layer frame. Only SetupConnection may be sent."""
    if message_type != MSG_SETUP_CONNECTION:
        raise StratumV2ProbeError("adapter may only send SetupConnection")
    if not isinstance(payload, bytes):
        raise StratumV2ProbeError("payload must be bytes")
    if len(payload) > MAX_STRATUM_V2_FRAME_BYTES:
        raise StratumV2ProbeError("SetupConnection payload exceeds the frame cap")
    return _u16le(0) + bytes([message_type]) + _u24le(len(payload)) + payload


def build_setup_connection(endpoint: PoolEndpoint) -> bytes:
    """Build a credential-free SetupConnection payload."""
    if not isinstance(endpoint, PoolEndpoint):
        raise StratumV2ProbeError("endpoint must be a PoolEndpoint")
    if ":" in endpoint.host or "/" in endpoint.host or "@" in endpoint.host:
        raise StratumV2ProbeError("SetupConnection host must not contain credentials")
    payload = b"".join(
        (
            _u16le(MIN_PROTOCOL_VERSION),
            _u16le(MAX_PROTOCOL_VERSION),
            _u32le(0),
            _str0_255(endpoint.host),
            _u16le(endpoint.port),
            _str0_255("CYPHER65"),
            _str0_255("War-Room"),
            _str0_255("1.0"),
            _str0_255(""),
        )
    )
    return encode_stratum_v2_frame(MSG_SETUP_CONNECTION, payload)


def _read_exact(connection, size: int) -> bytes:
    buffer = bytearray()
    while len(buffer) < size:
        chunk = connection.recv(size - len(buffer))
        if not chunk:
            raise _ProtocolFailure("connection_closed")
        buffer.extend(chunk)
    return bytes(buffer)


def read_stratum_v2_frame(
    connection, *, maximum_bytes: int = MAX_STRATUM_V2_FRAME_BYTES
) -> tuple[int, bytes]:
    """Read one bounded Common-layer frame. Does not return remote strings."""
    if not 6 <= maximum_bytes <= MAX_STRATUM_V2_FRAME_BYTES:
        raise StratumV2ProbeError("frame limit must be between 6 and 4096 bytes")
    header = _read_exact(connection, HEADER_BYTES)
    extension_type = int.from_bytes(header[0:2], "little")
    message_type = header[2]
    length = int.from_bytes(header[3:6], "little")
    if extension_type != 0:
        raise _ProtocolFailure("noise_required")
    if length > maximum_bytes:
        raise _ProtocolFailure("frame_too_large")
    payload = _read_exact(connection, length) if length else b""
    return message_type, payload


def validate_setup_connection_success(payload: bytes) -> int:
    """Accept only SetupConnectionSuccess. Discard flags and any extra bytes."""
    if not isinstance(payload, bytes) or len(payload) < 6:
        raise StratumV2ResponseError("invalid_setup_result")
    used_version = int.from_bytes(payload[0:2], "little")
    if used_version != MAX_PROTOCOL_VERSION:
        raise StratumV2ResponseError("invalid_setup_result")
    if len(payload) != 6:
        raise StratumV2ResponseError("invalid_setup_result")
    return used_version


def validate_stratum_v2_setup_response(message_type: int, payload: bytes) -> int:
    if message_type == MSG_SETUP_CONNECTION_ERROR:
        raise StratumV2ResponseError("setup_rejected")
    if message_type != MSG_SETUP_CONNECTION_SUCCESS:
        raise StratumV2ResponseError("unsupported_message")
    return validate_setup_connection_success(payload)


def _validated_probe_destination(resolution: PoolResolution) -> ValidatedDestination:
    if not isinstance(resolution, PoolResolution):
        raise StratumV2ProbeError("resolution must be a PoolResolution")
    destination = resolution.destination
    if (
        not isinstance(destination, ValidatedDestination)
        or not isinstance(destination.endpoint, PoolEndpoint)
        or not isinstance(destination.local_pool_mode, bool)
        or isinstance(resolution.dns_latency_ms, bool)
        or not isinstance(resolution.dns_latency_ms, (int, float))
        or not math.isfinite(resolution.dns_latency_ms)
        or resolution.dns_latency_ms < 0
    ):
        raise StratumV2ProbeError("validated resolution is malformed")
    if not destination.addresses:
        raise StratumV2ProbeError("validated destination contains no addresses")
    try:
        return DestinationPolicy(
            allowed_ports=frozenset({destination.endpoint.port}),
            local_pool_mode=destination.local_pool_mode,
            administrator_authorized=destination.local_pool_mode,
        ).validate(destination.endpoint, destination.addresses)
    except (PolicyError, TypeError, ValueError) as exc:
        raise StratumV2ProbeError(
            "validated destination failed connector policy"
        ) from exc


def probe_stratum_v2(
    resolution: PoolResolution,
    *,
    timeout_seconds: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
    maximum_frame_bytes: int = MAX_STRATUM_V2_FRAME_BYTES,
    socket_factory: Callable[..., socket.socket] = socket.socket,
    tls_context_factory: Callable[[], ssl.SSLContext] = ssl.create_default_context,
    clock: Callable[[], float] = time.perf_counter,
) -> StratumV2ProbeResult:
    """Probe SetupConnection without credentials, channels or share submit.

    DNS is never called here. Every connection target is a numeric address from
    the already validated ``PoolResolution``. TLS keeps the original hostname
    solely for SNI and certificate verification.
    """
    if isinstance(timeout_seconds, bool) or not 0 < timeout_seconds <= 30:
        raise StratumV2ProbeError("timeout must be greater than 0 and at most 30s")
    if not HEADER_BYTES <= maximum_frame_bytes <= MAX_STRATUM_V2_FRAME_BYTES:
        raise StratumV2ProbeError("frame limit must be between 6 and 4096 bytes")

    destination = _validated_probe_destination(resolution)
    endpoint = destination.endpoint
    targets = [
        (address, *_numeric_socket_target(address, endpoint.port))
        for address in destination.addresses[:MAX_CONNECT_ATTEMPTS]
    ]
    request = build_setup_connection(endpoint)

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

            stratum_started = clock()
            connection.sendall(request)
            message_type, payload = read_stratum_v2_frame(
                connection, maximum_bytes=maximum_frame_bytes
            )
            try:
                used_version = validate_stratum_v2_setup_response(message_type, payload)
            except StratumV2ResponseError as exc:
                raise _ProtocolFailure(exc.code) from exc
            last_stratum_ms = _round_ms(clock() - stratum_started)
            return StratumV2ProbeResult(
                endpoint=endpoint.normalized_url,
                connected_address=address,
                healthy=True,
                protocol=PoolProtocol.STRATUM_V2,
                capability=CapabilityState.SUPPORTED,
                dns_latency_ms=resolution.dns_latency_ms,
                tcp_latency_ms=last_tcp_ms,
                tls_latency_ms=last_tls_ms,
                stratum_latency_ms=last_stratum_ms,
                total_latency_ms=_round_ms(clock() - total_started)
                + resolution.dns_latency_ms,
                used_version=used_version,
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

    return StratumV2ProbeResult(
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
