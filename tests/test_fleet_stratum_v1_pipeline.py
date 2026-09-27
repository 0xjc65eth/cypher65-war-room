"""
CYPHER65 // Stratum V1 component integration for Fleet (Issue #635)
=================================================================
Complements the V1 security suite and the V2 component suite (#630) with
ASIC-shaped URL fixtures, endpoint parsing, provider detection, passive probes
against local TCP labs, and capability assertions. The tests compose the
``pool_intelligence`` components directly; they do not exercise Fleet telemetry
ingestion, routes, scanner, persistence, or device identity deduplication.

DNS results and latency are fixtures. Socket wrappers redirect the supplied
numeric destination to loopback, so this suite does not validate live DNS,
public-pool reachability, or destination pinning. TLS schemes are parsed and
roundtripped only; no TLS handshake, real ASIC, or cloud deployment is tested.

No production change is needed: the V1 schemes already parse. Cross-protocol
cases pin the transport/version distinction in both directions: a URL scheme
names a transport; only a probe observation identifies the protocol.
"""

import json
import socket

import pytest

from services.pool_intelligence import (
    CapabilityState,
    EndpointError,
    PoolProtocol,
    PoolResolution,
    Provenance,
    StratumV1ProbeError,
    ValidatedDestination,
    build_capability_graph,
    capability_from_v1_probe,
    detect_provider,
    parse_pool_endpoint,
    probe_stratum_v1,
    probe_stratum_v2,
)
from tests.virtual_pool.stratum_v1_lab import StratumV1Lab
from tests.virtual_pool.stratum_v2_lab import StratumV2Lab

ADDR = "bc1qexampleaddress000000000000000000000"


def _resolution(scheme: str, address: str, port: int) -> PoolResolution:
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
    """Redirect the fixture's destination to TCP loopback, bypassing real DNS."""

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
#  Transport parsing — the V1 schemes an ASIC reports
# ══════════════════════════════════════════════════════════════════════════


class TestStratumV1TransportParsing:
    @pytest.mark.parametrize(
        ("raw", "scheme", "tls"),
        [
            ("stratum+tcp://pool.example.test:3333", "stratum+tcp", False),
            ("stratum+ssl://pool.example.test:3333", "stratum+ssl", True),
            ("stratum+tls://pool.example.test:3333", "stratum+tls", True),
        ],
    )
    def test_v1_transport_schemes_parse(self, raw, scheme, tls):
        endpoint = parse_pool_endpoint(raw)
        assert endpoint.scheme == scheme
        assert endpoint.tls is tls
        # Transport scheme only — the version is discovered by probing.
        assert endpoint.protocol is PoolProtocol.UNKNOWN
        assert endpoint.normalized_url == f"{scheme}://pool.example.test:3333"

    def test_bare_asic_row_equals_the_explicit_v1_row(self):
        """Equivalent URL forms normalize to the same endpoint value."""
        assert parse_pool_endpoint("pool.example.test:3333") == parse_pool_endpoint(
            "stratum+tcp://pool.example.test:3333"
        )

    def test_default_port_is_honored_only_when_the_caller_supplies_one(self):
        endpoint = parse_pool_endpoint("pool.example.test", default_port=3333)
        assert endpoint.scheme == "stratum+tcp"
        assert endpoint.port == 3333
        with pytest.raises(EndpointError, match="port is required"):
            parse_pool_endpoint("pool.example.test")

    @pytest.mark.parametrize(
        "raw",
        [
            "stratum+tcp://user:secret@pool.example.test:3333",
            "stratum+tcp://pool.example.test:3333/worker",
            "stratum+tcp://pool.example.test:3333?x=1",
            "stratum+tcp://pool.example.test:notaport",
            "nds+://pool.example.test:3333",
        ],
    )
    def test_hostile_shapes_stay_rejected(self, raw):
        with pytest.raises(EndpointError):
            parse_pool_endpoint(raw)


# ══════════════════════════════════════════════════════════════════════════
#  Detection — ASIC reports a V1 pool_url
# ══════════════════════════════════════════════════════════════════════════


