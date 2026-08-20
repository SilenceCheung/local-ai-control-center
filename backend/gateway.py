"""Inference Gateway — the stable public entry of the Inference Plane.

Listens on 127.0.0.1:8080 (config api.port) and forwards OpenAI-compatible
requests to the internal runtime port. It is a separate process from the
control backend so that:

- control-plane crashes never take the model API down
- runtime restarts (mode switches) keep the same public URL
- agents always talk to one model alias (default "qwen3.8-27b-local")

Run: .venv/bin/python -m uvicorn backend.gateway:app --host 127.0.0.1 --port 8080
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from backend.core.config import GATEWAY_STATS_PATH, load_config
from backend.core.state import pid_alive, read_state

app = FastAPI(title="Local AI Gateway", docs_url=None, redoc_url=None)

_client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=5.0))

# ---------------------------------------------------------------- stats

stats: dict[str, Any] = {
    "started_at": time.time(),
    "requests_total": 0,
    "requests_active": 0,
    "errors_total": 0,
    "tokens_generated": 0,
    "last_request_at": None,
    "agents_seen": {},  # name -> last_seen ts
}

_AGENT_PATTERNS = [
    ("cursor", re.compile(r"cursor", re.I)),
    ("codex", re.compile(r"codex", re.I)),
    ("opencode", re.compile(r"opencode", re.I)),
    ("cline", re.compile(r"cline", re.I)),
    ("roo-code", re.compile(r"roo", re.I)),
    ("claude-code", re.compile(r"claude", re.I)),
    ("openai-sdk", re.compile(r"openai", re.I)),
]


def _note_agent(request: Request) -> None:
    ua = request.headers.get("user-agent", "")
    referer = request.headers.get("http-referer", "") + request.headers.get("x-title", "")
    for name, pat in _AGENT_PATTERNS:
        if pat.search(ua) or pat.search(referer):
            stats["agents_seen"][name] = time.time()
            return


def _flush_stats() -> None:
    try:
        GATEWAY_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = GATEWAY_STATS_PATH.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(stats, f)
        os.replace(tmp, GATEWAY_STATS_PATH)
    except OSError:
        pass


# ---------------------------------------------------------------- helpers

def _upstream_base() -> str:
    st = read_state()
    return f"http://{st.internal_host}:{st.internal_port}"


def _runtime_down_response() -> JSONResponse:
    st = read_state()
    if st.status == "starting":
        what, why = "The model is still loading.", "Runtime was started recently; a 27B model takes a moment to load."
        fix = "Wait for the runtime to finish loading, then retry."
    elif st.status in ("stopped", "stopping"):
        what, why = "The local AI runtime is not running.", "It was stopped from the Control Center or has not been started yet."
        fix = "Open http://127.0.0.1:8787 and click Start, or run: local-ai start"
    else:
        what, why = "The local AI runtime is unreachable.", st.error or "The inference process crashed or is not responding."
        fix = "Open http://127.0.0.1:8787 → Logs to see the cause, then Restart."
    return JSONResponse(
        status_code=503,
        content={"error": {
            "message": f"{what} {why} {fix}",
            "type": "runtime_unavailable",
            "what": what, "why": why, "how_to_fix": fix,
            "code": "runtime_unavailable",
        }},
    )


def _resolve_model_name(requested: str | None) -> str:
    """Map the public alias to whatever the runtime was started with."""
    st = read_state()
    served = st.target_path or st.target_model or requested or ""
    return served


# ---------------------------------------------------------------- routes

@app.get("/health")
async def health() -> dict[str, Any]:
    st = read_state()
    alive = pid_alive(st.pid)
    upstream_ok = False
    if alive:
        try:
            r = await _client.get(_upstream_base() + "/v1/models", timeout=2)
            upstream_ok = r.status_code < 500
        except httpx.HTTPError:
            try:
                r = await _client.get(_upstream_base() + "/metrics", timeout=2)
                upstream_ok = r.status_code < 500
            except httpx.HTTPError:
                upstream_ok = False
    return {
        "gateway": "ok",
        "runtime": {
            "status": st.status,
            "mode": st.mode,
            "process_alive": alive,
            "http_healthy": upstream_ok,
            "model_loaded": upstream_ok,
            "draft_loaded": upstream_ok and st.mode == "fast",
            "target_model": st.target_model,
            "draft_model": st.draft_model,
            "alias": st.alias,
        },
    }


@app.get("/gateway/stats")
async def gateway_stats() -> dict[str, Any]:
    return stats


@app.get("/v1/models")
async def models(request: Request) -> dict[str, Any]:
    _note_agent(request)
    st = read_state()
    cfg = load_config()
    alias = cfg["api"]["alias"]
    data = [{
        "id": alias,
        "object": "model",
        "created": int(st.started_at or time.time()),
        "owned_by": "local",
    }]
    if st.target_model and st.target_model != alias:
        data.append({
            "id": st.target_model,
            "object": "model",
            "created": int(st.started_at or time.time()),
            "owned_by": "local",
        })
    return {"object": "list", "data": data}


async def _proxy_post(request: Request, path: str) -> Response:
    _note_agent(request)
    st = read_state()
    if not (st.status in ("running", "starting") and pid_alive(st.pid)):
        stats["errors_total"] += 1
        return _runtime_down_response()

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"error": {
            "message": "Request body is not valid JSON.", "type": "invalid_request_error"}})

    if isinstance(body, dict) and "model" in body:
        body["model"] = _resolve_model_name(body.get("model"))

    stats["requests_total"] += 1
    stats["requests_active"] += 1
    stats["last_request_at"] = time.time()
    _flush_stats()

    url = _upstream_base() + path
    stream = bool(body.get("stream")) if isinstance(body, dict) else False
    headers = {"content-type": "application/json"}

    try:
        if stream:
            req = _client.build_request("POST", url, json=body, headers=headers)
            upstream = await _client.send(req, stream=True)

            async def gen():
                try:
                    async for chunk in upstream.aiter_bytes():
                        # count streamed completion tokens cheaply via SSE lines
                        stats["tokens_generated"] += chunk.count(b'"delta"')
                        yield chunk
                finally:
                    await upstream.aclose()
                    stats["requests_active"] -= 1
                    _flush_stats()

            return StreamingResponse(
                gen(), status_code=upstream.status_code,
                media_type=upstream.headers.get("content-type", "text/event-stream"),
            )
        else:
            r = await _client.post(url, json=body, headers=headers)
            stats["requests_active"] -= 1
            if r.status_code == 404:
                return JSONResponse(status_code=501, content={"error": {
                    "message": f"{path} is not supported by the current runtime engine "
                               f"({'dflash-mlx' if st.mode == 'fast' else 'mlx-lm'}).",
                    "type": "not_supported"}})
            try:
                payload = r.json()
                usage = payload.get("usage") or {}
                stats["tokens_generated"] += int(usage.get("completion_tokens") or 0)
            except ValueError:
                payload = None
            _flush_stats()
            if payload is not None:
                return JSONResponse(status_code=r.status_code, content=payload)
            return Response(content=r.content, status_code=r.status_code,
                            media_type=r.headers.get("content-type"))
    except httpx.HTTPError as e:
        stats["requests_active"] -= 1
        stats["errors_total"] += 1
        _flush_stats()
        return JSONResponse(status_code=502, content={"error": {
            "message": f"The runtime accepted the connection but the request failed: {e}. "
                       f"Check http://127.0.0.1:8787 → Logs.",
            "type": "upstream_error"}})


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    return await _proxy_post(request, "/v1/chat/completions")


@app.post("/v1/completions")
async def completions(request: Request) -> Response:
    return await _proxy_post(request, "/v1/completions")


@app.post("/v1/responses")
async def responses(request: Request) -> Response:
    return await _proxy_post(request, "/v1/responses")


def main() -> None:
    import uvicorn
    cfg = load_config()
    uvicorn.run("backend.gateway:app",
                host=cfg["api"]["host"], port=cfg["api"]["port"],
                log_level="warning")


if __name__ == "__main__":
    main()
