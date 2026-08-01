"""Роутер: валидация запроса + выбор tier (tiny / mid / heavy / xlarge / coder).

Решение принимает 0.5b, но её выбор ограничен снизу детерминированными
правилами (`tier_floor`) — модель может поднять тир, но не опустить ниже
того, что требует запрос. Так лечится главная беда: 0.5b недооценивает
сложность и отправляет тяжёлую задачу на слабую модель.

Правила auto-режима (минимальный тир):

| Признак запроса | Минимум |
|---|---|
| приветствие, спасибо/пока, `2+2` | tiny |
| длина > 60 символов | mid |
| «объясни / напиши / переведи / сделай / как …» | mid |
| код, SQL, стек, команды, ссылки | mid |
| нужны свежие данные (web) | mid |
| длина > 400 символов | heavy |
| архитектура, рефакторинг, оптимизация, сравнение, доказательство | heavy |
| тесты, обработка ошибок, план внедрения, миграция | heavy |
| запрос на код + длинное описание (> 90) или 3+ требований | coder |
| 3+ вопроса в одном сообщении | heavy |
| traceback / стектрейс / отладка ошибки | coder |

Эскалация после самопроверки: tiny → mid → heavy → xlarge.
Тяжёлый код стартует на `coder` (qwen2.5-coder:14b); при провале → xlarge.

Модель может поднять тир выше floor, но не опустить ниже.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from llm import chat

Tier = Literal["tiny", "mid", "heavy", "xlarge", "coder"]
# Лестница эскалации по размеру (coder — боковая ветка для кода)
TIER_ORDER: list[Tier] = ["tiny", "mid", "heavy", "xlarge"]
TIER_RANK: dict[Tier, int] = {
    "tiny": 0,
    "mid": 1,
    "heavy": 2,
    "xlarge": 3,
    "coder": 3,
}
ALL_TIERS: frozenset[str] = frozenset(TIER_RANK)

ROUTE_MODEL = "qwen2.5:0.5b"
REVALIDATE_MODEL = "qwen2.5:3b"

ROUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "tier": {"type": "string", "enum": ["tiny", "mid", "heavy"]},
        "need_web": {"type": "boolean"},
        "reason": {"type": "string"},
        "reply": {"type": "string"},
    },
    "required": ["ok", "tier", "need_web", "reason"],
}

SYSTEM = """Ты роутер запросов. Отвечай ТОЛЬКО валидным JSON без markdown.

Поля:
- ok: false ТОЛЬКО если запрос пустой, бессмысленный набор символов или спам.
      Непонятный, странный или очень короткий вопрос — это ok=true.
- tier: tiny | mid | heavy
- need_web: true если нужны свежие данные из интернета
- reason: коротко почему такой tier
- reply: если ok=false — вежливый отказ; если tier=tiny — полный короткий ответ; иначе пустая строка

Правила tier:
- tiny: приветствие, благодарность, прощание, простая арифметика, да/нет
- mid: объяснения, небольшой код, короткие тексты, советы, перевод
- heavy: сложный код, архитектура, отладка ошибок, оптимизация, сравнение подходов,
  многошаговые задачи, длинный анализ, доказательства, планы
