"""Boot-policy fail-closed guards (Issue #535)."""

import pytest

from config import is_cloud_deploy
from services.boot_policy import (
    cors_allow_origin,
    flask_debug_requested,
    validate_boot_policy,
)


def test_is_cloud_deploy_reads_mapping_without_process_env():
    assert is_cloud_deploy({}) is False
    assert is_cloud_deploy({"RENDER": "true"}) is True
    assert is_cloud_deploy({"RENDER": "0"}) is False
    assert is_cloud_deploy({"CLOUD_MODE": "yes"}) is True


def test_local_open_mode_allows_ephemeral_secret():
    validate_boot_policy({}, cloud=False)


def test_cloud_without_secret_aborts():
    with pytest.raises(SystemExit, match="SECRET_KEY is required"):
        validate_boot_policy({"RENDER": "true"}, cloud=True)


def test_auth_without_secret_aborts_even_locally():
    with pytest.raises(SystemExit, match="SECRET_KEY is required"):
        validate_boot_policy({"API_KEY": "k"}, cloud=False)


def test_cloud_with_stable_secret_boots():
    validate_boot_policy(
        {"SECRET_KEY": "stable-secret-key", "RENDER": "true"}, cloud=True
    )


def test_cloud_rejects_cors_wildcard():
    with pytest.raises(SystemExit, match="CORS_ORIGINS=\\*"):
        validate_boot_policy(
            {"SECRET_KEY": "stable", "CORS_ORIGINS": "*"},
            cloud=True,
        )


def test_local_allows_cors_wildcard():
    validate_boot_policy({"CORS_ORIGINS": "*"}, cloud=False)


def test_cloud_rejects_flask_debug():
    with pytest.raises(SystemExit, match="Flask debug"):
        validate_boot_policy(
            {"SECRET_KEY": "stable", "FLASK_DEBUG": "1"},
            cloud=True,
        )


def test_cloud_rejects_flask_env_development():
    with pytest.raises(SystemExit, match="Flask debug"):
        validate_boot_policy(
            {"SECRET_KEY": "stable", "FLASK_ENV": "development"},
            cloud=True,
        )


def test_flask_debug_requested_truth_table():
    assert flask_debug_requested({}) is False
    assert flask_debug_requested({"FLASK_DEBUG": "0"}) is False
    assert flask_debug_requested({"FLASK_DEBUG": "true"}) is True
    assert flask_debug_requested({"FLASK_ENV": "production"}) is False
    assert flask_debug_requested({"FLASK_ENV": "development"}) is True


def test_cors_allow_origin_unset():
    assert cors_allow_origin("", "https://evil.example", cloud=False) is None
    assert cors_allow_origin("", "https://evil.example", cloud=True) is None


def test_cors_allow_origin_wildcard_local_only():
    assert cors_allow_origin("*", "https://site-qualquer.com", cloud=False) == "*"
    assert cors_allow_origin("*", "https://site-qualquer.com", cloud=True) is None


def test_cors_allow_origin_allowlist():
    allow = "https://app.example.com, https://x.io"
    assert cors_allow_origin(allow, "https://app.example.com", cloud=True) == (
        "https://app.example.com"
    )
    assert cors_allow_origin(allow, "https://evil.io", cloud=True) is None
    assert cors_allow_origin(allow, "", cloud=False) is None
