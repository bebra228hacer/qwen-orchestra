"""Локальный веб-сервер: Cursor-like UI + оркестр (только 127.0.0.1)."""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Any, Iterator

import urllib.error

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from qwen_orchestra.llm import installed_models
from qwen_orchestra.metrics import collect as collect_metrics
from qwen_orchestra.orchestra import MODELS, handle, missing_models, missing_optional_models
from qwen_orchestra import settings as app_settings

app_settings.ensure_bootstrapped()

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
ALLOWED_HOSTS = frozenset(
    {
        "127.0.0.1",
        "localhost",
        "127.0.0.1:8787",
        "localhost:8787",
        "[::1]",
        "[::1]:8787",
    }
)
SSE_QUEUE_MAX = 512
MAX_MESSAGE_CHARS = 100_000

app = FastAPI(title="Qwen Orchestra Chat", docs_url=None, redoc_url=None)


class ChatMessage(BaseModel):
    role: str
    content: str
    meta: dict[str, Any] | None = None


class ChatSession(BaseModel):
    id: str
    title: str
    created_at: float
    updated_at: float
    messages: list[ChatMessage] = Field(default_factory=list)
    generation: int = 0


class CreateChatBody(BaseModel):
    title: str | None = None


class SendMessageBody(BaseModel):
    content: str
    force_tier: str | None = None


class SettingsPutBody(BaseModel):
    slots: list[dict[str, Any]]
    router_model: str | None = None


class AddSlotBody(BaseModel):
    model: str
    label: str | None = None
    router_prompt: str | None = None
    id: str | None = None
    rank: int = 2
    router_auto: bool = True
    provider: str = "ollama"


class OpenRouterKeyBody(BaseModel):
    api_key: str | None = None
    clear: bool = False


_chats: dict[str, ChatSession] = {}
_lock = threading.Lock()
# Один активный ответ на чат — иначе гонка истории при параллельных POST
_chat_workers: dict[str, threading.Lock] = {}


def _now() -> float:
    return time.time()


def _title_from(text: str) -> str:
    t = " ".join(text.strip().split())
    if not t:
        return "New Chat"
    return t[:48] + ("…" if len(t) > 48 else "")


def _chat_summary(chat: ChatSession) -> dict[str, Any]:
    return {
        "id": chat.id,
        "title": chat.title,
        "created_at": chat.created_at,
        "updated_at": chat.updated_at,
        "message_count": len(chat.messages),
    }


def _result_meta(result: Any) -> dict[str, Any]:
    return {
        "tier": result.tier,
        "model": result.model,
        "need_web": result.need_web,
        "route_reason": result.route_reason,
        "escalated": result.escalated,
        "attempts": result.attempts,
        "checked": result.checked,
        "problems": result.problems,
        "num_ctx": result.num_ctx,
        "used_history": result.used_history,
        "context_reason": result.context_reason,
    }


def _worker_lock(chat_id: str) -> threading.Lock:
    with _lock:
        lock = _chat_workers.get(chat_id)
        if lock is None:
            lock = threading.Lock()
            _chat_workers[chat_id] = lock
        return lock


@app.middleware("http")
async def localhost_host_guard(request: Request, call_next):  # noqa: ANN001
    """Защита от DNS rebinding: принимаем только localhost Host."""
    host = (request.headers.get("host") or "").strip().lower()
    if host and host not in ALLOWED_HOSTS:
        return JSONResponse({"detail": "Forbidden host"}, status_code=403)
    origin = (request.headers.get("origin") or "").strip().lower()
    if origin and request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        # browser Origin вида http://127.0.0.1:8787
        allowed_origins = {
            "http://127.0.0.1:8787",
            "http://localhost:8787",
            "http://[::1]:8787",
            "null",  # file:// / некоторые локальные кейсы
        }
        if origin not in allowed_origins:
            return JSONResponse({"detail": "Forbidden origin"}, status_code=403)
    return await call_next(request)


@app.get("/api/ready")
def ready() -> dict[str, bool]:
    """Быстрый ping для лаунчера (без обращения к Ollama)."""
    return {"ok": True}


@app.get("/api/health")
def health() -> dict[str, Any]:
    ollama_ok = False
    models: list[str] = []
    missing: list[str] = []
    missing_optional: list[str] = []
    error: str | None = None
    router_missing = False
    try:
        models = installed_models()
        have = set(models)
        ollama_ok = True
        missing = missing_models(have)
        missing_optional = missing_optional_models(have)
        router_name = app_settings.get_settings().router_model
        if router_name and router_name not in have:
            # точное имя или префикс тега
            router_missing = not any(
                m == router_name or m.startswith(router_name + ":") for m in have
            )
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    or_status = app_settings.openrouter_status()
    return {
        "ok": ollama_ok and not missing,
        "ollama": ollama_ok,
        "models": models,
        "missing": missing,
        "missing_optional": missing_optional,
        "router_model": app_settings.get_settings().router_model,
        "router_missing": router_missing,
        "tiers": MODELS,
        "slots": [s.to_dict() for s in app_settings.get_settings().slots],
        "providers": {"openrouter": or_status},
        "error": error,
    }


