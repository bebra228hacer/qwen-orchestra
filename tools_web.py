"""Shim: ядро перенесено в пакет qwen_orchestra."""

from qwen_orchestra.tools_web import *  # noqa: F403
from qwen_orchestra.tools_web import (  # noqa: F401
    TOOLS,
    TOOL_IMPL,
    fetch_url,
    web_search,
)
