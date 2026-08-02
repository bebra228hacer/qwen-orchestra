"""
Один запрос к Qwen3.5 4B без интерактива.
Пример: python ask_once.py "Объясни что такое рекурсия простыми словами"
"""

from __future__ import annotations

import sys

from llm import chat

MODEL = "qwen3.5:4b"


def ask(prompt: str) -> str:
    msg = chat(
        MODEL,
        [{"role": "user", "content": prompt}],
        temperature=0.3,
        num_ctx=4096,
        think=False,
    )
    return (msg.get("content") or "").strip()


def main() -> None:
    if len(sys.argv) < 2:
        print('Использование: python ask_once.py "ваш вопрос"')
        sys.exit(1)
    question = " ".join(sys.argv[1:])
    try:
        print(ask(question))
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