@app.get("/api/metrics")
def metrics() -> dict[str, Any]:
    """CPU / RAM / GPU / загруженные в Ollama модели (для правой панели)."""
    return collect_metrics()


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return app_settings.public_settings_payload()


@app.put("/api/settings")
def put_settings(body: SettingsPutBody) -> dict[str, Any]:
    try:
        saved = app_settings.update_settings(body.slots, router_model=body.router_model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return app_settings.public_settings_payload(saved)


@app.post("/api/settings/reset")
def reset_settings() -> dict[str, Any]:
    saved = app_settings.reset_settings()
    return app_settings.public_settings_payload(saved)


@app.post("/api/settings/slots")
def add_settings_slot(body: AddSlotBody) -> dict[str, Any]:
    try:
        saved = app_settings.add_slot(
            model=body.model,
            label=body.label,
            router_prompt=body.router_prompt,
            slot_id=body.id,
            rank=body.rank,
            router_auto=body.router_auto,
            provider=body.provider,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return app_settings.public_settings_payload(saved)


@app.put("/api/settings/providers/openrouter")
def put_openrouter_key(body: OpenRouterKeyBody) -> dict[str, Any]:
    """Сохранить или очистить OpenRouter API key (secrets.json)."""
    if body.clear or not (body.api_key or "").strip():
        if body.clear or body.api_key is not None:
            app_settings.set_openrouter_api_key(None)
        else:
            raise HTTPException(status_code=400, detail="Укажите api_key или clear=true")
    else:
        app_settings.set_openrouter_api_key(body.api_key)
    return app_settings.public_settings_payload()


@app.delete("/api/settings/slots/{slot_id}")
def delete_settings_slot(slot_id: str) -> dict[str, Any]:
    try:
        saved = app_settings.delete_slot(slot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Слот не найден: {slot_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return app_settings.public_settings_payload(saved)


@app.get("/api/chats")
def list_chats() -> list[dict[str, Any]]:
    with _lock:
        chats = sorted(_chats.values(), key=lambda c: c.updated_at, reverse=True)
        return [_chat_summary(c) for c in chats]


@app.post("/api/chats")
def create_chat(body: CreateChatBody | None = None) -> dict[str, Any]:
    body = body or CreateChatBody()
    chat_id = uuid.uuid4().hex[:12]
    ts = _now()
    chat = ChatSession(
        id=chat_id,
        title=(body.title or "New Chat").strip() or "New Chat",
        created_at=ts,
        updated_at=ts,
    )
    with _lock:
        _chats[chat_id] = chat
    return _chat_summary(chat)


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: str) -> dict[str, Any]:
    with _lock:
        chat = _chats.get(chat_id)
        if not chat:
            raise HTTPException(404, "Chat not found")
        return {
            **_chat_summary(chat),
            "messages": [m.model_dump() for m in chat.messages],
        }


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str) -> dict[str, str]:
    wlock = _worker_lock(chat_id)
    if not wlock.acquire(blocking=False):
        raise HTTPException(409, "Дождитесь ответа на предыдущее сообщение в этом чате")
    try:
        with _lock:
            if chat_id not in _chats:
                raise HTTPException(404, "Chat not found")
            del _chats[chat_id]
            _chat_workers.pop(chat_id, None)
        return {"status": "ok"}
    finally:
        wlock.release()


@app.post("/api/chats/{chat_id}/clear")
def clear_chat(chat_id: str) -> dict[str, Any]:
    wlock = _worker_lock(chat_id)
    if not wlock.acquire(blocking=False):
        raise HTTPException(409, "Дождитесь ответа на предыдущее сообщение в этом чате")
    try:
        with _lock:
            chat = _chats.get(chat_id)
            if not chat:
                raise HTTPException(404, "Chat not found")
            chat.messages.clear()
            chat.title = "New Chat"
            chat.updated_at = _now()
            chat.generation += 1
            return _chat_summary(chat)
    finally:
        wlock.release()


def _sse(event: str, data: dict[str, Any] | str) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _q_put(q: Queue, item: tuple[str, Any] | None) -> None:
    """Неблокирующая запись: при переполнении вытесняем старые token-события."""
    while True:
        try:
            q.put(item, block=False)
            return
        except Full:
            try:
                q.get_nowait()
            except Empty:
                return


@app.post("/api/chats/{chat_id}/messages")
def send_message(chat_id: str, body: SendMessageBody) -> StreamingResponse:
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(400, "Empty message")
    if len(content) > MAX_MESSAGE_CHARS:
        raise HTTPException(400, f"Сообщение слишком длинное (>{MAX_MESSAGE_CHARS})")

    wlock = _worker_lock(chat_id)
    if not wlock.acquire(blocking=False):
        raise HTTPException(409, "Дождитесь ответа на предыдущее сообщение в этом чате")

    try:
        with _lock:
            chat = _chats.get(chat_id)
            if not chat:
                wlock.release()
                raise HTTPException(404, "Chat not found")
            history = [
                {"role": m.role, "content": m.content}
                for m in chat.messages
                if m.role in {"user", "assistant"}
            ]
            if chat.title == "New Chat":
                chat.title = _title_from(content)
            chat.messages.append(ChatMessage(role="user", content=content))
            chat.updated_at = _now()
            generation = chat.generation
    except HTTPException:
        raise
    except Exception:
        wlock.release()
        raise

    q: Queue[tuple[str, Any] | None] = Queue(maxsize=SSE_QUEUE_MAX)

    def on_token(token: str) -> None:
        _q_put(q, ("token", {"text": token}))

    def on_status(event: str, payload: dict[str, Any]) -> None:
        if event == "route":
            _q_put(
                q,
                (
                    "meta",
                    {
                        "tier": payload.get("tier"),
                        "model": payload.get("model"),
                        "need_web": payload.get("need_web"),
                        "route_reason": payload.get("reason"),
                        "ok": payload.get("ok"),
                    },
                ),
            )
        elif event == "tool":
            _q_put(
                q,
                (
                    "tool",
                    {
                        "name": payload.get("name"),
                        "arguments": payload.get("arguments"),
                        "model": payload.get("model"),
                    },
                ),
            )
        elif event == "worker":
            _q_put(
                q,
                (
                    "meta",
                    {
                        "tier": payload.get("tier"),
                        "model": payload.get("model"),
                        "need_web": payload.get("need_web"),
                        "phase": "worker",
                        "num_ctx": payload.get("num_ctx"),
                        "used_history": payload.get("used_history"),
                    },
                ),
            )
        elif event == "context":
            _q_put(
                q,
                (
                    "meta",
                    {
                        "phase": "context",
                        "num_ctx": payload.get("num_ctx"),
                        "used_history": payload.get("used_history"),
                        "context_reason": payload.get("reason"),
                        "history_messages": payload.get("history_messages"),
                        "tier": payload.get("tier"),
                    },
                ),
            )
        elif event == "selfcheck":
            _q_put(
                q,
                (
                    "check",
                    {
                        "ok": payload.get("ok"),
                        "problems": payload.get("problems") or [],
                        "note": payload.get("note") or "",
                        "attempt": payload.get("attempt"),
                        "model": payload.get("model"),
                        "checked": payload.get("checked"),
                    },
                ),
            )
        elif event == "retry":
            _q_put(
                q,
                (
                    "meta",
                    {
                        "phase": "retry",
                        "from_model": payload.get("from_model"),
                        "model": payload.get("to_model"),
                        "attempt": payload.get("attempt"),
                        "problems": payload.get("problems") or [],
                        "escalated": True,
                    },
                ),
            )
        elif event == "restore":
            _q_put(
                q,
                (
                    "meta",
                    {
                        "phase": "restore",
                        "model": payload.get("model"),
                        "tier": payload.get("tier"),
                        "problems": [],
                    },
                ),
            )

    def worker() -> None:
        try:
            result = handle(
                content,
                history,
                force_tier=body.force_tier,
                stream=True,
                verbose=False,
                on_token=on_token,
                on_status=on_status,
            )
            meta = _result_meta(result)
            with _lock:
                c = _chats.get(chat_id)
                if c is not None and c.generation == generation:
                    c.messages.append(
                        ChatMessage(
                            role="assistant",
                            content=result.text,
                            meta=meta,
                        )
                    )
                    c.updated_at = _now()
            _q_put(q, ("done", {"text": result.text, **meta}))
        except urllib.error.URLError as exc:
            _q_put(q, ("error", {"message": f"Ollama недоступна: {exc}"}))
        except Exception as exc:  # noqa: BLE001
            _q_put(q, ("error", {"message": str(exc)}))
        finally:
            wlock.release()
            _q_put(q, None)

    threading.Thread(target=worker, daemon=True).start()

    def event_stream() -> Iterator[str]:
        while True:
            try:
                item = q.get(timeout=600)
            except Empty:
                yield _sse("error", {"message": "Timeout"})
                break
            if item is None:
                break
            event, data = item
            yield _sse(event, data)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def main() -> None:
    import uvicorn

    uvicorn.run(
        "server:app",
        host="127.0.0.1",
        port=8787,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
