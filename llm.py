"""Низкоуровневый клиент Ollama, общий для всех моделей оркестра."""

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
    )
    with _request(payload, timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("message") or {}


def chat_stream(
    model: str,
    messages: list[dict],
    *,
    on_token: Callable[[str], None] | None = None,
    temperature: float = 0.3,
    num_ctx: int = 8192,
    keep_alive: str | None = None,
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
    )
    parts: list[str] = []
    with _request(payload, timeout) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            chunk = json.loads(line)
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
