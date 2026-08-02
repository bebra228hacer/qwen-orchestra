"""Shim: ядро перенесено в пакет qwen_orchestra."""

from qwen_orchestra.settings import *  # noqa: F403
from qwen_orchestra import settings as _pkg
from qwen_orchestra.settings import (  # noqa: F401
    SETTINGS_PATH,
    AppSettings,
    ModelSlot,
    PoolModel,
    add_model,
    add_slot,
    apply_to_runtime,
    bootstrap,
    delete_model,
    delete_slot,
    ensure_bootstrapped,
    get_settings,
    get_settings_path,
    load_settings,
    public_settings_payload,
    reset_settings,
    runtime_lock,
    save_settings,
    set_settings_path,
    update_settings,
)

# Для `import settings as app_settings` — атрибуты модуля совпадают с пакетом
runtime_lock = _pkg.runtime_lock
