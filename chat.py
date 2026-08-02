"""
Простой чат с локальной Qwen3.5 4B через Ollama API.
Запуск: python chat.py
Требует: Ollama запущен, модель скачана (ollama pull qwen3.5:4b)
"""

from __future__ import annotations

import urllib.error

from llm import chat_stream

MODEL = "qwen3.5:4b"


def main() -> None:
    print(f"Чат с {MODEL} (Ollama). Пустая строка или /exit — выход.\n")
    messages: list[dict[str, str]] = [
        {"role": "system", "content": "Ты полезный ассистент. Отвечай кратко и по делу."}
    ]

    while True:
        try:
            user = input("Вы: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nПока.")
            break

        if not user or user in {"/exit", "/quit", "exit", "quit"}:
            print("Пока.")
            break

        messages.append({"role": "user", "content": user})
        print("Qwen: ", end="", flush=True)
        try:
            reply = chat_stream(
                MODEL,
                messages,
                on_token=lambda t: print(t, end="", flush=True),
                temperature=0.3,
            )
            print()
        except urllib.error.URLError as exc:
            print(f"\nОшибка: не удалось подключиться к Ollama ({exc}).")
            print("Убедитесь, что Ollama запущена (обычно после установки она в трее).")
            messages.pop()
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"\nОшибка: {exc}")
            messages.pop()
            continue

        messages.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    main()
