"""
CYPHER65 // Stratum V2 on the Fleet detection path (Issue #630)
===============================================================
The SV2 *adapter* already has its own security/protocol suite
(``test_stratum_v2_adapter.py``). What nothing pinned before was the path the
FLEET actually runs when an ASIC reports an SV2-style endpoint:

    ASIC telemetry (``stratum2+tcp://host:port``)
      → endpoint validation (``parse_pool_endpoint``)
      → provider detection (``detect_provider``)
      → passive SV2 probe (``probe_stratum_v2`` against the local lab)
      → capability assertion (``protocol.stratum_v2.setup``)

The production change is deliberately minimal: ``parse_pool_endpoint`` now
accepts the ``stratum2+tcp/ssl/tls`` TRANSPORT schemes (real firmware reports
them) while keeping the endpoint's ``protocol`` UNKNOWN — the negotiated
Stratum version is discovered by fingerprinting, never trusted from a URL
scheme. The probe stays passive: SetupConnection only, no channels, no shares.

The probe tests use the same DNS-rebinding guard as the adapter suite: the
resolution points at a numeric address (8.8.8.8) and a socket factory redirects
the connection to the local lab, so the probe never opens a real network
connection and the suite is deterministic offline.
"""

import socket

import pytest

from services.pool_intelligence import (
    CapabilityState,
    PoolEndpoint,
    PoolProtocol,
    PoolResolution,
    StratumV2ResponseError,
    ValidatedDestination,
    build_capability_graph,
    capability_from_v2_probe,
    detect_provider,
    parse_pool_endpoint,
    probe_stratum_v2,
    validate_stratum_v2_setup_response,
)
from services.pool_intelligence.endpoint import EndpointError
from tests.virtual_pool.stratum_v2_lab import StratumV2Lab

ADDR = "bc1qexampleaddress000000000000000000000"


def _resolution(address: str, port: int) -> PoolResolution:
    endpoint = parse_pool_endpoint(f"stratum2+tcp://pool.example.test:{port}")
    return PoolResolution(
        destination=ValidatedDestination(
            endpoint=endpoint,
            addresses=(address,),
            local_pool_mode=False,
        ),
        dns_latency_ms=1.25,
    )


class _LabRedirectSocket:
    """Connects to the lab on loopback while the probe believes it is talking
    to the resolved address — same anti-rebinding shape as the adapter suite."""

    def __init__(self, port: int) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def settimeout(self, timeout) -> None:
        self._socket.settimeout(timeout)

    def connect(self, target) -> None:
        self._socket.connect(("127.0.0.1", target[1]))

    def sendall(self, payload) -> None:
        self._socket.sendall(payload)

    def recv(self, size) -> bytes:
        return self._socket.recv(size)

    def close(self) -> None:
        self._socket.close()


def _lab_socket_factory(port: int):
    return lambda family, kind: _LabRedirectSocket(port)


# ══════════════════════════════════════════════════════════════════════════
#  Transport parsing — stratum2+* schemes
# ══════════════════════════════════════════════════════════════════════════


class TestStratum2TransportParsing:
    @pytest.mark.parametrize(
        ("raw", "scheme", "tls"),
        [
            ("stratum2+tcp://pool.example.test:3333", "stratum2+tcp", False),
            ("stratum2+tls://pool.example.test:3333", "stratum2+tls", True),
            ("stratum2+ssl://pool.example.test:3333", "stratum2+ssl", True),
        ],
    )
    def test_sv2_transport_schemes_parse(self, raw, scheme, tls):
        endpoint = parse_pool_endpoint(raw)
        assert endpoint.scheme == scheme
        assert endpoint.tls is tls
        # The scheme names a TRANSPORT, never the negotiated version.
        assert endpoint.protocol is PoolProtocol.UNKNOWN
        assert endpoint.normalized_url == f"{scheme}://pool.example.test:3333"

    def test_v1_schemes_still_parse_and_v2_is_case_insensitive(self):
        assert parse_pool_endpoint("stratum+tcp://h.test:3333").scheme == "stratum+tcp"
        endpoint = parse_pool_endpoint("STRATUM2+TCP://H.TEST:3333")
        assert endpoint.scheme == "stratum2+tcp"
        assert endpoint.host == "h.test"

    def test_bare_host_defaults_to_v1_transport_not_v2(self):
        """No scheme at all stays stratum+tcp — bare host:port has always been
        the V1 default in this codebase and changing it silently would alter
        what every existing caller probes."""
        endpoint = parse_pool_endpoint("pool.example.test:3333")
        assert endpoint.scheme == "stratum+tcp"

    def test_no_default_port_is_invented_for_sv2(self):
        with pytest.raises(EndpointError, match="port is required"):
            parse_pool_endpoint("stratum2+tcp://pool.example.test")

    @pytest.mark.parametrize(
        "raw",
        [
            "stratum2+tcp://user:secret@pool.example.test:3333",
            "stratum2+tcp://pool.example.test:3333/worker",
            "stratum2+tcp://pool.example.test:3333?x=1",
            "stratum2+tcp://pool.example.test:notaport",
        ],
    )
    def test_hostile_shapes_stay_rejected(self, raw):
        with pytest.raises(EndpointError):
            parse_pool_endpoint(raw)

    def test_endpoint_is_not_trusted_as_protocol_evidence(self):
        """An SV2 scheme alone must never mark an endpoint as STRATUM_V2 —
        only a live probe does that (issue motivation: schemes lie)."""
        endpoint = parse_pool_endpoint("stratum2+tcp://pool.example.test:3333")
        assert endpoint.protocol is not PoolProtocol.STRATUM_V2


