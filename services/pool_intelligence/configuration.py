"""Fail-closed validation for ASIC pool-update command payloads.

This module is deliberately network-free.  It validates and canonicalizes the
configuration that an already-authorized device command may send to firmware;
DNS resolution and destination policy remain separate release gates.
"""

from dataclasses import dataclass
import re
from typing import Any, Mapping

from .endpoint import EndpointError, parse_pool_endpoint
from .models import PoolEndpoint


_ALLOWED_FIELDS = frozenset({"stratumURL", "stratumPort", "stratumUser"})
_DECIMAL_PORT = re.compile(r"[0-9]+")


class PoolConfigurationError(ValueError):
    """The requested ASIC pool configuration is incomplete or unsafe."""


@dataclass(frozen=True)
class ValidatedPoolConfiguration:
    """Canonical, firmware-compatible pool configuration.

    Credentials are intentionally not part of this model.  The worker identity
    is transient command data and must be redacted by every public/audit sink.
    """

    endpoint: PoolEndpoint
    firmware_url: str
    worker: str

    def to_adapter_parameters(self) -> dict[str, Any]:
        """Return the only fields the current AxeOS adapter may transmit."""
        return {
            "stratumURL": self.firmware_url,
            "stratumPort": self.endpoint.port,
            "stratumUser": self.worker,
        }


def _parse_port(raw_port: Any) -> int:
    if isinstance(raw_port, bool):
        raise PoolConfigurationError("stratumPort must be an integer")
    if isinstance(raw_port, int):
        port = raw_port
    elif isinstance(raw_port, str) and _DECIMAL_PORT.fullmatch(raw_port):
        port = int(raw_port)
    else:
        raise PoolConfigurationError("stratumPort must be an integer")
    if not 1 <= port <= 65535:
        raise PoolConfigurationError(
            "stratumPort must be between 1 and 65535; it is never clamped"
        )
    return port


def _validate_worker(raw_worker: Any) -> str:
    if not isinstance(raw_worker, str):
        raise PoolConfigurationError("stratumUser must be a string")
    if not raw_worker or len(raw_worker) > 256:
        raise PoolConfigurationError(
            "stratumUser is required and must contain at most 256 characters"
        )
    if raw_worker != raw_worker.strip() or any(char.isspace() for char in raw_worker):
        raise PoolConfigurationError("stratumUser cannot contain whitespace")
    if any(ord(char) < 33 or ord(char) > 126 for char in raw_worker):
        raise PoolConfigurationError("stratumUser must use printable ASCII")
    return raw_worker


def validate_pool_configuration(
    parameters: Mapping[str, Any],
) -> ValidatedPoolConfiguration:
    """Validate and canonicalize the existing ``update_pool`` API payload.

    A complete configuration is required.  Partial writes could combine a new
    endpoint with stale firmware state and cannot be safely reconciled.
    """
    if not isinstance(parameters, Mapping):
        raise PoolConfigurationError("pool parameters must be an object")
    unknown = sorted(str(key) for key in parameters.keys() - _ALLOWED_FIELDS)
    if unknown:
        raise PoolConfigurationError("unsupported update_pool parameter")
    missing = sorted(_ALLOWED_FIELDS - parameters.keys())
    if missing:
        raise PoolConfigurationError(
            "update_pool requires stratumURL, stratumPort, and stratumUser"
        )

    raw_url = parameters["stratumURL"]
    if not isinstance(raw_url, str):
        raise PoolConfigurationError("stratumURL must be a string")
    if raw_url != raw_url.strip():
        raise PoolConfigurationError("stratumURL cannot contain surrounding whitespace")
    port = _parse_port(parameters["stratumPort"])
    worker = _validate_worker(parameters["stratumUser"])
    try:
        endpoint = parse_pool_endpoint(raw_url, default_port=port)
    except EndpointError as exc:
        raise PoolConfigurationError(str(exc)) from exc
    if endpoint.port != port:
        raise PoolConfigurationError(
            "stratumURL port and stratumPort must identify the same destination"
        )

    display_host = f"[{endpoint.host}]" if ":" in endpoint.host else endpoint.host
    return ValidatedPoolConfiguration(
        endpoint=endpoint,
        firmware_url=f"{endpoint.scheme}://{display_host}",
        worker=worker,
    )
