"""Local AI Analyst: grounded explanations over the canonical analytics backend.

The module is a *consumer* of the platform: it reads published analytics through
the same storage the HTTP API serves and never recomputes a score, a monetary
amount or a business fact.  The language model explains; the backend decides.
"""

from __future__ import annotations

from .config import AISettings, ai_settings
from .service import AIService, build_ai_service

__all__ = ["AISettings", "ai_settings", "AIService", "build_ai_service"]
