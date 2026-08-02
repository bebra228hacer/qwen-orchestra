"""Запуск веб-чата: Ollama (если нужно) + сервер + открытие браузера.

Ollama, поднятая этим лаунчером, останавливается вместе с сервером/консолью.
Уже работавшую до запуска Ollama не трогаем.

Режимы доступа:
  локальный (по умолчанию) — только этот ПК;
  --share — 0.0.0.0 (LAN / проброшенный порт), опционально --token.
"""

from __future__ import annotations

import atexit
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
OLLAMA_TAGS = "http://127.0.0.1:11434/api/tags"

# Процессы, которые лаунчер обязан погасить при выходе
_owned_ollama: subprocess.Popen | None = None
_owned_server: subprocess.Popen | None = None
_cleanup_done = False


def _share_config():
    import share_config

    return share_config


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


def _ready_url(port: int) -> str:
    return f"http://{DEFAULT_HOST}:{port}/api/ready"


def healthy(port: int = DEFAULT_PORT) -> bool:
    """Сервер принял соединение (не ждём Ollama)."""
    try:
        with urllib.request.urlopen(_ready_url(port), timeout=1.0) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def ollama_up() -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_TAGS, timeout=1.5) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _ollama_exe() -> Path | None:
    """Путь к ollama.exe: PATH, затем типичная установка Windows."""
    found = shutil.which("ollama")
    if found:
        return Path(found)
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    if local.is_file():
        return local
    pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Ollama" / "ollama.exe"
    if pf.is_file():
        return pf
    return None


def _kill_process_tree(proc: subprocess.Popen | None, label: str) -> None:
    if proc is None or proc.poll() is not None:
        return
    pid = proc.pid
    print(f"Остановка {label} (pid={pid})…")
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        try:
            proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            pass
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=3)
        except (subprocess.TimeoutExpired, OSError):
            pass
    except OSError:
        pass


def cleanup_owned() -> None:
    """Гасим сервер и Ollama, если их поднял этот лаунчер."""
    global _owned_ollama, _owned_server, _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True
    _kill_process_tree(_owned_server, "сервер чата")
    _owned_server = None
    _kill_process_tree(_owned_ollama, "Ollama")
    _owned_ollama = None


def _install_exit_hooks() -> None:
    atexit.register(cleanup_owned)
    if sys.platform != "win32":
        return
    # Закрытие окна консоли (крестик) — иначе atexit часто не успевает
    try:
        import ctypes
        from ctypes import wintypes

        HandlerRoutine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

        @HandlerRoutine
        def _console_handler(ctrl_type: int) -> bool:
            # 0 CTRL_C, 1 CTRL_BREAK, 2 CLOSE, 5 LOGOFF, 6 SHUTDOWN
            if ctrl_type in (0, 1, 2, 5, 6):
                cleanup_owned()
            return False  # пусть система продолжает закрытие

        ctypes.windll.kernel32.SetConsoleCtrlHandler(_console_handler, True)
        # удерживаем ссылку, иначе GC убьёт callback
        _install_exit_hooks._handler = _console_handler  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


def ensure_ollama(wait_seconds: float = 30.0) -> tuple[bool, subprocess.Popen | None]:
    """Поднять Ollama при необходимости.

    Возвращает `(ok, owned_proc)`: `owned_proc` не None только если serve
    запустили мы — тогда его нужно остановить при выходе.
    """
    if ollama_up():
        print("Ollama уже запущена (localhost:11434)")
        return True, None

    exe = _ollama_exe()
    if exe is None:
        print("Ollama не найдена. Установите: https://ollama.com/download")
        print("После установки перезапустите лаунчер.")
        return False, None

    print(f"Запуск Ollama: {exe} serve")
    try:
        kwargs: dict = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            # Новая группа, но не DETACHED — сохраняем pid для taskkill /T
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen([str(exe), "serve"], **kwargs)
    except OSError as exc:
        print(f"Не удалось запустить Ollama: {exc}")
        return False, None

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if ollama_up():
            print("Ollama готова (остановится вместе с лаунчером)")
            return True, proc
        if proc.poll() is not None:
            print(f"Ollama serve завершилась с кодом {proc.returncode}")
            return False, None
        time.sleep(0.4)

    print("Ollama не ответила вовремя на http://127.0.0.1:11434")
    print("Запустите вручную приложение Ollama из меню Пуск.")
    _kill_process_tree(proc, "Ollama")
    return False, None


