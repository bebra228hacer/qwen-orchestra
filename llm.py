"""Низкоуровневый клиент Ollama, общий для всех моделей оркестра.

`num_ctx` передаётся в `options` каждого chat/chat_stream; размер окна
подбирает оркестр (`plan_worker_context`), не этот модуль.

Для Qwen3/3.5 в payload уходит top-level `think: false` — иначе модель
тратит токены на reasoning и ломает JSON-роутер / tool_calls.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"


def _request(payload: dict, timeout: int):
    req = urllib.request.Request(
        OLLAMA_CHAT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(req, timeout=timeout)


def _think_default(model: str) -> bool | None:
    """Qwen3/3.5 по умолчанию думают — для оркестра это ломает JSON/tools/latency."""
    name = (model or "").lower()
    if name.startswith("qwen3") or "qwen3." in name:
        return False
    return None


def _payload(
    model: str,
    messages: list[dict],
    *,
    tools: list | None,
    fmt: Any,
    stream: bool,
    temperature: float,
    num_ctx: int,
    keep_alive: str | None,
    think: bool | None,
) -> dict:
    payload: dict = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "options": {"temperature": temperature, "num_ctx": num_ctx},
    }
    if tools:
        payload["tools"] = tools
    if fmt is not None:
        payload["format"] = fmt
    if keep_alive:
        payload["keep_alive"] = keep_alive
    # top-level (не в options): иначе Ollama игнорирует think
    resolved = _think_default(model) if think is None else think
    if resolved is not None:
        payload["think"] = resolved
    return payload


def chat(
    model: str,
    messages: list[dict],
    *,
    tools: list | None = None,
    fmt: Any = None,
    temperature: float = 0.3,
    num_ctx: int = 8192,
    keep_alive: str | None = None,
    think: bool | None = None,
    timeout: int = 600,
) -> dict:
    """Один запрос без стриминга. Возвращает объект message целиком."""
    payload = _payload(
        model,
        messages,
        tools=tools,
        fmt=fmt,
        stream=False,
        temperature=temperature,
        num_ctx=num_ctx,
        keep_alive=keep_alive,
        think=think,
    )
    with _request(payload, timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if err := data.get("error"):
        raise RuntimeError(f"Ollama ({model}): {err}")
    return data.get("message") or {}


def chat_stream(
    model: str,
    messages: list[dict],
    *,
    on_token: Callable[[str], None] | None = None,
    temperature: float = 0.3,
    num_ctx: int = 8192,
    keep_alive: str | None = None,
    think: bool | None = None,
    timeout: int = 600,
) -> str:
    """Потоковый ответ. Токены отдаются в on_token, полный текст возвращается."""
    payload = _payload(
        model,
        messages,
        tools=None,
        fmt=None,
        stream=True,
        temperature=temperature,
        num_ctx=num_ctx,
        keep_alive=keep_alive,
        think=think,
    )
    parts: list[str] = []
    with _request(payload, timeout) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            chunk = json.loads(line)
            if err := chunk.get("error"):
                raise RuntimeError(f"Ollama ({model}): {err}")
            piece = (chunk.get("message") or {}).get("content", "")
            if piece:
                parts.append(piece)
                if on_token:
                    on_token(piece)
            if chunk.get("done"):
                break
    return "".join(parts)


def installed_models() -> list[str]:
    with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [m["name"] for m in data.get("models", [])]
