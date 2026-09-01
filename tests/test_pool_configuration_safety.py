"""Unit tests for fail-closed ASIC pool configuration validation."""

import pytest

from services.pool_intelligence import (
    PoolConfigurationError,
    validate_pool_configuration,
)


def test_complete_pool_configuration_is_canonicalized():
    configuration = validate_pool_configuration(
        {
            "stratumURL": "STRATUM+TCP://POOL.EXAMPLE.COM",
            "stratumPort": "3333",
            "stratumUser": "wallet.worker-01",
        }
    )

    assert configuration.to_adapter_parameters() == {
        "stratumURL": "stratum+tcp://pool.example.com",
        "stratumPort": 3333,
        "stratumUser": "wallet.worker-01",
    }


@pytest.mark.parametrize("port", [0, -1, 65536, True, 3333.0, " 3333", "3e3"])
def test_invalid_port_is_rejected_instead_of_clamped(port):
    with pytest.raises(PoolConfigurationError, match="stratumPort"):
        validate_pool_configuration(
            {
                "stratumURL": "pool.example.com",
                "stratumPort": port,
                "stratumUser": "wallet.worker",
            }
        )


def test_embedded_and_separate_ports_must_match():
    with pytest.raises(PoolConfigurationError, match="same destination"):
        validate_pool_configuration(
            {
                "stratumURL": "pool.example.com:4444",
                "stratumPort": 3333,
                "stratumUser": "wallet.worker",
            }
        )


def test_endpoint_whitespace_is_rejected_not_silently_trimmed():
    with pytest.raises(PoolConfigurationError, match="surrounding whitespace"):
        validate_pool_configuration(
            {
                "stratumURL": " pool.example.com",
                "stratumPort": 3333,
                "stratumUser": "wallet.worker",
            }
        )


@pytest.mark.parametrize("worker", ["", " wallet.worker", "wallet worker", "w\n"])
def test_invalid_worker_is_rejected(worker):
    with pytest.raises(PoolConfigurationError, match="stratumUser"):
        validate_pool_configuration(
            {
                "stratumURL": "pool.example.com",
                "stratumPort": 3333,
                "stratumUser": worker,
            }
        )


def test_partial_configuration_is_rejected():
    with pytest.raises(PoolConfigurationError, match="requires"):
        validate_pool_configuration(
            {"stratumURL": "pool.example.com", "stratumPort": 3333}
        )


def test_unknown_fields_are_rejected_not_forwarded():
    with pytest.raises(PoolConfigurationError, match="unsupported"):
        validate_pool_configuration(
            {
                "stratumURL": "pool.example.com",
                "stratumPort": 3333,
                "stratumUser": "wallet.worker",
                "poolPassword": "do-not-forward",
            }
        )
