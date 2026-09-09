"""Single-pass DNS resolution followed by the pool destination policy."""

from dataclasses import dataclass
import socket
import time
from typing import Callable, Iterable

from .models import PoolEndpoint
from .policy import (
    MAX_DNS_ADDRESSES,
    DestinationPolicy,
    PolicyError,
    ValidatedDestination,
)


class ResolutionError(ValueError):
    """DNS resolution failed without exposing resolver-controlled details."""


@dataclass(frozen=True)
class PoolResolution:
    destination: ValidatedDestination
    dns_latency_ms: float


Resolver = Callable[..., Iterable[tuple]]


def resolve_pool_destination(
    endpoint: PoolEndpoint,
    policy: DestinationPolicy,
    *,
    resolver: Resolver = socket.getaddrinfo,
    clock: Callable[[], float] = time.perf_counter,
) -> PoolResolution:
    """Resolve exactly once and validate every returned address.

    The resulting numeric addresses are the only destinations a connector may
    consume. Resolver error text is deliberately not propagated to callers.
    """
    started = clock()
    try:
        records = resolver(
            endpoint.host,
            endpoint.port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        addresses: list[str] = []
        for index, record in enumerate(records, start=1):
            if index > MAX_DNS_ADDRESSES:
                raise PolicyError("DNS returned too many addresses")
            try:
                addresses.append(str(record[4][0]))
            except (IndexError, TypeError) as exc:
                raise ResolutionError("DNS returned an invalid record") from exc
    except PolicyError:
        raise
    except ResolutionError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise ResolutionError("pool hostname did not resolve") from exc
    elapsed_ms = max(0.0, (clock() - started) * 1000)
    return PoolResolution(
        destination=policy.validate(endpoint, addresses),
        dns_latency_ms=round(elapsed_ms, 3),
    )
