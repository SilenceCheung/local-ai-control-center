"""Public API model alias: pretty name from Target, optional manual lock.

Agents copy this string into Cursor / Codex. The gateway still rewrites any
requested model id to the loaded Target, so an old alias keeps working.
"""

from __future__ import annotations

import re
from typing import Any

from backend.core.config import load_config, update_config
from backend.core.state import read_state, write_state

_DROP_TOKENS = {
    "mlx", "gguf", "safetensors", "awq", "gptq", "ara",
    "dflash", "dflash2", "dflash-mlx",
}
_VARIANT_TOKENS = {
    "heretic": "Heretic",
}
_QUANT_BIT = re.compile(r"(?:mlx)?(\d+)bit$", re.I)
_QUANT_QW = re.compile(r"^[qw](\d+)$", re.I)
_ALIAS_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]{0,127}$")


def pretty_alias(repo_id: str) -> str:
    """Turn a Hugging Face id into a short, readable OpenAI-style model name."""
    name = (repo_id or "").strip().replace("\\", "/")
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    name = name.replace("_", "-")
    parts = [p for p in name.split("-") if p]
    kept: list[str] = []
    quant: str | None = None
    for part in parts:
        low = part.lower()
        if low in _DROP_TOKENS:
            continue
        if low in _VARIANT_TOKENS:
            kept.append(_VARIANT_TOKENS[low])
            continue
        m = _QUANT_BIT.fullmatch(low)
        if m:
            quant = f"{m.group(1)}bit"
            continue
        m = _QUANT_QW.fullmatch(low)
        if m and m.group(1) in {"2", "3", "4", "5", "6", "8"}:
            quant = f"{m.group(1)}bit"
            continue
        kept.append(part)
    if quant:
        kept.append(quant)
    out = "-".join(kept).strip("-") or "local-model"
    return out[:128]


def sanitize_alias(raw: Any) -> str:
    text = str(raw or "").strip().replace(" ", "-")
    text = re.sub(r"-{2,}", "-", text).strip("-")
    if not text:
        raise ValueError("alias must not be empty")
    if not _ALIAS_OK.match(text):
        raise ValueError(
            "alias may use letters, digits, and . _ : + / - (no spaces or CJK)"
        )
    return text


def publish_state_alias(alias: str) -> None:
    st = read_state()
    if st.alias == alias:
        return
    st.alias = alias
    write_state(st)


def apply_alias(name: str, *, auto: bool, source: str | None = None) -> dict[str, Any]:
    name = sanitize_alias(name)
    patch: dict[str, Any] = {"api": {"alias": name, "alias_auto": auto}}
    if source is not None:
        patch["api"]["alias_source"] = source
    cfg = update_config(patch)
    publish_state_alias(name)
    return cfg


def sync_alias_for_target(model_id: str, *, force: bool = False) -> dict[str, Any]:
    """If auto-naming is on (or force), set alias from the Target repo id."""
    cfg = load_config()
    auto = bool((cfg.get("api") or {}).get("alias_auto", True))
    if not force and not auto:
        publish_state_alias(str((cfg.get("api") or {}).get("alias") or ""))
        return cfg
    name = pretty_alias(model_id)
    api = cfg.get("api") or {}
    if (
        api.get("alias") == name
        and bool(api.get("alias_auto", True))
        and api.get("alias_source") == model_id
    ):
        publish_state_alias(name)
        return cfg
    return apply_alias(name, auto=True, source=model_id)


def after_settings_patch(patch: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Apply auto-rename after a settings write (manual lock vs Target change)."""
    api_patch = patch.get("api") if isinstance(patch.get("api"), dict) else {}
    runtime_patch = patch.get("runtime") if isinstance(patch.get("runtime"), dict) else {}
    if api_patch.get("alias_auto") is True:
        target = str((cfg.get("runtime") or {}).get("target_model") or "")
        return sync_alias_for_target(target, force=True)
    target = runtime_patch.get("target_model")
    if target and bool((cfg.get("api") or {}).get("alias_auto", True)):
        return sync_alias_for_target(str(target))
    publish_state_alias(str((cfg.get("api") or {}).get("alias") or ""))
    return cfg
