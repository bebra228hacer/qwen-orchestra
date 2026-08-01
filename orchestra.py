"""Оркестр: tiny (0.5b) -> mid (3b) -> heavy (7b) с вебом и самопроверкой.

Цикл одного запроса:
    route -> worker -> selfcheck -> (retry на старшем тире) -> ответ

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
from router import RouteDecision, Tier, route
from selfcheck import Verdict
from tools_web import TOOL_IMPL, TOOLS

MODELS: dict[Tier, str] = {
    "tiny": "qwen2.5:0.5b",
    "mid": "qwen2.5:3b",
    "heavy": "qwen2.5:7b",
}

TIER_ORDER: list[Tier] = ["tiny", "mid", "heavy"]
MAX_TOOL_ROUNDS = 4

# Сколько всего попыток на один запрос (1 основная + повторы после самопроверки)
MAX_ATTEMPTS = 3
# LLM-ревью ответа (ловит ошибки и уход от вопроса); проверяющий — 3b
SELFCHECK_LLM = True
SELFCHECK_MODEL = MODELS["mid"]

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

StatusCallback = Callable[[str, dict[str, Any]], None]
TokenCallback = Callable[[str], None]


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


def missing_models() -> list[str]:
    have = set(installed_models())
    need = list(MODELS.values())
    return [m for m in need if m not in have and f"{m}" not in have]


def _emit(on_status: StatusCallback | None, event: str, **payload: Any) -> None:
    if on_status:
        on_status(event, payload)


def _emit_token(on_token: TokenCallback | None, text: str) -> None:
    if on_token and text:
        on_token(text)


def _next_tier(tier: Tier) -> Tier:
    idx = TIER_ORDER.index(tier)
    return TIER_ORDER[min(idx + 1, len(TIER_ORDER) - 1)]


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
    for h in history[-8:]:
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
) -> str:
    messages = _build_messages(user_text, history, retry_hint)

    for _ in range(MAX_TOOL_ROUNDS):
        msg = chat(
            model,
            messages,
            tools=TOOLS,
            temperature=0.3,
            num_ctx=8192,
            keep_alive="10m",
        )
        content = (msg.get("content") or "").strip()
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            tool_calls = _fallback_tools(content)
        if not tool_calls:
            return content or "(пустой ответ)"

        messages.append(msg)
        for call in tool_calls:
            fn = call.get("function") or {}
            name = fn.get("name") or ""
            args = fn.get("arguments") or {}
            _emit(on_status, "tool", name=name, arguments=args, model=model)
            if verbose:
                print(f"  [tool/{model}] {name}({args})", flush=True)
            result = _run_tool(name, args)
            if verbose:
                preview = result if len(result) < 350 else result[:350] + "..."
                print(f"  <- {preview}\n", flush=True)
            messages.append({"role": "tool", "content": result})

    msg = chat(model, messages, temperature=0.3, num_ctx=8192, keep_alive="10m")
    return (msg.get("content") or "").strip() or "(пустой ответ)"


def _worker_plain(
    model: str,
    user_text: str,
    history: list[dict],
    *,
    stream: bool,
    on_token: TokenCallback | None,
    retry_hint: str | None = None,
) -> str:
    messages = _build_messages(user_text, history, retry_hint)

    if stream:
        return chat_stream(
            model,
            messages,
            on_token=on_token,
            temperature=0.3,
            num_ctx=8192,
            keep_alive="10m",
        )

    msg = chat(model, messages, temperature=0.3, num_ctx=8192, keep_alive="10m")
    return (msg.get("content") or "").strip() or "(пустой ответ)"


@dataclass
class _Attempt:
    text: str
    verdict: Verdict
    tier: Tier
    model: str


def _best_attempt(attempts: list[_Attempt]) -> _Attempt:
    """Прошедшая проверку попытка, иначе — с наименее серьёзными проблемами."""
    for a in attempts:
        if a.verdict.ok:
            return a
    return min(attempts, key=lambda a: (a.verdict.severity(), -len(a.text)))


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
            print(f"  [worker] {payload.get('model')}{web}{suffix}", flush=True)
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

    if stream and on_token is None and verbose:
        on_token = lambda t: print(t, end="", flush=True)  # noqa: E731
    if on_status is None and verbose:
        on_status = _cli_status_printer(verbose)

    decision = route(user_text)
    if force_tier:
        decision = RouteDecision(
            ok=True,
            tier=force_tier,
            need_web=decision.need_web,
            reason=f"forced:{force_tier}",
            reply="",
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
        _emit(
            on_status,
            "retry",
            attempt=2,
            problems=verdict.problems,
            from_model=MODELS["tiny"],
            to_model=MODELS["mid"],
        )
        decision = RouteDecision(True, "mid", decision.need_web, decision.reason + " +recheck", "")

    tier: Tier = decision.tier
    retry_hint: str | None = None
    attempts: list[_Attempt] = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        model = MODELS[tier]
        _emit(
            on_status,
            "worker",
            model=model,
            need_web=decision.need_web,
            tier=tier,
            attempt=attempt,
        )

        if decision.need_web:
            text = _worker_with_tools(
                model,
                user_text,
                history,
                on_status=on_status,
                verbose=verbose,
                retry_hint=retry_hint,
            )
            _emit_token(on_token, text)
        else:
            text = _worker_plain(
                model,
                user_text,
                history,
                stream=stream,
                on_token=on_token,
                retry_hint=retry_hint,
            )

        verdict = selfcheck.check(
            user_text,
            text,
            model=SELFCHECK_MODEL,
            expect_detail=tier != "tiny",
            use_llm=SELFCHECK_LLM and attempt < MAX_ATTEMPTS,
        )
        attempts.append(_Attempt(text=text, verdict=verdict, tier=tier, model=model))
        _emit(
            on_status,
            "selfcheck",
            ok=verdict.ok,
            problems=verdict.problems,
            note=verdict.note,
            attempt=attempt,
            model=model,
        )

        if verdict.ok or attempt == MAX_ATTEMPTS:
            break

        next_tier = _next_tier(tier)
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
        escalated=TIER_ORDER.index(best.tier) > TIER_ORDER.index(start_tier),
        attempts=len(attempts),
        checked=best.verdict.ok,
        problems=list(best.verdict.problems),
    )
