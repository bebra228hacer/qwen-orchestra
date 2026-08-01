"""
Один запрос к Qwen2.5 3B без интерактива.
Пример: python ask_once.py "Объясни что такое рекурсия простыми словами"
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:3b"


def ask(prompt: str) -> str:
    payload = json.dumps({"model": MODEL, "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["response"]


def main() -> None:
    if len(sys.argv) < 2:
        print('Использование: python ask_once.py "ваш вопрос"')
        sys.exit(1)

    prompt = " ".join(sys.argv[1:])
    try:
        print(ask(prompt))
    except urllib.error.URLError as exc:
        print(f"Не удалось подключиться к Ollama: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