- need_web=true => минимум mid
- Сомневаешься между двумя тирами — выбирай СТАРШИЙ."""


@dataclass
class RouteDecision:
    ok: bool
    tier: Tier
    need_web: bool
    reason: str
    reply: str = ""


_WEB_KEYS = (
    "погода",
    "новост",
    "курс доллар",
    "курс евро",
    "сегодня",
    "сейчас",
    "актуальн",
    "weather",
    "news",
    "http://",
    "https://",
    "что происходит",
    "свеж",
    "поищи",
    "погугли",
    "найди в интернет",
    "найди в сети",
    "гугл",
    "google",
    "look up",
    "search the web",
    "search online",
)

_TINY_KEYS = (
    "привет",
    "здравствуй",
    "здравствуйте",
    "как дела",
    "спасибо",
    "благодар",
    "пока",
    "доброе утро",
    "добрый день",
    "добрый вечер",
    "hello",
    "hi",
    "hey",
    "thanks",
    "bye",
)

# Короткие EN-приветствия только как целые слова (иначе hi ⊂ this/history)
_TINY_WORD_RE = re.compile(
    r"(?:^|[^\w])(?:hi|hey|hello|bye|thanks|привет|пока)(?:[^\w]|$)",
    re.IGNORECASE,
)

_HEAVY_KEYS = (
    "архитектур",
    "рефактор",
    "спроектир",
    "оптимизир",
    "сравни",
    "докажи",
    "выведи формулу",
    "подробно разбер",
    "напиши сервис",
    "напиши приложение",
    "напиши игру",
    "системный дизайн",
    "system design",
    "kubernetes",
    "microservice",
    "микросервис",
    "миграци",
    "пошагов",
    "план внедрения",
    "производительност",
    "бенчмарк",
    "почини",
    "отлад",
    "не работает",
    "ошибка в коде",
    "тест",
    "обработку ошибок",
    "обработка ошибок",
)

_DEBUG_RE = re.compile(r"traceback|стектрейс|stack trace|exception|error:|errno", re.IGNORECASE)
_CODE_RE = re.compile(
    r"```|\bdef\s|\bclass\s|\bimport\s|\bselect\s|\bfunction\s|=>|\bnpm\b|\bpip\b|\bgit\b|\bsql\b|\bregex\b",
    re.IGNORECASE,
)
_MID_RE = re.compile(
    r"объясн|напиш|переведи|сделай|подскаж|как\s|почему|что такое|скрипт|функци|код\b|список|инструкц|"
    r"\bexplain\b|\bwrite\b|\btranslate\b|\bhow\s+to\b|\bwhat\s+is\b|\bcode\b",
    re.IGNORECASE,
)
_MATH_RE = re.compile(r"\d{2,}\s*[\+\-\*/^]\s*\d|процент|интеграл|производн|уравнени")
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]{2,}")
_VOWEL_RE = re.compile(r"[аеёиоуыэюяAEIOUYaeiouy]", re.IGNORECASE)
_ALNUM_RE = re.compile(r"[A-Za-zА-Яа-яЁё\d]")
_BRIEF_RE = re.compile(r"кратко|коротко|в двух словах|одним словом|briefly|in short", re.IGNORECASE)
# 0.5b любит ставить need_web без причины; её «да» принимаем только при этих признаках
_SOFT_WEB_RE = re.compile(
    r"(?:"
    r"последн|нов(?:ый|ая|ое|ые|ости)|верси(?:я|и|ю)|релиз|стоимост|"
    r"\bкурс\b|когда\s|дата\b|кто такой|"
    r"рейтинг|статистик|прогноз|расписани|сколько сейчас|"
    r"поищи|погугли|найди\s+в\s+(?:интернет|сети)|look\s+up|search\s+(?:the\s+)?(?:web|online)|"
    r"цена\b"
    r")",
    re.IGNORECASE,
)
_CODE_REQUEST_RE = re.compile(
    r"напиши\s+(код|функци|скрипт|класс|программ|парсер|бот|сервис|приложени)"
    r"|реализуй|запрограммируй|допиши код|сгенерируй код",
    re.IGNORECASE,
)
# «сделай A, добавь B и C» — несколько требований в одном запросе
_REQUIREMENT_RE = re.compile(r"[,;]|\bи\b|\bтакже\b|\bплюс\b", re.IGNORECASE)


def _tier_max(a: Tier, b: Tier) -> Tier:
    return a if TIER_RANK[a] >= TIER_RANK[b] else b


def _extract_json(text: str) -> dict | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _looks_web(user_text: str) -> bool:
    t = user_text.strip().lower()
    return any(k in t for k in _WEB_KEYS) or bool(_SOFT_WEB_RE.search(t))


def need_web(user_text: str) -> bool:
    """Нужен ли интернет — детерминированно (для force_tier и shortcuts)."""
    return _looks_web(user_text)


def _looks_tiny(user_text: str) -> bool:
    t = user_text.strip().lower()
    if _looks_web(user_text):
        return False
    if len(t) > 24:
        return False
    # Многословные ключи — подстрокой; короткие EN — только целиком
    phrase_keys = (
        "привет",
        "здравствуй",
        "здравствуйте",
        "как дела",
        "спасибо",
        "благодар",
        "пока",
        "доброе утро",
        "добрый день",
        "добрый вечер",
        "hello",
        "thanks",
        "bye",
    )
    if any(k in t for k in phrase_keys):
        return True
    if _TINY_WORD_RE.search(t):
        return True
    if re.fullmatch(r"\d+\s*[\+\-\*/]\s*\d+\s*=?\s*", t):
        return True
    return False


def looks_meaningful(user_text: str) -> bool:
    """Есть ли в запросе хоть что-то осмысленное.

    0.5b часто помечает нормальные вопросы как невалидные, поэтому её `ok=false`
    принимается только для реально пустого/мусорного ввода.
    """
    t = (user_text or "").strip()
    if len(t) < 2:
        return False
    # слово с гласной — признак речи, а не случайного набора клавиш
    words = [w for w in _WORD_RE.findall(t) if _VOWEL_RE.search(w)]
    if len(words) >= 2:
        return True
    if words and len(t) >= 4:
        return True
    # голые цифры без слов — осмысленны только как арифметика / короткий номер
    if re.fullmatch(r"[\d\s\+\-\*/^=.,()]+", t) and re.search(r"[\+\-\*/^]", t):
        return True
    if re.fullmatch(r"\d{1,6}", t):
        return True
    return False


def tier_floor(user_text: str) -> Tier:
    """Минимальный тир, ниже которого опускаться нельзя (см. таблицу в докстринге)."""
    t = (user_text or "").strip()
    low = t.lower()
    n = len(t)

    if _looks_tiny(t):
        return "tiny"

    code_request = bool(_CODE_REQUEST_RE.search(t)) or bool(_CODE_RE.search(t))
    requirements = len(_REQUIREMENT_RE.findall(t))
    debug = bool(_DEBUG_RE.search(t))
    heavy_code = debug or (code_request and (n > 90 or requirements >= 3))

    heavy = (
        n > 400
        or t.count("?") >= 3
        or any(k in low for k in _HEAVY_KEYS)
        or heavy_code
    )
    if heavy:
        # Сложный код / отладка — сразу на coder 14b
        if heavy_code or (code_request and any(k in low for k in _HEAVY_KEYS)):
            return "coder"
        return "heavy"

    mid = (
        n > 60
        or _looks_web(t)
        or code_request
        or bool(_MID_RE.search(t))
        or bool(_MATH_RE.search(low))
    )
    return "mid" if mid else "tiny"


def tier_ceiling(user_text: str) -> Tier:
    """Потолок стартового тира: «кратко» не гоняем через 7b/14b без нужды.

    xlarge в auto появляется только при эскалации после selfcheck, не как старт
    от роутера 0.5b — кроме явного force_tier.
    """
    floor = tier_floor(user_text)
    if _BRIEF_RE.search(user_text or "") and floor not in {"heavy", "coder", "xlarge"}:
        return "mid"
    if floor == "coder":
        return "coder"
    if floor == "xlarge":
        return "xlarge"
    return "heavy"


def _clamp(tier: Tier, user_text: str) -> Tier:
    floor = tier_floor(user_text)
    ceiling = tier_ceiling(user_text)
    tier = _tier_max(tier, floor)
    if TIER_RANK[tier] > TIER_RANK[ceiling]:
        return ceiling
    # При равном ранге сохраняем специализацию floor (coder vs xlarge)
    if TIER_RANK[tier] == TIER_RANK[floor] and floor in {"coder", "xlarge"}:
        return floor
    return tier


def _heuristic(user_text: str) -> RouteDecision:
    """Запасной роут, если роутер-модель вернула мусор."""
    t = user_text.strip()
    if len(t) < 2:
        return RouteDecision(False, "tiny", False, "too short", "Напишите вопрос чуть подробнее.")

    if _looks_tiny(t):
        return RouteDecision(True, "tiny", False, "heuristic:greeting", "")

    return RouteDecision(True, tier_floor(t), _looks_web(t), "heuristic:floor", "")


def _ask_router(model: str, user_text: str, *, timeout: int) -> dict | None:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_text},
    ]
    try:
        msg = chat(
            model,
            messages,
            fmt=ROUTE_SCHEMA,
            temperature=0.0,
            num_ctx=2048,
            keep_alive="10m",
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001
        return None
    return _extract_json(msg.get("content") or "")


def _tiny_shortcut_reply(user_text: str) -> str | None:
    t = user_text.strip().lower()
    if any(k in t for k in ("спасибо", "благодар")) or re.search(
        r"(?:^|[^\w])thanks(?:[^\w]|$)", t
    ):
        return "Пожалуйста!"
    if any(k in t for k in ("пока",)) or re.search(r"(?:^|[^\w])bye(?:[^\w]|$)", t):
        return "Пока!"
    if any(k in t for k in ("привет", "здравствуй", "hello")) or re.search(
        r"(?:^|[^\w])(?:hi|hey)(?:[^\w]|$)", t
    ):
        return "Привет! Чем могу помочь?"
    return None


def route(user_text: str) -> RouteDecision:
    t = (user_text or "").strip()
    if len(t) < 2 or not _ALNUM_RE.search(t):
        return RouteDecision(
            False, "tiny", False, "invalid:empty", "Не понял ввод. Напишите вопрос текстом."
        )

    floor = tier_floor(user_text)
    web = need_web(user_text)

    # Жёсткие лёгкие кейсы — не спрашиваем 0.5b
    if floor == "tiny" and _looks_tiny(user_text):
        reply = _tiny_shortcut_reply(user_text)
        if reply:
            return RouteDecision(True, "tiny", False, "tiny-shortcut", reply)

    # Свежие данные и явно тяжёлые/средние задачи — без участия 0.5b
    if web:
        return RouteDecision(True, _tier_max("mid", floor), True, "web-shortcut", "")
    if floor == "heavy":
        return RouteDecision(True, "heavy", False, "floor:heavy", "")
    if floor == "coder":
        return RouteDecision(True, "coder", False, "floor:coder", "")
    if floor == "xlarge":
        return RouteDecision(True, "xlarge", False, "floor:xlarge", "")
    # Уверенный mid по правилам: 0.5b только тратит время и VRAM
    if floor == "mid":
        return RouteDecision(True, _clamp("mid", user_text), False, "floor:mid", "")

    data = _ask_router(ROUTE_MODEL, user_text, timeout=120)
    if not data:
        return _heuristic(user_text)

    ok = bool(data.get("ok", True))
    tier_raw = str(data.get("tier") or "mid").lower().strip()
    tier: Tier = tier_raw if tier_raw in {"tiny", "mid", "heavy"} else "mid"  # type: ignore[assignment]
    need = web or (
        bool(data.get("need_web", False)) and bool(_SOFT_WEB_RE.search(user_text))
    )
    reason = " ".join(str(data.get("reason") or "").split())[:80]
    reply = str(data.get("reply") or "").strip()

    # Валидация 0.5b часто ложно срабатывает: осмысленный запрос не отклоняем.
    # Её оценке тира в этом случае тоже не верим — берём floor.
    if not ok and looks_meaningful(user_text):
        ok = True
        tier = floor
        reason = "override:valid"
        reply = ""
    elif not ok:
        # ввод похож на мусор — второе мнение у 3b, прежде чем отказывать
        second = _ask_router(REVALIDATE_MODEL, user_text, timeout=180)
        if second and bool(second.get("ok", True)):
            ok = True
            tier = floor
            reason = "revalidated"
            reply = str(second.get("reply") or "").strip()

    if not ok:
        return RouteDecision(
            False,
            "tiny",
            False,
            reason or "invalid",
            reply or "Не понял запрос. Переформулируйте, пожалуйста.",
        )

    # Модель могла недооценить сложность — поднимаем до минимума
    tier = _clamp(tier, user_text)
    if need:
        tier = _tier_max(tier, "mid")
    if tier != "tiny":
        reply = ""

    return RouteDecision(ok, tier, need, reason or f"floor:{floor}", reply)
