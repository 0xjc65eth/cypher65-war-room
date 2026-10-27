"""Bounded, public-HTTPS-only delivery for probes and live notifications.

No redirects, environment proxies, second hostname lookup, response-body
download or automatic POST retry. Persistent queue policy belongs to callers.
"""

import ipaddress
import json
from queue import Empty, Queue
import re
import socket
import ssl
import threading
from urllib.parse import quote, urlsplit

import urllib3

from services.observability import emit_event
from services.pool_intelligence.models import PoolEndpoint, PoolProtocol
from services.pool_intelligence.policy import (
    MAX_DNS_ADDRESSES,
    DestinationPolicy,
    PolicyError,
)

DNS_TIMEOUT_SECONDS = 2.0
_DNS_CAPACITY = threading.BoundedSemaphore(4)
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


class WebhookDeliveryError(ValueError):
    """Safe, fixed error reason; never include the destination or credentials."""


def _public_target(url: str) -> tuple[str, str, str]:
    """Validate an HTTPS URL and return hostname, Host header and request target."""
    if (
        not isinstance(url, str)
        or len(url) > 2048
        or "\\" in url
        or any(ord(char) <= 32 or ord(char) == 127 for char in url)
    ):
        raise WebhookDeliveryError("invalid_destination")
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.port not in (None, 443)
            or "%" in host
        ):
            raise ValueError("invalid")
        host = host.encode("idna").decode("ascii").lower()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if len(host) > 253 or not all(
                _HOST_LABEL.fullmatch(label) for label in host.split(".")
            ):
                raise ValueError("invalid")
    except (ValueError, UnicodeError) as exc:
        raise WebhookDeliveryError("invalid_destination") from exc
    host_header = "[" + host + "]" if ":" in host else host
    target = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    if parsed.query:
        target += "?" + quote(parsed.query, safe="/%?:@!$&'()*+,;=-._~")
    return host, host_header, target


def _resolve_addresses(host: str) -> list[str]:
    """Resolve once, with a time budget and at most four outstanding DNS jobs.

    A stuck OS resolver is not killable in Python. Its daemon retains its
    capacity slot until return, bounding stranded threads rather than
    spawning an unbounded executor queue on every timed-out request.
    """
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        pass
    capacity = _DNS_CAPACITY
    if not capacity.acquire(blocking=False):
        raise WebhookDeliveryError("resolver_unavailable")
    result: Queue = Queue(maxsize=1)

    def resolve() -> None:
        try:
            records = socket.getaddrinfo(
                host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
            )
            addresses = []
            for index, record in enumerate(records):
                if index >= MAX_DNS_ADDRESSES:
                    raise ValueError("too many answers")
                addresses.append(str(record[4][0]))
            result.put((None, addresses))
        except OSError:
            result.put(("resolver_unavailable", None))
        except Exception:
            result.put(("invalid_destination", None))
        finally:
            capacity.release()

    try:
        threading.Thread(target=resolve, daemon=True, name="webhook-test-dns").start()
    except Exception as exc:
        capacity.release()
        raise WebhookDeliveryError("resolver_unavailable") from exc
    try:
        error, addresses = result.get(timeout=DNS_TIMEOUT_SECONDS)
    except Empty as exc:
        raise WebhookDeliveryError("resolver_unavailable") from exc
    if error:
        raise WebhookDeliveryError(error)
    return addresses


def deliver_webhook(url: str, payload: dict, timeout: float = 3.0) -> int:
    """POST once to public HTTPS, with DNS pinning and bounded request phases.

    Example: ``deliver_webhook(configured_url, {"severity": "WARN"})``.
    Return only the HTTP status; raise a redacted WebhookDeliveryError on
    unsafe input or transport failure. POST is never automatically retried:
    after a timeout delivery is unknown and retrying could duplicate it.
    ``timeout`` bounds each connect/read phase, not total wall-clock duration.
    """
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 0 < timeout <= 5
    ):
        raise WebhookDeliveryError("invalid_timeout")
    host, host_header, target = _public_target(url)
    endpoint = PoolEndpoint("https", host, 443, PoolProtocol.UNKNOWN, True, "")
    try:
        destination = DestinationPolicy(allowed_ports=frozenset({443})).validate(
            endpoint, _resolve_addresses(host)
        )
    except PolicyError as exc:
        raise WebhookDeliveryError("invalid_destination") from exc
    pool = None
    response = None
    try:
        pool = urllib3.HTTPSConnectionPool(
            destination.addresses[0],
            port=443,
            server_hostname=host,
            assert_hostname=host,
            cert_reqs="CERT_REQUIRED",
            ssl_context=ssl.create_default_context(),
            timeout=urllib3.Timeout(connect=timeout, read=timeout),
            retries=False,
        )
        response = pool.urlopen(
            "POST",
            target,
            body=json.dumps(payload, ensure_ascii=True, allow_nan=False).encode(
                "utf-8"
            ),
            headers={"Host": host_header, "Content-Type": "application/json"},
            redirect=False,
            retries=False,
            assert_same_host=False,
            preload_content=False,
            decode_content=False,
        )
        return int(response.status)
    except Exception as exc:
        raise WebhookDeliveryError("delivery_unavailable") from exc
    finally:
        for resource in (response, pool):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    # Cleanup is best-effort; still close the other resource.
                    # Never log provider-controlled URLs, tokens or details.
                    emit_event("webhook_test_cleanup_failed", outcome="cleanup_failed")


def deliver_test_webhook(url: str, payload: dict) -> int:
    """Send a synthetic probe using the same policy as every live webhook.

    Example: ``deliver_test_webhook(configured_url, {"severity": "TEST"})``.
    """
    return deliver_webhook(url, payload)
