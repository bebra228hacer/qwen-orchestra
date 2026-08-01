# AGENTS.md — Qwen Orchestra

Руководство для AI-агентов, работающих с этим репозиторием.

## Что это

Локальный **оркестр LLM** поверх **Ollama** (Qwen2.5: 0.5b → 3b → 7b → 14b + coder) + **веб-чат** в стиле Cursor Chat (только тёмная тема, один пользователь, `127.0.0.1`).

Это **не** облачный бот и **не** редактор кода. Веб-UI — чат/composer текста к оркестру.

## Обязательные зависимости среды

1. Сервис **Ollama** запущен (`http://localhost:11434`).
2. Модели: `qwen2.5:0.5b`, `qwen2.5:3b`, `qwen2.5:7b` (`ollama pull …`).
3. Опционально: `qwen2.5:14b`, `qwen2.5-coder:14b` (тиры `xlarge` / `coder`, Q4_K_M ~9 ГБ).
4. Python deps: `pip install -r requirements.txt` (`ddgs`, `fastapi`, `uvicorn`, `pydantic`).

На GPU ~8 ГБ VRAM 14b часто идёт как hybrid CPU/GPU — скорость ниже, чем у 7b на 100% GPU.

## Карта файлов

| Файл / папка | Роль |
|---|---|
| `orchestra.py` | Ядро: `handle()`, `plan_worker_context()`, цикл попыток, tools, колбэки |
| `router.py` | Роутер на 0.5b + `tier_floor` / `tier_ceiling` |
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
user → route → plan context → worker (± web tools) → selfcheck
                 ↑                                      │ не ok
                 └──── retry на тир выше ───────────────┘  (до MAX_ATTEMPTS)
```

- Тиры: `MODELS` в `orchestra.py` (`tiny`/`mid`/`heavy`/`xlarge`/`coder`).
- Обязательные для health: `REQUIRED_TIERS` (tiny/mid/heavy); 14b — `OPTIONAL_TIERS`.
- Эскалация: tiny → mid → heavy → xlarge; `coder` → xlarge при retry.
- Публичный вход: `orchestra.handle(user_text, history, force_tier=…, stream=…, verbose=…, on_token=…, on_status=…)`.
- История в `handle` **без** текущего user-сообщения (сервер так и передаёт; CLI тоже; если хвост дублирует вопрос — он снимается).
- Для веба/SSE **не** печатать в stdout: `verbose=False` + колбэки.
- События `on_status`: `route`, `context`, `worker`, `tool`, `selfcheck`, `retry`, `restore`.
- Эскалация пропускает **неустанавливанные** опциональные тиры (`xlarge`/`coder`); `force_tier` на отсутствующую модель → ошибка.
- `OrchestraResult`: `text`, `tier`, `model`, `need_web`, `route_reason`, `escalated`, `attempts`, `checked`, `problems`, `num_ctx`, `used_history`, `context_reason` (метаданные — от **выбранной** попытки).

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
| запрос на код + описание > 90 символов или 3+ требований | coder |
| traceback / стектрейс / отладка ошибки | coder |

Дополнительно:

- «кратко / коротко / в двух словах» → потолок **mid** (не гоняем 7b/14b зря).
- `xlarge` (14b) в auto — обычно через эскалацию после selfcheck; вручную — селектор.
- Детерминированные shortcuts **без** вызова 0.5b: tiny-приветствия, web-intent,
  floor `mid`/`heavy`/`coder`. 0.5b остаётся для неоднозначных коротких запросов.
- `need_web` — детерминированно (`need_web()` / hard+soft ключи, в т.ч. «поищи»,
  «погугли»); при `force_tier` LLM-роутер **не** вызывается.
- `ok=false` от 0.5b **игнорируется**, если запрос осмысленный (`looks_meaningful`):
  есть слова с гласными или простая арифметика. Пустой ввод и «??» отклоняются сразу,
  мусор — после второго мнения 3b.
- Ручной выбор тира (`force_tier` / селектор в UI) обходит модельный роутер;
  web определяется правилами.

## Контекст и VRAM

Перед воркером `plan_worker_context()` (все тиры; для heavy/xlarge/coder строже с историей):

1. **Приоритет** — текущий запрос целиком (не обрезать system + user).
2. **Второй** — минимальный `num_ctx` / VRAM.

Формула (токены):

```
num_ctx = min(8192, max(256, ceil_256(
  tokens(промпт) + template(128) + reserve_ответа + safety
)))
```

| Кусок | Значение |
|---|---|
| `tokens(промпт)` | system + история + user; оценка ~2 символа/токен (завышена для RU/кода) |
| `template` | 128 (chat-шаблон / спецтокены) |
| `reserve_ответа` | 512 короткий (< 48 символов) / 768 обычный / 1536 код (`coder` или признаки кода) |
| `safety` | `max(128, ~10% от суммы трёх кусков выше)` |
| `ceil_256` | выравнивание как в llama.cpp |

История:

- tiny/mid — до 8 реплик (урезаются с начала, если не влезают в потолок);
- heavy/xlarge/coder — только если нужна: отсылки («выше», «продолжи», «исправь это»),
  короткий follow-up, правка без кода в сообщении; иначе `[]`;
- самодостаточный длинный текст / блок кода → без истории.

Константы в `orchestra.py`: `CTX_TEMPLATE_TOKENS`, `CTX_OUT_*`, `CTX_SAFETY_FLAT`, `NUM_CTX_MAX`.

Событие `context` / SSE `meta.phase=context`: `used_history`, `num_ctx`, `context_reason`, `history_messages`.  
В `done` и чипах UI: `ctx N`, `без истории` / `история`.

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
   `num_ctx` ревьюера — 4096. При сбое ревьюера `ok=true`, но `checked=false`
   (`note=review-error`). Ревью запускается и на последней попытке (без дальнейшего retry).

Не прошло → запрос **переделывается** на модели уровнем выше, до `MAX_ATTEMPTS`
(по умолчанию 3). Правка (`Verdict.hint`) идёт в **system** (`RETRY_SYSTEM`), а не
в текст пользователя — иначе модель извиняется вместо ответа.
Web-tool результаты **кэшируются** между retry (повторный поиск не делается).

Если ни одна попытка не прошла, берётся ответ с минимальным весом проблем
(`Verdict.severity()` по таблице `SEVERITY`; `empty`/`error` тяжелее, чем
`too_short`/`incomplete`). Если это не последняя попытка — летит `restore`.

В UI: событие `check` (строка self-check), `meta.phase="retry"` очищает
забракованный текст, `meta.phase="restore"` — восстановление лучшей попытки,
чипы `попыток: N` / `проверено` / коды проблем.

Регулировка в `orchestra.py`: `MAX_ATTEMPTS`, `SELFCHECK_LLM`, `SELFCHECK_MODEL`.

## Веб-API (`server.py`, порт **8787**, host **127.0.0.1**)

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/ready` | Быстрый ping (лаунчер; **без** Ollama) |
| GET | `/api/health` | Ollama + `missing` + `missing_optional` + `tiers` |
| GET/POST | `/api/chats` | Список / создать |
| GET/DELETE | `/api/chats/{id}` | История / удалить |
| POST | `/api/chats/{id}/clear` | Очистить |
| POST | `/api/chats/{id}/messages` | SSE ответ |

