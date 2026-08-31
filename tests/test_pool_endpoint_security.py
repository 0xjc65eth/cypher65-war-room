"""Adversarial tests for the network-free Pool Intelligence foundation."""

import pytest

from services.pool_intelligence import (
    DestinationPolicy,
    EndpointError,
    PolicyError,
    PoolProtocol,
    parse_pool_endpoint,
)


@pytest.mark.parametrize(
    ("raw", "normalized", "tls"),
    [
        ("pool.example.com:3333", "stratum+tcp://pool.example.com:3333", False),
        (
            "stratum+ssl://POOL.EXAMPLE.COM:443",
            "stratum+ssl://pool.example.com:443",
            True,
        ),
        (
            "stratum+tls://[2001:4860:4860::8888]:443",
            "stratum+tls://[2001:4860:4860::8888]:443",
            True,
        ),
        ("8.8.8.8:3333", "stratum+tcp://8.8.8.8:3333", False),
    ],
)
def test_endpoint_normalization(raw, normalized, tls):
    endpoint = parse_pool_endpoint(raw)
    assert endpoint.normalized_url == normalized
    assert endpoint.tls is tls
    assert endpoint.protocol is PoolProtocol.UNKNOWN


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "http://pool.example.com:3333",
        "file:///etc/passwd",
        "gopher://127.0.0.1:70",
        "stratum+tcp://user:secret@pool.example.com:3333",
        "stratum+tcp://pool.example.com:3333/path",
        "stratum+tcp://pool.example.com:3333?worker=x",
        "stratum+tcp://pool.example.com:3333#fragment",
        "stratum+tcp://pool.example.com:0",
        "stratum+tcp://pool.example.com:65536",
        "stratum+tcp://pool.example.com",
        "stratum+tcp://pool.example.com:3333\r\nX-Test: yes",
        "2130706433:3333",
        "0x7f000001:3333",
        "127.1:3333",
        "127.0.1:3333",
        "0177.0.0.1:3333",
        "0x7f.1:3333",
        "1.2.3:3333",
        "stratum+tcp://pool．example.com:3333",
        "stratum+tcp://[2001:4860:4860::8888%25lo0]:3333",
    ],
)
def test_malformed_or_ambiguous_endpoint_is_rejected(raw):
    with pytest.raises(EndpointError):
        parse_pool_endpoint(raw)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "::1",
        "169.254.169.254",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "0.0.0.0",
        "224.0.0.1",
        "::ffff:127.0.0.1",
        "fc00::1",
        "fe80::1",
        "2002:7f00:1::",
        "2002:a9fe:a9fe::",
    ],
)
def test_default_policy_blocks_internal_and_special_addresses(address):
    endpoint = parse_pool_endpoint("pool.example.com:3333")
    with pytest.raises(PolicyError):
        DestinationPolicy().validate(endpoint, [address])


def test_mixed_dns_answer_fails_closed():
    endpoint = parse_pool_endpoint("pool.example.com:3333")
    with pytest.raises(PolicyError):
        DestinationPolicy().validate(endpoint, ["8.8.8.8", "127.0.0.1"])


def test_public_dns_answers_are_pinned_in_policy_result():
    endpoint = parse_pool_endpoint("pool.example.com:3333")
    result = DestinationPolicy().validate(endpoint, ["8.8.8.8", "1.1.1.1", "8.8.8.8"])
    assert result.addresses == ("8.8.8.8", "1.1.1.1")


def test_local_pool_requires_explicit_administrator_authorization():
    endpoint = parse_pool_endpoint("pool.lan:3333")
    with pytest.raises(PolicyError):
        DestinationPolicy(local_pool_mode=True).validate(endpoint, ["192.168.1.20"])
    result = DestinationPolicy(
        local_pool_mode=True, administrator_authorized=True
    ).validate(endpoint, ["192.168.1.20"])
    assert result.local_pool_mode is True


def test_local_mode_does_not_turn_documentation_ranges_into_lan_targets():
    endpoint = parse_pool_endpoint("pool.example:3333")
    with pytest.raises(PolicyError):
        DestinationPolicy(local_pool_mode=True, administrator_authorized=True).validate(
            endpoint, ["192.0.2.10"]
        )


def test_custom_port_requires_explicit_policy():
    endpoint = parse_pool_endpoint("pool.example.com:12345")
    with pytest.raises(PolicyError):
        DestinationPolicy().validate(endpoint, ["8.8.8.8"])
    assert (
        DestinationPolicy(allow_custom_ports=True)
        .validate(endpoint, ["8.8.8.8"])
        .endpoint.port
        == 12345
    )


def test_dns_answer_count_is_bounded():
    endpoint = parse_pool_endpoint("pool.example.com:3333")
    addresses = [f"8.8.8.{index}" for index in range(1, 18)]
    with pytest.raises(PolicyError, match="too many"):
        DestinationPolicy().validate(endpoint, addresses)


def test_resolved_scope_identifier_is_rejected():
    endpoint = parse_pool_endpoint("pool.example.com:3333")
    with pytest.raises(PolicyError, match="scope"):
        DestinationPolicy().validate(endpoint, ["2001:4860:4860::8888%eth0"])
