"""Hermetic tests for the fail-closed pool dry-run orchestrator."""

import socket

import pytest

from services.pool_intelligence import (
    CapabilityState,
    DestinationPolicy,
    PoolDryRunError,
    PoolDryRunStage,
    PoolProtocol,
    StratumV1ProbeError,
    StratumV1ProbeResult,
    run_pool_dry_run,
)


PARAMETERS = {
    "stratumURL": "stratum+tcp://pool.example.test",
    "stratumPort": 3333,
    "stratumUser": "wallet.private-worker",
}


def _resolver(address="93.184.216.34", expected_port=3333):
    def resolve(host, port, **kwargs):
        assert host == "pool.example.test"
        assert port == expected_port
        assert kwargs == {"type": socket.SOCK_STREAM, "proto": socket.IPPROTO_TCP}
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    return resolve


def _probe_result(**overrides):
    values = {
        "endpoint": "stratum+tcp://pool.example.test:3333",
        "connected_address": "93.184.216.34",
        "healthy": True,
        "protocol": PoolProtocol.STRATUM_V1,
        "capability": CapabilityState.SUPPORTED,
        "dns_latency_ms": 1.25,
        "tcp_latency_ms": 2.5,
        "tls_latency_ms": None,
        "stratum_latency_ms": 3.75,
        "total_latency_ms": 7.5,
        "failure_code": None,
    }
    values.update(overrides)
    return StratumV1ProbeResult(**values)


def test_success_is_sanitized_and_worker_never_reaches_network_dependencies():
    observed = {}

    def resolver(host, port, **kwargs):
        observed["resolver"] = (host, port, kwargs)
        return _resolver()(host, port, **kwargs)

    def probe(resolution, *, timeout_seconds):
        observed["probe"] = (resolution, timeout_seconds)
        return _probe_result()

    result = run_pool_dry_run(PARAMETERS, resolver=resolver, probe=probe)

    assert result.ready is True
    assert result.stage is PoolDryRunStage.READY
    assert result.protocol is PoolProtocol.STRATUM_V1
    assert result.capability is CapabilityState.SUPPORTED
    public = result.to_public_dict()
    assert public["latency_ms"] == {
        "dns": 1.25,
        "tcp": 2.5,
        "tls": None,
        "stratum": 3.75,
        "total": 7.5,
    }
    assert "wallet" not in repr(observed)
    assert "worker" not in repr(observed)
    assert "endpoint" not in public
    assert "address" not in public


@pytest.mark.parametrize(
    ("parameters", "failure_code"),
    [
        ({}, "configuration_invalid"),
        ({**PARAMETERS, "stratumPort": 0}, "configuration_invalid"),
        (
            {**PARAMETERS, "stratumURL": "http://pool.example.test"},
            "configuration_invalid",
        ),
    ],
)
def test_invalid_configuration_never_resolves_or_probes(parameters, failure_code):
    def forbidden(*args, **kwargs):
        raise AssertionError("network dependency must not be called")

    result = run_pool_dry_run(parameters, resolver=forbidden, probe=forbidden)
    assert result.stage is PoolDryRunStage.CONFIGURATION
    assert result.failure_code == failure_code
    assert result.ready is False


def test_resolution_failure_is_controlled():
    def resolver(*args, **kwargs):
        raise OSError("secret resolver detail")

    result = run_pool_dry_run(PARAMETERS, resolver=resolver)
    assert result.stage is PoolDryRunStage.RESOLUTION
    assert result.failure_code == "resolution_failed"
    assert "secret" not in repr(result)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.8", "169.254.1.2"])
def test_ssrf_destinations_fail_before_probe(address):
    def forbidden(*args, **kwargs):
        raise AssertionError("probe must not receive a rejected destination")

    result = run_pool_dry_run(
        PARAMETERS,
        resolver=_resolver(address),
        probe=forbidden,
    )
    assert result.failure_code == "destination_rejected"


def test_custom_port_is_rejected_by_default_policy_before_probe():
    parameters = {**PARAMETERS, "stratumPort": 12345}
    parameters["stratumURL"] = "stratum+tcp://pool.example.test"
    result = run_pool_dry_run(
        parameters,
        resolver=pytest.fail,
        probe=pytest.fail,
    )
    assert result.failure_code == "destination_rejected"


