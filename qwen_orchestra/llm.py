"""Клиент LLM: Ollama (локально) + OpenRouter (OpenAI-compatible).

`num_ctx` передаётся в `options` Ollama; для OpenRouter — эвристика `max_tokens`.
Размер окна подбирает оркестр (`plan_worker_context`), не этот модуль.

Для Qwen3/3.5 в Ollama-payload уходит top-level `think: false` — иначе модель
тратит токены на reasoning и ломает JSON-роутер / tool_calls.

OpenRouter (MVP): chat / stream без tools; ключ — env или secrets.json.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_OPENROUTER_BASE = "https://openrouter.ai/api/v1"

_ollama_host = DEFAULT_OLLAMA_HOST
OLLAMA_CHAT_URL = f"{DEFAULT_OLLAMA_HOST}/api/chat"
OLLAMA_TAGS_URL = f"{DEFAULT_OLLAMA_HOST}/api/tags"


def get_ollama_host() -> str:
    return _ollama_host


def set_ollama_host(host: str) -> None:
    """Сменить базовый URL Ollama (без завершающего слэша)."""
    global _ollama_host, OLLAMA_CHAT_URL, OLLAMA_TAGS_URL
    base = (host or DEFAULT_OLLAMA_HOST).strip().rstrip("/")
    if not base:
        base = DEFAULT_OLLAMA_HOST
    _ollama_host = base
    OLLAMA_CHAT_URL = f"{base}/api/chat"
    OLLAMA_TAGS_URL = f"{base}/api/tags"


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


def _normalize_provider(provider: str | None) -> str:
    name = (provider or "ollama").strip().lower() or "ollama"
    if name not in {"ollama", "openrouter"}:
        raise ValueError(f"Неизвестный provider: {name}")
    return name


def _openrouter_key_and_base() -> tuple[str, str]:
    from . import settings as app_settings

    key = app_settings.get_openrouter_api_key()
    if not key:
        raise RuntimeError(
            "OpenRouter не настроен: задайте переменную окружения "
            f"{app_settings.OPENROUTER_API_KEY_ENV} или ключ в «Модели и промпты»."
        )
    base = getattr(app_settings, "DEFAULT_OPENROUTER_BASE", DEFAULT_OPENROUTER_BASE)
    return key, str(base).rstrip("/")


def _openrouter_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://127.0.0.1:8787",
        "X-Title": "Qwen Orchestra",
    }


def _openai_messages(messages: list[dict]) -> list[dict]:
    """Только roles, которые понимает OpenAI-compatible API."""
    out: list[dict] = []
    for m in messages:
        role = m.get("role") or "user"
        if role not in {"system", "user", "assistant"}:
            continue
        out.append({"role": role, "content": str(m.get("content") or "")})
    return out


def _max_tokens_from_ctx(num_ctx: int) -> int:
    # Грубый запас под ответ; OpenRouter не принимает num_ctx как Ollama
    return max(256, min(4096, int(num_ctx) // 2 if num_ctx else 1024))


def _openrouter_chat(
    model: str,
    messages: list[dict],
    *,
    temperature: float,
    num_ctx: int,
    timeout: int,
) -> dict:
    api_key, base = _openrouter_key_and_base()
    payload = {
        "model": model,
        "messages": _openai_messages(messages),
        "temperature": temperature,
        "max_tokens": _max_tokens_from_ctx(num_ctx),
        "stream": False,
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=_openrouter_headers(api_key),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"OpenRouter ({model}): HTTP {exc.code} {body}") from exc
    if err := data.get("error"):
        msg = err if isinstance(err, str) else err.get("message") or err
        raise RuntimeError(f"OpenRouter ({model}): {msg}")
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    return {
        "role": message.get("role") or "assistant",
        "content": message.get("content") or "",
    }


def _openrouter_chat_stream(
    model: str,
    messages: list[dict],
    *,
    on_token: Callable[[str], None] | None,
    temperature: float,
    num_ctx: int,
    timeout: int,
) -> str:
    api_key, base = _openrouter_key_and_base()
    payload = {
        "model": model,
        "messages": _openai_messages(messages),
        "temperature": temperature,
        "max_tokens": _max_tokens_from_ctx(num_ctx),
        "stream": True,
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=_openrouter_headers(api_key),
        method="POST",
    )
    parts: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if err := chunk.get("error"):
                    msg = err if isinstance(err, str) else err.get("message") or err
                    raise RuntimeError(f"OpenRouter ({model}): {msg}")
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                piece = delta.get("content") or ""
                if piece:
                    parts.append(piece)
                    if on_token:
                        on_token(piece)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"OpenRouter ({model}): HTTP {exc.code} {body}") from exc
    return "".join(parts)


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
    provider: str = "ollama",
) -> dict:
    """Один запрос без стриминга. Возвращает объект message целиком."""
    prov = _normalize_provider(provider)
    if prov == "openrouter":
        if tools:
            raise RuntimeError("OpenRouter: tools пока не поддерживаются")
        return _openrouter_chat(
            model,
            messages,
            temperature=temperature,
            num_ctx=num_ctx,
            timeout=timeout,
        )
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
    provider: str = "ollama",
) -> str:
    """Потоковый ответ. Токены отдаются в on_token, полный текст возвращается."""
    prov = _normalize_provider(provider)
    if prov == "openrouter":
        return _openrouter_chat_stream(
            model,
            messages,
            on_token=on_token,
            temperature=temperature,
            num_ctx=num_ctx,
            timeout=timeout,
        )
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
