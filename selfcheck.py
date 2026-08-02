"""Shim: ядро перенесено в пакет qwen_orchestra."""

from qwen_orchestra.selfcheck import *  # noqa: F403
from qwen_orchestra.selfcheck import (  # noqa: F401
    HINTS,
    Verdict,
    arithmetic_problems,
    check,
    content_problems,
    language_problems,
    llm_review,
)
