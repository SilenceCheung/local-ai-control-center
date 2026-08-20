"""Control-plane API routes (all under /api)."""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.benchmark.engine import job_manager
from backend.benchmark.prompts import BENCHMARK_PROMPTS
from backend.core.config import GATEWAY_STATS_PATH, load_config, update_config
from backend.core.state import read_state
from backend.database.db import benchmark_history, recent_events
from backend.integrations import agents as agents_mod
from backend.models import registry
from backend.monitoring.sampler import sampler
from backend.runtime.manager import runtime_manager
from backend.services import launchd, logs as logs_mod

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ health

@router.get("/health")
async def health() -> dict[str, Any]:
    rt = await runtime_manager.status()
    gateway = await _gateway_health()
    cfg = load_config()
    return {
        "backend": "ok",
        "time": time.time(),
        "runtime": {
            "status": rt["status"],
            "mode": rt["mode"],
            "process_alive": rt["process_alive"],
            "http_healthy": rt["http_healthy"],
            "model_loaded": rt["http_healthy"],
            "draft_loaded": rt["http_healthy"] and rt["mode"] == "fast",
            "error": rt.get("error"),
        },
        "api": gateway,
        "ports": {"dashboard": cfg["dashboard"]["port"], "api": cfg["api"]["port"]},
    }


async def _gateway_health() -> dict[str, Any]:
    cfg = load_config()
    url = f"http://{cfg['api']['host']}:{cfg['api']['port']}/health"
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            r = await client.get(url)
            return {"ok": r.status_code == 200, "detail": r.json()}
    except (httpx.HTTPError, ValueError):
        return {"ok": False, "detail": "gateway process is not responding on port "
                                       f"{cfg['api']['port']}"}


# ------------------------------------------------------------------ runtime

class ModeBody(BaseModel):
    mode: str


@router.get("/runtime/status")
async def runtime_status() -> dict[str, Any]:
    return await runtime_manager.status()


@router.post("/runtime/start")
async def runtime_start(body: ModeBody | None = None) -> dict[str, Any]:
    return await runtime_manager.start(body.mode if body else None)


@router.post("/runtime/stop")
async def runtime_stop() -> dict[str, Any]:
    return await runtime_manager.stop()


@router.post("/runtime/restart")
async def runtime_restart(body: ModeBody | None = None) -> dict[str, Any]:
    return await runtime_manager.restart(body.mode if body else None)


@router.post("/runtime/mode")
async def runtime_mode(body: ModeBody) -> dict[str, Any]:
    if body.mode not in ("safe", "fast"):
        raise HTTPException(422, "mode must be 'safe' or 'fast'")
    return await runtime_manager.set_mode(body.mode)


@router.get("/runtime/metrics")
async def runtime_metrics() -> dict[str, Any]:
    return await runtime_manager.provider.metrics()


# ------------------------------------------------------------------ models

class RoleBody(BaseModel):
    model_id: str
    role: str


@router.get("/models")
async def models_list() -> list[dict[str, Any]]:
    return registry.list_models()


@router.post("/models/scan")
async def models_scan() -> dict[str, Any]:
    found = await asyncio.to_thread(registry.scan_models)
    return {"ok": True, "found": len(found)}


@router.post("/models/role")
async def models_role(body: RoleBody) -> dict[str, Any]:
    if body.role not in ("target", "draft", "embedding", "reranker", "none"):
        raise HTTPException(422, "invalid role")
    registry.set_role(body.model_id, body.role)
    if body.role == "target":
        update_config({"runtime": {"target_model": body.model_id}})
    elif body.role == "draft":
        update_config({"runtime": {"draft_model": body.model_id}})
    st = read_state()
    return {"ok": True, "restart_required": st.status == "running"}


@router.post("/models/open-folder")
async def models_open_folder(body: dict) -> dict[str, Any]:
    m = registry.get_model(body.get("model_id", ""))
    if not m or not m.get("local_path"):
        raise HTTPException(404, "model not found")
    subprocess.Popen(["open", m["local_path"]])
    return {"ok": True}


# ------------------------------------------------------------------ dflash

class DFlashSettings(BaseModel):
    enabled: bool | None = None
    verify_mode: str | None = None
    verify_len_cap: int | None = None
    draft_quant: str | None = None
    fastpath_max_tokens: int | None = None
    prefix_cache: bool | None = None
    draft_model: str | None = None


@router.get("/dflash")
async def dflash_status() -> dict[str, Any]:
    cfg = load_config()
    st = read_state()
    metrics = await runtime_manager.provider.metrics()
    draft = registry.get_model(cfg["runtime"]["draft_model"])
    return {
        "config": cfg["dflash"],
        "mode": cfg["runtime"]["mode"],
        "active": st.status == "running" and st.mode == "fast",
        "draft_model": cfg["runtime"]["draft_model"],
        "draft_info": draft,
        "block_size_trained": (draft or {}).get("extra", {}).get("block_size"),
        "metrics": metrics,
        "fallback_count": runtime_manager._fallback_count,
        "advisory": runtime_manager._advisory,
    }


@router.put("/dflash")
async def dflash_update(body: DFlashSettings) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    df_patch = {k: v for k, v in body.model_dump().items()
                if v is not None and k not in ("enabled", "draft_model")}
    if df_patch:
        patch["dflash"] = df_patch
    if body.draft_model is not None:
        patch.setdefault("runtime", {})["draft_model"] = body.draft_model
    if body.enabled is not None:
        patch.setdefault("runtime", {})["mode"] = "fast" if body.enabled else "safe"
        patch.setdefault("dflash", {})["enabled"] = body.enabled
    cfg = update_config(patch)
    st = read_state()
    return {"ok": True, "config": cfg["dflash"], "mode": cfg["runtime"]["mode"],
            "restart_required": st.status == "running"}