Тело сообщения: `{ "content": "...", "force_tier": null|"tiny"|"mid"|"heavy"|"xlarge"|"coder" }`.

SSE events: `meta`, `token`, `tool`, `check`, `done`, `error`.

- `meta.phase`: `context` | `worker` | `retry` | `restore` (`retry`/`restore` очищают текст в UI).
- `meta` также может нести `num_ctx`, `used_history`, `context_reason`.
- `check`: `{ok, problems, note, attempt, model, checked}` — результат самопроверки.
- `done`: `attempts`, `checked`, `problems`, `num_ctx`, `used_history`, `context_reason`.

`/api/health`: `ok` = Ollama доступна и нет **обязательных** missing; `missing_optional` — 14b/coder.
Один запрос `/api/tags` на health (список моделей переиспользуется).

Параллельные сообщения в одном чате сериализуются (второй POST получит ошибку, пока идёт первый).

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
3. Новые проверки ответа — в `selfcheck.py` (код проблемы + текст в `HINTS`);
   правила выбора модели — в `router.tier_floor` / `tier_ceiling`;
   размер окна / история — в `plan_worker_context` / связанные хелперы в `orchestra.py`.
4. Лаунчер readiness — только `/api/ready`; тяжёлые проверки Ollama — в `/api/health`.
5. Не слушать `0.0.0.0` без явной просьбы пользователя.
6. Не добавлять светлую тему / аккаунты / IDE без запроса.
7. CLI (`orchestra_chat.py` и др.) оставлять рабочими.
8. Отвечать пользователю **по-русски**, если не попросил иначе.
9. Коммиты — только по явной просьбе.
10. При смене тиров / контекста / API — обновлять `README.md`, `AGENTS.md`, `.cursor/rules/qwen-orchestra.mdc`.

## Типичный roadmap (ещё не сделано)

- Персистентность чатов (SQLite), контракт API сохранить.
- Реестр многих моделей/агентов (`/api/agents`).
- Правая панель Tools/Logs.
- Редактор кода — отдельный этап по запросу.
- Точный подсчёт токенов через токенизатор модели вместо эвристики символов.
