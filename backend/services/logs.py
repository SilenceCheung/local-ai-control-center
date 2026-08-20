"""Log access: categorized tail/search over the project's log files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from backend.core.config import LOGS_DIR

LOG_FILES: dict[str, str] = {
    "runtime": "runtime.log",
    "api": "gateway.log",
    "backend": "backend.log",
    "benchmark": "benchmark.log",
}

_LEVEL_RE = re.compile(r"\b(ERROR|CRITICAL|WARN(?:ING)?|Traceback|Exception|failed|crash)", re.I)
_IMPORTANT_RE = re.compile(
    r"\b(ERROR|CRITICAL|WARN(?:ING)?|Traceback|restart|start|stop|load|model|benchmark|fallback)", re.I
)


def read_log(category: str, lines: int = 300, query: str = "",
             errors_only: bool = False, important_only: bool = True) -> dict[str, Any]:
    fname = LOG_FILES.get(category)
    if not fname:
        return {"ok": False, "error": f"unknown log category '{category}'"}
    path = Path(LOGS_DIR) / fname
    if not path.exists():
        return {"ok": True, "lines": [], "path": str(path), "note": "log file does not exist yet"}
    try:
        raw = path.read_text(errors="replace").splitlines()
    except OSError as e:
        return {"ok": False, "error": str(e)}

    out = raw
    if errors_only:
        out = [l for l in out if _LEVEL_RE.search(l)]
    elif important_only:
        out = [l for l in out if _IMPORTANT_RE.search(l)] or raw[-50:]
    if query:
        q = query.lower()
        out = [l for l in out if q in l.lower()]
    return {"ok": True, "lines": out[-lines:], "path": str(path), "total_lines": len(raw)}


def list_categories() -> list[dict[str, Any]]:
    out = []
    for cat, fname in LOG_FILES.items():
        p = Path(LOGS_DIR) / fname
        out.append({
            "category": cat,
            "file": str(p),
            "exists": p.exists(),
            "size_bytes": p.stat().st_size if p.exists() else 0,
        })
    return out
