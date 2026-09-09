"""Tests for conservative pool evidence aggregation."""

from dataclasses import FrozenInstanceError

import pytest

from services.pool_intelligence import (
    CapabilityAssertion,
    CapabilityState,
    ChainSignal,
    EvidenceError,
    PoolProtocol,
    ProviderSignal,
    Provenance,
    StratumV1ProbeResult,
    build_capability_graph,
    capability_from_v1_probe,
    classify_chain,
    fingerprint_provider,
)


def _provider(
    provider="pool_alpha",
    feature="server_banner",
    confidence=9_000,
    provenance=Provenance.OBSERVED,
    source="stratum_probe",
):
    return ProviderSignal(provider, feature, confidence, provenance, source)


def _chain(
    chain="bitcoin_mainnet",
    feature="genesis_hash",
    confidence=9_000,
    provenance=Provenance.OBSERVED,
    source="job_probe",
):
    return ChainSignal(chain, feature, confidence, provenance, source)


def test_capability_graph_resolves_trusted_assertions_and_dependencies():
    graph = build_capability_graph(
        [
            CapabilityAssertion(
                "transport.tcp",
                CapabilityState.SUPPORTED,
                Provenance.OBSERVED,
                "tcp_probe",
            ),
            CapabilityAssertion(
                "protocol.stratum_v1",
                CapabilityState.SUPPORTED,
                Provenance.API_REPORTED,
                "protocol_probe",
                requires=("transport.tcp",),
            ),
        ]
    )

    protocol = graph.get("PROTOCOL.STRATUM_V1")
    assert protocol is not None
    assert protocol.observed_state is CapabilityState.SUPPORTED
    assert protocol.effective_state is CapabilityState.SUPPORTED
    assert protocol.requires == ("transport.tcp",)
    assert protocol.blocked_by == ()
    with pytest.raises(FrozenInstanceError):
        protocol.name = "changed"


def test_untrusted_assertion_is_preserved_but_does_not_establish_capability():
    graph = build_capability_graph(
        [
            CapabilityAssertion(
                "payout.pps",
                CapabilityState.SUPPORTED,
                Provenance.USER_PROVIDED,
                "operator_form",
            )
        ]
    )

    node = graph.get("payout.pps")
    assert node is not None
    assert node.observed_state is CapabilityState.UNKNOWN
    assert node.effective_state is CapabilityState.UNKNOWN
    assert node.provenances == (Provenance.USER_PROVIDED,)


def test_untrusted_assertion_cannot_inject_a_dependency():
    graph = build_capability_graph(
        [
            CapabilityAssertion(
                "protocol.stratum_v1",
                CapabilityState.SUPPORTED,
                Provenance.OBSERVED,
                "protocol_probe",
            ),
            CapabilityAssertion(
                "protocol.stratum_v1",
                CapabilityState.SUPPORTED,
                Provenance.INFERRED,
                "provider_guess",
                requires=("malicious.requirement",),
            ),
        ]
    )

    protocol = graph.get("protocol.stratum_v1")
    assert protocol.effective_state is CapabilityState.SUPPORTED
    assert protocol.requires == ()
    assert graph.get("malicious.requirement") is None


@pytest.mark.parametrize(
    ("dependency_state", "expected_state"),
    [
        (CapabilityState.UNKNOWN, CapabilityState.UNKNOWN),
        (CapabilityState.AUTH_REQUIRED, CapabilityState.AUTH_REQUIRED),
        (CapabilityState.UNSUPPORTED, CapabilityState.ERROR),
        (CapabilityState.ERROR, CapabilityState.ERROR),
    ],
)
def test_dependency_state_fails_closed(dependency_state, expected_state):
    graph = build_capability_graph(
        [
            CapabilityAssertion(
                "auth.worker",
                dependency_state,
                Provenance.OBSERVED,
                "auth_probe",
            ),
            CapabilityAssertion(
                "jobs.stream",
                CapabilityState.SUPPORTED,
                Provenance.OBSERVED,
                "job_probe",
                requires=("auth.worker",),
            ),
        ]
    )

    jobs = graph.get("jobs.stream")
    assert jobs is not None
    assert jobs.effective_state is expected_state
    assert jobs.blocked_by == ("auth.worker",)


