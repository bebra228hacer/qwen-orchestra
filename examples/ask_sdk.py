"""Минимальный пример SDK qwen_orchestra.

Требуется: Ollama на localhost:11434 и модели оркестра.
Запуск из корня репо: python examples/ask_sdk.py

Полный гайд для ботов и AI-агентов: docs/SDK.md
Шаблон с изолированным settings + OpenRouter: examples/ask_sdk_bot.py
"""

from __future__ import annotations

from qwen_orchestra import Client


def main() -> None:
    client = Client()
    print("ready:", client.ready())
    print("health ok:", client.health().get("ok"))
    decision = client.route("привет")
    print(f"route: tier={decision.tier} reason={decision.reason!r}")
    result = client.ask("2+2")
    print(f"ask: {result.text!r} (model={result.model}, tier={result.tier})")


if __name__ == "__main__":
    main()
