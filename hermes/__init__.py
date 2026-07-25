"""
HERMES — Cognitive Core v4
==========================
CYPHER MINING INTELLIGENCE PLATFORM
"""

from .integration import hermes, build_hermes_system
from .routes import hermes_bp

__version__ = "4.0.0-foundation"
__all__ = ["hermes", "build_hermes_system", "hermes_bp"]