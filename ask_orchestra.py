"""Один вопрос через оркестр. Пример: python ask_orchestra.py \"привет\""""

from __future__ import annotations

import sys

from orchestra import handle, missing_models


def main() -> None:
    if len(sys.argv) < 2:
        print('Использование: python ask_orchestra.py "ваш вопрос"')
        sys.exit(1)

    missing = missing_models()
    if missing:
        print("Сначала скачайте модели:")
        for m in missing:
            print(f"  ollama pull {m}")
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    result = handle(question, stream=True, verbose=True)
    print(
        f"\n---\nmodel={result.model} tier={result.tier} web={result.need_web} "
        f"escalated={result.escalated} attempts={result.attempts} "
        f"checked={result.checked} problems={result.problems or '-'}"
    )


if __name__ == "__main__":
    main()
