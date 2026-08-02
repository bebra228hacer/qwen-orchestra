# Правило для AI-агента: qwen_orchestra SDK

Скопируй этот файл в `.cursor/rules/` или приложи к `AGENTS.md` **потребительского** проекта.  
Полный справочник: в репозитории оркестра — `docs/SDK.md`.

## Назначение

Локальный оркестр LLM: Ollama + опционально OpenRouter. Встраивание **in-process** через `Client`, не через HTTP UI.

```python
from qwen_orchestra import Client
client = Client(settings_path="…/orchestra_settings.json")
result = client.ask("…", history=[…])  # history БЕЗ текущего user
```

## Must

- Установка: `pip install -e <путь-к-клону-qwen-orchestra>` (ядро без `[web]`).
- Всегда задавай **свой** `settings_path` (не общий конфиг оркестра).
- Перед работой: `client.ready()` (Ollama) и `client.health()["ok"]`.
- Роутер и selfcheck — **локальные** Ollama; OpenRouter только как воркер в пуле.
- `force_model` = **id записи пула** (`ollama:…` / `openrouter:…`), не сырой tag.
- Стрим: `on_token` / `on_status`; на `retry`/`restore` сбрасывай показанный текст.
- Ключ OR: `OPENROUTER_API_KEY` или `client.set_openrouter_api_key`; не в git.
- Не дублируй роутинг/selfcheck; не импортируй внутренности пакета без нужды.

## Пул

- С `tier` + `rank` → Auto и эскалация; без `tier` → только `force_model`.
- Тиры: `tiny` `nano` `small` `mid` `large` `heavy` `xlarge` `coder` `ultra` `frontier`.
- `provider`: `ollama` | `openrouter`. Tools (web) — только Ollama.

## API (кратко)

`ready` · `health` · `route` · `ask` · `get_settings` · `update_settings` · `reset_settings` · `add_model` · `delete_model` · `set_openrouter_api_key`

`OrchestraResult`: `text`, `tier`, `model`, `attempts`, `checked`, `problems`, `need_web`, `need_local_time`, …

## Не делай

- Не обещай OpenAI-compatible HTTP API.
- Не считай, что история всегда попадает в heavy/coder (там фильтр по отсылкам).
- Не коммить `secrets.json` / API-ключи.
