"""Qwen Orchestra — локальный SDK поверх Ollama (+ OpenRouter).

Публичный вход для приложений::

    from qwen_orchestra import Client, GenOptions

    client = Client()
    result = client.ask("привет", temperature=0.2)
    # или: client.ask("…", gen=GenOptions(temperature=0.2, seed=42))

Полная документация для встраивания в другой проект: ``docs/SDK.md``.
"""

from __future__ import annotations

from .client import Client
from .llm import GenOptions, merge_gen, worker_gen
from .orchestra import OrchestraResult
from .router import RouteDecision, Tier
from .selfcheck import Verdict

__all__ = [
    "Client",
    "GenOptions",
    "OrchestraResult",
    "RouteDecision",
    "Tier",
    "Verdict",
    "merge_gen",
    "worker_gen",
]

__version__ = "0.1.1"
