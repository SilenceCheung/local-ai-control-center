"""Hugging Face discovery for models this stack can run, plus everything else.

Search is remote. Classification is local: `format=mlx` keeps models this
runtime can load; `format=all` lists GGUF / vision / other weights too.
Downloads never happen in this module — pull.py installs any ungated repo.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from backend.models.registry import list_models, parse_repo_id, library_model_path, _is_incomplete

log = logging.getLogger(__name__)

_VISION_PIPELINES_HARD = frozenset({
    "image-to-text",
    "visual-question-answering",
    "image-classification",
    "object-detection",
})
_VL_NAME_RE = re.compile(r"(?:^|[-_/])(vl|vision|llava|internvl|pixtral|moondream)(?:$|[-_/0-9])", re.I)
_MLX_TAGS = frozenset({"mlx", "mlx-lm", "apple-silicon"})
_SORT = {
    "downloads": "downloads",
    "updated": "last_modified",
    "relevance": None,
}


def list_models_kwargs(q: str, *, sort: str = "downloads", limit: int = 24, fmt: str = "mlx") -> dict[str, Any]:
    """Build HfApi.list_models kwargs for huggingface_hub 1.x (no `direction`)."""
    query = (q or "").strip() or None
    limit = max(1, min(int(limit), 50))
    sort_key = _SORT.get(sort, "downloads")
    kwargs: dict[str, Any] = {"search": query, "limit": limit}
    if sort_key:
        kwargs["sort"] = sort_key
    if fmt == "mlx":
        kwargs["filter"] = "mlx"
    return kwargs

_PARAM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[bB](?![a-zA-Z])")


def classify(
    repo_id: str,
    *,
    tags: list[str] | None = None,
    pipeline_tag: str | None = None,
    library_name: str | None = None,
    filenames: list[str] | None = None,
) -> dict[str, Any]:
    """Decide whether a Hub repo can run on this MLX + DFlash stack.

    Returns kind: target | draft | unusable
    and reason when unusable: vision | gguf | not_mlx
    """
    tags_l = {t.lower() for t in (tags or [])}
    files = [f.lower() for f in (filenames or [])]
    rid = (repo_id or "").lower()
    lib = (library_name or "").lower()
    pipe = (pipeline_tag or "").lower()

    has_gguf = any(f.endswith(".gguf") for f in files) or "gguf" in tags_l or rid.endswith("-gguf")
    has_st = any(f.endswith(".safetensors") for f in files)
    has_mlx = (
        lib == "mlx"
        or bool(tags_l & _MLX_TAGS)
        or "mlx" in rid
        or any("mlx" in f for f in files)
    )
    vision = _blocked_vision(rid, tags_l=tags_l, pipe=pipe, files=files, has_mlx=has_mlx)
    draft = "dflash" in rid or "dflashdraft" in "".join(tags_l)

    if vision and not has_mlx:
        return _cls(False, "unusable", "vision")
    if vision and has_mlx:
        # This runtime is text-only. LM Studio can still load these locally;
        # Discover will not pull them.
        return _cls(False, "unusable", "vision")
    if has_gguf and not has_mlx and not has_st:
        return _cls(False, "unusable", "gguf")
    if has_gguf and not has_mlx:
        return _cls(False, "unusable", "gguf")
    if has_mlx or has_st:
        if draft:
            return _cls(True, "draft", None)
        return _cls(True, "target", None)
    return _cls(False, "unusable", "not_mlx")


def _blocked_vision(
    rid: str, *, tags_l: set[str], pipe: str, files: list[str], has_mlx: bool
) -> bool:
    """Block dedicated VL packs. Unified LLMs tagged image-text-to-text stay downloadable as text."""
    if any("mmproj" in f or "model-vision" in f for f in files):
        return True
    if _VL_NAME_RE.search(rid):
        return True
    if pipe in _VISION_PIPELINES_HARD:
        return True
    if "vision" in tags_l and not has_mlx:
        return True
    return False


def _cls(runnable: bool, kind: str, reason: str | None) -> dict[str, Any]:
    return {"runnable": runnable, "kind": kind, "reason": reason}


def guess_param_size(repo_id: str) -> str | None:
    m = _PARAM_RE.search(repo_id.replace("-", " "))
    return f"{m.group(1)}B" if m else None


def _local_ids() -> set[str]:
    return {m["id"] for m in list_models()}


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _filenames(info: Any) -> list[str]:
    out: list[str] = []
    for sib in getattr(info, "siblings", None) or []:
        name = getattr(sib, "rfilename", None) or getattr(sib, "filename", None)
        if name:
            out.append(str(name))
    return out


def _file_rows(info: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sib in getattr(info, "siblings", None) or []:
        name = getattr(sib, "rfilename", None) or getattr(sib, "filename", None)
        if not name:
            continue
        size = getattr(sib, "size", None)
        rows.append({"name": str(name), "size_bytes": size})
    return rows


def serialize_hit(info: Any, local_ids: set[str] | None = None) -> dict[str, Any]:
    local_ids = local_ids if local_ids is not None else _local_ids()
    repo_id = getattr(info, "id", "") or ""
    tags = list(getattr(info, "tags", None) or [])
    cls = classify(
        repo_id,
        tags=tags,
        pipeline_tag=getattr(info, "pipeline_tag", None),
        library_name=getattr(info, "library_name", None),
        filenames=_filenames(info),
    )
    return {
        "id": repo_id,
        "downloads": getattr(info, "downloads", None) or 0,
        "likes": getattr(info, "likes", None) or 0,
        "last_modified": _iso(getattr(info, "last_modified", None)),
        "pipeline_tag": getattr(info, "pipeline_tag", None),
        "library_name": getattr(info, "library_name", None),
        "tags": tags[:24],
        "param_size": guess_param_size(repo_id),
        "local": repo_id in local_ids,
        "partial": _repo_is_partial(repo_id),
        **cls,
    }


def _repo_is_partial(repo_id: str) -> bool:
    try:
        dest = library_model_path(repo_id)
    except ValueError:
        return False
    return dest.exists() and _is_incomplete(dest)


def apply_search_scope(
    rows: list[dict[str, Any]],
    *,
    fmt: str,
    pinned_ids: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    """mlx = this stack can run it (plus exact-id pins). all = keep every hit."""
    limit = max(1, min(int(limit), 50))
    if fmt == "mlx":
        rows = [r for r in rows if r.get("runnable") or r.get("id") in pinned_ids]
    return rows[:limit]


def recommended_repo_ids() -> list[str]:
    """Recipe Target/Draft first — this stack's real recommendations."""
    from backend.runtime.recipes import DEFAULT_SLOTS, RECIPE_IDS

    out: list[str] = []
    for rid in RECIPE_IDS:
        slot = DEFAULT_SLOTS[rid]
        for key in ("target_model", "draft_model"):
            mid = slot.get(key)
            if isinstance(mid, str) and mid and mid not in out:
                out.append(mid)
    return out


