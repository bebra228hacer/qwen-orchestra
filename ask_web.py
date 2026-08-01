"""Неинтерактивный тест: один вопрос с доступом в интернет."""

from __future__ import annotations

import sys

from chat_web import SYSTEM_PROMPT, agent_turn


def main() -> None:
    if len(sys.argv) < 2:
        print('Использование: python ask_web.py "ваш вопрос"')
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    print(agent_turn(messages))


if __name__ == "__main__":
    main()
