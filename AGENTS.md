# AGENTS.md — Qwen Orchestra

Руководство для AI-агентов, работающих с этим репозиторием.

## Что это

Локальный **оркестр LLM** поверх **Ollama** (Qwen2.5: 0.5b → 3b → 7b) + **веб-чат** в стиле Cursor Chat (только тёмная тема, один пользователь, `127.0.0.1`).

Это **не** облачный бот и **не** редактор кода. Веб-UI — чат/composer текста к оркестру.

## Обязательные зависимости среды

1. Сервис **Ollama** запущен (`http://localhost:11434`).
2. Модели: `qwen2.5:0.5b`, `qwen2.5:3b`, `qwen2.5:7b` (`ollama pull …`).
3. Python deps: `pip install -r requirements.txt` (`ddgs`, `fastapi`, `uvicorn`, `pydantic`).

## Карта файлов

| Файл / папка | Роль |
|---|---|
| `orchestra.py` | Ядро: `handle()`, цикл попыток, tools, колбэки `on_token` / `on_status` |
| `router.py` | Роутер на 0.5b + жёсткие правила тира (`tier_floor`, `tier_ceiling`) |
| `selfcheck.py` | Самопроверка ответа: правила + LLM-ревью на 3b |
| `llm.py` | Клиент Ollama: `chat`, `chat_stream`, `installed_models` |
| `tools_web.py` | `web_search`, `fetch_url` |
| `orchestra_chat.py` | CLI оркестра |
| `ask_orchestra.py` | Один вопрос через оркестр |
| `chat.py` / `ask_once.py` | Только 3B, без оркестра |
| `chat_web.py` / `ask_web.py` | Только 3B + web tools |
| `server.py` | FastAPI: статика + API чатов + SSE |
| `web/` | UI: `index.html`, `styles.css`, `app.js` |
| `open_web.py` | Лаунчер: старт сервера + открытие браузера |
| `QwenChat.exe` / `QwenChat.bat` | Сборка/обёртка лаунчера |
| `start.bat` | Меню режимов (CP866, `cd /d "%~dp0"`) |

## Оркестр — как работает

```
user → route → worker (± web tools) → selfcheck
                  ↑                       │ не ok
                  └──── retry на тир выше ┘   (до MAX_ATTEMPTS)
```

- Тиры: `MODELS` в `orchestra.py` (`tiny`/`mid`/`heavy`).
- Публичный вход: `orchestra.handle(user_text, history, force_tier=…, stream=…, verbose=…, on_token=…, on_status=…)`.
- Для веба/SSE **не** печатать в stdout: `verbose=False` + колбэки.
- События `on_status`: `route`, `worker`, `tool`, `selfcheck`, `retry`, `restore`.
- `OrchestraResult`: `text`, `tier`, `model`, `need_web`, `route_reason`, `escalated`, `attempts`, `checked`, `problems`.

## Auto-режим: когда какая модель

Решение 0.5b **ограничено** детерминированными правилами `router.tier_floor()` —
модель может поднять тир, но не опустить ниже нужного (0.5b систематически
недооценивает сложность). `router.tier_ceiling()` держит потолок.

| Признак запроса | Минимум |
|---|---|
| приветствие, спасибо/пока, `2+2` | tiny |
| длина > 60 символов | mid |
| «объясни / напиши / переведи / сделай / как …», «что такое» | mid |
| код, SQL, git/pip/npm, ссылки, regex | mid |
| нужны свежие данные (web) | mid |
| длина > 400 символов, или 3+ вопроса в сообщении | heavy |
| архитектура, рефакторинг, оптимизация, сравнение, доказательство | heavy |
| тесты, обработка ошибок, миграция, план внедрения | heavy |
| запрос на код + описание > 90 символов или 3+ требований | heavy |
| traceback / стектрейс / отладка ошибки | heavy |

Дополнительно:

- «кратко / коротко / в двух словах» → потолок **mid** (не гоняем 7b зря).
- `need_web` от 0.5b принимается только при явных признаках (`последн`, `верси`,
  `цена`, `курс`, `когда`, `кто такой`, …) либо по жёстким web-ключам.
- `ok=false` от 0.5b **игнорируется**, если запрос осмысленный (`looks_meaningful`):
  есть слова с гласными или цифры. Пустой ввод и «??» отклоняются сразу,
  мусор — после второго мнения 3b.
- Ручной выбор тира (`force_tier` / селектор в UI) обходит все правила.

## Самопроверка (`selfcheck.py`)

После каждого ответа запускается `selfcheck.check()`:

