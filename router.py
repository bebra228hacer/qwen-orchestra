"""Shim: ядро перенесено в пакет qwen_orchestra."""

from qwen_orchestra.router import *  # noqa: F403
from qwen_orchestra.router import (  # noqa: F401
    ALL_TIERS,
    ROUTE_MODEL,
    SYSTEM,
    TIER_ORDER,
    TIER_RANK,
    RouteDecision,
    Tier,
    looks_meaningful,
    need_web,
    route,
    tier_ceiling,
    tier_floor,
)
