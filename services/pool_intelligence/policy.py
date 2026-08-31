"""Destination policy applied after DNS and before any connection."""

import ipaddress
from dataclasses import dataclass
from typing import Iterable

from .models import PoolEndpoint

DEFAULT_STRATUM_PORTS = frozenset(
    {3333, 3334, 443, 4444, 5555, 7777, 8888, 9999, 21496}
)
LOCAL_POOL_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)
BLOCKED_IPV6_TRANSITION_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("2002::/16", "2001::/32", "64:ff9b::/96")
)
MAX_DNS_ADDRESSES = 16


class PolicyError(ValueError):
    """A destination is unsafe or outside deployment policy."""


@dataclass(frozen=True)
class ValidatedDestination:
    endpoint: PoolEndpoint
    addresses: tuple[str, ...]
    local_pool_mode: bool


@dataclass(frozen=True)
class DestinationPolicy:
    allowed_ports: frozenset[int] = DEFAULT_STRATUM_PORTS
    allow_custom_ports: bool = False
    local_pool_mode: bool = False
    administrator_authorized: bool = False

    def validate(
        self, endpoint: PoolEndpoint, resolved_addresses: Iterable[str]
    ) -> ValidatedDestination:
        if endpoint.port not in self.allowed_ports and not self.allow_custom_ports:
            raise PolicyError("pool port is not allowed by deployment policy")
        if self.local_pool_mode and not self.administrator_authorized:
            raise PolicyError("local pool mode requires administrator authorization")
        normalized: list[str] = []
        seen: set[str] = set()
        for index, raw in enumerate(resolved_addresses, start=1):
            if index > MAX_DNS_ADDRESSES:
                raise PolicyError("DNS returned too many addresses")
            if "%" in str(raw):
                raise PolicyError("IPv6 scope identifiers are not allowed")
            try:
                address = ipaddress.ip_address(str(raw))
            except ValueError as exc:
                raise PolicyError("DNS returned an invalid address") from exc
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
            if isinstance(address, ipaddress.IPv6Address) and any(
                address in network for network in BLOCKED_IPV6_TRANSITION_NETWORKS
            ):
                raise PolicyError("IPv6 transition destinations are blocked")
            if address.is_loopback or address.is_link_local or address.is_unspecified:
                raise PolicyError(
                    "loopback, link-local, and unspecified destinations are blocked"
                )
            if address.is_multicast or address.is_reserved:
                raise PolicyError("multicast and reserved destinations are blocked")
            if not address.is_global:
                explicitly_local = any(
                    address in network for network in LOCAL_POOL_NETWORKS
                )
                if not (self.local_pool_mode and explicitly_local):
                    raise PolicyError("non-public pool destination is blocked")
            compressed = address.compressed
            if compressed not in seen:
                seen.add(compressed)
                normalized.append(compressed)
        if not normalized:
            raise PolicyError("pool hostname did not resolve")
        # Every answer is validated. A mixed public/private DNS response fails
        # above rather than allowing the connector to choose an unsafe answer.
        return ValidatedDestination(
            endpoint=endpoint,
            addresses=tuple(normalized),
            local_pool_mode=self.local_pool_mode,
        )