def test_unauthorized_local_mode_is_rejected_before_dns():
    result = run_pool_dry_run(
        PARAMETERS,
        policy=DestinationPolicy(local_pool_mode=True),
        resolver=pytest.fail,
        probe=pytest.fail,
    )
    assert result.failure_code == "destination_rejected"


def test_probe_contract_error_is_controlled():
    def probe(*args, **kwargs):
        raise StratumV1ProbeError("internal detail")

    result = run_pool_dry_run(PARAMETERS, resolver=_resolver(), probe=probe)
    assert result.failure_code == "probe_invalid"
    assert "internal" not in repr(result)


@pytest.mark.parametrize(
    "failure_code",
    [
        "timeout",
        "tls_failed",
        "invalid_json",
        "subscribe_rejected",
        "response_too_large",
    ],
)
def test_known_probe_failure_is_preserved_without_remote_detail(failure_code):
    result = run_pool_dry_run(
        PARAMETERS,
        resolver=_resolver(),
        probe=lambda *args, **kwargs: _probe_result(
            healthy=False,
            protocol=PoolProtocol.UNKNOWN,
            capability=CapabilityState.ERROR,
            failure_code=failure_code,
        ),
    )
    assert result.stage is PoolDryRunStage.STRATUM
    assert result.failure_code == failure_code
    assert result.protocol is PoolProtocol.UNKNOWN


def test_unknown_probe_failure_is_collapsed():
    result = run_pool_dry_run(
        PARAMETERS,
        resolver=_resolver(),
        probe=lambda *args, **kwargs: _probe_result(
            healthy=False,
            failure_code="remote says wallet.private-worker invalid",
        ),
    )
    assert result.failure_code == "probe_failed"
    assert "wallet" not in repr(result)


@pytest.mark.parametrize(
    "overrides",
    [
        {"dns_latency_ms": float("nan")},
        {"tcp_latency_ms": -1},
        {"stratum_latency_ms": True},
        {"total_latency_ms": "remote detail"},
    ],
)
def test_invalid_probe_latency_is_not_exposed(overrides):
    result = run_pool_dry_run(
        PARAMETERS,
        resolver=_resolver(),
        probe=lambda *args, **kwargs: _probe_result(**overrides),
    )
    assert result.failure_code == "probe_invalid"
    assert result.to_public_dict()["latency_ms"] == {
        "dns": None,
        "tcp": None,
        "tls": None,
        "stratum": None,
        "total": None,
    }


def test_non_text_probe_failure_is_collapsed():
    result = run_pool_dry_run(
        PARAMETERS,
        resolver=_resolver(),
        probe=lambda *args, **kwargs: _probe_result(
            healthy=False,
            failure_code=["remote", "detail"],
        ),
    )
    assert result.failure_code == "probe_failed"


@pytest.mark.parametrize(
    ("healthy", "protocol", "capability"),
    [
        (True, PoolProtocol.UNKNOWN, CapabilityState.SUPPORTED),
        (True, PoolProtocol.STRATUM_V1, CapabilityState.UNKNOWN),
        (False, PoolProtocol.STRATUM_V1, CapabilityState.SUPPORTED),
    ],
)
def test_inconsistent_probe_result_never_becomes_ready(healthy, protocol, capability):
    result = run_pool_dry_run(
        PARAMETERS,
        resolver=_resolver(),
        probe=lambda *args, **kwargs: _probe_result(
            healthy=healthy,
            protocol=protocol,
            capability=capability,
        ),
    )
    assert result.ready is False
    assert result.failure_code == "probe_failed"


def test_invalid_policy_and_probe_return_type_raise_contract_error():
    with pytest.raises(PoolDryRunError, match="DestinationPolicy"):
        run_pool_dry_run(PARAMETERS, policy="unsafe")
    with pytest.raises(PoolDryRunError, match="StratumV1ProbeResult"):
        run_pool_dry_run(
            PARAMETERS,
            policy=DestinationPolicy(),
            resolver=_resolver(),
            probe=lambda *args, **kwargs: {"healthy": True},
        )
