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


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _positive(v: Any) -> float | None:
    n = _num(v)
    if n is None or n <= 0:
        return None
    return n


def _rate_unit(v: Any) -> float | None:
    """Acceptance: keep 0–1 fractions; older dumps used 0–100 percent."""
    n = _num(v)
    if n is None:
        return None
    return n / 100.0 if n > 1.0 else n


def _prefill_from_request(req: dict[str, Any] | None) -> float | None:
    if not isinstance(req, dict):
        return None
    seconds = _positive(req.get("prefill_s"))
    tokens = _num(
        req.get("prefill_tokens_processed")
        or req.get("prefill_tokens_total")
        or req.get("prompt_tokens")
    )
    if seconds is None or tokens is None:
        return None
    return tokens / seconds


def _mean(vals: list[float]) -> float | None:
    return sum(vals) / len(vals) if vals else None


def runtime_fields_from_dflash(data: dict[str, Any]) -> dict[str, Any]:
    """Map dflash-mlx /metrics JSON onto the Overview runtime card.

    dflash-mlx 0.1.8 keeps live decode speed on ``current_request`` and
    ``rates.active_decode_tok_s``. ``rates.average_decode_tok_s`` stays null
    until a request finishes, and ``recent_requests`` is empty while one is
    in flight — that is why Overview showed em dashes during a real chat.
    """
    rates = data.get("rates") if isinstance(data.get("rates"), dict) else {}
    memory = data.get("memory") if isinstance(data.get("memory"), dict) else {}
    totals = data.get("totals") if isinstance(data.get("totals"), dict) else {}
    cur = data.get("current_request") if isinstance(data.get("current_request"), dict) else {}
    last = data.get("last_request") if isinstance(data.get("last_request"), dict) else {}
    recents = [r for r in (data.get("recent_requests") or []) if isinstance(r, dict)]
    latest_done = recents[-1] if recents else last

    decode = (
        _positive(cur.get("decode_tok_s"))
        or _positive(rates.get("active_decode_tok_s"))
        or _positive(rates.get("average_decode_tok_s"))
        or _positive(latest_done.get("decode_tok_s"))
        or _positive(rates.get("generated_tokens_per_s"))
    )
    prefill = (
        _positive(rates.get("prefill_tok_s_physical"))
        or _positive(rates.get("prefill_tok_s"))
        or _positive(rates.get("prefill_tokens_physical_per_s"))
        or _prefill_from_request(cur)
        or _prefill_from_request(latest_done)
    )
    rss = _positive(data.get("rss_gb")) or _positive(memory.get("rss_gb"))

    accs = [_rate_unit(r.get("acceptance_rate")) for r in recents]
    accs = [a for a in accs if a is not None]
    acceptance = (
        _rate_unit(cur.get("acceptance_rate"))
        or _rate_unit(latest_done.get("acceptance_rate"))
        or _mean(accs)
    )

    ttfts = [_num(r.get("ttft_s") if r.get("ttft_s") is not None else r.get("ttft")) for r in recents]
    ttfts = [t for t in ttfts if t is not None and t >= 0]
    ttft = (
        _num(cur.get("ttft_s") if cur.get("ttft_s") is not None else cur.get("ttft"))
        or _num(latest_done.get("ttft_s") if latest_done.get("ttft_s") is not None else latest_done.get("ttft"))
        or _mean(ttfts)
    )

    completed = _num(totals.get("requests"))
    if completed is None:
        completed = float(len(recents))

    state = str(cur.get("state") or "")
    active = state in {"prefill", "decode", "running"} or (
        bool(cur) and _num(cur.get("request_id")) is not None
    )

    raw: dict[str, Any] = {}
    cache = cur.get("cache_status") or data.get("cache_status")
    if cache:
        raw["cache_status"] = cache
    for key in (
        "tokens_per_cycle",
        "cycles",
        "verify_mode",
        "verify_block_tokens",
        "draft_block_tokens",
        "adaptive_block",
    ):
        value = cur.get(key)
        if value is None:
            value = latest_done.get(key)
        if value is None:
            value = data.get(key)
        if value is not None:
            raw[key] = value

    out: dict[str, Any] = {
        "decode_tok_s": decode,
        "prefill_tok_s": prefill,
        "rss_gb": rss,
        "active_request": active,
        "requests_completed": int(completed),
        "raw": raw,
    }
    if acceptance is not None:
        out["acceptance_rate"] = acceptance
    if ttft is not None:
        out["ttft_s"] = ttft
    return out


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
            sample["runtime"] = runtime_fields_from_dflash(m.get("data") or {})
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
