"""Pytest configuration for the backend test suite.

Inserts the backend directory on ``sys.path`` so tests can ``import app.*``
the same way the runnable scripts (``prematch.py`` et al.) do when launched
from ``backend/``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
