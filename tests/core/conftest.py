"""Shared pytest fixtures for core tests."""

import pytest


@pytest.fixture
def client():
    """Yield a Flask test client and the core device registry."""
    from app import app, _core_registry

    app.config["TESTING"] = True
    yield app.test_client(), _core_registry
