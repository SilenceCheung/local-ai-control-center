"""RuntimeManager — supervises the active RuntimeProvider.

Responsibilities:
- re-attach to an already-running inference process after a control restart
- watchdog: if FAST mode crashes, automatically fall back to SAFE mode
  (user requests must not just die); records a fallback event
- DFlash advisory: if acceptance rate stays below threshold, emit a warning
  event recommending Safe Mode (advisory only, no forced switch)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from backend.core.state import pid_alive, read_state
from backend.database.db import add_event
from backend.runtime.mlx_provider import MLXRuntimeProvider

log = logging.getLogger("lacc.runtime")

ACCEPTANCE_WARN_THRESHOLD = 0.25
ACCEPTANCE_WARN_WINDOW_S = 120


class RuntimeManager:
    def __init__(self) -> None:
        self.provider = MLXRuntimeProvider()
        self._watchdog_task: asyncio.Task | None = None
        self._low_acceptance_since: float | None = None
        self._advisory: dict[str, Any] | None = None
        self._fallback_count = 0

    # ---------- lifecycle passthrough ----------

    async def start(self, mode: str | None = None) -> dict[str, Any]:
        from backend.core.config import load_config, update_config
        cfg = load_config()
        mode = mode or cfg["runtime"]["mode"]
        if mode != cfg["runtime"]["mode"]:
            update_config({"runtime": {"mode": mode}})
        return await self.provider.start(mode)

    async def stop(self) -> dict[str, Any]:
        return await self.provider.stop()

    async def restart(self, mode: str | None = None) -> dict[str, Any]:
        from backend.core.config import load_config, update_config
        if mode:
            cfg = load_config()
            if mode != cfg["runtime"]["mode"]:
                update_config({"runtime": {"mode": mode}})
        return await self.provider.restart(mode)

    async def set_mode(self, mode: str) -> dict[str, Any]:
        """Switch safe/fast. Restarts the inference process only if running."""
        assert mode in ("safe", "fast")
        from backend.core.config import update_config
        update_config({"runtime": {"mode": mode}})
        add_event("mode_change", {"mode": mode})
        state = read_state()
        if state.status in ("running", "starting") and pid_alive(state.pid):
            return await self.provider.restart(mode)
        return await self.provider.status()

    async def status(self) -> dict[str, Any]:
        d = await self.provider.status()
        d["advisory"] = self._advisory
        d["fallback_count"] = self._fallback_count
        return d

    # ---------- boot / watchdog ----------

    async def on_boot(self) -> None:
        """Re-attach or auto-start according to config."""
        from backend.core.config import load_config
        state = read_state()
        if state.status == "running" and pid_alive(state.pid):
            h = await self.provider.health()
            if h.get("ok"):
                log.info("re-attached to running inference pid=%s mode=%s", state.pid, state.mode)
            else:
                log.warning("stale runtime state (pid alive but unhealthy)")
        cfg = load_config()
        if cfg["runtime"].get("auto_load") and not (state.status == "running" and pid_alive(state.pid)):
            log.info("auto_load enabled -> starting runtime")
            asyncio.get_event_loop().create_task(self.start())
        self._watchdog_task = asyncio.get_event_loop().create_task(self._watchdog())

    async def shutdown(self) -> None:
        if self._watchdog_task:
            self._watchdog_task.cancel()
        # NOTE: we intentionally do NOT stop the inference process here —
        # control-plane restarts must not interrupt inference.

    async def _watchdog(self) -> None:
        while True:
            try:
                await asyncio.sleep(5)
                await self._watchdog_tick()
            except asyncio.CancelledError:
                return
            except Exception:  # watchdog must never die
                log.exception("watchdog tick failed")

    async def _watchdog_tick(self) -> None:
        state = read_state()
        if state.status == "running" and not pid_alive(state.pid):
            add_event("crash", {"mode": state.mode, "pid": state.pid})
            if state.mode == "fast":
                # Automatic failover: FAST crashed -> bring service back in SAFE
                self._fallback_count += 1
                add_event("fallback", {
                    "from": "fast", "to": "safe",
                    "reason": "fast-mode inference process crashed",
                })
                log.warning("FAST mode crashed; falling back to SAFE mode")
                await self.provider.start("safe")
                self._advisory = {
                    "level": "warning",
                    "title": "DFlash runtime crashed — fell back to Safe Mode",
                    "detail": "The speculative-decoding process died and was restarted target-only. "
                              "Check Logs for the crash cause before re-enabling Fast Mode.",
                    "at": time.time(),
                }
            return

        # acceptance advisory (fast mode only)
        if state.status == "running" and state.mode == "fast":
            m = await self.provider.metrics()
            acc = _extract_acceptance(m)
            if acc is not None:
                now = time.time()
                if acc < ACCEPTANCE_WARN_THRESHOLD:
                    if self._low_acceptance_since is None:
                        self._low_acceptance_since = now
                    elif now - self._low_acceptance_since > ACCEPTANCE_WARN_WINDOW_S:
                        if not (self._advisory and self._advisory.get("kind") == "low_acceptance"):
                            self._advisory = {
                                "kind": "low_acceptance",
                                "level": "warning",
                                "title": "DFlash performance is currently worse than baseline",
                                "detail": f"Draft acceptance rate has stayed below "
                                          f"{ACCEPTANCE_WARN_THRESHOLD:.0%} for over "
                                          f"{ACCEPTANCE_WARN_WINDOW_S}s. Safe Mode is recommended.",
                                "at": now,
                            }
                            add_event("warning", {"kind": "low_acceptance", "acceptance": acc})
                else:
                    self._low_acceptance_since = None
                    if self._advisory and self._advisory.get("kind") == "low_acceptance":
                        self._advisory = None


def _extract_acceptance(metrics: dict[str, Any]) -> float | None:
    if not metrics.get("available"):
        return None
    data = metrics.get("data") or {}
    for key in ("acceptance_rate", "acceptance"):
        v = data.get(key)
        if isinstance(v, (int, float)):
            return float(v) if v <= 1 else float(v) / 100.0
    recents = data.get("recent_requests") or []
    vals = [r.get("acceptance_rate") for r in recents if isinstance(r.get("acceptance_rate"), (int, float))]
    if vals:
        avg = sum(vals) / len(vals)
        return avg if avg <= 1 else avg / 100.0
    return None


runtime_manager = RuntimeManager()
