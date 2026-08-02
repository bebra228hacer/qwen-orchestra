"""Персистентные настройки оркестра: слоты моделей + промпты роутера.

Файл: settings.json — в корне репозитория при разработке, иначе в user config
(`%LOCALAPPDATA%/qwen-orchestra` / `~/.config/qwen-orchestra`). Builtin-слоты
(tiny…coder) нельзя удалить; можно сменить Ollama-модель и текст «когда использовать».
Пользовательские слоты добавляются из UI / SDK (Ollama или OpenRouter).

Ключ OpenRouter — env `OPENROUTER_API_KEY` или `secrets.json` рядом с settings
(не коммитить).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_PROVIDERS = frozenset({"ollama", "openrouter"})
DEFAULT_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"
_lock = threading.RLock()
# Синхронизация apply_to_runtime ↔ orchestra.handle (снимок слотов)
runtime_lock = threading.RLock()
_bootstrapped = False


def _user_config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "qwen-orchestra"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "qwen-orchestra"
    return Path.home() / ".config" / "qwen-orchestra"


def default_settings_path() -> Path:
    """Корень репо (если есть pyproject/server) или user config."""
    repo_json = PROJECT_ROOT / "settings.json"
    if repo_json.is_file():
        return repo_json
    if (PROJECT_ROOT / "pyproject.toml").is_file() or (PROJECT_ROOT / "server.py").is_file():
        return PROJECT_ROOT / "settings.json"
    return _user_config_dir() / "settings.json"


SETTINGS_PATH: Path = default_settings_path()
# Совместимость со старым именем ROOT (= каталог с settings при разработке)
ROOT = SETTINGS_PATH.parent


def set_settings_path(path: Path | str) -> None:
    """Задать путь к settings.json (до bootstrap / Client)."""
    global SETTINGS_PATH, ROOT, _bootstrapped, _settings
    SETTINGS_PATH = Path(path)
    ROOT = SETTINGS_PATH.parent
    with _lock:
        _bootstrapped = False
        _settings = None


def get_settings_path() -> Path:
    return SETTINGS_PATH


def secrets_path() -> Path:
    """secrets.json рядом с settings.json (API-ключи; не в git)."""
    return SETTINGS_PATH.parent / "secrets.json"


def _read_secrets() -> dict[str, Any]:
    p = secrets_path()
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_secrets(data: dict[str, Any]) -> None:
    p = secrets_path()
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(p.parent), prefix=".secrets-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, p)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def get_openrouter_api_key() -> str | None:
    """Ключ: сначала env OPENROUTER_API_KEY, иначе secrets.json."""
    env = (os.environ.get(OPENROUTER_API_KEY_ENV) or "").strip()
    if env:
        return env
    raw = _read_secrets().get("openrouter_api_key")
    key = str(raw or "").strip()
    return key or None


def openrouter_configured() -> bool:
    return bool(get_openrouter_api_key())


def set_openrouter_api_key(api_key: str | None) -> None:
    """Записать/очистить ключ в secrets.json. Env имеет приоритет при чтении."""
    data = _read_secrets()
    key = (api_key or "").strip()
    if key:
        data["openrouter_api_key"] = key
    else:
        data.pop("openrouter_api_key", None)
    if data:
        _write_secrets(data)
    else:
        p = secrets_path()
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                _write_secrets({})


def openrouter_status() -> dict[str, Any]:
    env_set = bool((os.environ.get(OPENROUTER_API_KEY_ENV) or "").strip())
    file_set = bool(str(_read_secrets().get("openrouter_api_key") or "").strip())
    return {
        "configured": openrouter_configured(),
        "from_env": env_set,
        "from_file": file_set and not env_set,
        "base_url": DEFAULT_OPENROUTER_BASE,
        "api_key_env": OPENROUTER_API_KEY_ENV,
    }


# Промпты по умолчанию: когда роутеру выбирать этот слот
DEFAULT_ROUTER_PROMPTS: dict[str, str] = {
    "tiny": (
        "Приветствия, благодарности, прощания, простая арифметика (2+2), "
        "короткие да/нет. Можно сразу дать короткий ответ в поле reply."
    ),
    "mid": (
        "Объяснения, перевод, советы, how-to, «что такое», небольшой код/скрипт, "
        "обычные вопросы по существу. Если нужен интернет (need_web) — минимум этот уровень."
    ),
    "heavy": (
        "Сложный анализ, сравнение подходов, архитектура, доказательства, "
        "длинные рассуждения, многошаговые планы, несколько вопросов сразу. "
        "Не ставь сюда тяжёлую отладку кода — для этого coder."
    ),
    "xlarge": (
        "Очень сложные задачи и верх эскалации, когда mid/heavy уже не справились. "
        "Обычно не выбирай первым — это запасная сила."
    ),
    "coder": (
        "Код и отладка: traceback, стектрейс, ошибки в коде, рефакторинг, "
        "сервис/API/приложение, unit-тесты, JWT и стек, ТЗ с кодом."
    ),
}

DEFAULT_SLOTS: list[dict[str, Any]] = [
    {
        "id": "tiny",
        "model": "qwen3.5:0.8b",
        "label": "tiny · 3.5 0.8b",
        "router_prompt": DEFAULT_ROUTER_PROMPTS["tiny"],
        "required": True,
        "optional": False,
        "rank": 0,
        "router_auto": True,
        "builtin": True,
    },
    {
        "id": "mid",
        "model": "qwen3.5:4b",
        "label": "mid · 3.5 4b",
        "router_prompt": DEFAULT_ROUTER_PROMPTS["mid"],
        "required": True,
        "optional": False,
        "rank": 1,
        "router_auto": True,
        "builtin": True,
    },
    {
        "id": "heavy",
        "model": "qwen3.5:9b",
        "label": "heavy · 3.5 9b",
        "router_prompt": DEFAULT_ROUTER_PROMPTS["heavy"],
        "required": True,
        "optional": False,
        "rank": 2,
        "router_auto": True,
        "builtin": True,
    },
    {
        "id": "xlarge",
        "model": "qwen2.5:14b",
        "label": "xlarge · 14b",
        "router_prompt": DEFAULT_ROUTER_PROMPTS["xlarge"],
        "required": False,
        "optional": True,
        "rank": 3,
        "router_auto": False,
        "builtin": True,
    },
    {
        "id": "coder",
        "model": "qwen2.5-coder:14b",
        "label": "coder · 14b",
        "router_prompt": DEFAULT_ROUTER_PROMPTS["coder"],
        "required": False,
        "optional": True,
        "rank": 3,
        "router_auto": False,
        "builtin": True,
    },
]

DEFAULT_ROUTER_MODEL = "qwen3.5:0.8b"

ROUTER_SYSTEM_HEADER = """Ты роутер запросов. Отвечай ТОЛЬКО валидным JSON без markdown.

