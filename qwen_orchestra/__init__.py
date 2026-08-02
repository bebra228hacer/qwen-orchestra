"""Qwen Orchestra — локальный SDK поверх Ollama (+ OpenRouter).

Публичный вход для приложений::

    from qwen_orchestra import Client

    client = Client()
    result = client.ask("привет")

Полная документация для встраивания в другой проект: ``docs/SDK.md``.
"""

from __future__ import annotations

from .client import Client
from .orchestra import OrchestraResult
from .router import RouteDecision, Tier
from .selfcheck import Verdict

__all__ = [
    "Client",
    "OrchestraResult",
    "RouteDecision",
    "Tier",
    "Verdict",
]

__version__ = "0.1.0"
