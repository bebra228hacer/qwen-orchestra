"""
Интерактивный оркестр моделей (10 фиксированных тиров):
  tiny / nano / small / mid / large / heavy / xlarge / coder / ultra / frontier

Запуск: python orchestra_chat.py
"""

from __future__ import annotations

import sys

from qwen_orchestra import settings as app_settings
from qwen_orchestra.llm import installed_models
from qwen_orchestra.orchestra import MODELS, handle, missing_models, missing_optional_models
from qwen_orchestra.router import ALL_TIERS, TIER_RANK

app_settings.ensure_bootstrapped()
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
        print("Нет ни одной доступной модели оркестра:")
        for m in missing:
            print(f"  ollama pull {m}" if not str(m).startswith("openrouter:") else f"  {m}")
        print()
        print("Установлено:", ", ".join(sorted(have)) or "(пусто)")
        sys.exit(1)

    optional = missing_optional_models(have)
    if optional:
        print("Не установлены (оркестр всё равно работает):")
        for m in optional:
            print(f"  ollama pull {m}" if not str(m).startswith("openrouter:") else f"  {m}")
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
