"""
Чат с Qwen3.5 4B + доступ в интернет (поиск и чтение страниц).

Модель сама не «выходит» в сеть — этот скрипт даёт ей инструменты:
web_search и fetch_url. Когда нужны свежие данные, модель вызывает инструмент,
скрипт выполняет запрос и возвращает результат в контекст.

Запуск: python chat_web.py
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from tools_web import TOOL_IMPL, TOOLS

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3.5:4b"
MAX_TOOL_ROUNDS = 4

SYSTEM_PROMPT = """Ты локальный ассистент Qwen3.5 с доступом в интернет через инструменты.

Инструменты:
- web_search(query) — поиск в интернете
- fetch_url(url) — прочитать текст страницы по ссылке

Правила:
1. Если нужны актуальные данные (новости, погода, курсы, даты событий, свежие факты) — сначала вызови web_search.
2. Если пользователь дал ссылку или после поиска нужен полный текст — вызови fetch_url.
3. Не выдумывай свежие факты: опирайся на результаты инструментов и указывай источники (URL).
4. Если вопрос не требует интернета (код, объяснения, общие знания) — отвечай сам, без инструментов.
5. Отвечай кратко и по делу, на языке пользователя.
"""

# Запасной протокол, если модель вместо tool_calls пишет текст
_SEARCH_RE = re.compile(r"(?:SEARCH|ПОИСК)\s*:\s*(.+)", re.IGNORECASE)
_FETCH_RE = re.compile(r"(?:FETCH|ОТКРЫТЬ)\s*:\s*(https?://\S+)", re.IGNORECASE)


def _ollama_chat(messages: list[dict], use_tools: bool = True) -> dict:
    payload: dict = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.3},
    }
    if use_tools:
        payload["tools"] = TOOLS

    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _run_tool(name: str, arguments) -> str:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            arguments = {"query": arguments} if name == "web_search" else {"url": arguments}

    if not isinstance(arguments, dict):
        arguments = {}

    impl = TOOL_IMPL.get(name)
    if not impl:
        return f"Неизвестный инструмент: {name}"
    return impl(arguments)


def _fallback_tool_from_text(content: str) -> list[dict]:
    """Если модель написала SEARCH:/FETCH: вместо официальных tool_calls."""
    calls = []
    for m in _SEARCH_RE.finditer(content or ""):
        calls.append({"function": {"name": "web_search", "arguments": {"query": m.group(1).strip()}}})
    for m in _FETCH_RE.finditer(content or ""):
        calls.append({"function": {"name": "fetch_url", "arguments": {"url": m.group(1).strip().rstrip(".,)")}}})
    return calls


def agent_turn(messages: list[dict]) -> str:
    """Один ход пользователя: возможно несколько вызовов инструментов, затем финальный ответ."""
    for _ in range(MAX_TOOL_ROUNDS):
        data = _ollama_chat(messages, use_tools=True)
        msg = data.get("message") or {}
        content = (msg.get("content") or "").strip()
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            tool_calls = _fallback_tool_from_text(content)

        if not tool_calls:
            return content or "(пустой ответ)"

        # Сохраняем ответ ассистента с tool_calls
        messages.append(msg)

        for call in tool_calls:
            fn = call.get("function") or {}
            name = fn.get("name") or ""
            args = fn.get("arguments") or {}
            print(f"  [tool] {name}({args})", flush=True)
            result = _run_tool(name, args)
            preview = result if len(result) < 400 else result[:400] + "..."
            print(f"  <- {preview}\n", flush=True)
            messages.append({"role": "tool", "content": result})

    # Последний ответ без инструментов
    data = _ollama_chat(messages, use_tools=False)
    return ((data.get("message") or {}).get("content") or "").strip() or "(пустой ответ)"


def main() -> None:
    print(f"Чат с {MODEL} + интернет (web_search / fetch_url)")
    print("Команды: /exit — выход, /clear — очистить историю\n")

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        try:
            user = input("Вы: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nПока.")
            break

        if not user:
            continue
        if user in {"/exit", "/quit", "exit", "quit"}:
            print("Пока.")
            break
        if user == "/clear":
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            print("История очищена.\n")
            continue

        messages.append({"role": "user", "content": user})
        print("Qwen: ", end="", flush=True)
        try:
            reply = agent_turn(messages)
            print(reply)
            print()
            messages.append({"role": "assistant", "content": reply})
        except urllib.error.URLError as exc:
            print(f"\nОшибка Ollama: {exc}")
            print("Проверьте, что Ollama запущена.")
            messages.pop()
        except Exception as exc:  # noqa: BLE001
            print(f"\nОшибка: {exc}")
            messages.pop()


if __name__ == "__main__":
    main()
