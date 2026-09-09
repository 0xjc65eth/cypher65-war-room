"""Fail-closed preflight for a proposed ASIC pool configuration."""

from dataclasses import dataclass
from enum import Enum
import math
import socket
from typing import Any, Callable, Mapping

from .configuration import PoolConfigurationError, validate_pool_configuration
from .models import CapabilityState, PoolProtocol
from .policy import DestinationPolicy, PolicyError
from .resolver import ResolutionError, Resolver, resolve_pool_destination
from .stratum_v1 import (
    DEFAULT_PROBE_TIMEOUT_SECONDS,
    StratumV1ProbeError,
    StratumV1ProbeResult,
    probe_stratum_v1,
)

_PUBLIC_PROBE_FAILURES = frozenset(
    {
        "connection_closed",
        "connection_failed",
        "invalid_json",
        "invalid_response",
        "invalid_subscribe_result",
        "response_too_large",
        "subscribe_rejected",
        "timeout",
        "tls_failed",
    }
)


class PoolDryRunError(ValueError):
    """The dry-run dependency contract or options are invalid."""


class PoolDryRunStage(str, Enum):
    CONFIGURATION = "configuration"
    RESOLUTION = "resolution"
    STRATUM = "stratum"
    READY = "ready"


@dataclass(frozen=True)
class PoolDryRunResult:
    """Sanitized result: endpoint, address, worker and remote data are absent."""

    ready: bool
    stage: PoolDryRunStage
    protocol: PoolProtocol = PoolProtocol.UNKNOWN
    capability: CapabilityState = CapabilityState.UNKNOWN
    failure_code: str | None = None
    dns_latency_ms: float | None = None
    tcp_latency_ms: float | None = None
    tls_latency_ms: float | None = None
    stratum_latency_ms: float | None = None
    total_latency_ms: float | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "stage": self.stage.value,
            "protocol": self.protocol.value,
            "capability": self.capability.value,
            "failure_code": self.failure_code,
            "latency_ms": {
                "dns": self.dns_latency_ms,
                "tcp": self.tcp_latency_ms,
                "tls": self.tls_latency_ms,
                "stratum": self.stratum_latency_ms,
                "total": self.total_latency_ms,
            },
        }


Probe = Callable[..., StratumV1ProbeResult]


def _failure(stage: PoolDryRunStage, code: str) -> PoolDryRunResult:
    return PoolDryRunResult(
        ready=False,
        stage=stage,
        capability=CapabilityState.ERROR,
        failure_code=code,
    )


def run_pool_dry_run(
    parameters: Mapping[str, Any],
    *,
    policy: DestinationPolicy | None = None,
    resolver: Resolver = socket.getaddrinfo,
    probe: Probe = probe_stratum_v1,
    timeout_seconds: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
) -> PoolDryRunResult:
    """Validate, resolve once and perform a credential-free V1 subscribe.

    The default policy accepts only public destinations on the reviewed
    Stratum port allowlist. Local destinations and custom ports require a
    separate administrator-only integration and remain unavailable here.
    """
    destination_policy = policy if policy is not None else DestinationPolicy()
    if not isinstance(destination_policy, DestinationPolicy):
        raise PoolDryRunError("policy must be a DestinationPolicy")

    try:
        configuration = validate_pool_configuration(parameters)
    except PoolConfigurationError:
        return _failure(PoolDryRunStage.CONFIGURATION, "configuration_invalid")

    if (
        configuration.endpoint.port not in destination_policy.allowed_ports
        and not destination_policy.allow_custom_ports
    ) or (
        destination_policy.local_pool_mode
        and not destination_policy.administrator_authorized
    ):
        return _failure(PoolDryRunStage.RESOLUTION, "destination_rejected")

    try:
        resolution = resolve_pool_destination(
            configuration.endpoint,
            destination_policy,
            resolver=resolver,
        )
    except ResolutionError:
        return _failure(PoolDryRunStage.RESOLUTION, "resolution_failed")
    except PolicyError:
        return _failure(PoolDryRunStage.RESOLUTION, "destination_rejected")

    try:
        result = probe(resolution, timeout_seconds=timeout_seconds)
    except StratumV1ProbeError:
        return _failure(PoolDryRunStage.STRATUM, "probe_invalid")
    if not isinstance(result, StratumV1ProbeResult):
        raise PoolDryRunError("probe must return StratumV1ProbeResult")

    latencies = (
        result.dns_latency_ms,
        result.tcp_latency_ms,
        result.tls_latency_ms,
        result.stratum_latency_ms,
        result.total_latency_ms,
    )
    if any(
        value is not None
        and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        )
        for value in latencies
    ):
        return _failure(PoolDryRunStage.STRATUM, "probe_invalid")

    failure_code = result.failure_code
    if not result.healthy:
        failure_code = (
            failure_code
            if isinstance(failure_code, str) and failure_code in _PUBLIC_PROBE_FAILURES
            else "probe_failed"
        )
    ready = bool(
        result.healthy
        and result.protocol is PoolProtocol.STRATUM_V1
        and result.capability is CapabilityState.SUPPORTED
        and failure_code is None
    )
    return PoolDryRunResult(
        ready=ready,
        stage=PoolDryRunStage.READY if ready else PoolDryRunStage.STRATUM,
        protocol=result.protocol if ready else PoolProtocol.UNKNOWN,
        capability=(CapabilityState.SUPPORTED if ready else CapabilityState.ERROR),
        failure_code=None if ready else (failure_code or "probe_failed"),
        dns_latency_ms=result.dns_latency_ms,
        tcp_latency_ms=result.tcp_latency_ms,
        tls_latency_ms=result.tls_latency_ms,
        stratum_latency_ms=result.stratum_latency_ms,
        total_latency_ms=result.total_latency_ms,
    )