def test_missing_dependency_becomes_explicit_unknown_node():
    graph = build_capability_graph(
        [
            CapabilityAssertion(
                "jobs.stream",
                CapabilityState.SUPPORTED,
                Provenance.OBSERVED,
                "job_probe",
                requires=("auth.worker",),
            )
        ]
    )

    missing = graph.get("auth.worker")
    assert missing is not None
    assert missing.observed_state is CapabilityState.UNKNOWN
    assert missing.sources == ()
    assert graph.get("jobs.stream").effective_state is CapabilityState.UNKNOWN


def test_conflicting_observed_capability_states_resolve_to_error():
    graph = build_capability_graph(
        [
            CapabilityAssertion(
                "protocol.stratum_v2",
                CapabilityState.SUPPORTED,
                Provenance.OBSERVED,
                "probe_a",
            ),
            CapabilityAssertion(
                "protocol.stratum_v2",
                CapabilityState.UNSUPPORTED,
                Provenance.API_REPORTED,
                "probe_b",
            ),
        ]
    )

    assert graph.get("protocol.stratum_v2").observed_state is CapabilityState.ERROR


def test_graph_rejects_cycles_invalid_items_and_excessive_evidence():
    with pytest.raises(EvidenceError, match="cycle"):
        build_capability_graph(
            [
                CapabilityAssertion(
                    "capability.a",
                    CapabilityState.SUPPORTED,
                    Provenance.OBSERVED,
                    "probe_a",
                    requires=("capability.b",),
                ),
                CapabilityAssertion(
                    "capability.b",
                    CapabilityState.SUPPORTED,
                    Provenance.OBSERVED,
                    "probe_b",
                    requires=("capability.a",),
                ),
            ]
        )
    with pytest.raises(EvidenceError, match="invalid item"):
        build_capability_graph([object()])
    assertion = CapabilityAssertion(
        "transport.tcp",
        CapabilityState.SUPPORTED,
        Provenance.OBSERVED,
        "tcp_probe",
    )
    with pytest.raises(EvidenceError, match="too many"):
        build_capability_graph([assertion] * 129)

    wide_graph = [
        CapabilityAssertion(
            f"capability.{index}",
            CapabilityState.SUPPORTED,
            Provenance.OBSERVED,
            f"probe.{index}",
            requires=tuple(
                f"requirement.{index}.{dependency}" for dependency in range(16)
            ),
        )
        for index in range(17)
    ]
    with pytest.raises(EvidenceError, match="too many capability nodes"):
        build_capability_graph(wide_graph)


def test_v1_probe_converts_only_valid_success_to_supported_capability():
    healthy = StratumV1ProbeResult(
        endpoint="stratum+tcp://pool.example:3333",
        connected_address="203.0.113.10",
        healthy=True,
        protocol=PoolProtocol.STRATUM_V1,
        capability=CapabilityState.SUPPORTED,
        dns_latency_ms=1.0,
        tcp_latency_ms=2.0,
        tls_latency_ms=None,
        stratum_latency_ms=3.0,
        total_latency_ms=6.0,
    )
    contradictory = StratumV1ProbeResult(
        endpoint=healthy.endpoint,
        connected_address=healthy.connected_address,
        healthy=True,
        protocol=PoolProtocol.UNKNOWN,
        capability=CapabilityState.SUPPORTED,
        dns_latency_ms=1.0,
        tcp_latency_ms=2.0,
        tls_latency_ms=None,
        stratum_latency_ms=3.0,
        total_latency_ms=6.0,
    )

    assert capability_from_v1_probe(healthy).state is CapabilityState.SUPPORTED
    assert capability_from_v1_probe(contradictory).state is CapabilityState.ERROR


def test_provider_requires_two_independent_trusted_strong_sources():
    single = fingerprint_provider([_provider()])
    duplicate_source = fingerprint_provider(
        [_provider(), _provider(feature="rpc_shape")]
    )
    untrusted_second = fingerprint_provider(
        [
            _provider(),
            _provider(
                feature="rpc_shape",
                source="api_metadata",
                provenance=Provenance.INFERRED,
            ),
        ]
    )

    assert single.provider is None
    assert single.reason == "insufficient_evidence"
    assert duplicate_source.provider is None
    assert untrusted_second.provider is None


