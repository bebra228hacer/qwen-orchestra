"""Оркестр: tiny (0.5b) → mid (3b) → heavy (7b) → xlarge (14b) + coder.

Цикл одного запроса:
    route → plan_worker_context → worker → selfcheck → (retry на старшем тире)

Адаптивный num_ctx (см. plan_worker_context):
    ceil_256(tokens(промпт) + template + reserve_ответа + safety)

Самопроверка (`selfcheck.check`) отбраковывает ответ, если он ушёл на другой
язык, оказался пустым/зацикленным, стал отказом или содержит явную ошибку.
Тогда запрос переделывается на модели уровнем выше с инструкцией-правкой.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import selfcheck
from llm import chat, chat_stream, installed_models
from router import ALL_TIERS, TIER_ORDER, TIER_RANK, RouteDecision, Tier, need_web, route
from selfcheck import Verdict
from tools_web import TOOL_IMPL, TOOLS

MODELS: dict[Tier, str] = {
    "tiny": "qwen2.5:0.5b",
    "mid": "qwen2.5:3b",
    "heavy": "qwen2.5:7b",
    "xlarge": "qwen2.5:14b",
    "coder": "qwen2.5-coder:14b",
}

# Без этих моделей оркестр не стартует; 14b — опционально
REQUIRED_TIERS: tuple[Tier, ...] = ("tiny", "mid", "heavy")
OPTIONAL_TIERS: tuple[Tier, ...] = ("xlarge", "coder")

MAX_TOOL_ROUNDS = 4
MAX_TOOL_CALLS = 8
TOOL_RESULT_CHARS = 4000

# Сколько всего попыток на один запрос (1 основная + повторы после самопроверки)
MAX_ATTEMPTS = 3
# LLM-ревью ответа (ловит ошибки и уход от вопроса); проверяющий — 3b
SELFCHECK_LLM = True
SELFCHECK_MODEL = MODELS["mid"]

# num_ctx = ceil_256(prompt + template + reserve_ответа + safety), clamp [MIN…MAX]
_COMPLEX_TIERS: frozenset[Tier] = frozenset({"heavy", "xlarge", "coder"})
NUM_CTX_MIN = 256
NUM_CTX_MAX = 8192
NUM_CTX_FULL = NUM_CTX_MAX
CTX_ALIGN = 256
CTX_TEMPLATE_TOKENS = 128  # chat-шаблон / спецтокены
CTX_SAFETY_FLAT = 128  # мин. safety поверх суммы
CTX_OUT_SHORT = 512
CTX_OUT_NORMAL = 768
CTX_OUT_CODE = 1536
HISTORY_LIGHT = 4
HISTORY_FULL = 8
# Запас под tool-результаты внутри уже выбранного num_ctx
CTX_TOOL_BUDGET_RATIO = 0.35

WORKER_SYSTEM = """Ты полезный ассистент. Отвечай на языке пользователя, кратко и по делу.
Если в контексте есть результаты поиска/страниц — опирайся на них и указывай URL.
Не выдумывай свежие факты без источников."""

# Правка идёт в system, а не в текст пользователя: иначе модель начинает
# извиняться и «соглашаться с поправкой» вместо нормального ответа
RETRY_SYSTEM = """Предыдущая попытка ответа забракована автопроверкой.
Что учесть: {hint}