def wait_ready(port: int, seconds: float = 45.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if healthy(port):
            return True
        time.sleep(0.25)
    return False


def open_browser(url: str) -> bool:
    """Надёжное открытие URL в браузере по умолчанию (Windows)."""
    errors: list[str] = []

    if sys.platform == "win32":
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            return True
        except OSError as exc:
            errors.append(f"startfile: {exc}")

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


def _lan_ipv4() -> list[str]:
    found: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    if not found:
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                probe.connect(("8.8.8.8", 80))
                ip = probe.getsockname()[0]
                if ip and not ip.startswith("127."):
                    found.append(ip)
            finally:
                probe.close()
        except OSError:
            pass
    return found


def _parse_args(argv: list[str] | None = None) -> tuple[bool, str, int, bool, bool]:
    """Возвращает (share, token, port, ask_mode, port_from_cli)."""
    import argparse

    parser = argparse.ArgumentParser(description="Лаунчер веб-чата Qwen Orchestra")
    parser.add_argument(
        "--share",
        action="store_true",
        help="Открыть порт в сеть (0.0.0.0), один общий сеанс",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Только этот ПК (по умолчанию, без интерактивного вопроса)",
    )
    parser.add_argument("--token", default="", help="Пароль для --share (HTTP Basic)")
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Порт. В --share берётся из share.json, если не указан.",
    )
    args = parser.parse_args(argv)

    share = bool(args.share) or os.environ.get("QWEN_SHARE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    token = (args.token or os.environ.get("QWEN_SHARE_TOKEN", "")).strip()
    port_from_cli = int(args.port) > 0
    port = int(args.port) if port_from_cli else 0
    ask = not args.share and not args.local and sys.stdin.isatty()
    return share, token, port, ask, port_from_cli


def _choose_access_mode() -> tuple[bool, str]:
    sc = _share_config()
    guest = sc.guest_url()
    print()
    print("  Доступ к веб-чату:")
    print("    1) Только этот ПК          (127.0.0.1)  [Enter]")
    if guest:
        print(f"    2) Открыть в сеть          ({guest})")
    else:
        print("    2) Открыть в сеть          (IP/порт из share.json)")
    print()
    try:
        choice = input("  Выбор (1/2): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return False, ""
    if choice == "2":
        try:
            token = input("  Пароль для гостя (Enter = без пароля): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            token = ""
        return True, token
    return False, ""


def _ensure_share_endpoint(port: int, port_from_cli: bool) -> int:
    """Подставить IP и порт из share.json; при отсутствии порта — спросить один раз."""
    sc = _share_config()
    public_ip = sc.ensure_public_ip(refresh=True)
    if port_from_cli and port > 0:
        sc.remember_share_endpoint(public_ip, port)
        return port

    cfg_port = sc.configured_share_port()
    if cfg_port is not None:
        sc.remember_share_endpoint(public_ip, cfg_port)
        return cfg_port

    if sys.stdin.isatty():
        hint = f" (сейчас IP {public_ip})" if public_ip else ""
        print()
        print(f"  В share.json ещё нет порта проброса{hint}.")
        try:
            raw = input(f"  Ваш открытый порт [{DEFAULT_PORT}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raw = ""
        chosen = int(raw) if raw.isdigit() else DEFAULT_PORT
        if not (1 <= chosen <= 65535):
            chosen = DEFAULT_PORT
        sc.remember_share_endpoint(public_ip, chosen)
        return chosen

    # без TTY — fallback
    chosen = DEFAULT_PORT
    sc.remember_share_endpoint(public_ip, chosen)
    return chosen


def main() -> int:
    global _owned_ollama, _owned_server

    _install_exit_hooks()
    root = _root()
    server_py = root / "server.py"

    share, token, port, ask, port_from_cli = _parse_args()
    if ask:
        share, token = _choose_access_mode()

    if share:
        port = _ensure_share_endpoint(port, port_from_cli)
    elif not port_from_cli:
        port = DEFAULT_PORT

    local_url = f"http://{DEFAULT_HOST}:{port}"
    sc = _share_config()
    guest = sc.guest_url(port=port) if share else None

    ok, owned = ensure_ollama()
    if not ok:
        input("Enter — выход...")
        return 1
    _owned_ollama = owned

    if healthy(port):
        print(f"Сервер уже запущен: {local_url}")
        if share:
            print("  Подсказка: уже работающий процесс мог быть запущен без --share.")
            print("  Остановите его и перезапустите лаунчер, если нужен доступ из сети.")
            if guest:
                print(f"  Гостю: {guest}")
        open_browser(local_url)
        print(f"Браузер: {local_url}")
        if _owned_ollama is not None:
            print("Ollama поднята лаунчером — Enter / Ctrl+C остановит её.")
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                print()
            cleanup_owned()
        return 0

    if not server_py.is_file():
        print(f"Не найден server.py рядом с лаунчером:\n  {server_py}")
        cleanup_owned()
        input("Enter — выход...")
        return 1

    try:
        py = _python()
    except FileNotFoundError as exc:
        print(exc)
        cleanup_owned()
        input("Enter — выход...")
        return 1

    cmd = [py, str(server_py)]
    if Path(py).name.lower() in {"py.exe", "py"}:
        cmd = [py, "-3", str(server_py)]
    if share:
        cmd.append("--share")
        cmd.extend(["--port", str(port)])
    elif port_from_cli:
        cmd.extend(["--port", str(port)])
    if token:
        cmd.extend(["--token", token])

    env = os.environ.copy()
    if share:
        env["QWEN_SHARE"] = "1"
        env["QWEN_PORT"] = str(port)
        if sc.configured_public_ip():
            env["QWEN_PUBLIC_IP"] = sc.configured_public_ip()
    if token:
        env["QWEN_SHARE_TOKEN"] = token

    print(f"Запуск сервера: {local_url}")
    if share:
        print("Режим SHARE — один общий сеанс (чаты/настройки как у вас).")
        if guest:
            print(f"  Гостю отдайте: {guest}")
        for ip in _lan_ipv4():
            print(f"  LAN: http://{ip}:{port}")
        print(f"  Конфиг: {sc.share_config_path()}")
        if token:
            print("  Пароль задан (логин любой, пароль = ваш токен)")
        else:
            print("  Без пароля — кто дойдёт до порта, получит полный доступ к UI.")
    print("Остановка: Ctrl+C (или закрытие консоли) — погасит сервер и Ollama")
    print()

    _owned_server = subprocess.Popen(cmd, cwd=str(root), env=env)

    if not wait_ready(port):
        print("Сервер не ответил вовремя. Проверьте:")
        print("  pip install -r requirements.txt")
        if _owned_server.poll() is not None:
            print(f"Процесс завершился с кодом {_owned_server.returncode}")
        cleanup_owned()
        input("Enter — выход...")
        return 1

    open_browser(local_url)
    print(f"Браузер: {local_url}")
    if guest:
        print(f"Гостю: {guest}")
    print()

    try:
        code = int(_owned_server.wait() or 0)
    except KeyboardInterrupt:
        print("\nОстановка…")
        code = 0
    finally:
        cleanup_owned()

    return code


if __name__ == "__main__":
    raise SystemExit(main())
