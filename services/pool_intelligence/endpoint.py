"""Pure parsing and normalization for user-provided Stratum endpoints."""

import ipaddress
import re
from urllib.parse import urlsplit

from .models import PoolEndpoint, PoolProtocol

_SCHEMES = {"stratum+tcp": False, "stratum+ssl": True, "stratum+tls": True}
_CONTROL = re.compile(r"[\x00-\x20\x7f]")
_HOSTNAME = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


class EndpointError(ValueError):
    """The endpoint is syntactically invalid or ambiguous."""


def _normalize_host(host: str) -> str:
    value = host.rstrip(".").lower()
    if not value:
        raise EndpointError("pool host is required")
    if "%" in value:
        raise EndpointError("IPv6 scope identifiers are not allowed")
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        if any(ord(char) > 127 for char in value):
            # IDNA/UTS-46 confusable handling needs a dedicated reviewed
            # dependency. Fail closed instead of silently changing identity.
            raise EndpointError("unicode pool hostnames are not supported")
        labels = value.split(".")
        if all(
            label.isdigit() or re.fullmatch(r"0x[0-9a-f]+", label) for label in labels
        ):
            raise EndpointError("ambiguous numeric host is not allowed")
        if not _HOSTNAME.fullmatch(value):
            raise EndpointError("invalid pool hostname")
        return value
    return address.compressed


def parse_pool_endpoint(
    raw_endpoint: str, *, default_port: int | None = None
) -> PoolEndpoint:
    """Parse without resolving DNS or opening a socket.

    Credentials are deliberately excluded from the endpoint and must be
    supplied to a later authentication stage.
    """
    if not isinstance(raw_endpoint, str):
        raise EndpointError("pool endpoint must be a string")
    raw = raw_endpoint.strip()
    if not raw or len(raw) > 512 or _CONTROL.search(raw):
        raise EndpointError("invalid pool endpoint length or characters")
    candidate = raw if "://" in raw else f"stratum+tcp://{raw}"
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise EndpointError("invalid pool port or IPv6 syntax") from exc
    scheme = parsed.scheme.lower()
    if scheme not in _SCHEMES:
        raise EndpointError("unsupported pool protocol")
    if parsed.username is not None or parsed.password is not None:
        raise EndpointError("pool credentials must be supplied separately")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise EndpointError("pool endpoint cannot contain path, query, or fragment")
    host = _normalize_host(parsed.hostname or "")
    if port is None:
        port = default_port
    if port is None or not 1 <= port <= 65535:
        raise EndpointError("pool port is required and must be between 1 and 65535")
    tls = _SCHEMES[scheme]
    display_host = f"[{host}]" if ":" in host else host
    return PoolEndpoint(
        scheme=scheme,
        host=host,
        port=port,
        # A URL scheme describes transport, not the negotiated Stratum
        # version. Discovery must fingerprint V1/V2 before setting this.
        protocol=PoolProtocol.UNKNOWN,
        tls=tls,
        normalized_url=f"{scheme}://{display_host}:{port}",
    )
