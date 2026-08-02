"""Сбор системных метрик для правой панели монитора.

CPU/RAM — psutil; GPU/VRAM — nvidia-smi (если есть);
загруженные модели и доля GPU/CPU — Ollama GET /api/ps.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Any

OLLAMA_PS_URL = "http://localhost:11434/api/ps"

# Не дёргать nvidia-smi / psutil чаще, чем раз в CACHE_TTL при частых poll UI
_CACHE_TTL = 0.6
_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"ts": 0.0, "payload": None}

# Прогрев счётчика CPU (первый cpu_percent(None) часто ≈ 0)
try:
    import psutil as _psutil_warmup

    _psutil_warmup.cpu_percent(interval=None)
except ImportError:
    pass


def _bytes_to_gb(n: int | float) -> float:
    return round(float(n) / (1024**3), 2)


def _bytes_to_mb(n: int | float) -> float:
    return round(float(n) / (1024**2), 1)


def _cpu_ram() -> tuple[dict[str, Any], dict[str, Any], str | None]:
    try:
        import psutil
    except ImportError:
        return (
            {"percent": None, "count": None},
            {"used_gb": None, "total_gb": None, "percent": None},
            "psutil не установлен (pip install psutil)",
        )
    # interval=None — мгновенное значение с прошлого вызова; первый вызов ≈ 0
    cpu_percent = float(psutil.cpu_percent(interval=None))
    if cpu_percent == 0.0:
        cpu_percent = float(psutil.cpu_percent(interval=0.05))
    mem = psutil.virtual_memory()
    return (
        {"percent": round(cpu_percent, 1), "count": psutil.cpu_count() or 0},
        {
            "used_gb": _bytes_to_gb(mem.used),
            "total_gb": _bytes_to_gb(mem.total),
            "percent": round(float(mem.percent), 1),
        },
        None,
    )


def _nvidia_gpus() -> tuple[list[dict[str, Any]], str | None]:
    if not shutil.which("nvidia-smi"):
        return [], None
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], f"nvidia-smi: {exc}"
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "ошибка").strip()
        return [], f"nvidia-smi: {err[:200]}"
    gpus: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            mem_used = float(parts[3])
            mem_total = float(parts[4])
            mem_pct = round(100.0 * mem_used / mem_total, 1) if mem_total > 0 else 0.0
            gpus.append(
                {
                    "index": int(parts[0]),
                    "name": parts[1],
                    "util_percent": float(parts[2]),
                    "mem_used_mb": mem_used,
                    "mem_total_mb": mem_total,
                    "mem_percent": mem_pct,
                }
            )
        except ValueError:
            continue
    return gpus, None


def _ollama_running() -> dict[str, Any]:
    try:
        with urllib.request.urlopen(OLLAMA_PS_URL, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        return {"ok": False, "models": [], "error": str(exc.reason if hasattr(exc, "reason") else exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "models": [], "error": str(exc)}

    models_out: list[dict[str, Any]] = []
    for m in data.get("models") or []:
        name = m.get("name") or m.get("model") or "?"
        size = int(m.get("size") or 0)
        size_vram = int(m.get("size_vram") or 0)
        if size > 0:
            gpu_ratio = max(0.0, min(1.0, size_vram / size))
        else:
            gpu_ratio = 1.0 if size_vram > 0 else 0.0
        cpu_ratio = round(1.0 - gpu_ratio, 3)
        gpu_ratio = round(gpu_ratio, 3)
        if gpu_ratio >= 0.99:
            place = "GPU"
        elif gpu_ratio <= 0.01:
            place = "CPU"
        else:
            place = "hybrid"
        models_out.append(
            {
                "name": name,
                "size_mb": _bytes_to_mb(size),
                "size_vram_mb": _bytes_to_mb(size_vram),
                "gpu_ratio": gpu_ratio,
                "cpu_ratio": cpu_ratio,
                "place": place,
                "processor": m.get("processor"),
                "expires_at": m.get("expires_at"),
            }
        )
    return {"ok": True, "models": models_out, "error": None}


def collect(*, use_cache: bool = True) -> dict[str, Any]:
    """Снимок метрик. Кэш ~0.6 с, чтобы UI мог poll чаще без лишней нагрузки."""
    now = time.time()
    if use_cache:
        with _cache_lock:
            if _cache["payload"] is not None and (now - _cache["ts"]) < _CACHE_TTL:
                return _cache["payload"]

    notes: list[str] = []
    cpu, ram, psutil_note = _cpu_ram()
    if psutil_note:
        notes.append(psutil_note)
    gpus, gpu_note = _nvidia_gpus()
    if gpu_note:
        notes.append(gpu_note)
    elif not gpus:
        notes.append("GPU: nvidia-smi не найден (только NVIDIA)")

    ollama = _ollama_running()
    payload: dict[str, Any] = {
        "ts": now,
        "cpu": cpu,
        "ram": ram,
        "gpu": gpus,
        "ollama": ollama,
        "note": "; ".join(notes) if notes else None,
    }
    with _cache_lock:
        _cache["ts"] = now
        _cache["payload"] = payload
    return payload
