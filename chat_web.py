"""
Чат с Qwen3.5 4B + доступ в интернет (поиск и чтение страниц).

Модель сама не «выходит» в сеть — этот скрипт даёт ей инструменты:
web_search и fetch_url. Когда нужны свежие данные, модель вызывает инструмент,
скрипт выполняет запрос и возвращает результат в контекст.

Запуск: python chat_web.py
"""

from __future__ import annotations

import urllib.error

from qwen_orchestra.llm import chat
from qwen_orchestra.orchestra import MAX_TOOL_CALLS, MAX_TOOL_ROUNDS, _fallback_tools, _run_tool
from qwen_orchestra.tools_web import TOOLS

MODEL = "qwen3.5:4b"

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


def agent_turn(messages: list[dict]) -> str:
    """Один ход пользователя: возможно несколько вызовов инструментов, затем финальный ответ."""
    start_len = len(messages)
    calls_done = 0
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            if calls_done >= MAX_TOOL_CALLS:
                break
            msg = chat(
                MODEL,
                messages,
                tools=TOOLS,
                temperature=0.3,
                keep_alive="10m",
            )
            content = (msg.get("content") or "").strip()
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                tool_calls = _fallback_tools(content)
            if not tool_calls:
                return content or "(пустой ответ)"

            messages.append(msg)
            for call in tool_calls:
                if calls_done >= MAX_TOOL_CALLS:
                    break
                fn = call.get("function") or {}
                name = fn.get("name") or ""
                args = fn.get("arguments") or {}
                print(f"  [tool] {name}({args})", flush=True)
                result = _run_tool(name, args)
                preview = result if len(result) < 400 else result[:400] + "..."
                print(f"  <- {preview}\n", flush=True)
                messages.append({"role": "tool", "content": result})
                calls_done += 1

        msg = chat(MODEL, messages, temperature=0.3, keep_alive="10m")
        return (msg.get("content") or "").strip() or "(пустой ответ)"
    except Exception:
        # Откат всех tool/assistant сообщений этого хода
        del messages[start_len:]
        raise


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
            if messages and messages[-1].get("role") == "user":
                messages.pop()


if __name__ == "__main__":
    main()
