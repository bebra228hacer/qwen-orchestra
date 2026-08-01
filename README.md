# Qwen Orchestra

Локальный оркестр моделей **Qwen2.5** поверх [Ollama](https://ollama.com): роутинг tiny → mid → heavy → xlarge (+ coder), адаптивный `num_ctx`, самопроверка ответов и веб-чат в стиле Cursor (только `127.0.0.1`, без аккаунтов).

| Tier | Модель | Роль |
|------|--------|------|
| tiny | `qwen2.5:0.5b` | Неоднозначные короткие запросы, приветствия |
| mid | `qwen2.5:3b` | Обычные задачи, код, объяснения; ревью ответов |
| heavy | `qwen2.5:7b` | Сложные задачи; эскалация после selfcheck |
| xlarge | `qwen2.5:14b` | Верх эскалации (опционально, ~9 ГБ) |
| coder | `qwen2.5-coder:14b` | Тяжёлый код и отладка (опционально, ~9 ГБ) |

Большинство mid/heavy/web/coder запросов роутятся **без** вызова 0.5b (детерминированные правила). Ручной тир в UI тоже не дергает роутер. Эскалация не падает на неустановленный 14b.

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
- [Ollama](https://ollama.com/download) с запущенным сервисом
- Для 14b желательно ≥8 ГБ VRAM (на 8 ГБ возможен CPU/GPU hybrid и ниже скорость)

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
ollama pull qwen2.5:0.5b
ollama pull qwen2.5:3b
ollama pull qwen2.5:7b
# опционально (xlarge / coder) — лучше по одной, не параллельно:
ollama pull qwen2.5:14b
ollama pull qwen2.5-coder:14b
```

Проверка: `ollama list`. Иконка Ollama в трее — сервис на `http://localhost:11434`.  
Теги 14b по умолчанию **Q4_K_M** (~9 ГБ каждая).

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

- Слева — чаты, снизу — Composer
- Селектор **Auto / tiny / mid / heavy / xlarge / coder**
- Чипы: tier, модель, `ctx N`, `история` / `без истории`, `проверено`, `попыток: N`
- Health: обязательные модели отдельно; 14b — «опционально», если не скачаны

Чаты в памяти процесса (сбрасываются при рестарте сервера).

### CLI оркестр

```powershell
python orchestra_chat.py
```

Команды: `/tier tiny|mid|heavy|xlarge|coder`, `/auto`, `/clear`, `/exit`.

```powershell
python ask_orchestra.py "Привет!"
python ask_orchestra.py "Какая погода в Москве?"
```

### Без оркестра

```powershell
python chat.py          # только 3B
python chat_web.py      # 3B + интернет
```

---

## Auto-режим (кратко)

| Запрос | Минимум |
|--------|---------|
| приветствие, `2+2` | tiny |
| объяснения, простой код, web | mid |
| архитектура, длинный анализ | heavy |
| сложный код, отладка, traceback | coder |

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
| `open_web.py` | Лаунчер сервера и браузера |
| `AGENTS.md` | Карта для AI-агентов |

---

## Лицензия

Свободно для личных и учебных целей. Модели Qwen — по их лицензиям через Ollama.
