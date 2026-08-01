"""Запуск веб-чата: одна консоль — сервер + открытие браузера."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8787
URL = f"http://{HOST}:{PORT}"
READY = f"{URL}/api/ready"


def _root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _python() -> str:
    """Интерпретатор для server.py (не сам .exe лаунчера)."""
    if not getattr(sys, "frozen", False):
        return sys.executable
    for name in ("python", "python3", "py"):
        found = shutil.which(name)
        if found:
            return found
    raise FileNotFoundError(
        "Python не найден в PATH. Установите Python или запускайте QwenChat.bat"
    )


def healthy() -> bool:
    """Сервер принял соединение (не ждём Ollama)."""
    try:
        with urllib.request.urlopen(READY, timeout=1.0) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def wait_ready(seconds: float = 45.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if healthy():
            return True
        time.sleep(0.25)
    return False


def open_browser(url: str) -> bool:
    """Надёжное открытие URL в браузере по умолчанию (Windows)."""
    errors: list[str] = []

    if sys.platform == "win32":
        # 1) Ассоциация Windows — самый надёжный способ для http(s)
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            return True
        except OSError as exc:
            errors.append(f"startfile: {exc}")

        # 2) cmd start (пустой заголовок окна обязателен)
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError as exc:
            errors.append(f"cmd start: {exc}")

    try:
        if webbrowser.open(url, new=2):
            return True
        errors.append("webbrowser.open returned False")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"webbrowser: {exc}")

    print("Не удалось открыть браузер автоматически.")
    for e in errors:
        print(f"  - {e}")
    print(f"Откройте вручную: {url}")
    return False


def main() -> int:
    root = _root()
    server_py = root / "server.py"

    if healthy():
        print(f"Сервер уже запущен: {URL}")
        open_browser(URL)
        print(f"Браузер: {URL}")
        return 0

    if not server_py.is_file():
        print(f"Не найден server.py рядом с лаунчером:\n  {server_py}")
        input("Enter — выход...")
        return 1

    try:
        py = _python()
    except FileNotFoundError as exc:
        print(exc)
        input("Enter — выход...")
        return 1

    cmd = [py, str(server_py)]
    if Path(py).name.lower() in {"py.exe", "py"}:
        cmd = [py, "-3", str(server_py)]

    print(f"Запуск сервера: {URL}")
    print("Остановка: Ctrl+C")
    print()

    proc = subprocess.Popen(cmd, cwd=str(root))

    if not wait_ready():
        print("Сервер не ответил вовремя. Проверьте:")
        print("  pip install -r requirements.txt")
        if proc.poll() is not None:
            print(f"Процесс завершился с кодом {proc.returncode}")
        else:
            proc.terminate()
        input("Enter — выход...")
        return 1

    open_browser(URL)
    print(f"Браузер: {URL}")
    print()

    try:
        return int(proc.wait() or 0)
    except KeyboardInterrupt:
        print("\nОстановка…")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