def search_hub(q: str, *, sort: str = "downloads", limit: int = 24, fmt: str = "mlx") -> dict[str, Any]:
    """Query Hugging Face. Empty query lists recipe models, then popular hits."""
    from huggingface_hub import HfApi

    query = (q or "").strip()
    limit = max(1, min(int(limit), 50))
    fmt = fmt if fmt in ("mlx", "all") else "mlx"
    api = HfApi()
    local_ids = _local_ids()
    hits: list[Any] = []
    seen: set[str] = set()
    pinned_ids: set[str] = set()
    fetch_n = min(50, limit * 3) if fmt == "mlx" else limit

    if "/" in query:
        try:
            parse_repo_id(query)
            info = api.model_info(query)
            hits.append(info)
            seen.add(info.id)
            pinned_ids.add(info.id)
        except Exception as e:  # exact id miss is fine; fall through to search
            log.debug("hub exact lookup failed for %s: %s", query, e)

    if not query:
        for rid in recommended_repo_ids():
            if rid in seen:
                continue
            try:
                info = api.model_info(rid)
                hits.append(info)
                seen.add(info.id)
                pinned_ids.add(info.id)
            except Exception as e:
                log.debug("recommended lookup failed for %s: %s", rid, e)

    kwargs = list_models_kwargs(query, sort=sort, limit=fetch_n, fmt=fmt)

    try:
        for info in api.list_models(**kwargs):
            if info.id in seen:
                continue
            hits.append(info)
            seen.add(info.id)
            if len(hits) >= fetch_n + len(pinned_ids):
                break
    except TypeError as e:
        # huggingface_hub 1.x dropped `direction`; never pass unknown kwargs.
        log.exception("hub search failed")
        raise RuntimeError(f"Hugging Face search failed: {e}") from e
    except Exception as e:
        log.exception("hub search failed")
        raise RuntimeError(f"Hugging Face search failed: {e}") from e

    rows = apply_search_scope(
        [serialize_hit(h, local_ids) for h in hits],
        fmt=fmt,
        pinned_ids=pinned_ids,
        limit=limit,
    )
    return {
        "ok": True,
        "query": query,
        "sort": sort,
        "format": fmt,
        "results": rows,
    }


def hub_card(repo_id: str) -> dict[str, Any]:
    from huggingface_hub import HfApi, ModelCard

    parse_repo_id(repo_id)
    api = HfApi()
    try:
        info = api.model_info(repo_id, files_metadata=True)
    except Exception as e:
        raise FileNotFoundError(str(e)) from e

    hit = serialize_hit(info)
    files = _file_rows(info)
    card_data = getattr(info, "card_data", None)
    license_id = None
    if card_data is not None:
        license_id = getattr(card_data, "license", None)
    readme = None
    try:
        card = ModelCard.load(repo_id)
        text = (card.content or "").strip()
        if text:
            readme = text[:2400]
    except Exception:
        readme = None

    gated = bool(getattr(info, "gated", False))
    return {
        **hit,
        "license": license_id,
        "gated": gated,
        "architectures": _architectures(card_data),
        "files": files,
        "readme": readme,
        "url": f"https://huggingface.co/{repo_id}",
        "reasoning": "qwen" in repo_id.lower() or "thinking" in " ".join(hit.get("tags") or []).lower(),
        "tools": "tool-calling" in " ".join(hit.get("tags") or []).lower()
                 or "function-calling" in " ".join(hit.get("tags") or []).lower(),
    }


def _architectures(card_data: Any) -> list[str]:
    if card_data is None:
        return []
    tags = getattr(card_data, "tags", None) or []
    return [t for t in tags if isinstance(t, str)][:8]
