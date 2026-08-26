"""Shared database schema revision metadata.

Keep this module side-effect free: operational tooling must inspect the
expected schema without importing ``app.py`` and booting the application.
"""

CURRENT_SCHEMA_VERSION = 4