class TestDetectionWithStratumV1Report:
    def test_registered_solo_pool_detected_from_v1_url(self):
        detection = detect_provider("stratum+tcp://solo.ckpool.org:3333", address=ADDR)
        assert detection.provider_id == "ckpool_solo"
        assert detection.kind.value == "solo"
        assert detection.chain.value == "btc"
        assert detection.stats_url is not None

    def test_new_registry_entry_is_stratum_only_and_says_so(self):
        """AtlasPool was added in #627 as ``stratum_only``: recognised, but
        with no stats API promised. Blurring that into a fabricated URL is
        exactly the "silent zeros" failure the registry exists to prevent."""
        detection = detect_provider("stratum+tcp://solo.atlaspool.io:3333")
        assert detection.provider_id == "atlaspool"
        assert detection.chain.value == "btc"
        assert detection.provider.has_stats_api is False
        assert detection.stats_url is None

    def test_scheme_never_changes_who_the_pool_is(self):
        for raw in (
            "stratum+tcp://solo.ckpool.org:3333",
            "stratum2+tcp://solo.ckpool.org:3333",
            "solo.ckpool.org:3333",
        ):
            assert detect_provider(raw).provider_id == "ckpool_solo"

    def test_documented_public_pool_contract_holds_on_the_v1_scheme(self):
        endpoint = parse_pool_endpoint("stratum+tcp://public-pool.io:21496")
        assert endpoint.host == "public-pool.io"
        assert endpoint.port == 21496
        assert detect_provider(endpoint.normalized_url).provider_id == "public_pool"

    def test_unknown_pool_is_unknown_not_mislabeled(self):
        detection = detect_provider("stratum+tcp://minha.pool.local:3333")
        assert detection.provider is None
        assert detection.provider_id == "unknown"
        assert detection.chain is None
        assert detection.label == "minha.pool.local"

    @pytest.mark.parametrize(
        "raw",
        [
            "stratum+tcp://",
            "stratum+tcp://:3333",
            "nonsense",
            "",
            None,
            "stratum+tcp://user:secret@pool.example.test:3333",
        ],
    )
    def test_detection_handles_malformed_url_fixtures(self, raw):
        """Provider detection returns a label for these untrusted URL shapes."""
        detection = detect_provider(raw)
        assert isinstance(detection.provider_id, str) and detection.provider_id
        assert isinstance(detection.label, str) and detection.label
        assert detection.kind is None

    def test_rejected_credentials_do_not_change_detected_provider(self):
        """Parsing rejects credentials; provider detection still extracts host."""
        with pytest.raises(EndpointError):
            parse_pool_endpoint("stratum+tcp://user:secret@solo.ckpool.org:3333")
        assert (
            detect_provider(
                "stratum+tcp://user:secret@solo.ckpool.org:3333"
            ).provider_id
            == "ckpool_solo"
        )


# ══════════════════════════════════════════════════════════════════════════
#  Passive TCP probe against the local lab and capability integration
# ══════════════════════════════════════════════════════════════════════════


class TestFleetV1ProbePipeline:
    def test_healthy_pool_reports_stratum_v1_capability(self):
        with StratumV1Lab() as lab:
            endpoint = f"stratum+tcp://pool.example.test:{lab.port}"
            assert detect_provider(endpoint).provider_id == "unknown"
            result = probe_stratum_v1(
                _resolution("stratum+tcp", "8.8.8.8", lab.port),
                socket_factory=_lab_socket_factory(lab.port),
            )

        assert result.healthy is True
        assert result.protocol is PoolProtocol.STRATUM_V1
        assert result.capability is CapabilityState.SUPPORTED
        assertion = capability_from_v1_probe(result)
        assert assertion.name == "protocol.stratum_v1.subscribe"
        assert assertion.provenance is Provenance.OBSERVED
        assert assertion.state is CapabilityState.SUPPORTED
        graph = build_capability_graph((assertion,))
        assert (
            graph.get("protocol.stratum_v1.subscribe").observed_state
            is CapabilityState.SUPPORTED
        )

    def test_probe_is_read_only_and_never_authorizes_a_worker(self):
        sent_payloads = []

        class _RecordingSocket(_LabRedirectSocket):
            def sendall(self, payload):
                # Record every attempted write, including any extra command
                # the single-request lab handler would not consume.
                sent_payloads.append(payload)
                super().sendall(payload)

        with StratumV1Lab() as lab:
            result = probe_stratum_v1(
                _resolution("stratum+tcp", "8.8.8.8", lab.port),
                socket_factory=lambda family, kind: _RecordingSocket(lab.port),
            )

        assert result.healthy is True
        requests = b"".join(sent_payloads).splitlines()
        assert len(requests) == 1
        assert json.loads(requests[0]) == {
            "id": 1,
            "method": "mining.subscribe",
            "params": ["CYPHER65-War-Room/1.0"],
        }

    @pytest.mark.parametrize(
        ("mode", "maximum_bytes", "failure_code"),
        [
            ("silent", 4096, "timeout"),
            ("rejected", 4096, "subscribe_rejected"),
            ("invalid_json", 4096, "invalid_json"),
            ("oversized", 256, "response_too_large"),
        ],
    )
    def test_failures_degrade_to_an_error_capability(
        self, mode, maximum_bytes, failure_code
    ):
        with StratumV1Lab(mode=mode, oversized_bytes=8192) as lab:
            result = probe_stratum_v1(
                _resolution("stratum+tcp", "8.8.8.8", lab.port),
                timeout_seconds=0.05,
                maximum_response_bytes=maximum_bytes,
                socket_factory=_lab_socket_factory(lab.port),
            )

        assert result.healthy is False
        assert result.protocol is PoolProtocol.UNKNOWN
        assert result.capability is CapabilityState.ERROR
        assert result.failure_code == failure_code
        # A failed observation is an ERROR capability, never a silent absence.
        assertion = capability_from_v1_probe(result)
        assert assertion.name == "protocol.stratum_v1.subscribe"
        assert assertion.state is CapabilityState.ERROR
        graph = build_capability_graph((assertion,))
        assert (
            graph.get("protocol.stratum_v1.subscribe").observed_state
            is CapabilityState.ERROR
        )
        # The lab's rejection detail must never surface in the result.
        assert "remote-secret-detail" not in repr(result)

    def test_probe_rejects_bogus_arguments_before_any_io(self):
        with pytest.raises(StratumV1ProbeError):
            probe_stratum_v1(
                _resolution("stratum+tcp", "8.8.8.8", 3333), timeout_seconds=0
            )
        with pytest.raises(StratumV1ProbeError, match="PoolResolution"):
            probe_stratum_v1("not-a-resolution")


