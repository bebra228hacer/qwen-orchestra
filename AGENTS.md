# AGENTS.md — Qwen Orchestra

Руководство для AI-агентов, работающих с этим репозиторием.

## Что это

Локальный **оркестр LLM** поверх **Ollama** (10 тиров: tiny→frontier, Qwen3.5/2.5 + optional OpenRouter) + **веб-чат** в стиле Cursor Chat (только тёмная тема, один пользователь, `127.0.0.1`).

Это **не** облачный бот и **не** редактор кода. Веб-UI — чат/composer текста к оркестру.

## Обязательные зависимости среды

1. Сервис **Ollama** запущен (`http://localhost:11434`).
2. Модели: `qwen3.5:0.8b`, `qwen3.5:4b`, `qwen3.5:9b` (`ollama pull …`).
3. Опционально: nano/small/large/xlarge/coder/ultra/frontier (`qwen3.5:2b`, `qwen2.5:7b`/`14b`, …).
4. Опционально: OpenRouter API key (`OPENROUTER_API_KEY` или UI → secrets.json) для внешних слотов.
5. Python: `pip install -e ".[web]"` или `pip install -r requirements.txt` (`ddgs`, `psutil`; для веба — `fastapi`, `uvicorn`, `pydantic`).
6. Публичный SDK: `from qwen_orchestra import Client` (in-process; см. `examples/ask_sdk.py`).
7. Фронтенд (vendored, без npm): см. `web/vendor/` —
   - `marked.min.js` — Markdown (GFM);
   - `purify.min.js` — DOMPurify, санитизация HTML;
   - `highlight.min.js` + `highlight-github-dark.min.css` — подсветка кода;
   - `katex/` — KaTeX + auto-render + fonts (формулы `$…$` / `$$…$$`).
   Подключение в `web/index.html`; CDN не нужен (офлайн-чат).
8. Для GPU-метрик и температур в правой панели — NVIDIA + `nvidia-smi` в PATH (иначе секции GPU/температур пустые). Температура цепей памяти часто N/A на GDDR.

На GPU ~8 ГБ VRAM 14b часто идёт как hybrid CPU/GPU — скорость ниже, чем у 9b на 100% GPU.

## Карта файлов

| Файл / папка | Роль |
|---|---|
| `qwen_orchestra/` | Устанавливаемый пакет (`pip install -e .`): ядро оркестра |
| `qwen_orchestra/client.py` | Публичный `Client`: ask / route / health / settings |
| `qwen_orchestra/orchestra.py` | `handle()`, `plan_worker_context()`, цикл попыток, tools, колбэки |
| `qwen_orchestra/settings.py` | Слоты + промпты (`settings.json`); OpenRouter key (`secrets.json` / env); lazy bootstrap |
| `qwen_orchestra/router.py` | Роутер + `tier_floor` / `tier_ceiling`; SYSTEM из settings |
| `qwen_orchestra/selfcheck.py` | Самопроверка ответа: правила + LLM-ревью на mid (4b) |
| `qwen_orchestra/llm.py` | Клиент Ollama + OpenRouter (`provider`, `think: false` для Qwen3.5) |
| `qwen_orchestra/metrics.py` | CPU/RAM/GPU/температуры + Ollama `/api/ps` |
| `qwen_orchestra/tools_web.py` | `web_search`, `fetch_url` |
| `orchestra.py` / `router.py` / … | Shim-модули для старых импортов |
| `orchestra_chat.py` | CLI оркестра |
| `ask_orchestra.py` | Один вопрос через оркестр |
| `chat.py` / `ask_once.py` | Только mid (4b), без оркестра |
| `chat_web.py` / `ask_web.py` | Только mid + web tools |
| `server.py` | FastAPI: статика + API чатов + SSE + `/api/settings` + `/api/metrics` |
| `web/` | UI: `index.html`, `styles.css`, `app.js` (чат + правая панель монитора) |
| `web/vendor/` | Фронт-библиотеки: marked, DOMPurify, highlight.js, KaTeX (+ тема/шрифты) |
| `open_web.py` | Лаунчер: старт сервера + открытие браузера |
| `examples/ask_sdk.py` | Пример встраивания `Client` |
| `QwenChat.exe` / `QwenChat.bat` | Сборка/обёртка лаунчера |
| `start.bat` | Меню режимов (CP866, `cd /d "%~dp0"`) |
| `README.md` | Обзор продукта: возможности, стек, особенности |
| `SETUP.md` | Установка, модели, запуск, CLI, SDK (для людей) |
| `CODE_AUDIT.md` | Статический аудит: баги / избыточность / оптимизации; не перепроверять заново без нужды |