def test_provider_fingerprint_is_identified_conservatively():
    result = fingerprint_provider(
        [
            _provider(confidence=9_500),
            _provider(
                feature="rpc_shape",
                confidence=8_500,
                provenance=Provenance.API_REPORTED,
                source="metadata_probe",
            ),
            _provider(feature="weak_hint", confidence=2_000, source="weak_probe"),
        ]
    )

    assert result.provider == "pool_alpha"
    assert result.confidence_bps == 8_500
    assert result.evidence_count == 3
    assert result.conflicted is False
    assert result.reason == "identified"


def test_conflicting_provider_signal_returns_unknown_without_names_in_reason():
    result = fingerprint_provider(
        [
            _provider(),
            _provider(feature="rpc_shape", source="metadata_probe"),
            _provider(provider="pool_beta", source="other_probe"),
        ]
    )

    assert result.provider is None
    assert result.confidence_bps == 0
    assert result.conflicted is True
    assert result.reason == "conflicting_evidence"
    assert "pool_" not in result.reason


def test_chain_classifier_uses_explicit_chain_signals_only():
    result = classify_chain(
        [
            _chain(confidence=9_200),
            _chain(
                feature="coinbase_commitment",
                confidence=8_800,
                provenance=Provenance.API_REPORTED,
                source="template_probe",
            ),
        ]
    )

    assert result.chain == "bitcoin_mainnet"
    assert result.confidence_bps == 8_800
    assert result.evidence_count == 2
    assert result.conflicted is False


def test_chain_conflict_and_low_confidence_remain_unknown():
    weak = classify_chain([_chain(confidence=7_999)])
    conflict = classify_chain(
        [
            _chain(),
            _chain(feature="template", source="template_probe"),
            _chain(chain="bitcoin_testnet", source="other_probe"),
        ]
    )

    assert weak.chain is None
    assert weak.reason == "insufficient_evidence"
    assert weak.evidence_count == 1
    assert conflict.chain is None
    assert conflict.conflicted is True


@pytest.mark.parametrize(
    "factory,args",
    [
        (
            ProviderSignal,
            ("bad provider", "feature", 9_000, Provenance.OBSERVED, "probe"),
        ),
        (
            ChainSignal,
            ("bitcoin", "feature", True, Provenance.OBSERVED, "probe"),
        ),
        (
            CapabilityAssertion,
            ("bad\nname", CapabilityState.SUPPORTED, Provenance.OBSERVED, "probe"),
        ),
    ],
)
def test_evidence_models_reject_unsafe_tokens_and_boolean_confidence(factory, args):
    with pytest.raises(EvidenceError):
        factory(*args)


def test_identity_signal_collection_is_bounded_and_typed():
    with pytest.raises(EvidenceError, match="invalid item"):
        fingerprint_provider([object()])
    with pytest.raises(EvidenceError, match="too many"):
        classify_chain([_chain()] * 65)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ProviderSignal(42, "feature", 9_000, Provenance.OBSERVED, "probe"),
        lambda: ProviderSignal("pool", "feature", 9_000, "observed", "probe"),
        lambda: CapabilityAssertion(
            "transport.tcp", "supported", Provenance.OBSERVED, "probe"
        ),
        lambda: CapabilityAssertion(
            "transport.tcp",
            CapabilityState.SUPPORTED,
            Provenance.OBSERVED,
            "probe",
            requires=["transport.ip"],
        ),
        lambda: CapabilityAssertion(
            "transport.tcp",
            CapabilityState.SUPPORTED,
            Provenance.OBSERVED,
            "probe",
            requires=tuple(f"capability.{index}" for index in range(17)),
        ),
        lambda: CapabilityAssertion(
            "transport.tcp",
            CapabilityState.SUPPORTED,
            Provenance.OBSERVED,
            "probe",
            requires=("transport.tcp",),
        ),
        lambda: build_capability_graph("not-evidence"),
        lambda: build_capability_graph(None),
        lambda: capability_from_v1_probe(object()),
    ],
)
def test_evidence_boundaries_reject_invalid_shapes(factory):
    with pytest.raises(EvidenceError):
        factory()