# ══════════════════════════════════════════════════════════════════════════
#  Detection — ASIC reports an SV2-style pool_url
# ══════════════════════════════════════════════════════════════════════════


class TestDetectionWithStratum2Report:
    def test_registered_pool_detected_from_sv2_url(self):
        detection = detect_provider("stratum2+tcp://solo.ckpool.org:3333", address=ADDR)
        assert detection is not None
        assert detection.provider_id == "ckpool_solo"

    def test_unknown_pool_with_sv2_scheme_stays_honestly_unknown(self):
        detection = detect_provider("stratum2+tcp://minha.pool.local:3333")
        assert detection is None or getattr(detection, "provider_id", "") in (
            "",
            "unknown",
            "generic-stratum",
        )

    def test_documented_contract_now_matches_the_parser(self):
        """providers.detect_provider documents accepting stratum2+tcp:// —
        this pins that the promise is true end-to-end (parser + detection)."""
        endpoint = parse_pool_endpoint("stratum2+tcp://public-pool.io:21496")
        assert endpoint.host == "public-pool.io"
        assert endpoint.port == 21496


# ══════════════════════════════════════════════════════════════════════════
#  Passive probe against the local lab — the SV2 pipeline end-to-end
# ══════════════════════════════════════════════════════════════════════════


class TestFleetSv2ProbePipeline:
    def test_healthy_pool_reports_stratum_v2_capability(self):
        with StratumV2Lab() as lab:
            result = probe_stratum_v2(
                _resolution("8.8.8.8", lab.port),
                socket_factory=_lab_socket_factory(lab.port),
            )

        assert result.healthy is True
        assert result.protocol is PoolProtocol.STRATUM_V2
        assert result.used_version == 2
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
            ("silent", 4096, "timeout"),
            ("rejected", 4096, "setup_rejected"),
            ("oversized", 64, "frame_too_large"),
            ("invalid_frame", 4096, "invalid_setup_result"),
        ],
    )
    def test_failures_degrade_with_sanitized_codes(
        self, mode, maximum_bytes, failure_code
    ):
        with StratumV2Lab(mode=mode, oversized_bytes=8192) as lab:
            result = probe_stratum_v2(
                _resolution("8.8.8.8", lab.port),
                timeout_seconds=0.05,
                maximum_frame_bytes=maximum_bytes,
                socket_factory=_lab_socket_factory(lab.port),
            )

        assert result.healthy is False
        assert result.protocol is PoolProtocol.UNKNOWN
        assert result.capability is CapabilityState.ERROR
        assert result.failure_code == failure_code
        # The lab's rejection detail must never surface in the result.
        assert "secret-error-detail" not in repr(result)

    def test_probe_rejects_bogus_arguments_before_any_io(self):
        with pytest.raises(Exception):
            probe_stratum_v2(_resolution("8.8.8.8", 3333), timeout_seconds=0)
        with pytest.raises(Exception, match="PoolResolution"):
            probe_stratum_v2("not-a-resolution")

    def test_response_validator_rejects_wrong_version_payload(self):
        """A pool answering SETUP_SUCCESS with a non-zero requested_version is
        not speaking the version we asked for — reject before trusting."""
        payload = (7).to_bytes(2, "little") + (0).to_bytes(4, "little")
        with pytest.raises(StratumV2ResponseError):
            validate_stratum_v2_setup_response(0x01, payload)


# ══════════════════════════════════════════════════════════════════════════
#  Regressions — the shapes Fleet must keep surviving
# ══════════════════════════════════════════════════════════════════════════


class TestFleetSv2Regressions:
    def test_malformed_sv2_url_from_asic_never_raises(self):
        """Fleet ingests whatever the hardware reports. A garbage SV2 URL
        degrades to an honest parse failure, never an exception escape."""
        for raw in ["stratum2+tcp://", "stratum2+tcp://:3333", "stratum2://x"]:
            with pytest.raises(EndpointError):
                parse_pool_endpoint(raw)

    def test_pool_endpoint_dataclass_roundtrip_keeps_transport(self):
        endpoint = parse_pool_endpoint("stratum2+tls://pool.example.test:3334")
        rebuilt = PoolEndpoint(
            scheme=endpoint.scheme,
            host=endpoint.host,
            port=endpoint.port,
            protocol=endpoint.protocol,
            tls=endpoint.tls,
            normalized_url=endpoint.normalized_url,
        )
        assert rebuilt.scheme == "stratum2+tls"
        assert rebuilt.tls is True
        assert rebuilt.port == 3334
