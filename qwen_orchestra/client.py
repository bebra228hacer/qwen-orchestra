"""Публичный in-process клиент оркестра для других Python-приложений."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from . import settings as app_settings
from .llm import get_ollama_host, installed_models, set_ollama_host
from .orchestra import (
    MODELS,
    OrchestraResult,
    handle,
    missing_models,
    missing_optional_models,
)
from .router import RouteDecision, Tier, route as route_fn
from .selfcheck import Verdict

StatusCallback = Callable[[str, dict[str, Any]], None]
TokenCallback = Callable[[str], None]


class Client:
    """Локальный SDK: роутинг + оркестр + настройки поверх Ollama / OpenRouter."""

    def __init__(
        self,
        *,
        ollama_host: str | None = None,
        settings_path: str | Path | None = None,
    ) -> None:
        if ollama_host:
            set_ollama_host(ollama_host)
        if settings_path is not None:
            app_settings.set_settings_path(settings_path)
        app_settings.bootstrap()

    @property
    def ollama_host(self) -> str:
        return get_ollama_host()

    @property
    def settings_path(self) -> Path:
        return app_settings.get_settings_path()

    def ready(self) -> bool:
        """Ollama отвечает на /api/tags."""
        try:
            installed_models()
            return True
        except Exception:  # noqa: BLE001
            return False

    def health(self) -> dict[str, Any]:
        """Снимок как у GET /api/health (без HTTP)."""
        app_settings.ensure_bootstrapped()
        ollama_ok = False
        models: list[str] = []
        missing: list[str] = []
        missing_optional: list[str] = []
        error: str | None = None
        router_missing = False
        cfg = app_settings.get_settings()
        try:
            models = installed_models()
            have = set(models)
            ollama_ok = True
            missing = missing_models(have)
            missing_optional = missing_optional_models(have)
            router_name = cfg.router_model
            if router_name and router_name not in have:
                router_missing = not any(
                    m == router_name or m.startswith(router_name + ":") for m in have
                )
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            have: set[str] = set()
            missing = missing_models(have)
            missing_optional = missing_optional_models(have)
            router_missing = True
        return {
            "ok": not missing,
            "ollama": ollama_ok,
            "models": models,
            "missing": missing,
            "missing_optional": missing_optional,
            "router_model": cfg.router_model,
            "router_missing": router_missing,
            "tiers": dict(MODELS),
            "slots": [s.to_dict() for s in cfg.slots],
            "providers": {"openrouter": app_settings.openrouter_status()},
            "error": error,
        }

    def route(self, user_text: str) -> RouteDecision:
        """Только роутинг (без генерации воркера)."""
        return route_fn(user_text)

    def ask(
        self,
        user_text: str,
        history: list[dict] | None = None,
        *,
        force_tier: Tier | None = None,
        stream: bool = True,
        on_token: TokenCallback | None = None,
        on_status: StatusCallback | None = None,
    ) -> OrchestraResult:
        """Полный цикл оркестра. По умолчанию без print в stdout."""
        return handle(
            user_text,
            history,
            force_tier=force_tier,
            stream=stream,
            verbose=False,
            on_token=on_token,
            on_status=on_status,
        )

    def get_settings(self) -> dict[str, Any]:
        app_settings.ensure_bootstrapped()
        return app_settings.public_settings_payload()

    def update_settings(
        self,
        slots: list[dict[str, Any]],
        *,
        router_model: str | None = None,
    ) -> dict[str, Any]:
        app_settings.ensure_bootstrapped()
        app_settings.update_settings(slots, router_model=router_model)
        return app_settings.public_settings_payload()

    def reset_settings(self) -> dict[str, Any]:
        app_settings.reset_settings()
        return app_settings.public_settings_payload()

    def add_slot(
        self,
        *,
        model: str,
        label: str | None = None,
        router_prompt: str | None = None,
        slot_id: str | None = None,
        tier: str | None = None,
        rank: int | None = None,
        router_auto: bool | None = None,
        provider: str = "ollama",
    ) -> dict[str, Any]:
        """Назначить модель на фиксированный тир (`tier` или устаревший `slot_id`)."""
        app_settings.ensure_bootstrapped()
        app_settings.add_slot(
            model=model,
            label=label,
            router_prompt=router_prompt,
            slot_id=slot_id,
            tier=tier,
            rank=rank,
            router_auto=router_auto,
            provider=provider,
        )
        return app_settings.public_settings_payload()

    def delete_slot(self, slot_id: str) -> dict[str, Any]:
        app_settings.ensure_bootstrapped()
        app_settings.delete_slot(slot_id)
        return app_settings.public_settings_payload()

    def set_openrouter_api_key(self, api_key: str | None) -> dict[str, Any]:
        """Сохранить или очистить (None) ключ OpenRouter в secrets.json."""
        app_settings.ensure_bootstrapped()
        app_settings.set_openrouter_api_key(api_key)
        return app_settings.public_settings_payload()


__all__ = [
    "Client",
    "OrchestraResult",
    "RouteDecision",
    "Tier",
    "Verdict",
]
