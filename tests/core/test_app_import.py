"""Ensure app.py imports cleanly at module load."""


def test_app_imports_without_error():
    import app  # noqa: F401
