"""Shim: ядро перенесено в пакет qwen_orchestra."""

from qwen_orchestra.tools_local import *  # noqa: F403
from qwen_orchestra.tools_local import (  # noqa: F401
    TOOL_IMPL_LOCAL,
    TOOLS_LOCAL,
    get_local_time,
    local_context_block,
    local_datetime_snapshot,
    local_datetime_text,
)
