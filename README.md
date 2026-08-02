# Qwen Orchestra

Локальный оркестр LLM поверх [Ollama](https://ollama.com): несколько моделей Qwen работают как одна система — роутер выбирает тир, воркер отвечает, selfcheck переделывает слабый ответ на модели сильнее. Веб-чат в стиле Cursor Chat (тёмная тема, один пользователь, только `127.0.0.1`).

**Не** облачный бот и **не** IDE: чат/composer текста к оркестру.

---

## Возможности

- **Авто-роутинг** по тирам tiny→frontier; модели живут в **пуле** (несколько на тир, rank = приоритет). Ручной выбор модели в UI.
- **Детерминированный floor/ceiling** — tiny не «занижает» сложность; «кратко» держит потолок mid.
- **Самопроверка ответа** (правила + LLM-ревью) и **retry с эскалацией по rank** до нескольких попыток.
- **Адаптивный `num_ctx`** — минимальное окно под запрос, история для тяжёлых тиров только по отсылкам.
- **Web-tools** — поиск и чтение URL (кэш между retry, лимиты вызовов).
- **Веб-UI** — чаты, Markdown/код/формулы, чипы статуса, «Модели и промпты», монитор CPU/RAM/GPU/Ollama.
- **OpenRouter** — внешняя модель в пуле (с тиром или только вручную; ключ в env / `secrets.json`); tools пока только на Ollama.
- **Python SDK** — `from qwen_orchestra import Client` (ask / route / health / settings in-process).
- **CLI** — интерактивный оркестр и one-shot; лаунчер с автозапуском Ollama при необходимости.

Defaults: `0.8b` · `nano` · `2b` · `4b` · `7b` · `9b` · `14b` · `coder` · `ultra` · `frontier`. Модель без тира — только ручной выбор.

```
user → route → plan context → worker (± web) → selfcheck
                 ↑                                    │ не ok
                 └──────── retry (больший rank) ──────┘
```

---

## Стек

| Слой | Технологии |
|------|------------|
| Ядро | Python 3.10+, пакет `qwen_orchestra` |
| Локальные модели | [Ollama](https://ollama.com) (HTTP API) |
| Внешние модели | [OpenRouter](https://openrouter.ai) (опционально) |
| Веб-сервер | FastAPI, Uvicorn, Pydantic, SSE |
| Метрики | psutil, nvidia-smi, Ollama `/api/ps` |
| Web-tools | ddgs (+ fetch URL) |
| UI | vanilla JS/CSS/HTML, без npm/CDN |
| Рендер чата | marked, DOMPurify, highlight.js, KaTeX (`web/vendor/`) |
| Лаунчер | `open_web.py` → опционально `QwenChat.exe` (PyInstaller) |

Публичный вход для приложений: `qwen_orchestra.Client`. Слоты и промпты роутера — `settings.json` / UI.

---

## Особенности

- Роутер и selfcheck остаются **локальными**; эскалация идёт по **rank** моделей пула.
- У Qwen3.5 всегда `think: false` — иначе ломаются JSON-роутер и tools.
- Приоритет контекста: **не обрезать запрос**, затем экономия VRAM (`num_ctx` 256…8192).
- Чаты **in-memory** (сбрасываются при рестарте сервера).
- Слушает только localhost; без auth, без светлой темы, без редактора кода.
- На ~8 ГБ VRAM 14b часто hybrid CPU/GPU — медленнее 9b на полном GPU.

---

## Документация

| Файл | Для кого |
|------|----------|
| [SETUP.md](SETUP.md) | Установка, модели, запуск, CLI, SDK |
| [AGENTS.md](AGENTS.md) | Карта кода и правила для AI-агентов |
| [THANKS_NEURAL_NETS.md](THANKS_NEURAL_NETS.md) | Благодарность нейронкам |

---

## Лицензия

Свободно для личных и учебных целей. Модели Qwen — по их лицензиям через Ollama.
