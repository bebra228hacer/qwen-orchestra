"""Персистентные настройки оркестра: слоты моделей + промпты роутера.

Файл: settings.json рядом с этим модулем. Builtin-слоты (tiny…coder)
нельзя удалить; можно сменить Ollama-модель и текст «когда использовать».
Пользовательские слоты добавляются из UI.
"""

from __future__ import annotations

import json
import re
import threading
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = ROOT / "settings.json"

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_lock = threading.RLock()

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
    return ModelSlot(
        id=sid,
        model=model,
        label=label,
        router_prompt=prompt,
        required=bool(base.get("required", False)),
        optional=bool(base.get("optional", True)),
        rank=int(base.get("rank", 1)),
        router_auto=bool(base.get("router_auto", True)),
        builtin=bool(base.get("builtin", False)),
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
            _settings = _merge_with_defaults(raw if isinstance(raw, dict) else None)
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
    # сохранить и пользовательские слоты как есть после merge
    # merge уже включил customs из settings.to_dict()
    text = json.dumps(normalized.to_dict(), ensure_ascii=False, indent=2) + "\n"
    with _lock:
        p.write_text(text, encoding="utf-8")
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
        lines.append(
            f"- {slot.id} (модель `{slot.model}`, rank={slot.rank}, {auto}): {slot.router_prompt}"
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
    }


def add_slot(
    *,
    model: str,
    label: str | None = None,
    router_prompt: str | None = None,
    slot_id: str | None = None,
    rank: int = 2,
    router_auto: bool = True,
) -> AppSettings:
    s = get_settings()
    model = (model or "").strip()
    if not model:
        raise ValueError("Укажите имя модели Ollama")
    sid = (slot_id or "").strip().lower()
    if not sid:
        sid = re.sub(r"[^a-z0-9]+", "_", model.lower()).strip("_")[:32] or "custom"
        if sid[0].isdigit():
            sid = "m_" + sid
    if not _ID_RE.match(sid):
        raise ValueError(f"Некорректный id: {sid}")
    if any(x.id == sid for x in s.slots):
        raise ValueError(f"Слот {sid} уже есть")
    prompt = (router_prompt or "").strip() or (
        f"Используй модель {model} для задач, которые ей лучше подходят "
        f"(опиши критерии точнее в настройках)."
    )
    s.slots.append(
        ModelSlot(
            id=sid,
            model=model,
            label=(label or model).strip() or model,
            router_prompt=prompt,
            required=False,
            optional=True,
            rank=int(rank),
            router_auto=bool(router_auto),
            builtin=False,
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


# совместимость со старым именем
def update_slots(slots_payload: list[dict[str, Any]]) -> AppSettings:
    return update_settings(slots_payload)


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
    import orchestra
    import router

    models = models_map(s)
    ranks = tier_rank(s)
    order = tier_order(s)

    # mutate in place — иначе `from orchestra import MODELS` останется со старым dict
    orchestra.MODELS.clear()
    orchestra.MODELS.update(models)
    orchestra.REQUIRED_TIERS = required_ids(s)  # type: ignore[assignment]
    orchestra.OPTIONAL_TIERS = optional_ids(s)  # type: ignore[assignment]
    orchestra.SELFCHECK_MODEL = models.get("mid") or next(iter(models.values()), "")
    heavy_rank = ranks.get("heavy", 2)
    orchestra._COMPLEX_TIERS = frozenset(  # type: ignore[attr-defined]
        tid for tid, r in ranks.items() if r >= heavy_rank or tid in {"heavy", "xlarge", "coder"}
    )

    router.TIER_RANK.clear()
    router.TIER_RANK.update(ranks)
    router.TIER_ORDER[:] = order
    router.ALL_TIERS = frozenset(ranks)
    router.ROUTE_MODEL = s.router_model or models.get("tiny") or router.ROUTE_MODEL
    router.REVALIDATE_MODEL = models.get("mid") or router.REVALIDATE_MODEL
    router.SYSTEM = build_router_system(s)
    router.ROUTE_SCHEMA = build_route_schema(s)
    router.ROUTER_AUTO_TIERS = frozenset(router_auto_ids(s))


# Загрузка при импорте модуля настроек — оркестр/роутер подхватят через apply
def bootstrap() -> AppSettings:
    s = load_settings()
    apply_to_runtime(s)
    return s
