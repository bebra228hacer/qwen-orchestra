"""
Интерактивный оркестр моделей:
  tiny  = qwen2.5:0.5b  (валидация + лёгкие ответы)
  mid   = qwen2.5:3b    (обычные задачи)
  heavy = qwen2.5:7b    (сложное)

Запуск: python orchestra_chat.py
"""

from __future__ import annotations

import sys

from llm import installed_models
from orchestra import MODELS, handle, missing_models


def main() -> None:
    print("Оркестр Qwen: 0.5b (роутер) -> 3b -> 7b")
    print("Команды: /exit  /clear  /tier tiny|mid|heavy  /auto")
    print()

    missing = missing_models()
    if missing:
        print("Не хватает моделей:")
        for m in missing:
            print(f"  ollama pull {m}")
        print()
        have = installed_models()
        print("Установлено:", ", ".join(have) or "(пусто)")
        if not any(MODELS["tiny"] in x or x.startswith("qwen2.5:0.5b") for x in have):
            print("Без 0.5b роутер не заработает. Сначала докачайте модели.")
            sys.exit(1)

    history: list[dict] = []
    force_tier = None

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
            history.clear()
            print("История очищена.\n")
            continue
        if user == "/auto":
            force_tier = None
            print("Авто-роутинг включён.\n")
            continue
        if user.startswith("/tier"):
            parts = user.split()
            if len(parts) == 2 and parts[1] in {"tiny", "mid", "heavy"}:
                force_tier = parts[1]  # type: ignore[assignment]
                print(f"Принудительный tier: {force_tier}\n")
            else:
                print("Использование: /tier tiny|mid|heavy\n")
            continue

        history.append({"role": "user", "content": user})
        print("Оркестр: ", end="", flush=True)
        try:
            result = handle(user, history, force_tier=force_tier, stream=True, verbose=True)
            print(f"  (model={result.model}, escalated={result.escalated})\n")
            history.append({"role": "assistant", "content": result.text})
        except Exception as exc:  # noqa: BLE001
            print(f"\nОшибка: {exc}\n")
            history.pop()


if __name__ == "__main__":
    main()
