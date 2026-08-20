"""SQLite persistence (WAL mode, shared by control backend only).

Privacy: prompt/response bodies are never stored unless privacy.log_prompts
is explicitly enabled — and even then only benchmark prompts, which are fixed
public strings, are kept.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator

from backend.core.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS models (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    provider TEXT,
    architecture TEXT,
    parameter_size TEXT,
    quantization TEXT,
    format TEXT,
    local_path TEXT,
    huggingface_repo TEXT,
    role TEXT DEFAULT 'none',
    compatibility TEXT,
    context_length INTEGER,
    memory_estimate_gb REAL,
    size_bytes INTEGER,
    status TEXT DEFAULT 'available',
    extra TEXT
);

CREATE TABLE IF NOT EXISTS benchmark_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,              -- quick | ab | autotune | agent | long_context | tool_calling
    label TEXT,
    mode TEXT,                       -- safe | fast | ab
    prompt_key TEXT,
    config TEXT,                     -- json: runtime settings used
    results TEXT NOT NULL,           -- json: measured numbers
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,              -- start | stop | restart | crash | fallback | mode_change | model_load | warning
    detail TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_connections (
    agent TEXT PRIMARY KEY,
    last_seen REAL,
    last_test REAL,
    last_test_ok INTEGER,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS settings_kv (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def add_event(kind: str, detail: str | dict[str, Any] = "") -> None:
    if isinstance(detail, dict):
        detail = json.dumps(detail, ensure_ascii=False)
    with db() as conn:
        conn.execute(
            "INSERT INTO runtime_events (kind, detail, created_at) VALUES (?, ?, ?)",
            (kind, detail, time.time()),
        )


def recent_events(limit: int = 100) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM runtime_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def save_benchmark(kind: str, label: str, mode: str, prompt_key: str,
                   config: dict[str, Any], results: dict[str, Any]) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO benchmark_runs (kind, label, mode, prompt_key, config, results, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kind, label, mode, prompt_key,
             json.dumps(config, ensure_ascii=False),
             json.dumps(results, ensure_ascii=False),
             time.time()),
        )
        return int(cur.lastrowid)


def benchmark_history(limit: int = 50, kind: str | None = None) -> list[dict[str, Any]]:
    q = "SELECT * FROM benchmark_runs"
    args: tuple = ()
    if kind:
        q += " WHERE kind = ?"
        args = (kind,)
    q += " ORDER BY id DESC LIMIT ?"
    args = args + (limit,)
    with db() as conn:
        rows = conn.execute(q, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["config"] = json.loads(d["config"] or "{}")
        d["results"] = json.loads(d["results"] or "{}")
        out.append(d)
    return out
