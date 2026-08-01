"""
Простой чат с локальной Qwen2.5 3B через Ollama API.
Запуск: python chat.py
Требует: Ollama запущен, модель скачана (ollama pull qwen2.5:3b)
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5:3b"


def chat(messages: list[dict[str, str]], stream: bool = True) -> str:
    payload = json.dumps({"model": MODEL, "messages": messages, "stream": stream}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    if not stream:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["message"]["content"]

    full = []
    with urllib.request.urlopen(req, timeout=300) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            chunk = json.loads(line)
            part = chunk.get("message", {}).get("content", "")
            if part:
                print(part, end="", flush=True)
                full.append(part)
            if chunk.get("done"):
                break
    print()
    return "".join(full)


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
            reply = chat(messages)
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
