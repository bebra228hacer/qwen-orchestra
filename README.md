# Qwen Orchestra

Локальный оркестр моделей **Qwen3.5** (+ Qwen2.5 14b) поверх [Ollama](https://ollama.com): роутинг tiny → mid → heavy → xlarge (+ coder), адаптивный `num_ctx`, самопроверка ответов и веб-чат в стиле Cursor (только `127.0.0.1`, без аккаунтов).

| Tier | Модель | Роль |
|------|--------|------|
| tiny | `qwen3.5:0.8b` | Роутер, приветствия, простая арифметика |
| mid | `qwen3.5:4b` | Обычные задачи, код, объяснения; ревью ответов |
| heavy | `qwen3.5:9b` | Сложные задачи; эскалация после selfcheck |
| xlarge | `qwen2.5:14b` | Верх эскалации (опционально, ~9 ГБ) |
| coder | `qwen2.5-coder:14b` | Тяжёлый код и отладка (опционально, ~9 ГБ) |

Большинство mid/heavy/web/coder запросов роутятся **без** вызова tiny (детерминированные правила). Ручной тир в UI тоже не дергает роутер. Эскалация не падает на неустановленный 14b. У Qwen3.5 thinking **выключен** (`think: false`) — иначе ломаются JSON-роутер и tools.

Слоты моделей и **промпты роутера** («когда какую модель выбирать») настраиваются в UI: кнопка **«Модели и промпты»** в сайдбаре (справка по **?**). Можно выбрать **модель роутера**, сменить Ollama-имя у слотов, отредактировать тексты для Auto и **добавить свою нейронку**. Defaults и файл `settings.json` — модуль `settings.py`.

Поток одного запроса:

```
user → route → plan context (история + num_ctx) → worker (± web)
                 ↑                                        │ selfcheck не ok
                 └──────── retry на тир выше ─────────────┘  (до 3 попыток)
```

Для AI-агентов: [AGENTS.md](AGENTS.md).

---

## Требования

- Windows 10/11 (лаунчер и `start.bat` рассчитаны на Windows)
- [Python 3.10+](https://www.python.org/downloads/) в `PATH`
- [Ollama](https://ollama.com/download) (лаунчер сам поднимет `ollama serve`, если сервис не запущен)
- Для 14b желательно ≥8 ГБ VRAM (на 8 ГБ возможен CPU/GPU hybrid и ниже скорость)

### Python (бэкенд)

```powershell
python -m pip install -r requirements.txt
```

Пакеты: `fastapi`, `uvicorn`, `pydantic`, `ddgs` (и транзитивные зависимости из `requirements.txt`).

### Фронтенд-библиотеки (уже в репозитории)

Веб-чат **не** требует `npm` / CDN: минифицированные файлы лежат в `web/vendor/` и отдаются как статика (`/static/vendor/…`).

| Файл | Библиотека | Зачем |
|------|------------|--------|
| `web/vendor/marked.min.js` | [marked](https://github.com/markedjs/marked) v15 | Markdown → HTML (GFM) |
| `web/vendor/purify.min.js` | [DOMPurify](https://github.com/cure53/DOMPurify) v3 | Санитизация HTML (XSS) |
| `web/vendor/highlight.min.js` | [highlight.js](https://github.com/highlightjs/highlight.js) v11 | Подсветка синтаксиса в блоках кода |
| `web/vendor/highlight-github-dark.min.css` | hljs theme **GitHub Dark** | Цвета токенов под тёмный UI |

Подключаются из `web/index.html`. Обновлять версии — скачать те же артефакты с jsDelivr / CDN release и заменить файлы в `web/vendor/`.

---

## Развёртывание

### 1. Клонировать репозиторий

```powershell
git clone https://github.com/bebra228hacer/qwen-orchestra.git
cd qwen-orchestra
```

### 2. Установить зависимости Python

```powershell
python -m pip install -r requirements.txt
```

### 3. Скачать модели Ollama

```powershell
ollama pull qwen3.5:0.8b
ollama pull qwen3.5:4b
ollama pull qwen3.5:9b
# опционально (xlarge / coder) — лучше по одной, не параллельно:
ollama pull qwen2.5:14b
ollama pull qwen2.5-coder:14b
```

Проверка: `ollama list`. Иконка Ollama в трее — сервис на `http://localhost:11434`.  
Теги 14b по умолчанию **Q4_K_M** (~9 ГБ каждая). `qwen3.5:9b` ≈ 6.6 ГБ.

### 4. Запустить веб-чат

```powershell
python server.py
```

Откройте: **http://127.0.0.1:8787**

Либо лаунчер:

```powershell
python open_web.py
# или QwenChat.bat / QwenChat.exe
```

Сборка exe:

```powershell
pip install pyinstaller
pyinstaller --noconfirm --onefile --console --name QwenChat --distpath . --workpath build\qwenchat --specpath build\qwenchat open_web.py
```

Меню режимов: `start.bat`.

---

## Использование

### Веб-UI

- Слева — чаты (очистка/удаление у каждого пункта), снизу — Composer
- Ответы и сообщения рендерятся как **Markdown** (GFM: код, списки, таблицы; `marked` + `DOMPurify` + подсветка `highlight.js` в `web/vendor/`)
- Селектор **Auto / tiny / mid / heavy / xlarge / coder**
- Чипы: tier, модель, `ctx N`, `история` / `без истории`, `проверено`, `попыток: N`
- Health: обязательные модели отдельно; 14b — «опционально», если не скачаны

Чаты в памяти процесса (сбрасываются при рестарте сервера).

### CLI оркестр

```powershell
python orchestra_chat.py
```

Команды: `/tier <id>`, `/tiers`, `/auto`, `/clear`, `/exit`.

```powershell
python ask_orchestra.py "Привет!"
python ask_orchestra.py "Какая погода в Москве?"
```

### Без оркестра

```powershell
python chat.py          # только mid (qwen3.5:4b)
python chat_web.py      # mid + интернет
```

---

## Auto-режим (кратко)

| Запрос | Минимум |
|--------|---------|
| приветствие, `2+2` | tiny |
| объяснения, перевод, простой код, web | mid |
| сравнение, архитектура, длинный анализ, план | heavy |
| сервис/API, рефакторинг, тесты кода, traceback | coder |

«Кратко» → потолок mid. Эскалация: tiny → mid → heavy → xlarge (`coder` → xlarge).  
Полная таблица — в [AGENTS.md](AGENTS.md).

### Контекст (`num_ctx`)

Перед воркером считается минимальное окно под запрос (приоритет — не обрезать текст; затем экономия VRAM):

```
num_ctx = ceil_256(tokens(промпт) + 128 + reserve_ответа + safety) ∈ [256…8192]
```

- история чата для heavy/xlarge/coder — только если нужна («исправь это», follow-up…);
- запас на ответ: 512 / 768 / 1536 (короткий / обычный / код).

---

## Структура

| Путь | Назначение |
|------|------------|
| `orchestra.py` | Ядро: route → context → worker → selfcheck → retry |
| `router.py` | Выбор tier + валидация |
| `selfcheck.py` | Самопроверка ответа |
| `llm.py` | Клиент Ollama (`num_ctx` в options) |
| `server.py` | FastAPI + SSE, порт `8787` |
| `web/` | Тёмный Cursor-like UI |
| `open_web.py` | Лаунчер: Ollama (если нужно) + сервер + браузер |
| `AGENTS.md` | Карта для AI-агентов |

---

## Лицензия

Свободно для личных и учебных целей. Модели Qwen — по их лицензиям через Ollama.
