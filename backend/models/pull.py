"""One-at-a-time Hugging Face pull into the LM Studio library folder.

Destination: {library}/{org}/{name} — same layout LM Studio uses.
Never writes into ~/.cache/huggingface/hub as the install location.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from tqdm.auto import tqdm

from backend.models.registry import (
    _INCOMPLETE_MARKER,
    _is_incomplete,
    library_model_path,
    library_status,
    parse_repo_id,
    scan_models,
    set_role,
)

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, str], None]
PART_SUFFIX = ".part"


class _Cancel(Exception):
    pass


def pull_preflight(card: dict[str, Any]) -> None:
    """Gated repos stay blocked. Unsupported formats can still be stored in the library."""
    if card.get("gated"):
        raise RuntimeError(
            "this repo is gated on Hugging Face. Accept the license in a browser first."
        )


def safe_relpath(name: str) -> Path:
    rel = Path(str(name or ""))
    if not str(name) or rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"unsafe path in repo: {name!r}")
    return rel


def part_path(dest: Path) -> Path:
    return dest.with_name(dest.name + PART_SUFFIX)


def file_complete(path: Path, expected: int | None) -> bool:
    if not path.is_file():
        return False
    if expected is None:
        return True
    return path.stat().st_size == int(expected)


def existing_bytes(dest: Path, files: list[dict[str, Any]]) -> tuple[int, int, bool]:
    """Return (done, total, has_partial) for a library folder."""
    done = 0
    total = 0
    partial = (dest / _INCOMPLETE_MARKER).exists()
    for row in files:
        try:
            rel = safe_relpath(str(row.get("name") or ""))
        except ValueError:
            continue
        size = row.get("size_bytes")
        if isinstance(size, int) and size >= 0:
            total += size
        target = dest / rel
        part = part_path(target)
        if file_complete(target, size if isinstance(size, int) else None):
            done += target.stat().st_size
        elif part.is_file():
            done += part.stat().st_size
            partial = True
    if dest.exists() and _is_incomplete(dest):
        partial = True
    return done, total, partial


def download_file_resumable(
    url: str,
    dest: Path,
    *,
    expected_size: int | None,
    headers: dict[str, str],
    tqdm_class: type | None = None,
    http_get_fn: Callable[..., Any] | None = None,
) -> None:
    """HTTP Range resume into dest.name.part, then atomic rename. Keeps the part on failure."""
    from huggingface_hub.file_download import http_get as _http_get

    getter = http_get_fn or _http_get
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and expected_size is not None and dest.stat().st_size != int(expected_size):
        dest.unlink()
    if file_complete(dest, expected_size):
        return
    part = part_path(dest)
    resume_size = part.stat().st_size if part.is_file() else 0
    if expected_size is not None and resume_size > int(expected_size):
        part.unlink()
        resume_size = 0
    with part.open("ab") as handle:
        getter(
            url,
            handle,
            resume_size=resume_size,
            headers=headers,
            expected_size=expected_size,
            displayed_filename=dest.name,
            tqdm_class=tqdm_class,
        )
    got = part.stat().st_size
    if expected_size is not None and got != int(expected_size):
        raise OSError(f"size mismatch for {dest.name}: {got} != {expected_size}")
    part.replace(dest)


class PullJobManager:
    """Queue + one active download. Pause keeps .part files; delete removes the folder."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self.job: dict[str, Any] | None = None
        self._cancel = threading.Event()
        self._stop_reason = "pause"
        self._acc_base = 0
        self._active_id: str | None = None
        self._lock = threading.RLock()
        self.items: dict[str, dict[str, Any]] = {}
        self._queue: list[str] = []
        self._load()

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def snapshot(self) -> dict[str, Any]:
        self._hydrate_disk()
        if self.busy and self.job and self._active_id:
            with self._lock:
                live = self.items.get(self._active_id)
                if live:
                    live["bytes_done"] = self.job.get("bytes_done") or live.get("bytes_done") or 0
                    live["bytes_total"] = self.job.get("bytes_total") or live.get("bytes_total") or 0
                    live["detail"] = self.job.get("detail") or live.get("detail") or ""
                    live["current"] = self.job.get("current") or live.get("current") or ""
        items = sorted(
            (self._with_disk_facts(row) for row in self.items.values()),
            key=lambda row: (
                {"running": 0, "queued": 1, "paused": 2, "error": 3, "done": 4}.get(row.get("status") or "", 9),
                -(row.get("updated_at") or 0),
            ),
        )
        return {
            "busy": self.busy,
            "job": self.job,
            "active_id": self._active_id if self.busy else None,
            "items": items,
            "queue": list(self._queue),
            "library": library_status(),
        }

    @staticmethod
    def _with_disk_facts(item: dict[str, Any]) -> dict[str, Any]:
        """Return UI-safe disk facts without trusting the persisted job state."""
        row = dict(item)
        repo_id = str(row.get("repo_id") or "")
        try:
            dest = library_model_path(repo_id)
        except ValueError:
            row.update(has_partial_files=False, has_complete_model=False, partial_bytes=0)
            return row
        partial_bytes = 0
        if dest.is_dir():
            for path in dest.rglob(f"*{PART_SUFFIX}"):
                if not path.is_file() or ".cache" in path.parts:
                    continue
                try:
                    partial_bytes += path.stat().st_size
                except OSError:
                    pass
        has_partials = partial_bytes > 0 or (dest / _INCOMPLETE_MARKER).exists()
        has_complete_model = (
            not has_partials
            and (dest / "config.json").is_file()
            and any(dest.glob("*.safetensors"))
        )
        row.update(
            has_partial_files=has_partials,
            has_complete_model=has_complete_model,
            partial_bytes=partial_bytes,
        )
        return row

    def cancel(self) -> dict[str, Any]:
        """Compat: stop the active transfer and keep files (same as pause)."""
        return self.pause(None)

    def pause(self, repo_id: str | None = None) -> dict[str, Any]:
        target = repo_id or self._active_id
        if not target:
            return {"ok": False, "error": "nothing to pause"}
        with self._lock:
            item = self.items.get(target)
            if item is None:
                return {"ok": False, "error": "unknown download"}
            if target == self._active_id and self.busy:
                self._stop_reason = "pause"
                self._cancel.set()
                item["status"] = "pausing"
                if self.job is not None:
                    self.job["status"] = "pausing"
                    self.job["current"] = "pause"
            elif item.get("status") == "queued":
                item["status"] = "paused"
                if target in self._queue:
                    self._queue.remove(target)
            elif item.get("status") == "running":
                item["status"] = "paused"
            item["updated_at"] = time.time()
            self._save()
        return {"ok": True, **self.snapshot()}

    def resume(self, repo_id: str) -> dict[str, Any]:
        try:
            parse_repo_id(repo_id)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        with self._lock:
            item = self._ensure_item(repo_id, None)
            if self.busy:
                if self._active_id == repo_id:
                    return {"ok": True, "already": True, **self.snapshot()}
                item["status"] = "queued"
                if repo_id not in self._queue:
                    self._queue.append(repo_id)
                item["updated_at"] = time.time()
                self._save()
                return {"ok": True, "queued": True, **self.snapshot()}
        return self._launch(repo_id, item.get("assign_role"))

    def dismiss(self, repo_id: str) -> dict[str, Any]:
        with self._lock:
            item = self.items.get(repo_id)
            if item is None:
                return {"ok": False, "error": "unknown download"}
            if item.get("status") in {"running", "pausing"}:
                return {"ok": False, "error": "pause or delete the active download first"}
            self.items.pop(repo_id, None)
            if repo_id in self._queue:
                self._queue.remove(repo_id)
            self._save()
        return {"ok": True, **self.snapshot()}

    async def clear_partials(self, repo_id: str) -> dict[str, Any]:
        """Delete resumable artifacts only; completed model files are never removed."""
        try:
            dest = library_model_path(repo_id)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        if not await self.pause_wait(repo_id):
            return {"ok": False, "error": "download did not stop; no files were removed"}
        removed_files = 0
        removed_bytes = 0
        if dest.is_dir():
            for path in list(dest.rglob(f"*{PART_SUFFIX}")):
                if not path.is_file() or ".cache" in path.parts:
                    continue
                try:
                    removed_bytes += path.stat().st_size
                    path.unlink()
                    removed_files += 1
                except OSError as e:
                    return {"ok": False, "error": f"could not remove partial file: {e}"}
            try:
                (dest / _INCOMPLETE_MARKER).unlink(missing_ok=True)
            except OSError as e:
                return {"ok": False, "error": f"could not clear incomplete marker: {e}"}
            # Remove empty download-created directories, but never the repo root
            # and never a directory containing a completed file.
            for directory in sorted(
                (p for p in dest.rglob("*") if p.is_dir()),
                key=lambda p: len(p.parts),
                reverse=True,
            ):
                try:
                    directory.rmdir()
                except OSError:
                    pass
        self.forget(repo_id)
        return {
            "ok": True,
            "repo_id": repo_id,
            "removed_files": removed_files,
            "removed_bytes": removed_bytes,
            **self.snapshot(),
        }

    def _progress(self, step: str, detail: str = "") -> None:
        if self.job is None:
            return
        self.job["steps"].append({"step": step, "detail": detail, "t": time.time()})
        self.job["current"] = step
        if detail:
            self.job["detail"] = detail

    def _blank_item(self, repo_id: str, assign_role: str | None, dest: Path) -> dict[str, Any]:
        now = time.time()
        return {
            "repo_id": repo_id,
            "status": "queued",
            "assign_role": assign_role,
            "dest": str(dest),
            "bytes_done": 0,
            "bytes_total": 0,
            "current": "",
            "detail": "",
            "error": None,
            "added_at": now,
            "updated_at": now,
        }

    def _ensure_item(self, repo_id: str, assign_role: str | None) -> dict[str, Any]:
        dest = library_model_path(repo_id)
        item = self.items.get(repo_id)
        if item is None:
            item = self._blank_item(repo_id, assign_role, dest)
            self.items[repo_id] = item
        if assign_role in ("target", "draft"):
            item["assign_role"] = assign_role
        if item.get("status") == "done":
            item["status"] = "queued"
            item["error"] = None
        item["updated_at"] = time.time()
        return item

    def start(self, repo_id: str, assign_role: str | None = None) -> dict[str, Any]:
        try:
            parse_repo_id(repo_id)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        if assign_role not in (None, "target", "draft"):
            return {"ok": False, "error": "assign_role must be target, draft, or omitted"}
        with self._lock:
            item = self._ensure_item(repo_id, assign_role)
            if self.busy:
                if self._active_id == repo_id:
                    return {"ok": True, "already": True, **self.snapshot()}
                item["status"] = "queued"
                if repo_id not in self._queue:
                    self._queue.append(repo_id)
                self._save()
                return {"ok": True, "queued": True, **self.snapshot()}
        return self._launch(repo_id, assign_role)

    def _launch(self, repo_id: str, assign_role: str | None = None) -> dict[str, Any]:
        dest = library_model_path(repo_id)
        self._cancel.clear()
        self._stop_reason = "pause"
        self._acc_base = 0
        self._active_id = repo_id
        with self._lock:
            item = self._ensure_item(repo_id, assign_role)
            item["status"] = "running"
            item["error"] = None
            item["updated_at"] = time.time()
            if repo_id in self._queue:
                self._queue.remove(repo_id)
            role = item.get("assign_role")
            self._save()
        self.job = {
            "kind": "pull",
            "status": "running",
            "repo_id": repo_id,
            "dest": str(dest),
            "assign_role": role,
            "steps": [],
            "current": "queued",
            "detail": "",
            "bytes_done": int(item.get("bytes_done") or 0),
            "bytes_total": int(item.get("bytes_total") or 0),
            "started_at": time.time(),
            "result": None,
            "error": None,
        }

        manager = self

        class JobTqdm(tqdm):
            def update(self, n: float | None = 1) -> bool | None:
                if manager._cancel.is_set():
                    raise _Cancel("download paused")
                ok = super().update(n)
                if manager.job is not None:
                    done = int(manager._acc_base) + int(self.n or 0)
                    manager.job["bytes_done"] = done
                    if self.desc:
                        manager.job["detail"] = str(self.desc)
                return ok

        async def wrapper() -> None:
            kick = False
            try:
                result = await asyncio.to_thread(
                    self._download, repo_id, dest, role, JobTqdm, self._progress
                )
                self.job["result"] = result
                self.job["status"] = "done"
                self.job["current"] = "done"
                with self._lock:
                    row = self.items.get(repo_id)
                    if row:
                        row["status"] = "done"
                        row["error"] = None
                        row["bytes_done"] = self.job.get("bytes_done") or row.get("bytes_done")
                        row["updated_at"] = time.time()
                kick = True
            except _Cancel:
                self.job["status"] = "paused"
                self.job["current"] = "paused"
                self.job["error"] = None
                with self._lock:
                    row = self.items.get(repo_id)
                    if row:
                        row["status"] = "paused"
                        row["updated_at"] = time.time()
                        if self.job:
                            row["bytes_done"] = self.job.get("bytes_done") or row.get("bytes_done")
                kick = self._stop_reason == "delete"
            except Exception as e:
                log.exception("model pull failed")
                self.job["status"] = "error"
                self.job["error"] = str(e)
                self.job["current"] = "error"
                with self._lock:
                    row = self.items.get(repo_id)
                    if row:
                        row["status"] = "error"
                        row["error"] = str(e)
                        row["updated_at"] = time.time()
                kick = True
            finally:
                if self.job is not None:
                    self.job["finished_at"] = time.time()
                self._active_id = None
                self._task = None
                self._save()
                if kick:
                    nxt = self._pop_queue()
                    if nxt:
                        self._launch(nxt, (self.items.get(nxt) or {}).get("assign_role"))

        self._task = asyncio.get_event_loop().create_task(wrapper())
        return {"ok": True, **self.snapshot()}

    def _pop_queue(self) -> str | None:
        with self._lock:
            while self._queue:
                rid = self._queue.pop(0)
                row = self.items.get(rid)
                if row and row.get("status") == "queued":
                    self._save()
                    return rid
            return None

    def _load(self) -> None:
        from backend.core.config import DOWNLOADS_PATH
        try:
            raw = json.loads(DOWNLOADS_PATH.read_text(encoding="utf-8"))
            rows = raw.get("items") or []
            self.items = {str(i["repo_id"]): i for i in rows if i.get("repo_id")}
            self._queue = [rid for rid in (raw.get("queue") or []) if rid in self.items]
        except (OSError, json.JSONDecodeError, TypeError, KeyError):
            self.items = {}
            self._queue = []
        for row in self.items.values():
            if row.get("status") in {"running", "pausing"}:
                row["status"] = "paused"

    def _save(self) -> None:
        from backend.core.config import DOWNLOADS_PATH
        DOWNLOADS_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "items": list(self.items.values()),
            "queue": self._queue,
            "updated_at": time.time(),
        }
        tmp = DOWNLOADS_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, DOWNLOADS_PATH)

    def _hydrate_disk(self) -> None:
        from backend.models.registry import discover_incomplete_repos
        changed = False
        for rid in discover_incomplete_repos():
            if rid in self.items:
                if self.items[rid].get("status") == "running" and not (
                    self.busy and self._active_id == rid
                ):
                    self.items[rid]["status"] = "paused"
                    changed = True
                continue
            dest = library_model_path(rid)
            self.items[rid] = self._blank_item(rid, None, dest)
            self.items[rid]["status"] = "paused"
            changed = True
        if changed:
            self._save()

    async def pause_wait(self, repo_id: str | None = None, timeout: float = 12) -> bool:
        target = repo_id or self._active_id
        if not target:
            return True
        if self.busy and self._active_id == target:
            self._stop_reason = "delete"
            self._cancel.set()
            with self._lock:
                item = self.items.get(target)
                if item:
                    item["status"] = "pausing"
                    item["updated_at"] = time.time()
            task = self._task
            if task is not None and not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    return False
        else:
            self.pause(target)
        return not (self.busy and self._active_id == target)

    def forget(self, repo_id: str) -> None:
        with self._lock:
            self.items.pop(repo_id, None)
            if repo_id in self._queue:
                self._queue.remove(repo_id)
            self._save()

    def _download(
        self,
        repo_id: str,
        dest: Path,
        assign_role: str | None,
        tqdm_class: type,
        progress: ProgressFn,
    ) -> dict[str, Any]:
        from huggingface_hub.file_download import hf_hub_url
        from huggingface_hub.utils import build_hf_headers

        from backend.models.hub import hub_card

        progress("classify", repo_id)
        try:
            card = hub_card(repo_id)
        except FileNotFoundError as e:
            raise RuntimeError(f"repo not found: {repo_id}") from e
        pull_preflight(card)
        files = [row for row in (card.get("files") or []) if row.get("name")]
        if not files:
            raise RuntimeError("this repo lists no files to download")

        dest.mkdir(parents=True, exist_ok=True)
        marker = dest / _INCOMPLETE_MARKER
        already, total, resuming = existing_bytes(dest, files)
        if self.job is not None:
            self.job["bytes_done"] = already
            self.job["bytes_total"] = total
        with self._lock:
            row = self.items.get(repo_id)
            if row:
                row["bytes_done"] = already
                row["bytes_total"] = total
        marker.write_text("downloading\n", encoding="utf-8")
        progress("resume" if resuming else "download", str(dest))
        headers = build_hf_headers()

        acc = 0
        try:
            for rowf in files:
                if self._cancel.is_set():
                    raise _Cancel("download paused")
                rel = safe_relpath(str(rowf["name"]))
                target = dest / rel
                size = rowf.get("size_bytes")
                expected = int(size) if isinstance(size, int) else None
                if file_complete(target, expected):
                    acc += target.stat().st_size
                    if self.job is not None:
                        self.job["bytes_done"] = acc
                    continue
                self._acc_base = acc
                progress("file", rel.as_posix())
                download_file_resumable(
                    hf_hub_url(repo_id, rel.as_posix()),
                    target,
                    expected_size=expected,
                    headers=headers,
                    tqdm_class=tqdm_class,
                )
                acc += target.stat().st_size if target.is_file() else 0
                if self.job is not None:
                    self.job["bytes_done"] = acc
            if self._cancel.is_set():
                raise _Cancel("download paused")
        except _Cancel:
            raise
        if marker.exists():
            marker.unlink()

        progress("scan", "rescan library")
        found = scan_models()
        local = next((m for m in found if m["id"] == repo_id), None)
        if assign_role and local and card.get("runnable"):
            set_role(repo_id, assign_role)
            from backend.core.config import update_config
            if assign_role == "target":
                update_config({"runtime": {"target_model": repo_id}})
                from backend.core.alias import sync_alias_for_target
                sync_alias_for_target(repo_id)
            elif assign_role == "draft":
                update_config({"runtime": {"draft_model": repo_id}})
            progress("role", assign_role)
        return {
            "ok": True,
            "repo_id": repo_id,
            "dest": str(dest),
            "role": assign_role if (assign_role and card.get("runnable")) else None,
            "found": local is not None,
            "resumed": resuming,
            "size_bytes": None if local is None else local.get("size_bytes"),
        }


pull_manager = PullJobManager()