## SDK (`qwen_orchestra.Client`)

Публичный вход для других Python-приложений (in-process, без HTTP):

```python
from qwen_orchestra import Client
client = Client()                      # или ollama_host=..., settings_path=...
client.ready() / client.health()
client.route(text)                     # RouteDecision
client.ask(text, history=..., on_token=...)  # OrchestraResult, verbose=False
client.get_settings() / update_settings(...) / add_slot(...) / delete_slot(...)
client.set_openrouter_api_key(...)  # secrets.json; None — очистить
```

`settings.json`: в корне репо при разработке; иначе `%LOCALAPPDATA%/qwen-orchestra/` (Windows) или `~/.config/qwen-orchestra/`.
Ключ OpenRouter — env `OPENROUTER_API_KEY` или `secrets.json` рядом (не в git).
Bootstrap ленивый (`ensure_bootstrapped` / `Client.__init__`), не при голом импорте модулей.

### OpenRouter на тирах

- В UI «Модели и промпты»: выберите тир, провайдер OpenRouter + id модели (`anthropic/claude-sonnet-4`) + rank/prompt.
- Поле слота `provider`: `ollama` (default) | `openrouter` (на любом из 10 тиров).
- Worker ходит в OpenRouter chat/completions (stream); **tools пока только на Ollama**.
- Роутер и selfcheck остаются локальными (tiny/mid).
- Availability: ключ задан → слот доступен; иначе как optional missing (`openrouter:…`).
- API: `PUT /api/settings/providers/openrouter` `{ "api_key": "…" }` / `{ "clear": true }`.

## Оркестр — как работает

```
user → route → plan context → worker (± web tools) → selfcheck
                 ↑                                      │ не ok
                 └──── retry на тир выше ───────────────┘  (до MAX_ATTEMPTS)
```

- Тиры: ровно **10 фиксированных** id: `tiny` / `nano` / `small` / `mid` / `large` / `heavy` / `xlarge` / `coder` / `ultra` / `frontier`.
- Обязательные для health: `REQUIRED_TIERS` (tiny/mid/heavy); optional — остальные 7 (+ OR без ключа).
- Промпты роутера («когда использовать») — per-slot `router_prompt`; собираются в `router.SYSTEM`.
- Эскалация: по `rank` тиров; `coder` → ultra/frontier/xlarge при retry.
- UI: «Модели и промпты» — remap моделей, выпадающий список тира, OpenRouter-ключ, промпты; «Назначить на тир».
- Публичный вход: `orchestra.handle(user_text, history, force_tier=…, stream=…, verbose=…, on_token=…, on_status=…)`.
- История в `handle` **без** текущего user-сообщения (сервер так и передаёт; CLI тоже; если хвост дублирует вопрос — он снимается).
- Для веба/SSE **не** печатать в stdout: `verbose=False` + колбэки.
- События `on_status`: `route`, `context`, `worker`, `tool`, `selfcheck`, `retry`, `restore`.
- Эскалация пропускает неустановленные optional-тиры; `force_tier` только из десятки, иначе ошибка.
- `OrchestraResult`: `text`, `tier`, `model`, `need_web`, `route_reason`, `escalated`, `attempts`, `checked`, `problems`, `num_ctx`, `used_history`, `context_reason` (метаданные — от **выбранной** попытки).

## Auto-режим: когда какая модель

Решение tiny (0.8b) **ограничено** детерминированными правилами `router.tier_floor()` —
модель может поднять тир, но не опустить ниже нужного (tiny систематически
недооценивает сложность). `router.tier_ceiling()` держит потолок.

