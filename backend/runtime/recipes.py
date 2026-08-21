"""Dual Fast-mode recipes: Heretic (default) vs official DFlash 2.

Recipes store Target + Draft + DFlash knobs. Switching snapshots the current
slot, then applies the other. Engine CLI flags are probed from `dflash serve
--help` so we never pass flags the installed dflash-mlx does not understand.

Official z-lab `pip install dflash` is a different package (generate/benchmark
only) and must not replace `dflash-mlx`'s `dflash serve` entry point.
"""

from __future__ import annotations

import importlib.metadata
import re
import subprocess
from typing import Any

from backend.core.config import PROJECT_ROOT, load_config, save_config
from backend.models.registry import resolve_path


def _venv_bin(name: str) -> str:
    return str(PROJECT_ROOT / ".venv" / "bin" / name)

HERETIC = "heretic"
OFFICIAL_DFLASH2 = "official_dflash2"
RECIPE_IDS = (HERETIC, OFFICIAL_DFLASH2)

SLOT_DFLASH_KEYS = (
    "verify_mode",
    "verify_len_cap",
    "draft_quant",
    "runtime_block_size",
    "draft_bits",
    "reasoning",
)

DEFAULT_SLOTS: dict[str, Any] = {
    HERETIC: {
        "id": HERETIC,
        "generation": "dflash1",
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
    OFFICIAL_DFLASH2: {
        "id": OFFICIAL_DFLASH2,
        "generation": "dflash2",
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
}

_SERVE_FLAGS: frozenset[str] | None = None
_ENGINE_MODELS: str | None = None
_DFLASH2_IMPORT_SUPPORTED: bool | None = None


def default_recipes_section() -> dict[str, Any]:
    return {
        "active": HERETIC,
        HERETIC: {
            "target_model": DEFAULT_SLOTS[HERETIC]["target_model"],
            "draft_model": DEFAULT_SLOTS[HERETIC]["draft_model"],
            "dflash": dict(DEFAULT_SLOTS[HERETIC]["dflash"]),
        },
        OFFICIAL_DFLASH2: {
            "target_model": DEFAULT_SLOTS[OFFICIAL_DFLASH2]["target_model"],
            "draft_model": DEFAULT_SLOTS[OFFICIAL_DFLASH2]["draft_model"],
            "dflash": dict(DEFAULT_SLOTS[OFFICIAL_DFLASH2]["dflash"]),
        },
    }


def ensure_recipes(cfg: dict[str, Any]) -> dict[str, Any]:
    """Fill missing recipe slots without clobbering user overrides."""
    from backend.core.config import _deep_merge

    base = default_recipes_section()
    user = cfg.get("recipes") or {}
    cfg["recipes"] = _deep_merge(base, user)
    active = cfg["recipes"].get("active")
    if active not in RECIPE_IDS:
        cfg["recipes"]["active"] = HERETIC
    return cfg


def snapshot_runtime_into_slot(cfg: dict[str, Any], recipe_id: str) -> dict[str, Any]:
    cfg = ensure_recipes(cfg)
    slot = cfg["recipes"][recipe_id]
    slot["target_model"] = cfg["runtime"]["target_model"]
    slot["draft_model"] = cfg["runtime"]["draft_model"]
    df = cfg.get("dflash") or {}
    stored = dict(slot.get("dflash") or {})
    for k in SLOT_DFLASH_KEYS:
        if k in df:
            stored[k] = df[k]
    slot["dflash"] = stored
    return cfg


def apply_slot(cfg: dict[str, Any], recipe_id: str) -> dict[str, Any]:
    cfg = ensure_recipes(cfg)
    slot = cfg["recipes"][recipe_id]
    meta = DEFAULT_SLOTS[recipe_id]
    cfg["runtime"]["target_model"] = slot["target_model"]
    cfg["runtime"]["draft_model"] = slot["draft_model"]
    df = dict(cfg.get("dflash") or {})
    for k, v in (slot.get("dflash") or meta["dflash"]).items():
        df[k] = v
    cfg["dflash"] = df
    cfg["recipes"]["active"] = recipe_id
    return cfg


def sync_active_from_runtime(cfg: dict[str, Any]) -> dict[str, Any]:
    cfg = ensure_recipes(cfg)
    return snapshot_runtime_into_slot(cfg, cfg["recipes"]["active"])


def missing_models(cfg: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for role, key in (("target", "target_model"), ("draft", "draft_model")):
        mid = cfg["runtime"].get(key) or ""
        if mid and resolve_path(mid) is None:
            out.append({"id": mid, "role": role})
    return out


def serve_flags() -> frozenset[str]:
    """Flag names advertised by the installed `dflash serve` CLI."""
    global _SERVE_FLAGS
    if _SERVE_FLAGS is not None:
        return _SERVE_FLAGS
    flags: set[str] = set()
    try:
        proc = subprocess.run(
            [_venv_bin("dflash"), "serve", "--help"],
            capture_output=True, text=True, timeout=8, check=False,
        )
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        flags.update(re.findall(r"(--[a-z0-9-]+)", text))
    except (OSError, subprocess.SubprocessError):
        flags.update({"--model", "--draft-model", "--verify-mode", "--draft-quant",
                      "--verify-len-cap", "--chat-template-args"})
    _SERVE_FLAGS = frozenset(flags)
    return _SERVE_FLAGS


def serve_supports(flag: str) -> bool:
    return flag in serve_flags()


def engine_identity() -> dict[str, Any]:
    pkg, ver = "unknown", None
    try:
        ver = importlib.metadata.version("dflash-mlx")
        pkg = "dflash-mlx"
    except importlib.metadata.PackageNotFoundError:
        try:
            ver = importlib.metadata.version("dflash")
            pkg = "dflash"
        except importlib.metadata.PackageNotFoundError:
            pass
    flags = sorted(serve_flags())
    models_txt = _engine_models_text()
    dflash2_in_registry = "dflash2" in models_txt.lower() or "qwen3.8" in models_txt.lower()
    dflash2_import = _dflash2_import_supported()
    return {
        "package": pkg,
        "version": ver,
        "cli": "dflash serve",
        "upstream": "community-mlx" if pkg == "dflash-mlx" else pkg,
        "not_zlab_source": pkg != "dflash",
        "serve_flags": flags,
        "knobs_live": {
            "runtime_block_size": "--block-size" in flags,
            "draft_bits": "--draft-bits" in flags,
            "reasoning": "--reasoning" in flags,
            "draft_quant": "--draft-quant" in flags,
            "verify_mode": "--verify-mode" in flags,
            "prefill_step_size": "--prefill-step-size" in flags,
            "draft_sink_size": "--draft-sink-size" in flags,
            "draft_window_size": "--draft-window-size" in flags,
            "prefix_cache_l2": "--prefix-cache-l2" in flags,
            "cache_limit": "--cache-limit" in flags,
        },
        "official_dflash2_in_engine_registry": dflash2_in_registry,
        "dflash2_import_supported": dflash2_import,
        "generation_supported": {
            "dflash1": True,
            "dflash2": dflash2_in_registry and dflash2_import,
        },
    }


def _dflash2_import_supported() -> bool:
    """Require the actual DFlash2 implementation, not a coincidental CLI flag."""
    global _DFLASH2_IMPORT_SUPPORTED
    if _DFLASH2_IMPORT_SUPPORTED is not None:
        return _DFLASH2_IMPORT_SUPPORTED
    try:
        proc = subprocess.run(
            [
                _venv_bin("python"),
                "-c",
                "from dflash_mlx.draft.dflash2 import DFlash2DraftModel",
            ],
            capture_output=True, text=True, timeout=8, check=False,
        )
        _DFLASH2_IMPORT_SUPPORTED = proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        _DFLASH2_IMPORT_SUPPORTED = False
    return _DFLASH2_IMPORT_SUPPORTED


def _engine_models_text() -> str:
    global _ENGINE_MODELS
    if _ENGINE_MODELS is not None:
        return _ENGINE_MODELS
    try:
        proc = subprocess.run(
            [_venv_bin("dflash"), "models"],
            capture_output=True, text=True, timeout=8, check=False,
        )
        _ENGINE_MODELS = (proc.stdout or "") + "\n" + (proc.stderr or "")
    except (OSError, subprocess.SubprocessError):
        _ENGINE_MODELS = ""
    return _ENGINE_MODELS


def activate(recipe_id: str) -> dict[str, Any]:
    if recipe_id not in RECIPE_IDS:
        raise ValueError(f"recipe must be one of {RECIPE_IDS}")
    cfg = ensure_recipes(load_config())
    current = cfg["recipes"]["active"]
    if current != recipe_id:
        # Legacy UIs allowed users to select the destination model pair before
        # changing the recipe id. Snapshotting that pair into the source slot
        # corrupts both recipes (for example, Heretic starts pointing at the
        # official Qwen3.8 pair). Preserve the source slot in that case.
        destination = cfg["recipes"][recipe_id]
        rt = cfg["runtime"]
        already_destination_models = (
            rt.get("target_model") == destination.get("target_model")
            and rt.get("draft_model") == destination.get("draft_model")
        ) or (
            rt.get("target_model") == DEFAULT_SLOTS[recipe_id]["target_model"]
            and rt.get("draft_model") == DEFAULT_SLOTS[recipe_id]["draft_model"]
        )
        if not already_destination_models:
            cfg = snapshot_runtime_into_slot(cfg, current)
        cfg = apply_slot(cfg, recipe_id)
        save_config(cfg)
        from backend.core.alias import sync_alias_for_target
        sync_alias_for_target(str(cfg["runtime"]["target_model"]))
    return describe(cfg)


def describe(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = ensure_recipes(cfg or load_config())
    active = cfg["recipes"]["active"]
    meta = DEFAULT_SLOTS[active]
    engine = engine_identity()
    return {
        "active": active,
        "generation": meta["generation"],
        "slots": {
            rid: {
                "id": rid,
                "generation": DEFAULT_SLOTS[rid]["generation"],
                "target_model": cfg["recipes"][rid]["target_model"],
                "draft_model": cfg["recipes"][rid]["draft_model"],
                "dflash": cfg["recipes"][rid]["dflash"],
            }
            for rid in RECIPE_IDS
        },
        "applied": {
            "target_model": cfg["runtime"]["target_model"],
            "draft_model": cfg["runtime"]["draft_model"],
            "dflash": {k: cfg["dflash"].get(k) for k in SLOT_DFLASH_KEYS},
        },
        "missing": missing_models(cfg),
        "engine": engine,
    }
