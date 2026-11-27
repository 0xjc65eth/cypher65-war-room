"""Cloud egress guard: a PaaS process must not open a miner socket into RFC1918.

Self-host is unchanged. On a cloud deploy, a literal private/loopback/link-local/
CGNAT address is blocked, and so is a hostname that resolves to one of those.
DNS lookup is not a miner connection. An unresolvable name fails closed.
"""

from __future__ import annotations

import ipaddress
import socket


def private_target_on_cloud(target: str) -> tuple[bool, str]:
    """Return (blocked, reason). False when this process is not a cloud deploy."""
    from config import is_cloud_deploy

    if not is_cloud_deploy():
        return False, ""
    return _non_public(target)


def _non_public(target: str) -> tuple[bool, str]:
    raw = str(target or "").strip()
    if not raw or "://" in raw or "/" in raw or "@" in raw:
        return True, "invalid"
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return _hostname_non_public(raw)
    if address.version != 4 or _is_non_public_ip(address):
        return True, "literal"
    return False, ""


def _hostname_non_public(host: str) -> tuple[bool, str]:
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except OSError:
        return True, "unresolved"
    if not infos:
        return True, "unresolved"
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except (ValueError, IndexError):
            return True, "resolved"
        if address.version != 4 or _is_non_public_ip(address):
            return True, "resolved"
    return False, ""


def _is_non_public_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    from axe_fleet.scanner import is_private_ip

    if address.version != 4:
        return True
    return is_private_ip(str(address))