1. **Быстрые правила** (без модели):
   `cjk` (ушёл в иероглифы), `language` (не язык вопроса), `empty`, `too_short`,
   `refusal`, `uncertain`, `repetition` (зацикливание), `truncated` (незакрытый ```).
2. **Арифметика** (`arithmetic_problems`): если в вопросе есть «сколько / посчитай /
   вычисли» и выражение, оно считается через `ast` и сверяется с ответом.
   Расхождение → `error`, а в `hint` уходит правильное значение. Совпало →
   ответ считается проверенным, LLM-ревью пропускается (оно тут только шумит).
3. **LLM-ревью** на 3b (`SELFCHECK_LLM`), если предыдущее прошло:
   `irrelevant`, `error`, `incomplete`. Ревьюер оценивает только существо, не стиль.

Не прошло → запрос **переделывается** на модели уровнем выше, до `MAX_ATTEMPTS`
(по умолчанию 3). Правка (`Verdict.hint`) идёт в **system** (`RETRY_SYSTEM`), а не
в текст пользователя — иначе модель извиняется вместо ответа.

Если ни одна попытка не прошла, берётся ответ с минимальным весом проблем
(`Verdict.severity()` по таблице `SEVERITY`; `empty`/`error` тяжелее, чем
`too_short`/`incomplete`). Если это не последняя попытка — летит `restore`.

В UI: событие `check` (строка self-check), `meta.phase="retry"` очищает
забракованный текст, чипы `попыток: N` / `проверено` / коды проблем.

Регулировка в `orchestra.py`: `MAX_ATTEMPTS`, `SELFCHECK_LLM`, `SELFCHECK_MODEL`.

## Веб-API (`server.py`, порт **8787**, host **127.0.0.1**)

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/ready` | Быстрый ping (лаунчер; **без** Ollama) |
| GET | `/api/health` | Ollama + missing models |
| GET/POST | `/api/chats` | Список / создать |
| GET/DELETE | `/api/chats/{id}` | История / удалить |
| POST | `/api/chats/{id}/clear` | Очистить |
| POST | `/api/chats/{id}/messages` | SSE ответ |

Тело сообщения: `{ "content": "...", "force_tier": null|"tiny"|"mid"|"heavy" }`.

SSE events: `meta`, `token`, `tool`, `check`, `done`, `error`.

- `meta.phase`: `worker` | `retry` (UI очищает текст) — `retry` приходит и на `restore`.
- `check`: `{ok, problems, note, attempt, model}` — результат самопроверки.
- `done`: добавляет `attempts`, `checked`, `problems`.

Чаты **in-memory** (пропадают при рестарте процесса).

## Запуск

```powershell
# CLI оркестр
python orchestra_chat.py

# Веб
python server.py
# → http://127.0.0.1:8787

# Лаунчер (одна консоль, открывает браузер)
python open_web.py
# или QwenChat.exe / QwenChat.bat
```

Лаунчер ждёт `/api/ready` (не `/api/health`), браузер открывает через `os.startfile` / `cmd start`.
`QwenChat.exe` при старте сервера вызывает системный `python` (не себя). После правок `open_web.py` пересобрать:

```powershell
pyinstaller --noconfirm --onefile --console --name QwenChat --distpath . --workpath build\qwenchat --specpath build\qwenchat open_web.py
```

`start.bat` хранить в **CP866 без BOM**; всегда начинать с `cd /d "%~dp0"`.

## UI-ограничения продукта

- Только **тёмная** тема, без light-switch.
- Один локальный пользователь, без auth.
- Нет редактора кода / файлового дерева / диффов (пока).
- Визуал: Cursor-like (серый/уголь), без фиолетовых AI-градиентов.

## Правила изменений для агентов

1. **Переиспользовать** `orchestra.handle` — не дублировать роутинг в `server.py`.
2. Стрим в UI — только через колбэки оркестра + SSE.
3. Новые проверки ответа — в `selfcheck.py` (код проблемы + текст в `HINTS`),
   правила выбора модели — в `router.tier_floor` / `tier_ceiling`, не в воркере.
3. Лаунчер readiness — только `/api/ready`; тяжёлые проверки Ollama — в `/api/health`.
4. Не слушать `0.0.0.0` без явной просьбы пользователя.
5. Не добавлять светлую тему / аккаунты / IDE без запроса.
6. CLI (`orchestra_chat.py` и др.) оставлять рабочими.
7. Отвечать пользователю **по-русски**, если не попросил иначе.
8. Коммиты — только по явной просьбе.

## Типичный roadmap (ещё не сделано)

- Персистентность чатов (SQLite), контракт API сохранить.
- Реестр многих моделей/агентов (`/api/agents`).
- Правая панель Tools/Logs.
- Редактор кода — отдельный этап по запросу.