Ответь на вопрос заново и полностью. Не упоминай предыдущие попытки,
не извиняйся и не благодари за замечание."""

_SEARCH_RE = re.compile(r"(?:SEARCH|ПОИСК)\s*:\s*(.+)", re.IGNORECASE)
_FETCH_RE = re.compile(r"(?:FETCH|ОТКРЫТЬ)\s*:\s*(https?://\S+)", re.IGNORECASE)
_CODEISH_RE = re.compile(
    r"```|\bdef\s|\bclass\s|\bfunction\s|напиши\s+(код|функци|скрипт|класс|программ)|"
    r"реализуй|запрограммируй|сгенерируй\s+код|\btraceback\b|\bstack\s+trace\b",
    re.IGNORECASE,
)
# Отсылки к предыдущим репликам чата (без голых «это/этот» — слишком широко)
_HISTORY_REF_RE = re.compile(
    r"(?:"
    r"\b(?:выше|ранее|предыдущ\w*|продолж\w*|вышесказан\w*)\b|"
    r"как\s+ты\s+(?:сказал|написал|предложил|ответил)|"
    r"\b(?:ещё|еще)\s+раз\b|"
    r"(?:исправь|поправь|переделай|доработай)\s+(?:это|этот|код|ответ|функци\w*)|"
    r"\b(?:тот\s+же|ту\s+же|тот\s+код|мой\s+код|из\s+чата|из\s+истории)\b|"
    r"\b(?:previous|above|continue|aforementioned)\b|"
    r"\b(?:fix|change|update)\s+(?:it|that|this|the\s+code)\b"
    r")",
    re.IGNORECASE,
)

StatusCallback = Callable[[str, dict[str, Any]], None]
TokenCallback = Callable[[str], None]


@dataclass
class ContextPlan:
    """Сколько истории и num_ctx отдать воркеру (экономия VRAM на 14b)."""

    history: list[dict]
    num_ctx: int
    use_history: bool
    reason: str


@dataclass
class OrchestraResult:
    text: str
    tier: Tier
    model: str
    need_web: bool
    route_reason: str
    escalated: bool = False
    attempts: int = 1
    checked: bool = True
    problems: list[str] = field(default_factory=list)
    num_ctx: int = NUM_CTX_FULL
    used_history: bool = True
    context_reason: str = ""


def missing_models(have: set[str] | None = None) -> list[str]:
    """Обязательные модели (tiny/mid/heavy), без которых auto не работает."""
    have = have if have is not None else set(installed_models())
    return [MODELS[t] for t in REQUIRED_TIERS if MODELS[t] not in have]


def missing_optional_models(have: set[str] | None = None) -> list[str]:
    """14b / coder — можно пользоваться без них, но тиры будут недоступны."""
    have = have if have is not None else set(installed_models())
    return [MODELS[t] for t in OPTIONAL_TIERS if MODELS[t] not in have]


def available_tiers(have: set[str] | None = None) -> set[Tier]:
    have = have if have is not None else set(installed_models())
    return {t for t, name in MODELS.items() if name in have}


def _emit(on_status: StatusCallback | None, event: str, **payload: Any) -> None:
    if on_status:
        on_status(event, payload)


def _emit_token(on_token: TokenCallback | None, text: str) -> None:
    if on_token and text:
        on_token(text)


def _fit_tier(tier: Tier, available: set[Tier]) -> Tier:
    """Подобрать установленную модель: тот же тир, иначе ближайший ниже/альтернатива."""
    if not available:
        raise RuntimeError("Нет установленных моделей оркестра")
    if tier in available:
        return tier
    if tier == "coder" and "xlarge" in available:
        return "xlarge"
    if tier == "xlarge" and "coder" in available:
        return "coder"
    # вниз по лестнице размера
    for t in reversed(TIER_ORDER):
        if TIER_RANK[t] <= TIER_RANK[tier] and t in available:
            return t
    for t in TIER_ORDER:
        if t in available:
            return t
    # coder единственный доступный
    return next(iter(available))


def _next_tier(tier: Tier, available: set[Tier] | None = None) -> Tier | None:
    """Следующий установленный тир при эскалации: coder → xlarge, иначе по лестнице."""
    if available is None:
        # без списка — старое поведение по лестнице (тесты / offline)
        if tier == "coder":
            return "xlarge"
        if tier not in TIER_ORDER:
            return tier
        idx = TIER_ORDER.index(tier)
        nxt = TIER_ORDER[min(idx + 1, len(TIER_ORDER) - 1)]
        return None if nxt == tier else nxt

    if tier == "coder":
        for cand in ("xlarge", "heavy", "mid"):
            if cand in available and cand != tier:
                return cand
        return None

    if tier not in TIER_ORDER:
        return None
    idx = TIER_ORDER.index(tier)
    for cand in TIER_ORDER[idx + 1 :]:
        if cand in available:
            return cand
    return None


def _escalated(start: Tier, final: Tier) -> bool:
    if TIER_RANK[final] > TIER_RANK[start]:
        return True
    # coder ↔ xlarge: смена специализации тоже эскалация
    return start != final and {start, final} <= {"coder", "xlarge"}


def _tool_cache_key(name: str, arguments: dict) -> str:
    return f"{name}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True)}"


def _trim_tool_result(result: str, budget_chars: int) -> str:
    text = result or ""
    if len(text) <= budget_chars:
        return text
    return text[: max(0, budget_chars - 20)] + "\n...[обрезано]"


def _run_tool(name: str, arguments) -> str:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            arguments = {"query": arguments} if name == "web_search" else {"url": arguments}
    if not isinstance(arguments, dict):
        arguments = {}
    impl = TOOL_IMPL.get(name)
    if not impl:
        return f"Неизвестный инструмент: {name}"
    return impl(arguments)


def needs_chat_history(user_text: str, history: list[dict]) -> tuple[bool, str]:
    """Нужны ли предыдущие сообщения чата для ответа.

    Для heavy/xlarge/coder отказ от истории → меньший num_ctx → больше VRAM под веса.
    """
    if not history:
        return False, "no-history"
    t = (user_text or "").strip()
    if not t:
        return False, "empty"
    if _HISTORY_REF_RE.search(t):
        return True, "ref"
    # «исправь/поправь» без кода в сообщении — почти наверняка про прошлый ответ
    if re.search(r"\b(?:исправь|поправь|переделай|доработай)\b", t, re.IGNORECASE) and "```" not in t:
        return True, "edit-prev"
    # Короткий follow-up почти всегда про прошлый ответ
    if len(t) < 48:
        return True, "short-followup"
    # Самодостаточный запрос: длинный текст или код внутри сообщения
    if "```" in t or len(t) >= 160:
        return False, "self-contained"
    return False, "standalone"


def _estimate_tokens(text: str) -> int:
    """Оценка токенов: ~2 символа/токен (завышено для RU/кода, чтобы не обрезать)."""
    n = len(text or "")
    if n == 0:
        return 0
    return max(1, (n + 1) // 2)


def _prompt_tokens(
    user_text: str, history: list[dict], *, system: str = WORKER_SYSTEM
) -> int:
    """Токены сырого промпта (system + история + user), без шаблона."""
    total = _estimate_tokens(system) + _estimate_tokens(user_text) + 8
    for h in history:
        total += _estimate_tokens(str(h.get("content") or "")) + 4
    return total


def _output_reserve_tokens(user_text: str, tier: Tier) -> int:
    """Запас под ответ: короткий / обычный / код."""
    t = user_text or ""
    if tier == "coder" or _CODEISH_RE.search(t) or "```" in t:
        return CTX_OUT_CODE
    if len(t.strip()) < 48:
        return CTX_OUT_SHORT
    return CTX_OUT_NORMAL


def _ceil_align(n: int, step: int = CTX_ALIGN) -> int:
    if n <= 0:
        return step
    return ((n + step - 1) // step) * step


def _min_num_ctx(prompt_tokens: int, out_reserve: int) -> int:
    """num_ctx = ceil_256(prompt + template + reserve_ответа + safety)."""
    base = prompt_tokens + CTX_TEMPLATE_TOKENS + out_reserve
    safety = max(CTX_SAFETY_FLAT, base // 10)  # ≥128 или ~10% суммы
    need = _ceil_align(base + safety)
    return min(NUM_CTX_MAX, max(NUM_CTX_MIN, need))


def _trim_history_to_fit(
    user_text: str, history: list[dict], *, out_reserve: int
) -> list[dict]:
    """Приоритет — полный текущий запрос; историю урезаем с начала, если не влезает."""
    # Сколько токенов промпта максимум влезает при потолке num_ctx
    # num_ctx >= prompt + template + out + safety(≥10% of base)
    # худший случай safety ≈ 10% → prompt ≈ (0.9*MAX - template - out) / 1.0 приблизительно
    max_prompt = NUM_CTX_MAX - CTX_TEMPLATE_TOKENS - out_reserve - CTX_SAFETY_FLAT
    max_prompt = max(64, (max_prompt * 9) // 10)  # чуть места под 10% safety
    base = _estimate_tokens(WORKER_SYSTEM) + _estimate_tokens(user_text) + 8
    if base >= max_prompt:
        return []
    kept: list[dict] = []
    used = base
    for h in reversed(history):
        cost = _estimate_tokens(str(h.get("content") or "")) + 4
        if used + cost > max_prompt:
            break
        kept.append(h)
        used += cost
    kept.reverse()
    return kept


def plan_worker_context(
    user_text: str, history: list[dict], tier: Tier
) -> ContextPlan:
    """История и num_ctx: 1) не обрезать запрос 2) минимальный ctx / VRAM."""
    hist = [
        h
        for h in (history or [])
        if h.get("role") in {"user", "assistant"} and (h.get("content") or "").strip()
    ]
    out_res = _output_reserve_tokens(user_text, tier)

    if tier not in _COMPLEX_TIERS:
        hist = _trim_history_to_fit(user_text, hist[-HISTORY_FULL:], out_reserve=out_res)
        prompt_tok = _prompt_tokens(user_text, hist)
        return ContextPlan(
            history=hist,
            num_ctx=_min_num_ctx(prompt_tok, out_res),
            use_history=bool(hist),
            reason="light-tier",
        )

    use, why = needs_chat_history(user_text, hist)
    if use:
        hist = _trim_history_to_fit(user_text, hist[-HISTORY_LIGHT:], out_reserve=out_res)
        if not hist:
            why = f"{why}+drop-hist"
            use = False
    else:
        hist = []

    prompt_tok = _prompt_tokens(user_text, hist)
    ctx = _min_num_ctx(prompt_tok, out_res)
    if ctx >= NUM_CTX_MAX and prompt_tok + CTX_TEMPLATE_TOKENS + out_res + CTX_SAFETY_FLAT > NUM_CTX_MAX:
        why = f"{why}+ctx-max"

    return ContextPlan(
        history=hist,
        num_ctx=ctx,
        use_history=use and bool(hist),
        reason=why,
    )


def _fallback_tools(content: str) -> list[dict]:
    calls = []
    for m in _SEARCH_RE.finditer(content or ""):
        calls.append({"function": {"name": "web_search", "arguments": {"query": m.group(1).strip()}}})
    for m in _FETCH_RE.finditer(content or ""):
        url = m.group(1).strip().rstrip(".,)")
        calls.append({"function": {"name": "fetch_url", "arguments": {"url": url}}})
    return calls


def _build_messages(
    user_text: str, history: list[dict], retry_hint: str | None
) -> list[dict]:
    system = WORKER_SYSTEM
    if retry_hint:
        system = f"{WORKER_SYSTEM}\n\n{RETRY_SYSTEM.format(hint=retry_hint)}"
    messages: list[dict] = [{"role": "system", "content": system}]
    for h in history:
        if h.get("role") in {"user", "assistant"}:
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_text})
    return messages


def _worker_with_tools(
    model: str,
    user_text: str,
    history: list[dict],
    *,
    on_status: StatusCallback | None,
    verbose: bool,
    retry_hint: str | None = None,
    num_ctx: int = NUM_CTX_FULL,
    tool_cache: dict[str, str] | None = None,
) -> str:
    messages = _build_messages(user_text, history, retry_hint)
    cache = tool_cache if tool_cache is not None else {}
    calls_done = 0
    # Бюджет символов под evidence: доля окна минус уже занятый промпт
    prompt_chars = sum(len(str(m.get("content") or "")) for m in messages)
    tool_budget = max(
        1200,
        min(
            TOOL_RESULT_CHARS * 2,
            int((num_ctx * 2) * CTX_TOOL_BUDGET_RATIO) - prompt_chars // 4,
        ),
    )

    for _ in range(MAX_TOOL_ROUNDS):
        if calls_done >= MAX_TOOL_CALLS:
            break
        msg = chat(
            model,
            messages,
            tools=TOOLS,
            temperature=0.3,
            num_ctx=num_ctx,
            keep_alive="10m",
        )
        content = (msg.get("content") or "").strip()
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            tool_calls = _fallback_tools(content)
        if not tool_calls:
            return content or "(пустой ответ)"

        messages.append(msg)
        seen_round: set[str] = set()
        for call in tool_calls:
            if calls_done >= MAX_TOOL_CALLS:
                break
            fn = call.get("function") or {}
            name = fn.get("name") or ""
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args.strip() else {}
                except json.JSONDecodeError:
                    args = {"query": args} if name == "web_search" else {"url": args}
            if not isinstance(args, dict):
                args = {}
            key = _tool_cache_key(name, args)
            if key in seen_round:
                continue
            seen_round.add(key)
            _emit(on_status, "tool", name=name, arguments=args, model=model)
            if verbose:
                cached = " cached" if key in cache else ""
                print(f"  [tool/{model}] {name}({args}){cached}", flush=True)
            if key in cache:
                result = cache[key]
            else:
                result = _run_tool(name, args)
                cache[key] = result
            per_call = max(800, tool_budget // max(1, MAX_TOOL_CALLS - calls_done))
            result = _trim_tool_result(result, min(TOOL_RESULT_CHARS, per_call))
            if verbose:
                preview = result if len(result) < 350 else result[:350] + "..."
                print(f"  <- {preview}\n", flush=True)
            messages.append({"role": "tool", "content": result})
            calls_done += 1
            tool_budget = max(400, tool_budget - len(result))

    msg = chat(model, messages, temperature=0.3, num_ctx=num_ctx, keep_alive="10m")
    return (msg.get("content") or "").strip() or "(пустой ответ)"


def _worker_plain(
    model: str,
    user_text: str,
    history: list[dict],
    *,
    stream: bool,
    on_token: TokenCallback | None,
    retry_hint: str | None = None,
    num_ctx: int = NUM_CTX_FULL,
) -> str:
    messages = _build_messages(user_text, history, retry_hint)

    if stream:
        return chat_stream(
            model,
            messages,
            on_token=on_token,
            temperature=0.3,
            num_ctx=num_ctx,
            keep_alive="10m",
        )

    msg = chat(model, messages, temperature=0.3, num_ctx=num_ctx, keep_alive="10m")
    return (msg.get("content") or "").strip() or "(пустой ответ)"


@dataclass
class _Attempt:
    text: str
    verdict: Verdict
    tier: Tier
    model: str
    ctx: ContextPlan


def _best_attempt(attempts: list[_Attempt]) -> _Attempt:
    """Прошедшая проверку попытка, иначе — с наименее серьёзными проблемами."""
    for a in attempts:
        if a.verdict.ok:
            return a
    return min(attempts, key=lambda a: (a.verdict.severity(), -len(a.text)))


def _emit_context(on_status: StatusCallback | None, ctx_plan: ContextPlan, tier: Tier) -> None:
    _emit(
        on_status,
        "context",
        used_history=ctx_plan.use_history,
        num_ctx=ctx_plan.num_ctx,
        reason=ctx_plan.reason,
        history_messages=len(ctx_plan.history),
        tier=tier,
    )


def _cli_status_printer(verbose: bool) -> StatusCallback:
    def _print(event: str, payload: dict[str, Any]) -> None:
        if event == "route":
            print(
                f"  [route] ok={payload.get('ok')} tier={payload.get('tier')} "
                f"web={payload.get('need_web')} ({payload.get('reason')})",
                flush=True,
            )
        elif event == "worker":
            web = " + web" if payload.get("need_web") else ""
            attempt = payload.get("attempt") or 1
            suffix = f" (попытка {attempt})" if attempt > 1 else ""
            ctx = payload.get("num_ctx")
            hist = "hist" if payload.get("used_history") else "no-hist"
            ctx_s = f" ctx={ctx} {hist}" if ctx else ""
            print(f"  [worker] {payload.get('model')}{web}{suffix}{ctx_s}", flush=True)
        elif event == "context":
            hist = "история" if payload.get("used_history") else "без истории"
            print(
                f"  [context] {hist}, num_ctx={payload.get('num_ctx')} ({payload.get('reason')})",
                flush=True,
            )
        elif event == "selfcheck":
            state = "ok" if payload.get("ok") else ", ".join(payload.get("problems") or [])
            print(f"\n  [check] {state}", flush=True)
        elif event == "retry":
            print(
                f"  [retry] {payload.get('from_model')} -> {payload.get('to_model')} "
                f"({', '.join(payload.get('problems') or [])})",
                flush=True,
            )
        elif event == "restore":
            print(f"  [restore] лучший ответ: {payload.get('model')}", flush=True)

    return _print


def handle(
    user_text: str,
    history: list[dict] | None = None,
    *,
    force_tier: Tier | None = None,
    stream: bool = True,
    verbose: bool = True,
    on_token: TokenCallback | None = None,
    on_status: StatusCallback | None = None,
) -> OrchestraResult:
    history = history or []
    # История не должна содержать текущий user — иначе вопрос уйдёт дважды
    if (
        history
        and history[-1].get("role") == "user"
        and (history[-1].get("content") or "").strip() == (user_text or "").strip()
    ):
        history = history[:-1]

    if stream and on_token is None and verbose:
        on_token = lambda t: print(t, end="", flush=True)  # noqa: E731
    if on_status is None and verbose:
        on_status = _cli_status_printer(verbose)

    try:
        installed = set(installed_models())
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Ollama недоступна: {exc}") from exc
    available = available_tiers(installed)
    if not available:
        raise RuntimeError("Нет установленных моделей оркестра")

    if force_tier:
        if force_tier not in ALL_TIERS:
            raise ValueError(f"Неизвестный tier: {force_tier}")
        if force_tier not in available:
            raise ValueError(
                f"Модель {MODELS[force_tier]} не установлена. "
                f"Установите: ollama pull {MODELS[force_tier]}"
            )
        # Ручной тир — без LLM-роутера
        decision = RouteDecision(
            ok=True,
            tier=force_tier,
            need_web=need_web(user_text),
            reason=f"forced:{force_tier}",
            reply="",
        )
    else:
        decision = route(user_text)
        if decision.ok:
            fitted = _fit_tier(decision.tier, available)
            if fitted != decision.tier:
                decision = RouteDecision(
                    decision.ok,
                    fitted,
                    decision.need_web,
                    f"{decision.reason}+fit:{fitted}",
                    decision.reply if fitted == "tiny" else "",
                )

    _emit(
        on_status,
        "route",
        ok=decision.ok,
        tier=decision.tier,
        need_web=decision.need_web,
        reason=decision.reason,
        model=MODELS.get(decision.tier, MODELS["tiny"]),
    )

    if not decision.ok:
        text = decision.reply or "Не понял запрос. Переформулируйте, пожалуйста."
        _emit_token(on_token, text)
        if stream and verbose:
            print()
        return OrchestraResult(
            text=text,
            tier="tiny",
            model=MODELS["tiny"],
            need_web=False,
            route_reason=decision.reason,
            checked=False,
        )

    start_tier: Tier = decision.tier

    # Короткий ответ роутера — тоже под проверкой; не прошёл → идём к воркеру
    if decision.tier == "tiny" and decision.reply:
        verdict = selfcheck.check(
            user_text, decision.reply, model=None, expect_detail=False, use_llm=False
        )
        _emit(
            on_status,
            "selfcheck",
            ok=verdict.ok,
            problems=verdict.problems,
            attempt=1,
            model=MODELS["tiny"],
        )
        if verdict.ok:
            _emit_token(on_token, decision.reply)
            if stream and verbose:
                print()
            return OrchestraResult(
                text=decision.reply,
                tier="tiny",
                model=MODELS["tiny"],
                need_web=False,
                route_reason=decision.reason,
            )
        mid = _fit_tier("mid", available)
        _emit(
            on_status,
            "retry",
            attempt=2,
            problems=verdict.problems,
            from_model=MODELS["tiny"],
            to_model=MODELS[mid],
        )
        decision = RouteDecision(
            True, mid, decision.need_web, decision.reason + " +recheck", ""
        )

    tier: Tier = decision.tier
    retry_hint: str | None = None
    attempts: list[_Attempt] = []
    tool_cache: dict[str, str] = {}
    ctx_plan = plan_worker_context(user_text, history, tier)
    _emit_context(on_status, ctx_plan, tier)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        model = MODELS[tier]
        # При эскалации на сложный тир пересчитываем ctx (tiny/mid → xlarge)
        if attempt > 1:
            ctx_plan = plan_worker_context(user_text, history, tier)
            _emit_context(on_status, ctx_plan, tier)
        _emit(
            on_status,
            "worker",
            model=model,
            need_web=decision.need_web,
            tier=tier,
            attempt=attempt,
            num_ctx=ctx_plan.num_ctx,
            used_history=ctx_plan.use_history,
        )

        if decision.need_web:
            text = _worker_with_tools(
                model,
                user_text,
                ctx_plan.history,
                on_status=on_status,
                verbose=verbose,
                retry_hint=retry_hint,
                num_ctx=ctx_plan.num_ctx,
                tool_cache=tool_cache,
            )
            _emit_token(on_token, text)
        else:
            text = _worker_plain(
                model,
                user_text,
                ctx_plan.history,
                stream=stream,
                on_token=on_token,
                retry_hint=retry_hint,
                num_ctx=ctx_plan.num_ctx,
            )

        # LLM-ревью и на последней попытке — иначе checked врёт
        verdict = selfcheck.check(
            user_text,
            text,
            model=SELFCHECK_MODEL if SELFCHECK_MODEL in installed else None,
            expect_detail=tier != "tiny",
            use_llm=SELFCHECK_LLM,
        )
        attempts.append(
            _Attempt(text=text, verdict=verdict, tier=tier, model=model, ctx=ctx_plan)
        )
        _emit(
            on_status,
            "selfcheck",
            ok=verdict.ok,
            problems=verdict.problems,
            note=verdict.note,
            attempt=attempt,
            model=model,
            checked=verdict.checked,
        )

        if verdict.ok or attempt == MAX_ATTEMPTS:
            break

        next_tier = _next_tier(tier, available)
        if next_tier is None or next_tier == tier:
            break

        _emit(
            on_status,
            "retry",
            attempt=attempt + 1,
            problems=verdict.problems,
            reason=verdict.summary(),
            from_model=model,
            to_model=MODELS[next_tier],
        )
        retry_hint = verdict.hint
        tier = next_tier

    best = _best_attempt(attempts)
    if best is not attempts[-1]:
        # показанный текст хуже более раннего — возвращаем лучший
        _emit(on_status, "restore", model=best.model, tier=best.tier)
        _emit_token(on_token, best.text)

    if stream and verbose:
        print()

    return OrchestraResult(
        text=best.text,
        tier=best.tier,
        model=best.model,
        need_web=decision.need_web,
        route_reason=decision.reason,
        escalated=_escalated(start_tier, best.tier),
        attempts=len(attempts),
        checked=best.verdict.checked,
        problems=list(best.verdict.problems),
        num_ctx=best.ctx.num_ctx,
        used_history=best.ctx.use_history,
        context_reason=best.ctx.reason,
    )
