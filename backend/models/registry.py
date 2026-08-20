"""Model Registry: scans local model directories and classifies what it finds.

Only MLX-format safetensors models are marked runnable by the MLX provider;
everything else is still listed (role "none", compatibility noted) so the user
can see their full local inventory.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from backend.core.config import expand_model_dirs, load_config
from backend.database.db import db

# Directories that are HF hub caches store snapshots under models--org--name/snapshots/<rev>/
_HF_PREFIX = "models--"


def _dir_size_bytes(p: Path) -> int:
    total = 0
    for f in p.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def _is_incomplete(p: Path) -> bool:
    return any(p.glob("*.part")) or any(p.glob("*.incomplete"))


def _parse_model_dir(path: Path, repo_hint: str) -> dict[str, Any] | None:
    cfg_file = path / "config.json"
    if not cfg_file.exists():
        return None
    try:
        with open(cfg_file) as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    has_safetensors = any(path.glob("*.safetensors"))
    if not has_safetensors:
        return None

    model_type = cfg.get("model_type", "unknown")
    archs = cfg.get("architectures") or []
    arch = archs[0] if archs else model_type
    quant = cfg.get("quantization") or cfg.get("quantization_config")
    quant_str = None
    if isinstance(quant, dict) and quant.get("bits"):
        quant_str = f"{quant['bits']}-bit (gs{quant.get('group_size', '?')})"
    dtype = cfg.get("dtype") or cfg.get("torch_dtype")

    is_dflash_draft = "DFlashDraftModel" in archs or "dflash" in repo_hint.lower()
    size_bytes = _dir_size_bytes(path)

    # MLX-quantized safetensors or bf16 safetensors both load under mlx-lm as
    # long as the architecture is supported. We mark obviously-supported Qwen /
    # Gemma / Llama families; anything else is "untested".
    fam_ok = any(model_type.startswith(t) for t in ("qwen", "gemma", "llama", "glm", "deepseek", "kimi"))
    if is_dflash_draft:
        compatibility = "mlx-dflash-draft"
    elif quant_str or fam_ok:
        compatibility = "mlx"
    else:
        compatibility = "untested"

    return {
        "id": repo_hint,
        "display_name": path.name,
        "provider": "local",
        "architecture": arch,
        "parameter_size": _guess_param_size(repo_hint, cfg),
        "quantization": quant_str or (str(dtype) if dtype else None),
        "format": "mlx-safetensors" if quant_str else "safetensors",
        "local_path": str(path),
        "huggingface_repo": repo_hint if "/" in repo_hint else None,
        "role": "none",
        "compatibility": compatibility,
        "context_length": cfg.get("max_position_embeddings"),
        "memory_estimate_gb": round(size_bytes / 1e9 * 1.15, 1),
        "size_bytes": size_bytes,
        "status": "downloading" if _is_incomplete(path) else "available",
        "extra": json.dumps({
            "model_type": model_type,
            "is_dflash_draft": is_dflash_draft,
            "block_size": cfg.get("block_size"),
            "target_layer_ids": (cfg.get("dflash_config") or {}).get("target_layer_ids"),
        }),
    }


def _guess_param_size(repo: str, cfg: dict) -> str | None:
    import re
    m = re.search(r"(\d+(?:\.\d+)?)\s*[bB](?![a-zA-Z])", repo.replace("-", " "))
    if m:
        return f"{m.group(1)}B"
    return None


def scan_models() -> list[dict[str, Any]]:
    """Scan configured dirs; returns list of model dicts (also persisted)."""
    cfg = load_config()
    found: dict[str, dict[str, Any]] = {}

    for base in expand_model_dirs(cfg):
        if not base.exists():
            continue
        if base.name == "hub":  # HF cache layout
            for repo_dir in base.iterdir():
                if not repo_dir.name.startswith(_HF_PREFIX):
                    continue
                repo = repo_dir.name[len(_HF_PREFIX):].replace("--", "/")
                snaps = repo_dir / "snapshots"
                if not snaps.exists():
                    continue
                for snap in sorted(snaps.iterdir(), reverse=True):
                    info = _parse_model_dir(snap, repo)
                    if info:
                        found[repo] = info
                        break
        else:  # LM Studio layout: org/model
            for org_dir in base.iterdir():
                if not org_dir.is_dir() or org_dir.name.startswith("."):
                    continue
                for model_dir in org_dir.iterdir():
                    if not model_dir.is_dir():
                        continue
                    repo = f"{org_dir.name}/{model_dir.name}"
                    info = _parse_model_dir(model_dir, repo)
                    if info:
                        found[repo] = info

    # Merge with persisted roles
    with db() as conn:
        existing = {r["id"]: dict(r) for r in conn.execute("SELECT id, role FROM models")}
        for mid, info in found.items():
            if mid in existing:
                info["role"] = existing[mid]["role"]
            conn.execute(
                """INSERT INTO models (id, display_name, provider, architecture, parameter_size,
                       quantization, format, local_path, huggingface_repo, role, compatibility,
                       context_length, memory_estimate_gb, size_bytes, status, extra)
                   VALUES (:id, :display_name, :provider, :architecture, :parameter_size,
                       :quantization, :format, :local_path, :huggingface_repo, :role, :compatibility,
                       :context_length, :memory_estimate_gb, :size_bytes, :status, :extra)
                   ON CONFLICT(id) DO UPDATE SET
                       display_name=excluded.display_name, local_path=excluded.local_path,
                       quantization=excluded.quantization, size_bytes=excluded.size_bytes,
                       status=excluded.status, extra=excluded.extra,
                       compatibility=excluded.compatibility,
                       context_length=excluded.context_length,
                       memory_estimate_gb=excluded.memory_estimate_gb""",
                info,
            )
    return sorted(found.values(), key=lambda m: -(m["size_bytes"] or 0))


def list_models() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM models ORDER BY size_bytes DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["extra"] = json.loads(d.get("extra") or "{}")
        except json.JSONDecodeError:
            d["extra"] = {}
        out.append(d)
    return out


def get_model(model_id: str) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["extra"] = json.loads(d.get("extra") or "{}")
    except json.JSONDecodeError:
        d["extra"] = {}
    return d


def set_role(model_id: str, role: str) -> None:
    """Assign target/draft/none. Target and draft are exclusive slots."""
    assert role in ("target", "draft", "embedding", "reranker", "none")
    with db() as conn:
        if role in ("target", "draft"):
            conn.execute("UPDATE models SET role='none' WHERE role=?", (role,))
        conn.execute("UPDATE models SET role=? WHERE id=?", (role, model_id))


def resolve_path(model_id: str) -> str | None:
    m = get_model(model_id)
    if m and m.get("local_path") and Path(m["local_path"]).exists():
        return m["local_path"]
    return None
