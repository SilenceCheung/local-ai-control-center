"""Model Registry: scans local model directories and classifies what it finds.

Only MLX-format safetensors models are marked runnable by the MLX provider;
everything else is still listed (role "none", compatibility noted) so the user
can see their full local inventory.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from backend.core.config import expand_model_dirs, load_config
from backend.database.db import db

# Directories that are HF hub caches store snapshots under models--org--name/snapshots/<rev>/
_HF_PREFIX = "models--"
_INCOMPLETE_MARKER = ".download-incomplete"


def is_hf_hub_cache(path: Path) -> bool:
    """True for ~/.cache/huggingface/hub — scan-only, never the install library."""
    parts = [p.lower() for p in path.parts]
    return path.name == "hub" and "huggingface" in parts


def parse_repo_id(repo_id: str) -> tuple[str, str]:
    """Hugging Face / LM Studio id: org/name. Reject path traversal."""
    raw = (repo_id or "").strip().strip("/")
    if raw.count("/") != 1:
        raise ValueError("repo id must be org/name")
    org, name = raw.split("/", 1)
    if not org or not name or ".." in org or ".." in name:
        raise ValueError("invalid repo id")
    if "/" in name or org.startswith(".") or name.startswith("."):
        raise ValueError("invalid repo id")
    return org, name


def library_dir(cfg: dict[str, Any] | None = None) -> Path:
    """Primary library: first configured dir that is not the HF hub cache.

    Downloads land here as {org}/{name}, matching LM Studio.
    Changing it is an explicit Settings action — never inferred.
    """
    cfg = cfg or load_config()
    for base in expand_model_dirs(cfg):
        if not is_hf_hub_cache(base):
            return base
    return Path.home() / ".lmstudio" / "models"


def library_model_path(repo_id: str, cfg: dict[str, Any] | None = None) -> Path:
    org, name = parse_repo_id(repo_id)
    return library_dir(cfg) / org / name


def store_library_path(path: Path) -> str:
    """Prefer ~/… in yaml so the file stays portable across this Mac."""
    resolved = path.expanduser().resolve()
    home = Path.home()
    try:
        return "~/" + str(resolved.relative_to(home))
    except ValueError:
        return str(resolved)


def set_library_dir(path: str) -> dict[str, Any]:
    """Replace the primary library folder. Extra scan dirs (HF hub) are kept."""
    chosen = Path(os.path.expanduser(path)).resolve()
    if not chosen.is_dir():
        raise ValueError(f"directory does not exist: {chosen}")
    if is_hf_hub_cache(chosen):
        raise ValueError(
            "Hugging Face hub cache is scan-only. Pick an LM Studio-style folder "
            "(org/model subfolders), e.g. ~/.lmstudio/models"
        )
    cfg = load_config()
    extras: list[str] = []
    replaced = False
    for raw in cfg.get("model_dirs") or []:
        expanded = Path(os.path.expanduser(raw)).resolve()
        if is_hf_hub_cache(Path(os.path.expanduser(raw))):
            extras.append(raw)
            continue
        if not replaced:
            replaced = True  # drop previous library
            continue
        if expanded != chosen:
            extras.append(raw)
    stored = store_library_path(chosen)
    new_dirs = [stored, *extras]
    from backend.core.config import update_config
    update_config({"model_dirs": new_dirs})
    return {"ok": True, "library": stored, "model_dirs": new_dirs}


def library_status(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    lib = library_dir(cfg)
    extras = [
        str(p) for p in expand_model_dirs(cfg)
        if p.resolve() != lib.resolve()
    ]
    return {
        "library": store_library_path(lib),
        "library_resolved": str(lib.expanduser().resolve()),
        "exists": lib.exists(),
        "layout": "lmstudio",
        "extras": extras,
        "model_dirs": list(cfg.get("model_dirs") or []),
    }


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
    if (p / _INCOMPLETE_MARKER).exists():
        return True
    for f in p.rglob("*.part"):
        if ".cache" in f.parts:
            continue
        return True
    return False


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

    is_dflash2 = (
        "dflash2" in repo_hint.lower()
        or any("dflash2" in str(a).lower() for a in archs)
    )
    is_dflash_draft = (
        "DFlashDraftModel" in archs
        or "dflash" in repo_hint.lower()
        or is_dflash2
    )
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
            "is_dflash2": is_dflash2,
            "block_size": cfg.get("block_size") or (cfg.get("dflash_config") or {}).get("block_size"),
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
    if (
        m
        and m.get("status") == "available"
        and m.get("local_path")
        and Path(m["local_path"]).exists()
    ):
        return m["local_path"]
    return None


def forget_model(model_id: str) -> None:
    with db() as conn:
        conn.execute("DELETE FROM models WHERE id=?", (model_id,))


def discover_incomplete_repos(cfg: dict[str, Any] | None = None) -> list[str]:
    """org/name folders in the library that still have a marker or .part files."""
    lib = library_dir(cfg)
    out: list[str] = []
    if not lib.exists():
        return out
    for org_dir in lib.iterdir():
        if not org_dir.is_dir() or org_dir.name.startswith("."):
            continue
        for model_dir in org_dir.iterdir():
            if not model_dir.is_dir():
                continue
            if _is_incomplete(model_dir):
                out.append(f"{org_dir.name}/{model_dir.name}")
    return sorted(out)


def is_complete_library_model(repo_id: str, cfg: dict[str, Any] | None = None) -> bool:
    """Use current disk contents, not the registry DB or download ledger.

    Sharded models are complete only when every file referenced by the
    safetensors index exists. This prevents a downloader's temporary gap
    between shards from being mistaken for a finished model.
    """
    dest = library_model_path(repo_id, cfg).expanduser().resolve()
    if not dest.is_dir() or _is_incomplete(dest) or not (dest / "config.json").is_file():
        return False

    index = dest / "model.safetensors.index.json"
    if index.is_file():
        try:
            payload = json.loads(index.read_text(encoding="utf-8"))
            shards = {
                str(name) for name in (payload.get("weight_map") or {}).values()
                if isinstance(name, str) and name
            }
        except (OSError, json.JSONDecodeError, AttributeError):
            return False
        if not shards:
            return False
        shard_paths = [Path(shard) for shard in shards]
        if any(path.is_absolute() or ".." in path.parts for path in shard_paths):
            return False
        try:
            return all(
                (dest / shard).is_file() and (dest / shard).stat().st_size > 0
                for shard in shard_paths
            )
        except OSError:
            return False

    weights = list(dest.glob("*.safetensors"))
    try:
        return bool(weights) and all(path.stat().st_size > 0 for path in weights)
    except OSError:
        return False


def delete_library_folder(repo_id: str, cfg: dict[str, Any] | None = None) -> str:
    """Remove org/name from the model library. Refuses paths outside the library."""
    import shutil

    dest = library_model_path(repo_id, cfg).expanduser().resolve()
    lib = library_dir(cfg).expanduser().resolve()
    try:
        dest.relative_to(lib)
    except ValueError as e:
        raise ValueError("refusing to delete a path outside the model library") from e
    if dest == lib:
        raise ValueError("refusing to delete the library root")
    if dest.exists():
        shutil.rmtree(dest)
    org = dest.parent
    try:
        if org.is_dir() and org != lib and not any(org.iterdir()):
            org.rmdir()
    except OSError:
        pass
    forget_model(repo_id)
    return str(dest)
