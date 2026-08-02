"""Shim: ядро перенесено в пакет qwen_orchestra."""

from qwen_orchestra.llm import *  # noqa: F403
from qwen_orchestra.llm import (  # noqa: F401
    DEFAULT_OLLAMA_HOST,
    OLLAMA_CHAT_URL,
    OLLAMA_TAGS_URL,
    chat,
    chat_stream,
    get_ollama_host,
    installed_models,
    set_ollama_host,
)
