"""Benchmark engine.

All numbers are measured against the real gateway + runtime — never mocked.
Long operations (A/B, auto-tune) run as a single background job with visible
progress; results are persisted to SQLite.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx
import psutil

from backend.benchmark.prompts import BENCHMARK_PROMPTS, build_long_context_prompt
from backend.core.config import load_config, update_config
from backend.core.state import read_state
from backend.database.db import add_event, save_benchmark

log = logging.getLogger("lacc.benchmark")


def _gateway_base() -> str:
    cfg = load_config()
    return f"http://{cfg['api']['host']}:{cfg['api']['port']}"


def _resolve_prompt(prompt_key: str) -> tuple[str, int]:
    spec = BENCHMARK_PROMPTS[prompt_key]
    if spec.get("prompt_builder") == "long_context":
        return build_long_context_prompt(), spec["max_tokens"]
    return spec["prompt"], spec["max_tokens"]


async def measure_generation(prompt: str, max_tokens: int) -> dict[str, Any]:
    """One streamed request via the gateway; returns real measured numbers."""
    cfg = load_config()
    alias = cfg["api"]["alias"]
    body = {
        "model": alias,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": True,
    }
    swap_before = psutil.swap_memory().used
    mem_before = psutil.virtual_memory()

    t_start = time.perf_counter()
    ttft: float | None = None
    chunk_tokens = 0
    usage_tokens: int | None = None
    error: str | None = None

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=5)) as client:
            async with client.stream(
                "POST", _gateway_base() + "/v1/chat/completions", json=body
            ) as r:
                if r.status_code >= 400:
                    text = (await r.aread()).decode(errors="replace")[:500]
                    return {"ok": False, "error": f"HTTP {r.status_code}: {text}"}
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        obj = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    for choice in obj.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("content") or delta.get("tool_calls") or delta.get("reasoning_content"):
                            if ttft is None:
                                ttft = time.perf_counter() - t_start
                            chunk_tokens += 1
                    usage = obj.get("usage")
                    if usage and usage.get("completion_tokens"):
                        usage_tokens = int(usage["completion_tokens"])
    except httpx.HTTPError as e:
        error = str(e)

    total_s = time.perf_counter() - t_start
    tokens = usage_tokens if usage_tokens else chunk_tokens
    mem_after = psutil.virtual_memory()
    gen_s = total_s - (ttft or 0)

    if error or tokens == 0:
        return {"ok": False, "error": error or "no tokens generated"}

    return {
        "ok": True,
        "tokens": tokens,
        "total_s": round(total_s, 3),
        "ttft_s": round(ttft, 3) if ttft is not None else None,
        "tok_s": round(tokens / gen_s, 2) if gen_s > 0 else None,
        "ram_used_gb": round((mem_after.total - mem_after.available) / 1e9, 2),
        "ram_delta_gb": round((mem_before.available - mem_after.available) / 1e9, 2),
        "swap_delta_gb": round((psutil.swap_memory().used - swap_before) / 1e9, 2),
        "token_source": "usage" if usage_tokens else "stream_chunks",
    }


async def fetch_runtime_acceptance() -> float | None:
    """Read acceptance of the most recent request from dflash /metrics."""
    st = read_state()
    if st.mode != "fast":
        return None
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"http://{st.internal_host}:{st.internal_port}/metrics")
            data = r.json()
        recents = data.get("recent_requests") or []
        if recents:
            v = recents[-1].get("acceptance_rate")
            if isinstance(v, (int, float)):
                return float(v) if v <= 1 else float(v) / 100
    except (httpx.HTTPError, ValueError):
        pass
    return None


async def run_tool_calling_probe() -> dict[str, Any]:
    """Real check: does the runtime emit OpenAI tool_calls?"""
    cfg = load_config()
    body = {
        "model": cfg["api"]["alias"],
        "messages": [{"role": "user", "content": "What is the weather in Tokyo right now? Use the tool."}],
        "tools": [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get current weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }],
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": 256,
        "stream": False,
    }
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(_gateway_base() + "/v1/chat/completions", json=body)
        elapsed = round(time.perf_counter() - t0, 2)
        if r.status_code >= 400:
            return {"ok": False, "supported": False,
                    "error": f"HTTP {r.status_code}: {r.text[:300]}", "elapsed_s": elapsed}
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        tool_calls = msg.get("tool_calls") or []
        valid = False
        parsed_args = None
        if tool_calls:
            fn = tool_calls[0].get("function") or {}
            if fn.get("name") == "get_weather":
                try:
                    parsed_args = json.loads(fn.get("arguments") or "{}")
                    valid = "city" in parsed_args
                except json.JSONDecodeError:
                    valid = False
        return {
            "ok": True,
            "supported": bool(tool_calls),
            "valid_call": valid,
            "tool_calls": tool_calls,
            "arguments": parsed_args,
            "finish_reason": choice.get("finish_reason"),
            "elapsed_s": elapsed,
        }
    except httpx.HTTPError as e:
        return {"ok": False, "supported": False, "error": str(e)}


# ------------------------------------------------------------------ jobs

class BenchmarkJobManager:
    """One background job at a time, with observable progress."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self.job: dict[str, Any] | None = None

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def _progress(self, step: str, detail: str = "") -> None:
        if self.job is not None:
            self.job["steps"].append({"step": step, "detail": detail, "t": time.time()})
            self.job["current"] = step

    def start_job(self, kind: str, coro_factory) -> dict[str, Any]:
        if self.busy:
            return {"ok": False, "error": "another benchmark job is already running"}
        self.job = {"kind": kind, "status": "running", "steps": [],
                    "current": "queued", "started_at": time.time(), "result": None}

        async def wrapper():
            try:
                result = await coro_factory(self._progress)
                self.job["result"] = result
                self.job["status"] = "done"
            except Exception as e:  # keep the failure visible, never silent
                log.exception("benchmark job failed")
                self.job["status"] = "error"
                self.job["error"] = str(e)
            finally:
                self.job["finished_at"] = time.time()

        self._task = asyncio.get_event_loop().create_task(wrapper())
        return {"ok": True, "job": self.job}

    # ---------- job implementations ----------

    async def _run_quick(self, progress, prompt_key: str) -> dict[str, Any]:
        st = read_state()
        prompt, max_tokens = _resolve_prompt(prompt_key)
        progress("generate", f"mode={st.mode} prompt={prompt_key}")
        res = await measure_generation(prompt, max_tokens)
        if res.get("ok"):
            res["acceptance_rate"] = await fetch_runtime_acceptance()
            res["mode"] = st.mode
        run_id = save_benchmark("quick", BENCHMARK_PROMPTS[prompt_key]["label"],
                                st.mode, prompt_key, _current_bench_config(), res)
        res["run_id"] = run_id
        return res

    async def _run_ab(self, progress, prompt_key: str) -> dict[str, Any]:
        from backend.runtime.manager import runtime_manager
        prompt, max_tokens = _resolve_prompt(prompt_key)
        original_mode = read_state().mode
        out: dict[str, Any] = {"prompt_key": prompt_key}

        try:
            progress("safe_mode_start", "restarting runtime target-only")
            status = await runtime_manager.restart("safe")
            if not status.get("http_healthy"):
                raise RuntimeError(f"safe mode failed to start: {status.get('error')}")
            progress("safe_mode_warmup")
            await measure_generation("Warm up.", 8)
            progress("safe_mode_benchmark")
            normal = await measure_generation(prompt, max_tokens)
            out["normal"] = normal

            progress("fast_mode_start", "restarting runtime with DFlash draft")
            status = await runtime_manager.restart("fast")
            if not status.get("http_healthy"):
                raise RuntimeError(f"fast mode failed to start: {status.get('error')}")
            progress("fast_mode_warmup")
            await measure_generation("Warm up.", 8)
            progress("fast_mode_benchmark")
            dflash = await measure_generation(prompt, max_tokens)
            dflash["acceptance_rate"] = await fetch_runtime_acceptance()
            out["dflash"] = dflash

            if normal.get("ok") and dflash.get("ok") and normal.get("tok_s") and dflash.get("tok_s"):
                out["speedup"] = round(dflash["tok_s"] / normal["tok_s"], 2)
            out["ok"] = normal.get("ok", False) and dflash.get("ok", False)
        finally:
            if read_state().mode != original_mode:
                progress("restore_mode", f"restoring {original_mode}")
                await runtime_manager.restart(original_mode)

        run_id = save_benchmark("ab", BENCHMARK_PROMPTS[prompt_key]["label"], "ab",
                                prompt_key, _current_bench_config(), out)
        out["run_id"] = run_id
        add_event("benchmark", {"kind": "ab", "speedup": out.get("speedup")})
        return out

    async def _run_autotune(self, progress) -> dict[str, Any]:
        """Benchmark real dflash-mlx knobs and recommend the fastest stable one.

        The draft checkpoint's block size (16) is fixed at training time, so we
        tune what actually exists: verify-len-cap and verify-mode.
        """
        from backend.runtime.manager import runtime_manager
        prompt, max_tokens = _resolve_prompt("coding_long")
        candidates = [
            {"verify_mode": "adaptive", "verify_len_cap": 0, "label": "adaptive (default)"},
            {"verify_mode": "dflash", "verify_len_cap": 0, "label": "fixed verify, full block"},
            {"verify_mode": "dflash", "verify_len_cap": 8, "label": "fixed verify, cap 8"},
            {"verify_mode": "dflash", "verify_len_cap": 4, "label": "fixed verify, cap 4"},
        ]
        original = load_config()["dflash"]
        results = []
        try:
            for cand in candidates:
                progress("tune_candidate", cand["label"])
                update_config({"dflash": {"verify_mode": cand["verify_mode"],
                                          "verify_len_cap": cand["verify_len_cap"]}})
                status = await runtime_manager.restart("fast")
                if not status.get("http_healthy"):
                    results.append({**cand, "ok": False, "error": status.get("error")})
                    continue
                await measure_generation("Warm up.", 8)
                r = await measure_generation(prompt, max_tokens)
                r["acceptance_rate"] = await fetch_runtime_acceptance()
                results.append({**cand, **r})
        finally:
            progress("restore_config")
            update_config({"dflash": {"verify_mode": original["verify_mode"],
                                      "verify_len_cap": original["verify_len_cap"]}})

        valid = [r for r in results if r.get("ok") and r.get("tok_s")]
        best = max(valid, key=lambda r: r["tok_s"]) if valid else None
        out = {"ok": bool(best), "candidates": results, "recommended": best}
        if best:
            out["recommendation_text"] = (
                f"Recommended: {best['label']} — {best['tok_s']} tok/s"
                + (f", acceptance {best['acceptance_rate']:.0%}" if best.get("acceptance_rate") else "")
            )
        run_id = save_benchmark("autotune", "Auto Tune DFlash", "fast", "coding_long",
                                _current_bench_config(), out)
        out["run_id"] = run_id
        return out

    async def _run_tool_calling(self, progress) -> dict[str, Any]:
        st = read_state()
        progress("tool_probe", f"mode={st.mode}")
        res = await run_tool_calling_probe()
        run_id = save_benchmark("tool_calling", "Tool Calling Probe", st.mode,
                                "tool_probe", _current_bench_config(), res)
        res["run_id"] = run_id
        return res

    # public API
    def quick(self, prompt_key: str):
        return self.start_job("quick", lambda p: self._run_quick(p, prompt_key))

    def ab(self, prompt_key: str):
        return self.start_job("ab", lambda p: self._run_ab(p, prompt_key))

    def autotune(self):
        return self.start_job("autotune", self._run_autotune)

    def tool_calling(self):
        return self.start_job("tool_calling", self._run_tool_calling)


def _current_bench_config() -> dict[str, Any]:
    cfg = load_config()
    return {"runtime": cfg["runtime"], "dflash": cfg["dflash"]}


job_manager = BenchmarkJobManager()
