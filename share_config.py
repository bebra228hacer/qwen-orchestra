"""Эндпоинт для --share: статический публичный IP + один открытый порт.

Файл share.json рядом с settings.json (корень репо при разработке).
Не коммитить — личный IP/порт.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from qwen_orchestra import settings as app_settings

DEFAULT_LOCAL_PORT = 8787
# Ваш статический эндпоинт (fallback, если share.json пуст/нет)
DEFAULT_PUBLIC_IP = "109.195.163.20"
DEFAULT_SHARE_PORT = 25565


def share_config_path() -> Path:
    return app_settings.get_settings_path().parent / "share.json"


def load_share_config() -> dict[str, Any]:
    path = share_config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_share_config(updates: dict[str, Any]) -> dict[str, Any]:
    path = share_config_path()
    data = load_share_config()
    for key, value in updates.items():
        if value is None or value == "":
            data.pop(key, None)
        else:
            data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def detect_public_ip(timeout: float = 4.0) -> str | None:
    """Внешний IPv4 (для статического IP обычно совпадает с конфигом)."""
    urls = (
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
        "https://icanhazip.com",
    )
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                ip = resp.read().decode("utf-8", errors="replace").strip()
            if ip and " " not in ip and "." in ip and len(ip) <= 45:
                return ip
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            continue
    return None


def configured_public_ip() -> str:
    env = os.environ.get("QWEN_PUBLIC_IP", "").strip()
    if env:
        return env
    cfg = load_share_config()
    raw = str(cfg.get("public_ip") or "").strip()
    return raw or DEFAULT_PUBLIC_IP


def ip_is_locked() -> bool:
    """Не перезаписывать IP автодетектом (VPN иначе подменит выходной адрес)."""
    env = os.environ.get("QWEN_PUBLIC_IP", "").strip()
    if env:
        return True
    cfg = load_share_config()
    if cfg.get("static") is False:
        return False
    # По умолчанию: раз IP уже в конфиге или задан DEFAULT — считаем статическим
    return True


def configured_share_port() -> int | None:
    env = os.environ.get("QWEN_PUBLIC_PORT", "").strip() or os.environ.get(
        "QWEN_SHARE_PORT", ""
    ).strip()
    if env.isdigit():
        n = int(env)
        if 1 <= n <= 65535:
            return n
    cfg = load_share_config()
    raw = cfg.get("port")
    if isinstance(raw, int) and 1 <= raw <= 65535:
        return raw
    if isinstance(raw, str) and raw.strip().isdigit():
        n = int(raw.strip())
        if 1 <= n <= 65535:
            return n
    if 1 <= DEFAULT_SHARE_PORT <= 65535:
        return DEFAULT_SHARE_PORT
    return None


def ensure_public_ip(refresh: bool = True) -> str | None:
    """IP для ссылки гостю. Зафиксированный (static) не трогаем — VPN его не перебьёт."""
    current = configured_public_ip()
    if current and ip_is_locked():
        # держим share.json в синхроне с известным IP/портом
        cfg = load_share_config()
        if cfg.get("public_ip") != current or cfg.get("port") != configured_share_port():
            save_share_config(
                {
                    "public_ip": current,
                    "port": configured_share_port(),
                    "static": True,
                }
            )
        return current
    if current and not refresh:
        return current
    detected = detect_public_ip()
    if detected:
        if detected != current:
            save_share_config({"public_ip": detected})
        return detected
    return current or None


def resolve_share_port(cli_port: int = 0) -> int:
    """Порт для share: CLI > env/config > DEFAULT_LOCAL_PORT."""
    if cli_port > 0:
        return cli_port
    cfg_port = configured_share_port()
    if cfg_port is not None:
        return cfg_port
    env_listen = os.environ.get("QWEN_PORT", "").strip()
    if env_listen.isdigit():
        n = int(env_listen)
        if 1 <= n <= 65535:
            return n
    return DEFAULT_LOCAL_PORT


def guest_url(public_ip: str | None = None, port: int | None = None) -> str | None:
    ip = (public_ip or configured_public_ip() or "").strip()
    p = port if port is not None else configured_share_port()
    if not ip or not p:
        return None
    return f"http://{ip}:{p}"


def remember_share_endpoint(public_ip: str | None, port: int | None) -> None:
    updates: dict[str, Any] = {}
    if public_ip:
        updates["public_ip"] = public_ip.strip()
    if port is not None and 1 <= int(port) <= 65535:
        updates["port"] = int(port)
    if updates:
        save_share_config(updates)