# ------------------------------------------------------------------ benchmark

class BenchBody(BaseModel):
    prompt_key: str = "coding_long"


@router.get("/benchmark/prompts")
async def bench_prompts() -> dict[str, Any]:
    return {k: {"label": v["label"], "max_tokens": v["max_tokens"]}
            for k, v in BENCHMARK_PROMPTS.items()}


@router.get("/benchmark/history")
async def bench_history(limit: int = 50, kind: str | None = None) -> list[dict[str, Any]]:
    return benchmark_history(limit=limit, kind=kind)


@router.get("/benchmark/job")
async def bench_job() -> dict[str, Any]:
    return {"busy": job_manager.busy, "job": job_manager.job}


def _require_running() -> None:
    st = read_state()
    if st.status != "running":
        raise HTTPException(409, "Runtime is not running. Start it first (Overview → Start).")


@router.post("/benchmark/quick")
async def bench_quick(body: BenchBody) -> dict[str, Any]:
    if body.prompt_key not in BENCHMARK_PROMPTS:
        raise HTTPException(422, "unknown prompt_key")
    _require_running()
    return job_manager.quick(body.prompt_key)


@router.post("/benchmark/ab")
async def bench_ab(body: BenchBody) -> dict[str, Any]:
    if body.prompt_key not in BENCHMARK_PROMPTS:
        raise HTTPException(422, "unknown prompt_key")
    return job_manager.ab(body.prompt_key)


@router.post("/benchmark/autotune")
async def bench_autotune() -> dict[str, Any]:
    return job_manager.autotune()


@router.post("/benchmark/tool-calling")
async def bench_tool_calling() -> dict[str, Any]:
    _require_running()
    return job_manager.tool_calling()


# ------------------------------------------------------------------ agents

@router.get("/agents")
async def agents_list() -> list[dict[str, Any]]:
    return agents_mod.agent_catalog()


@router.post("/agents/test")
async def agents_test() -> dict[str, Any]:
    return await agents_mod.test_connection()


# ------------------------------------------------------------------ monitoring

@router.get("/monitor/snapshot")
async def monitor_snapshot(n: int = 450) -> dict[str, Any]:
    return {
        "samples": sampler.snapshot(n),
        "memory_advisory": sampler.memory_advisory,
    }


@router.get("/monitor/stream")
async def monitor_stream(request: Request) -> StreamingResponse:
    q = sampler.subscribe()

    async def gen():
        try:
            # initial snapshot so the UI paints immediately
            yield f"data: {json.dumps({'type': 'snapshot', 'samples': sampler.snapshot(60)})}\n\n"
            while True:
                if await request.is_disconnected():
                    return
                try:
                    sample = await asyncio.wait_for(q.get(), timeout=15)
                    payload = {"type": "sample", "sample": sample,
                               "memory_advisory": sampler.memory_advisory}
                    yield f"data: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            sampler.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


# ------------------------------------------------------------------ logs / events

@router.get("/logs/categories")
async def logs_categories() -> list[dict[str, Any]]:
    return logs_mod.list_categories()


@router.get("/logs")
async def logs_read(category: str = "runtime", lines: int = 300, query: str = "",
                    errors_only: bool = False, important_only: bool = True) -> dict[str, Any]:
    return logs_mod.read_log(category, lines, query, errors_only, important_only)


@router.get("/events")
async def events(limit: int = 100) -> list[dict[str, Any]]:
    return recent_events(limit)


# ------------------------------------------------------------------ gateway stats

@router.get("/gateway/stats")
async def gateway_stats() -> dict[str, Any]:
    cfg = load_config()
    url = f"http://{cfg['api']['host']}:{cfg['api']['port']}/gateway/stats"
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            r = await client.get(url)
            return {"ok": True, "live": True, "stats": r.json()}
    except (httpx.HTTPError, ValueError):
        try:
            with open(GATEWAY_STATS_PATH) as f:
                return {"ok": True, "live": False, "stats": json.load(f)}
        except (OSError, json.JSONDecodeError):
            return {"ok": False, "live": False, "stats": None}


# ------------------------------------------------------------------ settings

@router.get("/settings")
async def settings_get() -> dict[str, Any]:
    return load_config()


@router.put("/settings")
async def settings_put(patch: dict[str, Any]) -> dict[str, Any]:
    allowed_top = {"api", "dashboard", "runtime", "dflash", "model_dirs", "logging",
                   "memory", "privacy"}
    bad = set(patch) - allowed_top
    if bad:
        raise HTTPException(422, f"unknown config sections: {sorted(bad)}")
    cfg = update_config(patch)
    st = read_state()
    return {"ok": True, "config": cfg, "restart_required": st.status == "running"}


# ------------------------------------------------------------------ launchd service

@router.get("/service/status")
async def service_status() -> dict[str, Any]:
    return {name: launchd.status(name) for name in launchd.SERVICES}


@router.post("/service/install")
async def service_install(body: dict) -> dict[str, Any]:
    name = body.get("service", "")
    if name not in launchd.SERVICES:
        raise HTTPException(422, "service must be 'backend' or 'gateway'")
    return launchd.install(name)


@router.post("/service/uninstall")
async def service_uninstall(body: dict) -> dict[str, Any]:
    name = body.get("service", "")
    if name not in launchd.SERVICES:
        raise HTTPException(422, "service must be 'backend' or 'gateway'")
    return launchd.uninstall(name)
