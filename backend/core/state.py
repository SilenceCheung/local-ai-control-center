"""Cross-process runtime state contract.

The control backend owns writes; the gateway and CLI only read. The file lives
in data/runtime_state.json so that a control-plane restart can re-attach to a
still-running inference process instead of killing it.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.core.config import STATE_PATH


@dataclass
class RuntimeState:
    status: str = "stopped"  # stopped | starting | running | stopping | error
    mode: str = "fast"  # safe | fast
    provider: str = "mlx"
    pid: int | None = None
    internal_host: str = "127.0.0.1"
    internal_port: int = 18080
    alias: str = "Qwen3.8-27B-Heretic-8bit"
    target_model: str | None = None
    target_path: str | None = None
    draft_model: str | None = None
    draft_path: str | None = None
    # Immutable, privacy-safe snapshot of the arguments that were effective
    # when this process was launched.  Disk configuration may change while a
    # model remains loaded, so the UI must not present saved values as live.
    launch_config: dict[str, Any] | None = None
    started_at: float | None = None
    updated_at: float = field(default_factory=time.time)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_state() -> RuntimeState:
    try:
        with open(STATE_PATH) as f:
            raw = json.load(f)
        known = {k: raw[k] for k in RuntimeState.__dataclass_fields__ if k in raw}
        return RuntimeState(**known)
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return RuntimeState()


def write_state(state: RuntimeState) -> None:
    state.updated_at = time.time()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(state.to_dict(), f, indent=2)
    os.replace(tmp, STATE_PATH)


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
