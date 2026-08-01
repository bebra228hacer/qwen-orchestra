"""Роутер: валидация запроса + выбор tier (tiny / mid / heavy).

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
| запрос на код + длинное описание (> 90) или 3+ требований | heavy |
| 3+ вопроса в одном сообщении | heavy |
| traceback / стектрейс / отладка ошибки | heavy |

Модель может поднять тир выше floor, но не опустить ниже.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from llm import chat

Tier = Literal["tiny", "mid", "heavy"]
TIER_ORDER: list[Tier] = ["tiny", "mid", "heavy"]

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
    r"объясн|напиш|переведи|сделай|подскаж|как\s|почему|что такое|скрипт|функци|код\b|список|инструкц",
    re.IGNORECASE,
)
_MATH_RE = re.compile(r"\d{2,}\s*[\+\-\*/^]\s*\d|процент|интеграл|производн|уравнени")
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]{2,}")
_VOWEL_RE = re.compile(r"[аеёиоуыэюяAEIOUYaeiouy]", re.IGNORECASE)
_ALNUM_RE = re.compile(r"[A-Za-zА-Яа-яЁё\d]")
_BRIEF_RE = re.compile(r"кратко|коротко|в двух словах|одним словом|briefly|in short", re.IGNORECASE)
# 0.5b любит ставить need_web без причины; её «да» принимаем только при этих признаках
_SOFT_WEB_RE = re.compile(
    r"последн|нов(ый|ая|ости)|верси|релиз|цена|стоимост|курс|когда\s|дата|кто такой|"
    r"рейтинг|статистик|прогноз|расписани|сколько сейчас",
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
    return TIER_ORDER[max(TIER_ORDER.index(a), TIER_ORDER.index(b))]


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
    return any(k in t for k in _WEB_KEYS)


def _looks_tiny(user_text: str) -> bool:
    t = user_text.strip().lower()
    if _looks_web(user_text):
        return False
    if len(t) <= 24 and any(k in t for k in _TINY_KEYS):
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
    return bool(re.search(r"\d", t))


def tier_floor(user_text: str) -> Tier:
    """Минимальный тир, ниже которого опускаться нельзя (см. таблицу в докстринге)."""
    t = (user_text or "").strip()
    low = t.lower()
    n = len(t)

    if _looks_tiny(t):
        return "tiny"

    code_request = bool(_CODE_REQUEST_RE.search(t)) or bool(_CODE_RE.search(t))
    requirements = len(_REQUIREMENT_RE.findall(t))

    heavy = (
        n > 400
        or t.count("?") >= 3
        or any(k in low for k in _HEAVY_KEYS)
        or bool(_DEBUG_RE.search(t))
        or (code_request and (n > 90 or requirements >= 3))
    )
    if heavy:
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
    """Потолок тира: просьбу «кратко» не гоняем через 7b без нужды."""
    if _BRIEF_RE.search(user_text or "") and tier_floor(user_text) != "heavy":
        return "mid"
    return "heavy"


def _clamp(tier: Tier, user_text: str) -> Tier:
    floor = tier_floor(user_text)
    ceiling = tier_ceiling(user_text)
    tier = _tier_max(tier, floor)
    if TIER_ORDER.index(tier) > TIER_ORDER.index(ceiling):
        tier = ceiling
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
            keep_alive="30m",
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001
        return None
    return _extract_json(msg.get("content") or "")


def route(user_text: str) -> RouteDecision:
    t = (user_text or "").strip()
    if len(t) < 2 or not _ALNUM_RE.search(t):
        return RouteDecision(
            False, "tiny", False, "invalid:empty", "Не понял ввод. Напишите вопрос текстом."
        )

    floor = tier_floor(user_text)

    # Жёсткие лёгкие кейсы — не спрашиваем 0.5b
    if floor == "tiny" and _looks_tiny(user_text):
        t = user_text.strip().lower()
        if any(k in t for k in ("привет", "здравствуй", "hello", "hi", "hey")):
            return RouteDecision(True, "tiny", False, "tiny-shortcut", "Привет! Чем могу помочь?")
        if any(k in t for k in ("спасибо", "благодар", "thanks")):
            return RouteDecision(True, "tiny", False, "tiny-shortcut", "Пожалуйста!")
        if any(k in t for k in ("пока", "bye")):
            return RouteDecision(True, "tiny", False, "tiny-shortcut", "Пока!")

    # Свежие данные и явно тяжёлые задачи — без участия 0.5b
    if _looks_web(user_text):
        return RouteDecision(True, _tier_max("mid", floor), True, "web-shortcut", "")
    if floor == "heavy":
        return RouteDecision(True, "heavy", False, "floor:heavy", "")

    data = _ask_router(ROUTE_MODEL, user_text, timeout=120)
    if not data:
        return _heuristic(user_text)

    ok = bool(data.get("ok", True))
    tier_raw = str(data.get("tier") or "mid").lower().strip()
    tier: Tier = tier_raw if tier_raw in {"tiny", "mid", "heavy"} else "mid"  # type: ignore[assignment]
    need_web = _looks_web(user_text) or (
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
    if need_web:
        tier = _tier_max(tier, "mid")
    if tier != "tiny":
        reply = ""

    return RouteDecision(ok, tier, need_web, reason or f"floor:{floor}", reply)
