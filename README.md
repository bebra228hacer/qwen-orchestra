# Qwen Orchestra

Локальный оркестр моделей **Qwen2.5** поверх [Ollama](https://ollama.com): роутинг tiny → mid → heavy, самопроверка ответов и веб-чат в стиле Cursor (только `127.0.0.1`, без аккаунтов).

| Tier | Модель | Роль |
|------|--------|------|
| tiny | `qwen2.5:0.5b` | Роутинг, приветствия, простые ответы |
| mid | `qwen2.5:3b` | Обычные задачи, код, объяснения; ревью ответов |
| heavy | `qwen2.5:7b` | Сложные задачи; повтор после неудачной самопроверки |

Если ответ ушёл на другой язык, оказался пустым/зацикленным, отказом или с явной ошибкой — оркестр **переделывает запрос на модели уровнем выше** (до 3 попыток).

Для AI-агентов: [AGENTS.md](AGENTS.md).

---

## Требования

- Windows 10/11 (лаунчер и `start.bat` рассчитаны на Windows)
- [Python 3.10+](https://www.python.org/downloads/) в `PATH`
- [Ollama](https://ollama.com/download) с запущенным сервисом

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
```

Проверка: `ollama list` — все три модели должны быть в списке. Иконка Ollama в трее означает, что сервис слушает `http://localhost:11434`.

### 4. Запустить веб-чат

```powershell
python server.py
```

Откройте в браузере: **http://127.0.0.1:8787**

Либо лаунчер (одна консоль + браузер):

```powershell
python open_web.py
# или двойной клик QwenChat.bat
```

Опционально собрать `QwenChat.exe`:

```powershell
pip install pyinstaller
pyinstaller --noconfirm --onefile --console --name QwenChat --distpath . --workpath build\qwenchat --specpath build\qwenchat open_web.py
```

Меню всех режимов: `start.bat`.

---

## Использование

### Веб-UI

- Слева — чаты, снизу — Composer
- Селектор **Auto / tiny / mid / heavy**
- Чипы у ответа: модель, tier, `проверено`, `попыток: N`

Чаты хранятся в памяти процесса и сбрасываются при рестарте сервера.

### CLI оркестр

```powershell
python orchestra_chat.py
```

Команды: `/tier tiny|mid|heavy`, `/auto`, `/clear`, `/exit`.

Один вопрос:

```powershell
python ask_orchestra.py "Привет!"
python ask_orchestra.py "Какая погода в Москве?"
```

### Другие режимы (без оркестра)

```powershell
python chat.py          # только 3B
python chat_web.py      # 3B + интернет (web_search / fetch_url)
```

---

## Auto-режим (кратко)

| Запрос | Минимум |
|--------|---------|
| приветствие, `2+2` | tiny |
| объяснения, код, web | mid |
| архитектура, отладка, длинный код с требованиями | heavy |

Просьба «кратко» не пускает на 7b. Полная таблица — в [AGENTS.md](AGENTS.md).

---

## Структура

| Путь | Назначение |
|------|------------|
| `orchestra.py` | Ядро: route → worker → selfcheck → retry |
| `router.py` | Выбор tier + валидация |
| `selfcheck.py` | Самопроверка ответа |
| `server.py` | FastAPI + SSE, порт `8787` |
| `web/` | Тёмный Cursor-like UI |
| `open_web.py` | Лаунчер сервера и браузера |

---

## Лицензия

Используйте свободно для личных и учебных целей. Модели Qwen — на условиях их лицензий через Ollama.
