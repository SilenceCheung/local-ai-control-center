"""Central configuration: config/config.yaml is the single source of truth.

All processes (control backend, gateway, CLI) read the same file. Writes go
through save_config() which is atomic (tmp + rename) so a crashed writer can
never leave a half-written config behind.
"""

from __future__ import annotations

import copy
import os
import threading
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
STATE_PATH = DATA_DIR / "runtime_state.json"
GATEWAY_STATS_PATH = DATA_DIR / "gateway_stats.json"
DOWNLOADS_PATH = DATA_DIR / "downloads.json"
DB_PATH = DATA_DIR / "lacc.db"

DEFAULT_CONFIG: dict[str, Any] = {
    "api": {
        "host": "127.0.0.1",
        "port": 8080,
        "api_key": "local",
        "alias": "Qwen3.8-27B-Heretic-8bit",
        "alias_auto": True,
        "alias_source": "McG-221/Qwen3.8-27B-heretic-ara-mlx-8Bit",
    },
    "dashboard": {
        "host": "127.0.0.1",
        "port": 8787,
    },
    "runtime": {
        "provider": "mlx",
        "internal_host": "127.0.0.1",
        "internal_port": 18080,
        "mode": "fast",  # "safe" = target only, "fast" = target + DFlash
        "auto_load": False,
        "target_model": "McG-221/Qwen3.8-27B-heretic-ara-mlx-8Bit",
        "draft_model": "jfan/Qwen3.8-27B-heretic-dflash",
        "max_context": 65536,
        "default_max_tokens": 4096,
        "enable_thinking": True,  # Qwen3.8 tokenizer default; set False to save tokens
    },
    "dflash": {
        "enabled": True,
        # Real dflash-mlx knobs. Heretic draft block size (16) is trained-fixed.
        # Official DFlash 2 stores runtime_block_size as recipe intent; only
        # forwarded to CLI when `dflash serve` advertises --block-size.
        "verify_mode": "adaptive",  # adaptive | dflash | ddtree
        "verify_len_cap": 0,  # 0 = runtime default
        "draft_quant": "default",  # default | none | w4:gs64 ...
        "fastpath_max_tokens": 0,
        "prefix_cache": True,
        "prefill_step_size": 2048,
        "draft_sink_size": 64,
        "draft_window_size": 1024,
        "prefix_cache_l2": True,
        "prefix_cache_max_entries": 4,
        "prefix_cache_max_bytes": "8GB",
        "prefix_cache_l2_max_bytes": "50GB",
        "cache_limit": "4GB",
        "runtime_block_size": 0,
        "draft_bits": 0,
        "reasoning": "default",  # default | low | medium | xhigh
    },
    "recipes": {
        "active": "heretic",  # heretic | official_dflash2
        "heretic": {
            "target_model": "McG-221/Qwen3.8-27B-heretic-ara-mlx-8Bit",
            "draft_model": "jfan/Qwen3.8-27B-heretic-dflash",
            "dflash": {
                "verify_mode": "adaptive",
                "verify_len_cap": 0,
                "draft_quant": "default",
                "runtime_block_size": 0,
                "draft_bits": 0,
                "reasoning": "default",
            },
        },
        "official_dflash2": {
            "target_model": "mlx-community/Qwen3.8-27B-4bit",
            "draft_model": "z-lab/Qwen3.8-27B-DFlash2",
            "dflash": {
                "verify_mode": "adaptive",
                "verify_len_cap": 0,
                "draft_quant": "w4:gs64",
                "runtime_block_size": 0,
                "draft_bits": 4,
                "reasoning": "xhigh",
            },
        },
    },
    "model_dirs": [
        "~/.lmstudio/models",  # primary library (LM Studio org/name). Downloads land here.
        "~/.cache/huggingface/hub",  # extra scan-only
    ],
    "logging": {"level": "INFO"},
    "memory": {
        "swap_warn_gb": 4.0,
        "pressure_warn_pct": 75,
    },
    "privacy": {
        "log_prompts": False,
    },
}

_lock = threading.Lock()


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict[str, Any]:
    with _lock:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                user_cfg = yaml.safe_load(f) or {}
        else:
            user_cfg = {}
    return _deep_merge(DEFAULT_CONFIG, user_cfg)


def save_config(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".yaml.tmp")
    with _lock:
        with open(tmp, "w") as f:
            yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)
        os.replace(tmp, CONFIG_PATH)


def update_config(patch: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge a patch into the persisted config and return the result."""
    cfg = load_config()
    merged = _deep_merge(cfg, patch)
    if "runtime" in patch or "dflash" in patch:
        from backend.runtime.recipes import sync_active_from_runtime
        merged = sync_active_from_runtime(merged)
    save_config(merged)
    return merged


def expand_model_dirs(cfg: dict[str, Any]) -> list[Path]:
    return [Path(os.path.expanduser(d)) for d in cfg.get("model_dirs", [])]


def ensure_dirs() -> None:
    for d in (DATA_DIR, LOGS_DIR, CONFIG_PATH.parent):
        d.mkdir(parents=True, exist_ok=True)