# ══════════════════════════════════════════════════════════════════════════
#  The scheme is not version evidence — honesty in both directions
# ══════════════════════════════════════════════════════════════════════════


class TestSchemeIsNotVersionEvidence:
    def test_v2_scheme_pointed_at_a_v1_pool_still_reports_observed_v1(self):
        """A V1 subscribe response supplies evidence even with a V2 scheme."""
        with StratumV1Lab() as lab:
            result = probe_stratum_v1(
                _resolution("stratum2+tcp", "8.8.8.8", lab.port),
                socket_factory=_lab_socket_factory(lab.port),
            )

        assert result.healthy is True
        assert result.protocol is PoolProtocol.STRATUM_V1
        assert result.endpoint.startswith("stratum2+tcp://")

    def test_v1_scheme_pointed_at_a_v2_pool_is_never_reported_as_v1(self):
        """The V1 probe cannot speak to an SV2 Common-layer listener, so the
        row must come back unhealthy/UNKNOWN — not "V1 because the URL said so"."""
        with StratumV2Lab() as lab:
            result = probe_stratum_v1(
                _resolution("stratum+tcp", "8.8.8.8", lab.port),
                timeout_seconds=0.05,
                socket_factory=_lab_socket_factory(lab.port),
            )

        assert result.healthy is False
        assert result.protocol is PoolProtocol.UNKNOWN
        assert result.failure_code in {
            "connection_closed",
            "timeout",
            "invalid_json",
            "invalid_response",
        }

    def test_v1_scheme_pointed_at_a_v2_pool_is_reported_as_v2(self):
        with StratumV2Lab() as lab:
            result = probe_stratum_v2(
                _resolution("stratum+tcp", "8.8.8.8", lab.port),
                socket_factory=_lab_socket_factory(lab.port),
            )

        assert result.healthy is True
        assert result.protocol is PoolProtocol.STRATUM_V2
        assert result.used_version == 2


# ══════════════════════════════════════════════════════════════════════════
#  Regressions in the component boundary
# ══════════════════════════════════════════════════════════════════════════


class TestFleetV1Regressions:
    def test_a_pool_that_dies_mid_response_is_a_sanitized_failure(self):
        class _DyingSocket(_LabRedirectSocket):
            def __init__(self, port):
                super().__init__(port)
                self._response_parts = iter((b'{"id":1,"resu', b""))

            def recv(self, size):
                return next(self._response_parts, b"")

        with StratumV1Lab() as lab:
            result = probe_stratum_v1(
                _resolution("stratum+tcp", "8.8.8.8", lab.port),
                socket_factory=lambda family, kind: _DyingSocket(lab.port),
            )

        assert result.healthy is False
        assert result.protocol is PoolProtocol.UNKNOWN
        assert result.failure_code == "connection_closed"
        assert result.capability is CapabilityState.ERROR
        assertion = capability_from_v1_probe(result)
        assert assertion.state is CapabilityState.ERROR

    def test_endpoint_roundtrip_keeps_v1_transport_and_latency(self):
        endpoint = parse_pool_endpoint("stratum+tls://pool.example.test:3334")
        rebuilt = parse_pool_endpoint(endpoint.normalized_url)
        assert rebuilt == endpoint
        assert rebuilt.tls is True
        assert rebuilt.scheme == "stratum+tls"

        with StratumV1Lab() as lab:
            result = probe_stratum_v1(
                _resolution("stratum+tcp", "8.8.8.8", lab.port),
                socket_factory=_lab_socket_factory(lab.port),
            )
        assert result.total_latency_ms >= result.dns_latency_ms == 1.25
