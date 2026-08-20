"""System + runtime metrics sampler.

Samples every 2 s into a ring buffer; pushed to the dashboard over SSE so the
frontend never needs to poll aggressively. Memory-safety rules live here.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from collections import deque
from typing import Any

import psutil

from backend.core.config import load_config
from backend.database.db import add_event

log = logging.getLogger("lacc.monitor")

SAMPLE_INTERVAL_S = 2.0
BUFFER_LEN = 450  # 15 minutes


def _memory_pressure_level() -> int | None:
    """macOS kernel memory pressure: 1=normal 2=warning 4=critical."""
    try:
        out = subprocess.run(
            ["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
            capture_output=True, text=True, timeout=1,
        )
        return int(out.stdout.strip())
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


class MetricsSampler:
    def __init__(self) -> None:
        self.buffer: deque[dict[str, Any]] = deque(maxlen=BUFFER_LEN)
        self._task: asyncio.Task | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._swap_warned_at: float = 0.0
        self.memory_advisory: dict[str, Any] | None = None

    def start(self) -> None:
        self._task = asyncio.get_event_loop().create_task(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def _loop(self) -> None:
        from backend.runtime.manager import runtime_manager
        while True:
            try:
                sample = await self._sample(runtime_manager)
                self.buffer.append(sample)
                self._check_memory_safety(sample)
                for q in list(self._subscribers):
                    if q.full():
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    q.put_nowait(sample)
            except asyncio.CancelledError:
                return
            except Exception:
                log.exception("sampler tick failed")
            await asyncio.sleep(SAMPLE_INTERVAL_S)

    async def _sample(self, runtime_manager) -> dict[str, Any]:
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
        sample: dict[str, Any] = {
            "t": time.time(),
            "cpu_pct": psutil.cpu_percent(interval=None),
            "mem_used_gb": round((vm.total - vm.available) / 1e9, 2),
            "mem_total_gb": round(vm.total / 1e9, 2),
            "mem_pct": vm.percent,
            "swap_used_gb": round(swap.used / 1e9, 2),
            "pressure_level": _memory_pressure_level(),
        }
        m = await runtime_manager.provider.metrics()
        if m.get("available"):
            data = m["data"]
            rates = data.get("rates") or {}
            cur = data.get("current_request") or {}
            sample["runtime"] = {
                "decode_tok_s": rates.get("average_decode_tok_s"),
                "prefill_tok_s": rates.get("prefill_tok_s_physical") or rates.get("prefill_tok_s"),
                "rss_gb": data.get("rss_gb"),
                "active_request": bool(cur),
                "requests_completed": len(data.get("recent_requests") or []),
                "raw": {k: data.get(k) for k in ("cache_status",) if k in data},
            }
            recents = data.get("recent_requests") or []
            accs = [r.get("acceptance_rate") for r in recents
                    if isinstance(r.get("acceptance_rate"), (int, float))]
            if accs:
                avg = sum(accs) / len(accs)
                sample["runtime"]["acceptance_rate"] = avg if avg <= 1 else avg / 100
            ttfts = [r.get("ttft_s") or r.get("ttft") for r in recents]
            ttfts = [t for t in ttfts if isinstance(t, (int, float))]
            if ttfts:
                sample["runtime"]["ttft_s"] = sum(ttfts) / len(ttfts)
        return sample

    def _check_memory_safety(self, sample: dict[str, Any]) -> None:
        cfg = load_config()
        swap_warn = float(cfg["memory"]["swap_warn_gb"])
        now = time.time()
        pressure = sample.get("pressure_level") or 1
        swap_gb = sample.get("swap_used_gb") or 0.0

        if swap_gb > swap_warn or pressure >= 4:
            self.memory_advisory = {
                "level": "critical" if pressure >= 4 else "warning",
                "title": "Memory pressure is high",
                "detail": (
                    f"Swap in use: {swap_gb:.1f} GB (threshold {swap_warn:.0f} GB), "
                    f"kernel pressure level {pressure}. Recommendations: lower max context, "
                    "reduce parallel requests, or unload the model."
                ),
                "at": now,
            }
            if now - self._swap_warned_at > 300:
                self._swap_warned_at = now
                add_event("warning", {"kind": "memory", "swap_gb": swap_gb, "pressure": pressure})
        elif pressure >= 2:
            self.memory_advisory = {
                "level": "warning",
                "title": "Memory pressure elevated",
                "detail": "macOS reports elevated memory pressure. Watch swap usage before "
                          "loading additional models.",
                "at": now,
            }
        else:
            self.memory_advisory = None

    def snapshot(self, n: int = BUFFER_LEN) -> list[dict[str, Any]]:
        return list(self.buffer)[-n:]


sampler = MetricsSampler()
