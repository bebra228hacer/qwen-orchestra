# CODE_AUDIT — обзор кодовой базы

**Дата первого аудита:** 2026-08-02  
**Дата правок:** 2026-08-02  
**Объём:** все исходники проекта (без `web/vendor/*`, без бинарников/`build`)

> **Для следующего агента:** пункты ниже **исправлены** в коде от 2026-08-02.
> Не повторяй полный аудит с нуля. Новый проход — только по изменённым файлам
> после этой даты или по явной просьбе. При новых фиксax обновляй changelog.

---

## Статус находок

| ID | Было | Статус |
|---|---|---|
| C1 | `heavy → coder` вместо xlarge | **исправлено** (`_escalate_sort_key` / лестница TIER_ORDER) |
| C2 | user в историю до worker-lock | **исправлено** (lock до append, HTTP 409) |
| C3 | hot-reload `MODELS.clear()` | **исправлено** (runtime_lock + update без clear + snapshot в handle) |
| C4 | `decodeURIComponent` / busy stuck | **исправлено** (safe decode + try/finally вокруг send) |
| C5 | обрыв SSE = успех | **исправлено** (`doneReceived` + финальный decode) |
| C6 | SSRF `fetch_url` | **исправлено** (block private/loopback + redirect check) |
| M1 | десятичная запятая `2,5` | **исправлено** |
| M2 | math skip LLM на смешанных вопросах | **исправлено** (`_math_only_question`) |
| M3 | SSE `check` без `checked` | **исправлено** |
| M4 | нумерация tiny-retry | **исправлено** (tiny в attempts) |
| M5 | tool budget chars/tokens | **исправлено** (оценка через `_estimate_tokens`) |
| M6 | clear во время gen | **исправлено** (lock + `generation`) |
| M7 | unbounded SSE queue | **исправлено** (maxsize + drop-oldest) |
| M8 | `router_model` qwen2.5:7b | **исправлено** → `qwen3.5:0.8b` + health `router_missing` |
| M9 | `_REQUIREMENT_RE` на голых запятых | **исправлено** |
| M10 | soft web `сейчас`/`когда` | **исправлено** |
| M11 | metrics `float(N/A)` | **исправлено** (`_smi_number`) |
| M12 | пустой temp cache | **исправлено** (failed TTL + monotonic) |
| M13 | неатомарный settings save | **исправлено** (temp + replace) |
| M14 | `chat_web` history / tool limit | **исправлено** (через orchestra helpers) |
| M15 | rank `0` → `2` | **исправлено** (`Number.isFinite`) |
| M16 | add/remove слота сбрасывает черновики | **исправлено** (`persistDraftSlots`) |
| M17 | overlapping metrics poll | **исправлено** (sequential timeout + inflight) |
| M18 | selectChat vs clear | **исправлено** (`selectGen++`) |
| M19 | Ollama-сирота в open_web | **исправлено** (ждём Enter, cleanup) |
| M20 | DNS rebinding Host/Origin | **исправлено** (middleware) |

### Избыточность (убрано)

- `chat.py` → `llm.chat_stream`
- `chat_web.py` → `llm.chat` + `orchestra._run_tool` / `_fallback_tools` / лимиты
- удалён неиспользуемый `deepcopy` import, alias `update_slots`
- недостижимая ветка `ROUTER_AUTO_TIERS` в `router.py`
- мёртвый CSS `.slot-row`
- избыточный селектор highlight

### Не делали (осознанно / низкий приоритет)

- Полная виртуализация сообщений UI
- AMD/Intel GPU
- Автотесты (всё ещё нет suite; точечные asserts при правках)
- Пересборка `QwenChat.exe` (нужна вручную после `open_web.py`)

---

## Что проверено повторно при фиксе

- `_next_tier("heavy") == "xlarge"`
- `_mentions_number` / arithmetic для `2,5`
- `_url_blocked` для localhost / private / example.com
- `py_compile` всех затронутых `.py`
- импорт `server`, `metrics`, `chat`, `chat_web`

---

## Changelog

| Дата | Что |
|---|---|
| 2026-08-02 | Первый статический аудит |
| 2026-08-02 | Все C*/M* из аудита закрыты в коде; избыточность CLI/router/CSS убрана |