Поля:
- ok: false ТОЛЬКО если запрос пустой, бессмысленный набор символов или спам.
      Непонятный, странный или очень короткий вопрос — это ok=true.
- tier: один из допустимых id моделей (см. список ниже)
- need_web: true если нужны свежие данные из интернета
- reason: коротко почему такой tier
- reply: если ok=false — вежливый отказ; если tier=tiny — полный короткий ответ; иначе пустая строка

Правила выбора tier (когда какую модель использовать):
"""

ROUTER_SYSTEM_FOOTER = """
Дополнительно:
- need_web=true => минимум mid (если mid есть в списке)
- Сомневаешься между двумя тирами — выбирай СТАРШИЙ (больший rank / сильнее).
- Не выбирай xlarge/coder без явной необходимости, если они есть в списке —
  обычно их подключает эскалация или явный код/сложность.
"""


@dataclass
class ModelSlot:
    id: str
    model: str
    label: str
    router_prompt: str
    required: bool = False
    optional: bool = True
    rank: int = 1
    router_auto: bool = True
    builtin: bool = False
    provider: str = "ollama"  # ollama | openrouter

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AppSettings:
    slots: list[ModelSlot] = field(default_factory=list)
    router_model: str = DEFAULT_ROUTER_MODEL

    def to_dict(self) -> dict[str, Any]:
        return {
            "router_model": self.router_model,
            "slots": [s.to_dict() for s in self.slots],
        }


_settings: AppSettings | None = None


def _normalize_provider(raw: Any, *, builtin: bool = False) -> str:
    if builtin:
        return "ollama"
    name = str(raw or "ollama").strip().lower() or "ollama"
    if name not in _PROVIDERS:
        raise ValueError(f"Неизвестный provider: {name!r} (ожидается ollama|openrouter)")
    return name


def _normalize_router_model(raw: Any, *, fallback: str = DEFAULT_ROUTER_MODEL) -> str:
    name = str(raw or "").strip()
    return name or fallback


def _slot_from_dict(raw: dict[str, Any], *, fallback: dict[str, Any] | None = None) -> ModelSlot:
    base = dict(fallback or {})
    base.update({k: v for k, v in raw.items() if v is not None})
    sid = str(base.get("id") or "").strip().lower()
    if not _ID_RE.match(sid):
        raise ValueError(f"Некорректный id слота: {sid!r}")
    model = str(base.get("model") or "").strip()
    if not model:
        raise ValueError(f"Пустое имя модели для слота {sid}")
    label = str(base.get("label") or model).strip() or model
    prompt = str(base.get("router_prompt") or "").strip()
    if not prompt:
        prompt = DEFAULT_ROUTER_PROMPTS.get(sid, "Используй для задач, которые подходят этой модели.")
    builtin = bool(base.get("builtin", False))
    return ModelSlot(
        id=sid,
        model=model,
        label=label,
        router_prompt=prompt,
        required=bool(base.get("required", False)),
        optional=bool(base.get("optional", True)),
        rank=int(base.get("rank", 1)),
        router_auto=bool(base.get("router_auto", True)),
        builtin=builtin,
        provider=_normalize_provider(base.get("provider"), builtin=builtin),
    )


def default_settings() -> AppSettings:
    return AppSettings(
        slots=[_slot_from_dict(s) for s in DEFAULT_SLOTS],
        router_model=DEFAULT_ROUTER_MODEL,
    )


def _merge_with_defaults(raw: dict[str, Any] | None) -> AppSettings:
    """Builtin-слоты всегда на месте; пользовательские — из файла."""
    defaults_by_id = {s["id"]: s for s in DEFAULT_SLOTS}
    raw = raw if isinstance(raw, dict) else {}
    raw_slots = list(raw.get("slots") or [])
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for d in DEFAULT_SLOTS:
        by_id[d["id"]] = dict(d)
        order.append(d["id"])

    for item in raw_slots:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or "").strip().lower()
        if not sid:
            continue
        if sid in defaults_by_id:
            merged = dict(defaults_by_id[sid])
            # Пользователь может менять model/label/prompt/router_auto/rank
            for key in ("model", "label", "router_prompt", "router_auto", "rank"):
                if key in item and item[key] is not None:
                    merged[key] = item[key]
            # required/optional/builtin фиксированы для builtin
            by_id[sid] = merged
        else:
            custom = dict(item)
            custom["id"] = sid
            custom["builtin"] = False
            custom["required"] = False
            custom.setdefault("optional", True)
            custom.setdefault("router_auto", True)
            custom.setdefault("rank", 2)
            custom.setdefault("provider", "ollama")
            by_id[sid] = custom
            if sid not in order:
                order.append(sid)

    slots = [_slot_from_dict(by_id[sid], fallback=defaults_by_id.get(sid)) for sid in order]
    tiny_model = next((s.model for s in slots if s.id == "tiny"), DEFAULT_ROUTER_MODEL)
    router_model = _normalize_router_model(
        raw.get("router_model"),
        fallback=tiny_model or DEFAULT_ROUTER_MODEL,
    )
    return AppSettings(slots=slots, router_model=router_model)


def load_settings(*, path: Path | None = None) -> AppSettings:
    global _settings
    p = path or SETTINGS_PATH
    with _lock:
        if p.is_file():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw = None
            try:
                _settings = _merge_with_defaults(raw if isinstance(raw, dict) else None)
            except (ValueError, TypeError):
                _settings = default_settings()
        else:
            _settings = default_settings()
        return deepcopy_settings(_settings)


def deepcopy_settings(src: AppSettings) -> AppSettings:
    return AppSettings(
        slots=[_slot_from_dict(s.to_dict()) for s in src.slots],
        router_model=src.router_model,
    )


def get_settings() -> AppSettings:
    with _lock:
        if _settings is None:
            return load_settings()
        return deepcopy_settings(_settings)


def save_settings(settings: AppSettings, *, path: Path | None = None) -> AppSettings:
    global _settings
    p = path or SETTINGS_PATH
    normalized = _merge_with_defaults(settings.to_dict())
    text = json.dumps(normalized.to_dict(), ensure_ascii=False, indent=2) + "\n"
    with _lock:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(p.parent), prefix=".settings-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                tmp.write(text)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, p)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        _settings = normalized
        apply_to_runtime(normalized)
        return deepcopy_settings(normalized)


def reset_settings(*, path: Path | None = None) -> AppSettings:
    return save_settings(default_settings(), path=path)


def slots_by_id(settings: AppSettings | None = None) -> dict[str, ModelSlot]:
    s = settings or get_settings()
    return {slot.id: slot for slot in s.slots}


def models_map(settings: AppSettings | None = None) -> dict[str, str]:
    return {slot.id: slot.model for slot in (settings or get_settings()).slots}


def providers_map(settings: AppSettings | None = None) -> dict[str, str]:
    return {slot.id: slot.provider for slot in (settings or get_settings()).slots}


def labels_map(settings: AppSettings | None = None) -> dict[str, str]:
    return {slot.id: slot.label for slot in (settings or get_settings()).slots}


def required_ids(settings: AppSettings | None = None) -> tuple[str, ...]:
    return tuple(s.id for s in (settings or get_settings()).slots if s.required)


def optional_ids(settings: AppSettings | None = None) -> tuple[str, ...]:
    return tuple(s.id for s in (settings or get_settings()).slots if s.optional)


def tier_order(settings: AppSettings | None = None) -> list[str]:
    """Лестница эскалации: уникальные id по возрастанию rank (без дублей ранга — стабильный порядок)."""
    slots = sorted((settings or get_settings()).slots, key=lambda s: (s.rank, s.id))
    # coder/xlarge оба rank=3 — в order оставляем xlarge как «вверх», coder — боковая ветка
    order: list[str] = []
    for s in slots:
        if s.id == "coder":
            continue
        order.append(s.id)
    return order


def tier_rank(settings: AppSettings | None = None) -> dict[str, int]:
    return {s.id: s.rank for s in (settings or get_settings()).slots}


def router_auto_ids(settings: AppSettings | None = None) -> list[str]:
    return [s.id for s in (settings or get_settings()).slots if s.router_auto]


def build_router_system(settings: AppSettings | None = None) -> str:
    s = settings or get_settings()
    lines = [ROUTER_SYSTEM_HEADER.rstrip(), ""]
    for slot in sorted(s.slots, key=lambda x: (x.rank, x.id)):
        auto = "auto" if slot.router_auto else "вручную/эскалация"
        prov = "" if slot.provider == "ollama" else f", provider={slot.provider}"
        lines.append(
            f"- {slot.id} (модель `{slot.model}`{prov}, rank={slot.rank}, {auto}): "
            f"{slot.router_prompt}"
        )
    lines.append(ROUTER_SYSTEM_FOOTER.rstrip())
    return "\n".join(lines) + "\n"


def build_route_schema(settings: AppSettings | None = None) -> dict[str, Any]:
    enums = router_auto_ids(settings) or ["tiny", "mid", "heavy"]
    return {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "tier": {"type": "string", "enum": enums},
            "need_web": {"type": "boolean"},
            "reason": {"type": "string"},
            "reply": {"type": "string"},
        },
        "required": ["ok", "tier", "need_web", "reason"],
    }


def public_settings_payload(settings: AppSettings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    return {
        "router_model": s.router_model,
        "slots": [slot.to_dict() for slot in s.slots],
        "defaults": {
            "router_model": DEFAULT_ROUTER_MODEL,
            "slots": DEFAULT_SLOTS,
            "router_prompts": DEFAULT_ROUTER_PROMPTS,
        },
        "router_system": build_router_system(s),
        "providers": {
            "openrouter": openrouter_status(),
        },
    }


def add_slot(
    *,
    model: str,
    label: str | None = None,
    router_prompt: str | None = None,
    slot_id: str | None = None,
    rank: int = 2,
    router_auto: bool = True,
    provider: str = "ollama",
) -> AppSettings:
    s = get_settings()
    model = (model or "").strip()
    if not model:
        raise ValueError("Укажите имя модели")
    prov = _normalize_provider(provider, builtin=False)
    sid = (slot_id or "").strip().lower()
    if not sid:
        sid = re.sub(r"[^a-z0-9]+", "_", model.lower()).strip("_")[:32] or "custom"
        if sid[0].isdigit():
            sid = "m_" + sid
    if not _ID_RE.match(sid):
        raise ValueError(f"Некорректный id: {sid}")
    if any(x.id == sid for x in s.slots):
        raise ValueError(f"Слот {sid} уже есть")
    if prov == "openrouter":
        prompt_default = (
            f"Внешняя модель OpenRouter `{model}` — сложные задачи, "
            f"когда локальных не хватает (опиши критерии точнее в настройках)."
        )
    else:
        prompt_default = (
            f"Используй модель {model} для задач, которые ей лучше подходят "
            f"(опиши критерии точнее в настройках)."
        )
    prompt = (router_prompt or "").strip() or prompt_default
    label_default = model if prov == "ollama" else f"{model} · OR"
    s.slots.append(
        ModelSlot(
            id=sid,
            model=model,
            label=(label or label_default).strip() or label_default,
            router_prompt=prompt,
            required=False,
            optional=True,
            rank=int(rank),
            router_auto=bool(router_auto),
            builtin=False,
            provider=prov,
        )
    )
    return save_settings(s)


def update_settings(
    slots_payload: list[dict[str, Any]],
    *,
    router_model: str | None = None,
) -> AppSettings:
    """Полная замена списка слотов (+ опционально модель роутера)."""
    if not isinstance(slots_payload, list) or not slots_payload:
        raise ValueError("Нужен непустой список slots")
    current = get_settings()
    rm = _normalize_router_model(
        router_model if router_model is not None else current.router_model,
        fallback=current.router_model or DEFAULT_ROUTER_MODEL,
    )
    return save_settings(
        AppSettings(
            slots=[_slot_from_dict(x) for x in slots_payload],
            router_model=rm,
        )
    )


def delete_slot(slot_id: str) -> AppSettings:
    s = get_settings()
    sid = slot_id.strip().lower()
    slot = next((x for x in s.slots if x.id == sid), None)
    if slot is None:
        raise KeyError(slot_id)
    if slot.builtin or slot.required:
        raise ValueError(f"Слот {sid} встроенный — его нельзя удалить")
    s.slots = [x for x in s.slots if x.id != sid]
    return save_settings(s)


def apply_to_runtime(settings: AppSettings | None = None) -> None:
    """Прописать MODELS / ранги / промпт роутера в orchestra и router."""
    s = settings or get_settings()
    from . import orchestra
    from . import router

    models = models_map(s)
    providers = providers_map(s)
    ranks = tier_rank(s)
    order = tier_order(s)
    required = required_ids(s)
    optional = optional_ids(s)
    selfcheck = models.get("mid") or next(iter(models.values()), "")
    heavy_rank = ranks.get("heavy", 2)
    complex_tiers = frozenset(
        tid for tid, r in ranks.items() if r >= heavy_rank or tid in {"heavy", "xlarge", "coder"}
    )
    route_model = s.router_model or models.get("tiny") or router.ROUTE_MODEL
    revalidate = models.get("mid") or router.REVALIDATE_MODEL
    system = build_router_system(s)
    schema = build_route_schema(s)
    auto_tiers = frozenset(router_auto_ids(s))

    with runtime_lock:
        # Без clear(): иначе параллельный handle() увидит пустой MODELS
        for key, val in models.items():
            orchestra.MODELS[key] = val
        for key in list(orchestra.MODELS):
            if key not in models:
                del orchestra.MODELS[key]
        for key, val in providers.items():
            orchestra.PROVIDERS[key] = val
        for key in list(orchestra.PROVIDERS):
            if key not in providers:
                del orchestra.PROVIDERS[key]
        orchestra.REQUIRED_TIERS = required  # type: ignore[assignment]
        orchestra.OPTIONAL_TIERS = optional  # type: ignore[assignment]
        orchestra.SELFCHECK_MODEL = selfcheck
        orchestra._COMPLEX_TIERS = complex_tiers  # type: ignore[attr-defined]

        for key, val in ranks.items():
            router.TIER_RANK[key] = val
        for key in list(router.TIER_RANK):
            if key not in ranks:
                del router.TIER_RANK[key]
        router.TIER_ORDER[:] = order
        router.ALL_TIERS = frozenset(ranks)
        router.ROUTE_MODEL = route_model
        router.REVALIDATE_MODEL = revalidate
        router.SYSTEM = system
        router.ROUTE_SCHEMA = schema
        router.ROUTER_AUTO_TIERS = auto_tiers


def bootstrap(*, path: Path | str | None = None) -> AppSettings:
    """Загрузить settings и применить к runtime (явно или через Client)."""
    global _bootstrapped
    if path is not None:
        set_settings_path(path)
    s = load_settings()
    apply_to_runtime(s)
    with _lock:
        _bootstrapped = True
    return s


def ensure_bootstrapped(*, path: Path | str | None = None) -> AppSettings:
    """Однократная инициализация; повторные вызовы — no-op (если path не задан)."""
    if path is not None:
        return bootstrap(path=path)
    with _lock:
        if _bootstrapped and _settings is not None:
            return deepcopy_settings(_settings)
    return bootstrap()