| Признак запроса | Минимум |
|---|---|
| приветствие, спасибо/пока, простая арифметика `2+2` | tiny |
| объяснения, перевод, советы, how-to, «что такое», web | mid |
| простой код / скрипт / 3+ слова / длина > 40 | mid |
| сравнение, архитектура, доказательство, длинный анализ | heavy |
| длина > 350 (или > 220 без «кратко»), 3+ вопроса, пошаговый план | heavy |
| traceback / стектрейс / «ошибка в коде» / отладка | coder |
| сервис/API/приложение, рефакторинг, unit-тесты, JWT+стек | coder |
| код + ТЗ > 80 символов или ≥2 требований | coder |

Дополнительно:

- По умолчанию осмысленный запрос — не ниже **mid** (tiny не гадает на реальных вопросах).
- Голые слова вроде «тест» / «не работает» **без** кодового контекста больше не поднимают heavy/coder.
- «кратко / коротко / в двух словах» → потолок **mid** (не гоняем 9b/14b зря).
- `xlarge` (14b) в auto — обычно через эскалацию после selfcheck; вручную — селектор.
- Детерминированные shortcuts **без** вызова tiny: приветствия, web-intent,
  floor `mid`/`heavy`/`coder`. tiny остаётся для неоднозначных коротких запросов.
- `need_web` — детерминированно (`need_web()` / hard+soft ключи, в т.ч. «поищи»,
  «погугли»); при `force_tier` LLM-роутер **не** вызывается.
- `ok=false` от tiny **игнорируется**, если запрос осмысленный (`looks_meaningful`):
  есть слова с гласными или простая арифметика. Пустой ввод и «??» отклоняются сразу,
  мусор — после второго мнения mid (4b).
- Ручной выбор тира (`force_tier` / селектор в UI) обходит модельный роутер;
  web определяется правилами.
- Qwen3.5 вызывается с `think: false` (см. `llm.py`), чтобы не ломать JSON/tools.

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
| GET | `/api/health` | Ollama + `missing` + `missing_optional` + `tiers` + `slots` |
| GET | `/api/metrics` | CPU / RAM / GPU / температуры / загруженные модели Ollama (`/api/ps`) |
| GET/PUT | `/api/settings` | Слоты моделей + `router_model` + промпты роутера (`settings.json`) |
| PUT | `/api/settings/providers/openrouter` | API-ключ OpenRouter (`secrets.json`; `{api_key}` / `{clear:true}`) |
| POST | `/api/settings/reset` | Сброс к defaults |
| POST | `/api/settings/slots` | Назначить модель на тир (`tier` + `provider`: ollama\|openrouter) |
| DELETE | `/api/settings/slots/{id}` | Тиры фиксированы — всегда 400 (смените модель / reset) |
| GET/POST | `/api/chats` | Список / создать |
| GET/DELETE | `/api/chats/{id}` | История / удалить (409 если идёт генерация) |
| POST | `/api/chats/{id}/clear` | Очистить (409 если идёт генерация) |
| POST | `/api/chats/{id}/messages` | SSE ответ (409 при параллельном POST) |

Тело сообщения: `{ "content": "...", "force_tier": null|"tiny"|"nano"|…|"ultra"|"frontier" }` (один из 10).

SSE events: `meta`, `token`, `tool`, `check`, `done`, `error`.

- `meta.phase`: `context` | `worker` | `retry` | `restore` (`retry`/`restore` очищают текст в UI).
- `meta` также может нести `num_ctx`, `used_history`, `context_reason`.
- `check`: `{ok, problems, note, attempt, model, checked}` — результат самопроверки.
- `done`: `attempts`, `checked`, `problems`, `num_ctx`, `used_history`, `context_reason`.

Middleware: только Host `127.0.0.1`/`localhost` (+порт); для мутаций — Origin localhost (защита от DNS rebinding).
Параллельные сообщения / clear / delete сериализуются worker-lock’ом; после clear ответ старого worker не дописывается (`generation`).

