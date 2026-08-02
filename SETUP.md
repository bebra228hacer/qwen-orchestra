# Установка и запуск

Практическая инструкция к [Qwen Orchestra](README.md). Карта кода для агентов — [AGENTS.md](AGENTS.md).

---

## Требования

- Windows 10/11 (лаунчер и `start.bat` рассчитаны на Windows)
- [Python 3.10+](https://www.python.org/downloads/) в `PATH`
- [Ollama](https://ollama.com/download) (лаунчер сам поднимет `ollama serve`, если сервис не запущен)
- Для 14b желательно ≥8 ГБ VRAM (на 8 ГБ возможен CPU/GPU hybrid)

---

## Установка

```powershell
git clone https://github.com/bebra228hacer/qwen-orchestra.git
cd qwen-orchestra
python -m pip install -e ".[web]"
# или: python -m pip install -r requirements.txt
# только ядро без веб-сервера: python -m pip install -e .
```

Пакет `qwen-orchestra`: ядро — `ddgs`, `psutil`; extra `[web]` — `fastapi`, `uvicorn`, `pydantic`.

### Модели Ollama

```powershell
ollama pull qwen3.5:0.8b
ollama pull qwen3.5:4b
ollama pull qwen3.5:9b
# опционально (xlarge / coder) — лучше по одной:
ollama pull qwen2.5:14b
ollama pull qwen2.5-coder:14b
```

Проверка: `ollama list`. Сервис — `http://localhost:11434`.  
Теги 14b по умолчанию **Q4_K_M** (~9 ГБ); `qwen3.5:9b` ≈ 6.6 ГБ.

### OpenRouter (опционально)

Ключ: env `OPENROUTER_API_KEY` или UI «Модели и промпты» → `secrets.json`.  
Каталог id моделей: [openrouter.ai/models](https://openrouter.ai/models) (формат `provider/model`, напр. `anthropic/claude-sonnet-4`).

### Фронтенд

`npm` / CDN не нужны: библиотеки уже в `web/vendor/` (marked, DOMPurify, highlight.js, KaTeX). Обновление — заменить файлы теми же артефактами с CDN/release.

---

## Запуск

### Веб-чат

```powershell
python server.py
# → http://127.0.0.1:8787
```

Лаунчер (Ollama при необходимости + сервер + браузер):

```powershell
python open_web.py
# или QwenChat.bat / QwenChat.exe
```

Сборка exe после правок `open_web.py`:

```powershell
pip install pyinstaller
pyinstaller --noconfirm --onefile --console --name QwenChat --distpath . --workpath build\qwenchat --specpath build\qwenchat open_web.py
```

Меню режимов: `start.bat` (CP866 без BOM, `cd /d "%~dp0"`).

### CLI

```powershell
python orchestra_chat.py
python ask_orchestra.py "Привет!"

# без оркестра (только mid):
python chat.py
python chat_web.py
```

В `orchestra_chat.py`: `/tier <id>`, `/tiers`, `/auto`, `/clear`, `/exit`.

### SDK

```python
from qwen_orchestra import Client

client = Client()  # ollama_host=..., settings_path=...
print(client.health())
print(client.route("напиши функцию сортировки"))
result = client.ask("2+2")
print(result.text, result.tier, result.model)
```

Пример: `examples/ask_sdk.py`.  
`settings.json`: в корне репо при разработке; иначе `%LOCALAPPDATA%/qwen-orchestra/` (Windows) или `~/.config/qwen-orchestra/`.

---

## Веб-UI (кратко)

- Слева — чаты; Composer; селектор Auto / модели пула
- Markdown + код + LaTeX; чипы tier / ctx / история / selfcheck
- «Модели и промпты» — пул моделей (тир опционален), Ollama/OpenRouter; «Удалить» убирает из пула
- Правая панель — монитор CPU/RAM/GPU/температуры/Ollama
- Чаты in-memory (сброс при рестарте сервера)

---

## Auto-режим (кратко)

| Запрос | Минимум |
|--------|---------|
| приветствие, `2+2` | tiny |
| объяснения, перевод, простой код, web | mid |
| сравнение, архитектура, длинный анализ, план | heavy |
| сервис/API, рефакторинг, тесты кода, traceback | coder |

«Кратко» → потолок mid. Эскалация: tiny → mid → heavy → xlarge (`coder` → xlarge).  
Полная таблица и формула `num_ctx` — в [AGENTS.md](AGENTS.md).

---

## Структура репозитория

| Путь | Назначение |
|------|------------|
| `qwen_orchestra/` | SDK: Client, orchestra, router, selfcheck, llm, settings, metrics |
| `orchestra.py` и др. | Shim-модули для старых импортов |
| `server.py` | FastAPI + SSE + `/api/metrics`, порт `8787` |
| `web/` | UI (чат + монитор) |
| `open_web.py` | Лаунчер |
| `examples/ask_sdk.py` | Пример SDK |
| `AGENTS.md` | Документация для AI-агентов |
