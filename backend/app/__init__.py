"""Aéza analytics application package.

The runtime is imported as ``backend.app.*`` when the API is started from the
repository root (``uvicorn main:app``) and as ``app.*`` when it is started from
inside ``backend/``.  The domain layer, however, is written against the shorter
``app.*`` prefix throughout.

Putting ``backend/`` on ``sys.path`` here — once, before the analytics factory is
loaded — makes ``app.*`` resolvable in both launch modes and guarantees that a
single copy of each domain module is imported, so risk constants and settings
are never duplicated across two module trees.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
