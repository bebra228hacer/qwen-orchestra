"""
Интерактивный оркестр моделей:
  tiny   = qwen3.5:0.8b       (валидация + лёгкие ответы)
  mid    = qwen3.5:4b         (обычные задачи)
  heavy  = qwen3.5:9b         (сложное)
  xlarge = qwen2.5:14b        (очень сложное / эскалация)
  coder  = qwen2.5-coder:14b  (код и отладка)

Запуск: python orchestra_chat.py
"""

from __future__ import annotations

import sys

from llm import installed_models
from orchestra import MODELS, handle, missing_models, missing_optional_models
from router import ALL_TIERS, TIER_RANK

TIERS = tuple(sorted(ALL_TIERS, key=lambda t: (TIER_RANK.get(t, 99), t)))


def main() -> None:
    print("Оркестр Qwen: слоты из settings.json (модели + промпты роутера)")
    print("Команды: /exit  /clear  /tier <id>  /auto  /tiers")
    print()

    try:
        have = set(installed_models())
    except Exception as exc:  # noqa: BLE001
        print(f"Ollama недоступна: {exc}")
        sys.exit(1)

    missing = missing_models(have)
    if missing:
        print("Не хватает обязательных моделей:")
        for m in missing:
            print(f"  ollama pull {m}")
        print()
        print("Установлено:", ", ".join(sorted(have)) or "(пусто)")
        sys.exit(1)

    optional = missing_optional_models(have)
    if optional:
        print("Опциональные модели не установлены:")
        for m in optional:
            print(f"  ollama pull {m}")
        print()

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
        if user == "/tiers":
            for tid in TIERS:
                print(f"  {tid}: {MODELS.get(tid)}")
            print()
            continue
        if user.startswith("/tier"):
            parts = user.split()
            if len(parts) == 2 and parts[1] in ALL_TIERS:
                force_tier = parts[1]
                print(f"Принудительный tier: {force_tier} ({MODELS[force_tier]})\n")
            else:
                print("Использование: /tier " + "|".join(TIERS) + "\n")
            continue

        # history без текущего user — handle сам добавит вопрос в промпт
        print("Оркестр: ", end="", flush=True)
        try:
            result = handle(user, history, force_tier=force_tier, stream=True, verbose=True)
            print(f"  (model={result.model}, escalated={result.escalated})\n")
            history.append({"role": "user", "content": user})
            history.append({"role": "assistant", "content": result.text})
        except Exception as exc:  # noqa: BLE001
            print(f"\nОшибка: {exc}\n")


if __name__ == "__main__":
    main()
