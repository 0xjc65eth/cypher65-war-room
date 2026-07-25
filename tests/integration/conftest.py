"""
Shared fixtures for Hermes integration tests.
Uses Flask test client with controlled auth environment.
"""

import os
import uuid
import pytest
from app import app as flask_app


@pytest.fixture
def client():
    """Flask test client with auth DISABLED (dev mode).
    Allows testing routing logic without auth interference."""
    old_key = os.environ.get("API_KEY")
    old_disabled = os.environ.get("HERMES_AUTH_DISABLED")
    os.environ["HERMES_AUTH_DISABLED"] = "1"
    os.environ["API_KEY"] = "integration-test-key"

    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c

    # Restore
    if old_key is None:
        os.environ.pop("API_KEY", None)
    else:
        os.environ["API_KEY"] = old_key
    if old_disabled is None:
        os.environ.pop("HERMES_AUTH_DISABLED", None)
    else:
        os.environ["HERMES_AUTH_DISABLED"] = old_disabled


@pytest.fixture
def client_auth_enabled():
    """Flask test client with auth ENFORCED.
    Used for authentication-related tests."""
    old_key = os.environ.get("API_KEY")
    old_disabled = os.environ.get("HERMES_AUTH_DISABLED")
    os.environ["API_KEY"] = "integration-test-key"
    os.environ.pop("HERMES_AUTH_DISABLED", None)

    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c

    if old_key is None:
        os.environ.pop("API_KEY", None)
    else:
        os.environ["API_KEY"] = old_key
    if old_disabled is not None:
        os.environ["HERMES_AUTH_DISABLED"] = old_disabled
    else:
        os.environ.pop("HERMES_AUTH_DISABLED", None)


@pytest.fixture
def valid_headers():
    """Valid auth headers for protected endpoints."""
    return {"X-API-Key": "integration-test-key"}


@pytest.fixture
def fresh_session_id():
    """A random UUID for session testing."""
    return str(uuid.uuid4())
