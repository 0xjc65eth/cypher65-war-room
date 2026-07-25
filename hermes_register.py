"""
Hermes Blueprint Registration Helper
====================================
Add this at the bottom of app.py:

    from hermes_register import register_hermes
    register_hermes(app)
"""

from flask import Flask
from hermes.routes import hermes_bp


def register_hermes(app: Flask):
    """Register Hermes Cognitive Core routes."""
    app.register_blueprint(hermes_bp)
    print("[Hermes] Cognitive Core v4 registered at /api/hermes/*")