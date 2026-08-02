"""Сбор системных метрик для правой панели монитора.

CPU/RAM — psutil; GPU/VRAM/температуры — nvidia-smi (если есть);
загруженные модели и доля GPU/CPU — Ollama GET /api/ps.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Any

OLLAMA_PS_URL = "http://localhost:11434/api/ps"
_GPU_HEADER_RE = re.compile(r"^GPU\s+[0-9a-fA-F]{8}:", re.I)

# Не дёргать nvidia-smi / psutil чаще, чем раз в CACHE_TTL при частых poll UI
_CACHE_TTL = 0.6
_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"ts": 0.0, "payload": None, "inflight": False}

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


def _smi_number(raw: str) -> float | None:
    """Парсит число из nvidia-smi CSV / -q (N/A → None)."""
    s = (raw or "").strip().strip("[]")
    if not s or s.upper() == "N/A":
        return None
    # строки вида "52 C" / "8192 MiB"
    token = s.split()[0].replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


# Пороги температуры почти не меняются — кэш длиннее живых метрик
_TEMP_LIMITS_TTL = 60.0
_temp_limits_lock = threading.Lock()
_temp_limits_cache: dict[str, Any] = {"ts": 0.0, "by_index": {}, "failed": False}


def _nvidia_temp_limits() -> dict[int, dict[str, float | None]]:
    """Пороги и доп. температуры из `nvidia-smi -q -d TEMPERATURE` (по index)."""
    now = time.monotonic()
    with _temp_limits_lock:
        age = now - _temp_limits_cache["ts"]
        if age < _TEMP_LIMITS_TTL and (
            _temp_limits_cache["by_index"] or _temp_limits_cache.get("failed")
        ):
            return _temp_limits_cache["by_index"]

    if not shutil.which("nvidia-smi"):
        with _temp_limits_lock:
            _temp_limits_cache["ts"] = now
            _temp_limits_cache["by_index"] = {}
            _temp_limits_cache["failed"] = True
        return {}
    try:
        proc = subprocess.run(
            ["nvidia-smi", "-q", "-d", "TEMPERATURE"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        with _temp_limits_lock:
            _temp_limits_cache["ts"] = now
            _temp_limits_cache["by_index"] = {}
            _temp_limits_cache["failed"] = True
        return {}
    if proc.returncode != 0:
        with _temp_limits_lock:
            _temp_limits_cache["ts"] = now
            _temp_limits_cache["by_index"] = {}
            _temp_limits_cache["failed"] = True
        return {}

    key_map = {
        "GPU Current Temp": "temp_gpu_c",
        "GPU T.Limit Temp": "temp_tlimit_c",
        "GPU Target Temperature": "temp_target_c",
        "GPU Max Operating Temp": "temp_max_op_c",
        "GPU Slowdown Temp": "temp_slowdown_c",
        "GPU Shutdown Temp": "temp_shutdown_c",
        "Memory Current Temp": "temp_memory_c",
        "Memory Max Operating Temp": "temp_memory_max_c",
    }
    by_index: dict[int, dict[str, float | None]] = {}
    cur: dict[str, float | None] | None = None
    gpu_i = -1
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if _GPU_HEADER_RE.match(line):
            if cur is not None:
                by_index[gpu_i] = cur
            gpu_i += 1
            cur = {}
            continue
        if cur is None or ":" not in line:
            continue
        label, _, value = line.partition(":")
        field = key_map.get(label.strip())
        if field:
            cur[field] = _smi_number(value)

    if cur is not None and gpu_i >= 0:
        by_index[gpu_i] = cur

    with _temp_limits_lock:
        _temp_limits_cache["ts"] = now
        _temp_limits_cache["by_index"] = by_index
        _temp_limits_cache["failed"] = False
    return by_index


def _nvidia_gpus() -> tuple[list[dict[str, Any]], str | None]:
    if not shutil.which("nvidia-smi"):
        return [], None
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,"
                "temperature.gpu,temperature.memory",
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

    limits = _nvidia_temp_limits()
    gpus: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 7:
            continue
        try:
            idx = int(parts[0])
            mem_used = float(parts[3])
            mem_total = float(parts[4])
            mem_pct = round(100.0 * mem_used / mem_total, 1) if mem_total > 0 else 0.0
            temp_gpu = _smi_number(parts[5])
            temp_memory = _smi_number(parts[6])
        except ValueError:
            continue
        util = _smi_number(parts[2])
        lim = limits.get(idx) or {}
        # -q иногда знает memory temp, когда CSV пишет N/A (и наоборот)
        if temp_memory is None:
            temp_memory = lim.get("temp_memory_c")
        if temp_gpu is None:
            temp_gpu = lim.get("temp_gpu_c")
        gpus.append(
            {
                "index": idx,
                "name": parts[1],
                "util_percent": util,
                "mem_used_mb": mem_used,
                "mem_total_mb": mem_total,
                "mem_percent": mem_pct,
                "temp_gpu_c": temp_gpu,
                "temp_memory_c": temp_memory,
                "temp_tlimit_c": lim.get("temp_tlimit_c"),
                "temp_target_c": lim.get("temp_target_c"),
                "temp_max_op_c": lim.get("temp_max_op_c"),
                "temp_slowdown_c": lim.get("temp_slowdown_c"),
                "temp_shutdown_c": lim.get("temp_shutdown_c"),
                "temp_memory_max_c": lim.get("temp_memory_max_c"),
            }
        )
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
    now = time.monotonic()
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
        "ts": time.time(),
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