`/api/health`: `ok` = Ollama доступна и нет **обязательных** missing; `missing_optional` — 14b/coder;
`router_missing` — модель роутера из settings не найдена в Ollama.
Один запрос `/api/tags` на health (список моделей переиспользуется).

`/api/metrics`: снимок для правой панели — `cpu`, `ram`, `gpu[]` (util, VRAM, `temp_gpu_c`, `temp_memory_c`, пороги), `ollama.models[]`
с `gpu_ratio`/`cpu_ratio`/`place` (из `size_vram`/`size`). Кэш ~0.6 с. Без NVIDIA секции GPU/температур пустые.

Чаты **in-memory** (пропадают при рестарте процесса).

## Правая панель (монитор)

Трёхколоночный layout: сайдбар · чат · монитор. По умолчанию открыта.

- Секции: модели в Ollama (размещение слоёв GPU/CPU + доля VRAM карты), GPU/VRAM, температуры (ядро + цепи памяти), RAM, CPU + sparklines.
- Ширина регулируется drag-ресайзером (220–960px, по ширине окна); частота опроса — селект 1…10 с.
- Высота каждого sparkline — отдельный вертикальный ресайзер (сохраняется в `localStorage`).
- Одна кнопка toggle `›`/`‹` в левом верхнем углу панели (свернуть / развернуть); в свёрнутом виде остаётся узкая полоска 40px.
- Настройки (`open` / `width` / `interval` / высоты графиков) в `localStorage` (`qwen.monitor.*`).
- Poll только когда панель открыта; метрики **не** через SSE чата.

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

Лаунчер сначала поднимает **Ollama** (`ollama serve`, если порт 11434 молчит),
затем ждёт `/api/ready` веб-сервера (не `/api/health`), браузер — через
`os.startfile` / `cmd start`. Ollama, **запущенная лаунчером**, гасится вместе
с сервером при Ctrl+C / закрытии консоли (уже работавшую до старта не трогаем).
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
- Правая панель — монитор ресурсов (не Tools/Logs); свёртываемая, ресайз.

## Правила изменений для агентов

1. **Переиспользовать** `qwen_orchestra.Client` / `orchestra.handle` — не дублировать роутинг в `server.py`.
2. Стрим в UI — только через колбэки оркестра + SSE.
3. Новые проверки ответа — в `qwen_orchestra/selfcheck.py` (код проблемы + текст в `HINTS`);
   жёсткий floor/ceiling — в `router.tier_floor` / `tier_ceiling`;
   тексты «когда модель» для LLM-роутера и список слотов — в `settings.py` / UI;
   размер окна / история — в `plan_worker_context` / связанные хелперы в `orchestra.py`.
4. Лаунчер readiness — только `/api/ready`; тяжёлые проверки Ollama — в `/api/health`.
5. Не слушать `0.0.0.0` без явной просьбы пользователя.
6. Не добавлять светлую тему / аккаунты / IDE без запроса.
7. CLI (`orchestra_chat.py` и др.) оставлять рабочими; shim-модули в корне — для совместимости.
8. Отвечать пользователю **по-русски**, если не попросил иначе.
9. Коммиты — только по явной просьбе.
10. При смене тиров / контекста / API / SDK — обновлять `README.md` (обзор), `SETUP.md` (установка/запуск), `AGENTS.md`, `.cursor/rules/qwen-orchestra.mdc`.
11. Перед полным «найди баги по всему проекту» — сначала `CODE_AUDIT.md`; повторный аудит только после крупных правок или по просьбе; при фиксе обновляй статусы там.

## Типичный roadmap (ещё не сделано)

- Персистентность чатов (SQLite), контракт API сохранить.
- Реестр многих моделей/агентов (`/api/agents`).
- В правой панели — вкладки Tools/Logs рядом с монитором.
- Редактор кода — отдельный этап по запросу.
- Точный подсчёт токенов через токенизатор модели вместо эвристики символов.
- GPU-метрики для AMD/Intel (сейчас только NVIDIA / nvidia-smi).
