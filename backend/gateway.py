"""Inference Gateway — the stable public entry of the Inference Plane.

Listens on 127.0.0.1:8080 (config api.port) and forwards OpenAI-compatible
requests to the internal runtime port. It is a separate process from the
control backend so that:

- control-plane crashes never take the model API down
- runtime restarts (mode switches) keep the same public URL
- agents see a public alias that follows the Target model (or a locked custom name)

This process is an **agent protocol adapter**, not a chat UI. Grok / Codex /
Cursor / Claude Code dialects are translated to the engine's Chat Completions
before they hit 18080.

Run: .venv/bin/python -m uvicorn backend.gateway:app --host 127.0.0.1 --port 8080
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from collections import deque
from typing import Any, AsyncIterator
from urllib.parse import unquote

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from backend.compat.anthropic import AnthropicCompatError, AnthropicStreamMapper, chat_to_messages, messages_to_chat
from backend.compat.identity import detect_agent
from backend.compat.responses import (
    ResponsesCompatError,
    chat_to_responses,
    remember_turn,
    responses_to_chat,
)
from backend.compat.sanitize import sanitize_chat_body
from backend.compat.stream import (
    HEARTBEAT_S,
    KEEPALIVE,
    ResponsesStreamMapper,
    map_chat_sse_chunk_to_responses,
    split_sse_frames,
    sse_data_payloads,
)
from backend.core.config import GATEWAY_STATS_PATH, LOGS_DIR, load_config
from backend.core.state import pid_alive, read_state

app = FastAPI(title="Local AI Gateway", docs_url=None, redoc_url=None)

_client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=5.0))
_chat_lock = asyncio.Lock()
_log = logging.getLogger("localai.gateway")
MAX_QUEUE = max(0, int(os.environ.get("LOCALAI_GATEWAY_MAX_QUEUE", "2")))
QUEUE_TIMEOUT_S = max(1.0, float(os.environ.get("LOCALAI_GATEWAY_QUEUE_TIMEOUT_S", "60")))
PRODUCTION_MAX_TOKENS = max(128, int(os.environ.get("LOCALAI_PRODUCTION_MAX_TOKENS", "4096")))
DEEP_MAX_TOKENS = max(PRODUCTION_MAX_TOKENS, int(os.environ.get("LOCALAI_DEEP_MAX_TOKENS", "16384")))
PRODUCTION_DEADLINE_S = max(30.0, float(os.environ.get("LOCALAI_PRODUCTION_DEADLINE_S", "300")))
DEEP_DEADLINE_S = max(PRODUCTION_DEADLINE_S, float(os.environ.get("LOCALAI_DEEP_DEADLINE_S", "900")))
RECENT_REQUESTS_MAX = 64
STREAM_COMPLETION_PROBE_S = max(
    0.25, float(os.environ.get("LOCALAI_STREAM_COMPLETION_PROBE_S", "1.0"))
)
AUXILIARY_GRACE_S = max(
    0.0, float(os.environ.get("LOCALAI_AUXILIARY_GRACE_S", "0.15"))
)
STREAM_DRAIN_TIMEOUT_S = max(
    2.0, float(os.environ.get("LOCALAI_STREAM_DRAIN_TIMEOUT_S", "30"))
)
_TERMINAL_FINISH_RE = re.compile(
    rb'"finish_reason"\s*:\s*"(?:stop|length|tool_calls|content_filter)"'
)


class AdmissionRejected(RuntimeError):
    def __init__(self, message: str, *, retry_after: int = 15) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class RequestCancelled(RuntimeError):
    pass


class _EngineLease:
    """Hold `_chat_lock` across a streamed completion, not just the POST.

    dflash/mlx_lm is single-slot. CodeG sends a parallel probe while the first
    stream is still prefilling. If the lock is released after headers, the
    second POST hits generate() and mlx_lm maps that exception to HTTP 404,
    which Claude Code shows as HTTP 503 retries.
    """

    def __init__(self, trace: dict[str, Any] | None = None) -> None:
        self.held = False
        self.trace = trace
        self.queued = False

    async def acquire(self) -> None:
        # Grok Build starts a tiny title/auxiliary stream and its full agent
        # turn concurrently.  If the 100-token helper wins the single MLX
        # slot, the client waits on the queued main turn and stops consuming
        # the helper stream: a cross-layer deadlock.  Give only this narrowly
        # identified auxiliary request a short grace period so the real turn
        # can claim the engine first.
        if (
            self.trace is not None
            and self.trace.get("agent") == "grok"
            and int(self.trace.get("max_tokens") or 0) <= 100
            and int(self.trace.get("tool_count") or 0) <= 1
            and int(self.trace.get("request_bytes") or 0) < 8_192
        ):
            self.trace["scheduler_class"] = "auxiliary"
            await asyncio.sleep(AUXILIARY_GRACE_S)
        elif self.trace is not None:
            self.trace["scheduler_class"] = "interactive"
        queue = stats["scheduler"]
        if _chat_lock.locked():
            if int(queue["waiting"]) >= MAX_QUEUE:
                queue["rejected_total"] += 1
                raise AdmissionRejected(
                    f"The local inference queue is full ({MAX_QUEUE} waiting requests)."
                )
            queue["waiting"] += 1
            queue["queued_total"] += 1
            self.queued = True
            _flush_stats()
        t0 = time.perf_counter()
        try:
            deadline = time.monotonic() + QUEUE_TIMEOUT_S
            while True:
                if self.trace is not None and self.trace.get("cancel_requested"):
                    raise RequestCancelled("request cancelled while queued")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    queue["timeouts_total"] += 1
                    raise AdmissionRejected(
                        f"The request waited more than {QUEUE_TIMEOUT_S:.0f}s for the local model.",
                        retry_after=15,
                    )
                try:
                    await asyncio.wait_for(_chat_lock.acquire(), timeout=min(0.25, remaining))
                    break
                except asyncio.TimeoutError:
                    continue
        finally:
            if self.queued:
                queue["waiting"] = max(0, int(queue["waiting"]) - 1)
                self.queued = False
        self.held = True
        queue_wait_ms = round((time.perf_counter() - t0) * 1000, 2)
        queue["active"] = 1
        queue["last_queue_wait_ms"] = queue_wait_ms
        queue["max_queue_wait_ms"] = max(float(queue["max_queue_wait_ms"]), queue_wait_ms)
        if self.trace is not None:
            self.trace["queue_wait_ms"] = queue_wait_ms
            self.trace["engine_started_at"] = time.time()
            self.trace["status"] = "running"
        _flush_stats()

    def release(self) -> None:
        if self.held:
            self.held = False
            stats["scheduler"]["active"] = 0
            _chat_lock.release()
            _flush_stats()


def normalize_asgi_scope(scope: dict[str, Any]) -> None:
    """Claude Code / CodeG sometimes put `?beta=true` in the path, not the query.

    Uvicorn then looks for a route named `/v1/messages?beta=true` and 404s.
    The client surfaces that as "selected model may not exist". Also collapse
    `//v1/messages` from a trailing slash on ANTHROPIC_BASE_URL.
    """
    path = scope.get("path") or ""
    if not isinstance(path, str):
        path = str(path)
    path = unquote(path)
    qs = scope.get("query_string") or b""
    if isinstance(qs, str):
        qs = qs.encode()
    if "?" in path:
        path, extra = path.split("?", 1)
        extra_b = extra.encode()
        qs = extra_b if not qs else qs + b"&" + extra_b
    if "//" in path:
        path = re.sub(r"/{2,}", "/", path) or "/"
    scope["path"] = path
    scope["raw_path"] = path.encode("utf-8", errors="replace")
    scope["query_string"] = qs


@app.middleware("http")
async def _normalize_agent_paths(request: Request, call_next):  # type: ignore[no-untyped-def]
    if request.scope.get("type") == "http":
        normalize_asgi_scope(request.scope)
    return await call_next(request)

stats: dict[str, Any] = {
    "started_at": time.time(),
    "lifetime_started_at": time.time(),
    "requests_total": 0,
    "requests_active": 0,
    "errors_total": 0,
    "tokens_generated": 0,
    "last_request_at": None,
    "agents_seen": {},
    "scheduler": {
        "capacity": 1,
        "max_queue": MAX_QUEUE,
        "active": 0,
        "waiting": 0,
        "queued_total": 0,
        "rejected_total": 0,
        "timeouts_total": 0,
        "duplicates_total": 0,
        "cancelled_total": 0,
        "budget_limited_total": 0,
        "last_queue_wait_ms": 0.0,
        "max_queue_wait_ms": 0.0,
    },
    "recent_requests": [],
}
_inflight: dict[str, dict[str, Any]] = {}
_upstream_start_tasks: dict[str, asyncio.Task[httpx.Response]] = {}


def _restore_persisted_observability() -> None:
    """Keep useful history across a gateway-only restart; reset live state."""
    try:
        with open(GATEWAY_STATS_PATH) as f:
            old = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return
    if not isinstance(old, dict):
        return
    for key in ("requests_total", "errors_total", "tokens_generated"):
        try:
            stats[key] = max(0, int(old.get(key) or 0))
        except (TypeError, ValueError):
            pass
    stats["lifetime_started_at"] = old.get("lifetime_started_at") or old.get("started_at") or stats["started_at"]
    stats["last_request_at"] = old.get("last_request_at")
    if isinstance(old.get("agents_seen"), dict):
        stats["agents_seen"] = old["agents_seen"]
    if isinstance(old.get("recent_requests"), list):
        stats["recent_requests"] = old["recent_requests"][-RECENT_REQUESTS_MAX:]
    old_scheduler = old.get("scheduler") if isinstance(old.get("scheduler"), dict) else {}
    for key in (
        "queued_total", "rejected_total", "timeouts_total", "duplicates_total",
        "cancelled_total", "budget_limited_total",
    ):
        try:
            stats["scheduler"][key] = max(0, int(old_scheduler.get(key) or 0))
        except (TypeError, ValueError):
            pass
    for key in ("last_queue_wait_ms", "max_queue_wait_ms"):
        try:
            stats["scheduler"][key] = max(0.0, float(old_scheduler.get(key) or 0.0))
        except (TypeError, ValueError):
            pass


_restore_persisted_observability()


def _note_agent(request: Request) -> str:
    name = detect_agent(
        user_agent=request.headers.get("user-agent", ""),
        referer=request.headers.get("http-referer", "") or request.headers.get("referer", ""),
        title=request.headers.get("x-title", ""),
        extra=[request.headers.get("anthropic-version", "")],
    )
    if name:
        stats["agents_seen"][name] = time.time()
        return name
    return "unknown"


def _safe_fingerprint(value: Any) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        raw = repr(type(value))
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def _request_shape(body: dict[str, Any], chat: dict[str, Any]) -> dict[str, Any]:
    messages = chat.get("messages") if isinstance(chat.get("messages"), list) else []
    tools = chat.get("tools") if isinstance(chat.get("tools"), list) else []
    system_prefix = [
        m for m in messages
        if isinstance(m, dict) and m.get("role") == "system"
    ]
    serialized = json.dumps(body, ensure_ascii=False, default=str)
    return {
        "request_bytes": len(serialized.encode("utf-8")),
        "estimated_input_tokens": max(1, len(serialized) // 4),
        "message_count": len(messages),
        "tool_count": len(tools),
        "tool_schema_bytes": len(json.dumps(tools, ensure_ascii=False, default=str).encode("utf-8")),
        "prompt_fingerprint": _safe_fingerprint(messages),
        "prefix_fingerprint": _safe_fingerprint({"system": system_prefix, "tools": tools}),
    }


def _new_trace(
    request: Request,
    *,
    dialect: str,
    body: dict[str, Any],
    chat: dict[str, Any],
) -> dict[str, Any]:
    trace: dict[str, Any] = {
        "request_id": f"req_{uuid.uuid4().hex[:16]}",
        "agent": _note_agent(request),
        "dialect": dialect,
        "submitted_at": time.time(),
        "status": "queued",
        "stream": bool(chat.get("stream")),
        "max_tokens": chat.get("max_tokens"),
        "queue_wait_ms": None,
        "gateway_ttft_ms": None,
        "total_ms": None,
    }
    trace.update(_request_shape(body, chat))
    trace["request_fingerprint"] = _safe_fingerprint({
        "agent": trace["agent"],
        "dialect": dialect,
        "model": chat.get("model"),
        "messages": chat.get("messages"),
        "tools": chat.get("tools"),
        "tool_choice": chat.get("tool_choice"),
    })
    _inflight[trace["request_id"]] = trace
    return trace


def _apply_request_policy(request: Request, chat: dict[str, Any], trace: dict[str, Any]) -> None:
    """Bound agent turns so one retry cannot monopolize the single MLX slot."""
    requested_profile = request.headers.get("x-localai-profile", "production").strip().lower()
    profile = "deep" if requested_profile == "deep" else "production"
    cap = DEEP_MAX_TOKENS if profile == "deep" else PRODUCTION_MAX_TOKENS
    deadline_s = DEEP_DEADLINE_S if profile == "deep" else PRODUCTION_DEADLINE_S
    requested = chat.get("max_tokens")
    requested_n = requested if isinstance(requested, int) and requested > 0 else cap
    effective = min(requested_n, cap)
    chat["max_tokens"] = effective
    if effective < requested_n:
        stats["scheduler"]["budget_limited_total"] += 1
    # Tool loops need fast, visible actions. Deep reasoning remains an explicit
    # opt-in profile for tool-free analysis instead of a global agent default.
    if profile == "production" and chat.get("tools"):
        kwargs = chat.get("chat_template_kwargs")
        safe_kwargs = dict(kwargs) if isinstance(kwargs, dict) else {}
        safe_kwargs["enable_thinking"] = False
        chat["chat_template_kwargs"] = safe_kwargs
    trace.update({
        "profile": profile,
        "requested_max_tokens": requested,
        "effective_max_tokens": effective,
        "deadline_s": deadline_s,
        "deadline_at": time.time() + deadline_s,
        "thinking_enabled": (
            chat.get("chat_template_kwargs", {}).get("enable_thinking")
            if isinstance(chat.get("chat_template_kwargs"), dict) else None
        ),
    })
    trace["request_fingerprint"] = _safe_fingerprint({
        "base": trace.get("request_fingerprint"),
        "profile": profile,
        "max_tokens": effective,
        "thinking": trace.get("thinking_enabled"),
    })


async def _duplicate_response(trace: dict[str, Any]) -> JSONResponse | None:
    duplicate = next((
        row for request_id, row in _inflight.items()
        if request_id != trace["request_id"]
        and row.get("request_fingerprint") == trace.get("request_fingerprint")
        and row.get("status") in {"queued", "running"}
    ), None)
    if duplicate is None:
        return None
    stats["scheduler"]["duplicates_total"] += 1
    trace["duplicate_of"] = duplicate.get("request_id")
    await _finish_trace(trace, status="rejected", error_type="duplicate_inflight")
    return JSONResponse(
        status_code=409,
        headers={"Retry-After": "2", **_trace_headers(trace)},
        content={"error": {
            "message": "An identical local request is already queued or running.",
            "type": "local_admission_error",
            "code": "duplicate_inflight",
            "request_id": duplicate.get("request_id"),
        }},
    )


async def _engine_last_request() -> dict[str, Any]:
    try:
        r = await _client.get(_upstream_base() + "/metrics", timeout=1.5)
        if r.status_code == 200:
            payload = r.json()
            current = payload.get("current_request") if isinstance(payload, dict) else None
            last = payload.get("last_request") if isinstance(payload, dict) else None
            source = current if isinstance(current, dict) and current else last
            if isinstance(source, dict):
                return {
                    "metrics_source": "current" if source is current else "last",
                    "engine_request_id": source.get("request_id"),
                    "prompt_tokens": source.get("prompt_tokens"),
                    "prefill_tokens_physical": source.get("prefill_tokens_physical"),
                    "prefill_tokens_restored": source.get("prefill_tokens_restored"),
                    "cache_status": source.get("cache_status"),
                    "cache_hit_tokens": source.get("cache_hit_tokens"),
                    "prefill_ms": round(float(source.get("prefill_s") or 0) * 1000, 2),
                    "engine_ttft_ms": round(float(source.get("ttft_s") or 0) * 1000, 2),
                    "decode_ms": round(float(source.get("decode_s") or 0) * 1000, 2),
                    "decode_tok_s": source.get("decode_tok_s"),
                    "acceptance_rate": source.get("acceptance_rate"),
                    "generated_tokens": source.get("generated_tokens"),
                    "finish_reason": source.get("finish_reason"),
                    "mode_used": source.get("mode_used"),
                }
    except (httpx.HTTPError, ValueError, TypeError):
        pass
    return {}


async def _finish_trace(
    trace: dict[str, Any] | None,
    *,
    status: str,
    error_type: str | None = None,
) -> None:
    if trace is None:
        return
    if trace.get("engine_started_at"):
        trace.update(await _engine_last_request())
    trace["status"] = status
    trace["completed_at"] = time.time()
    trace["total_ms"] = round((trace["completed_at"] - trace["submitted_at"]) * 1000, 2)
    if error_type:
        trace["error_type"] = error_type
    recent = deque(stats.get("recent_requests") or [], maxlen=RECENT_REQUESTS_MAX)
    recent.append(trace)
    stats["recent_requests"] = list(recent)
    _inflight.pop(str(trace.get("request_id") or ""), None)
    _flush_stats()


def _queue_error(exc: AdmissionRejected, trace: dict[str, Any] | None = None) -> JSONResponse:
    if trace is not None:
        trace["status"] = "rejected"
        trace["error_type"] = "queue_full"
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": str(exc.retry_after)},
        content={"error": {
            "message": str(exc),
            "type": "rate_limit_error",
            "code": "local_queue_full",
            "retry_after": exc.retry_after,
        }},
    )


def _cancelled_response(trace: dict[str, Any]) -> JSONResponse:
    deadline = trace.get("cancel_reason") == "deadline"
    return JSONResponse(status_code=504 if deadline else 409, content={"error": {
        "message": (
            "The local request exceeded its production deadline."
            if deadline else "The local request was cancelled."
        ),
        "type": "local_timeout_error" if deadline else "local_cancelled_error",
        "code": "request_deadline_exceeded" if deadline else "request_cancelled",
    }})


def _trace_headers(trace: dict[str, Any] | None) -> dict[str, str]:
    if trace is None:
        return {}
    headers = {"X-LocalAI-Request-ID": str(trace.get("request_id") or "")}
    wait = trace.get("queue_wait_ms")
    if wait is not None:
        headers["X-LocalAI-Queue-Wait-Ms"] = str(wait)
    if trace.get("profile"):
        headers["X-LocalAI-Profile"] = str(trace["profile"])
    if trace.get("effective_max_tokens"):
        headers["X-LocalAI-Max-Tokens"] = str(trace["effective_max_tokens"])
    return headers


def _flush_stats() -> None:
    try:
        GATEWAY_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = GATEWAY_STATS_PATH.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(stats, f)
        os.replace(tmp, GATEWAY_STATS_PATH)
    except OSError:
        pass


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
    st = read_state()
    served = st.target_path or st.target_model or requested or ""
    return served


def _public_model(requested: Any) -> str:
    if isinstance(requested, str) and requested.strip():
        return requested
    return str(load_config()["api"]["alias"])


def _begin_request() -> None:
    stats["requests_total"] += 1
    stats["requests_active"] += 1
    stats["last_request_at"] = time.time()
    _flush_stats()


def _end_request(*, error: bool = False) -> None:
    stats["requests_active"] = max(0, stats["requests_active"] - 1)
    if error:
        stats["errors_total"] += 1
    _flush_stats()


def _end_request_once(trace: dict[str, Any] | None, *, error: bool = False) -> None:
    if trace is not None:
        if trace.get("request_accounted"):
            return
        trace["request_accounted"] = True
    _end_request(error=error)


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
    now = time.time()
    live_metrics = await _engine_last_request() if _inflight else {}
    inflight = []
    for source in _inflight.values():
        row = dict(source)
        if row.get("status") == "running" and live_metrics.get("metrics_source") == "current":
            row.update(live_metrics)
        row["elapsed_ms"] = round((now - float(row.get("submitted_at") or now)) * 1000, 2)
        if row.get("deadline_at"):
            row["deadline_remaining_s"] = round(max(0.0, float(row["deadline_at"]) - now), 2)
        inflight.append(row)
    return {**stats, "inflight_requests": inflight}


@app.post("/gateway/requests/{request_id}/cancel")
async def cancel_gateway_request(request_id: str) -> Response:
    trace = _inflight.get(request_id)
    if trace is None:
        return JSONResponse(status_code=404, content={"error": {
            "type": "not_found_error", "code": "request_not_active",
            "message": "The request is no longer queued or running.",
        }})
    if not trace.get("cancel_requested"):
        stats["scheduler"]["cancelled_total"] += 1
    trace["cancel_requested"] = True
    trace["cancel_reason"] = "user"
    trace["cancel_requested_at"] = time.time()
    task = _upstream_start_tasks.get(request_id)
    if task is not None and not task.done():
        task.cancel()
    _flush_stats()
    return JSONResponse({"ok": True, "request_id": request_id, "status": trace.get("status")})


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
    created = int(st.started_at or time.time())
    seen = {row["id"] for row in data}
    for extra in ("sonnet", "haiku", "opus"):
        if extra not in seen:
            data.append({
                "id": extra,
                "object": "model",
                "created": created,
                "owned_by": "local",
            })
    return {"object": "list", "data": data}


async def _read_json(request: Request) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return None, JSONResponse(status_code=400, content={"error": {
            "message": "Request body is not valid JSON.", "type": "invalid_request_error"}})
    if not isinstance(body, dict):
        return None, JSONResponse(status_code=400, content={"error": {
            "message": "Request body must be a JSON object.", "type": "invalid_request_error"}})
    return body, None


def _runtime_ready() -> JSONResponse | None:
    st = read_state()
    if not (st.status in ("running", "starting") and pid_alive(st.pid)):
        stats["errors_total"] += 1
        return _runtime_down_response()
    return None


async def _upstream_chat(chat: dict[str, Any]) -> httpx.Response:
    url = _upstream_base() + "/v1/chat/completions"
    headers = {"content-type": "application/json"}
    stream = bool(chat.get("stream"))
    # Callers must hold `_EngineLease` for the whole response, including SSE.
    last: httpx.Response | None = None
    for attempt in range(3):
        if stream:
            req = _client.build_request("POST", url, json=chat, headers=headers)
            last = await _client.send(req, stream=True)
        else:
            last = await _client.post(url, json=chat, headers=headers)
        if last.status_code != 404 or attempt == 2:
            if last.status_code >= 400:
                err_body = b""
                try:
                    err_body = await last.aread()
                except Exception:
                    err_body = b""
                dump = {
                    "status": last.status_code,
                    "attempt": attempt,
                    "stream": stream,
                    "error": err_body.decode("utf-8", "replace")[:2000],
                    "chat_keys": sorted(chat.keys()),
                    "bytes": len(json.dumps(chat, ensure_ascii=False)),
                    "max_tokens": chat.get("max_tokens"),
                    "tool_choice": chat.get("tool_choice"),
                    "tool_names": [
                        ((t.get("function") or {}).get("name") if isinstance(t, dict) else None)
                        for t in (chat.get("tools") or [])
                    ][:40],
                    "messages": [
                        {
                            "role": m.get("role"),
                            "content_len": len(m.get("content") or "") if isinstance(m.get("content"), str) else type(m.get("content")).__name__,
                            "keys": sorted(m.keys()) if isinstance(m, dict) else [],
                        }
                        for m in (chat.get("messages") or [])[:8]
                    ],
                }
                try:
                    (LOGS_DIR / "last_upstream_404.json").write_text(
                        json.dumps(dump, indent=2, ensure_ascii=False), encoding="utf-8"
                    )
                except Exception:
                    pass
                _log.warning("upstream chat %s %s", last.status_code, dump)
            return last
        try:
            await last.aread()
        except Exception:
            pass
        await last.aclose()
        await asyncio.sleep(1.5)
    assert last is not None
    return last


def _anthropic_error_from_upstream(r: httpx.Response) -> JSONResponse:
    """Never pass engine 404 through — Claude Code treats 404 as a missing model."""
    if r.status_code == 404:
        detail = ""
        try:
            payload = r.json()
            if isinstance(payload, dict):
                err = payload.get("error")
                if isinstance(err, str):
                    detail = err[:240]
                elif isinstance(err, dict):
                    detail = str(err.get("message") or "")[:240]
        except ValueError:
            detail = (r.text or "")[:240]
        extra = f" Engine: {detail}" if detail else ""
        return JSONResponse(status_code=503, content={
            "type": "error",
            "error": {
                "type": "api_error",
                "message": (
                    "The local runtime is busy, still loading, or rejected this "
                    "completion. Wait until Local AI shows Running, then send again. "
                    "This is not a missing-model error."
                    + extra
                ),
            },
        })
    try:
        payload = r.json()
    except ValueError:
        payload = {"type": "error", "error": {"type": "upstream_error", "message": r.text[:500]}}
    if isinstance(payload, dict) and "type" not in payload:
        payload = {"type": "error", "error": payload.get("error") or payload}
    return JSONResponse(status_code=r.status_code, content=payload)


async def _iter_heartbeat(
    upstream: httpx.Response,
    trace: dict[str, Any] | None = None,
) -> AsyncIterator[bytes]:
    """Yield upstream bytes; emit SSE comments while the engine is silent.

    Do not cancel the pending read on timeout — that would abort a long
    prefill and drop the real chunk when it finally arrives.
    """
    agen = upstream.aiter_bytes()
    pending: asyncio.Task[bytes] = asyncio.create_task(agen.__anext__())
    sse_tail = b""
    saw_payload = False
    last_keepalive = time.monotonic()
    try:
        while True:
            if trace is not None:
                if trace.get("cancel_requested"):
                    return
                deadline_at = trace.get("deadline_at")
                if deadline_at and time.time() >= float(deadline_at):
                    trace["cancel_requested"] = True
                    trace["cancel_reason"] = "deadline"
                    stats["scheduler"]["cancelled_total"] += 1
                    _flush_stats()
                    return
            try:
                chunk = await asyncio.wait_for(
                    asyncio.shield(pending),
                    timeout=min(STREAM_COMPLETION_PROBE_S, HEARTBEAT_S),
                )
            except asyncio.TimeoutError:
                # Some dflash streams finish generation but omit the terminal
                # SSE frame when the stop reason is `length`.  Do not leave the
                # single inference slot wedged forever: after at least one real
                # payload, verify that this exact engine request completed and
                # synthesize only the protocol terminator.
                before_id = trace.get("engine_request_id_before") if trace else None
                if saw_payload and trace is not None and "engine_request_id_before" in trace:
                    metrics = await _engine_last_request()
                    after_id = metrics.get("engine_request_id")
                    if (
                        after_id is not None
                        and after_id != before_id
                        and metrics.get("finish_reason")
                    ):
                        trace["synthetic_done"] = True
                        yield b"data: [DONE]\n\n"
                        return
                now = time.monotonic()
                if now - last_keepalive >= HEARTBEAT_S:
                    last_keepalive = now
                    yield KEEPALIVE
                continue
            except StopAsyncIteration:
                return
            yield chunk
            saw_payload = True
            marker_window = sse_tail + chunk
            if b"data: [DONE]" in marker_window:
                return
            if _TERMINAL_FINISH_RE.search(marker_window):
                if trace is not None:
                    trace["synthetic_done"] = "terminal_finish_reason"
                yield b"data: [DONE]\n\n"
                return
            sse_tail = marker_window[-256:]
            pending = asyncio.create_task(agen.__anext__())
    finally:
        if not pending.done():
            pending.cancel()
            try:
                await asyncio.wait_for(pending, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, StopAsyncIteration):
                pass


async def _stream_chat_passthrough(
    upstream: httpx.Response,
    *,
    lease: _EngineLease | None = None,
    trace: dict[str, Any] | None = None,
) -> StreamingResponse:
    async def gen() -> AsyncIterator[bytes]:
        completed = False
        finalized = False

        async def finalize(status: str) -> None:
            nonlocal finalized
            if finalized:
                return
            finalized = True
            await upstream.aclose()
            await _finish_trace(trace, status=status)
            if lease is not None:
                lease.release()
            _end_request_once(trace)

        try:
            async for chunk in _iter_heartbeat(upstream, trace):
                if chunk != KEEPALIVE:
                    if trace is not None and trace.get("gateway_ttft_ms") is None:
                        trace["gateway_ttft_ms"] = round(
                            (time.time() - trace["submitted_at"]) * 1000, 2
                        )
                    stats["tokens_generated"] += chunk.count(b'"delta"')
                # Release the scarce MLX slot *before* yielding the terminal
                # marker. Several agents stop reading as soon as they see
                # [DONE], so code after that yield may never run.
                if b"data: [DONE]" in chunk:
                    completed = True
                    await finalize("completed")
                    yield chunk
                    return
                yield chunk
            if trace is not None and trace.get("cancel_requested"):
                return
            completed = True
        finally:
            await finalize("completed" if completed else "cancelled")

    return StreamingResponse(
        gen(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "text/event-stream"),
        headers=_trace_headers(trace),
    )


async def _stream_mapped(
    upstream: httpx.Response,
    *,
    dialect: str,
    public_model: str,
    chat_request: dict[str, Any],
    lease: _EngineLease | None = None,
    trace: dict[str, Any] | None = None,
) -> StreamingResponse:
    mapper_r = ResponsesStreamMapper(model=public_model) if dialect == "responses" else None
    mapper_a = (
        AnthropicStreamMapper(
            model=public_model,
            input_tokens=int((trace or {}).get("estimated_input_tokens") or 0),
        )
        if dialect == "anthropic" else None
    )
    carry = b""

    async def gen() -> AsyncIterator[bytes]:
        nonlocal carry
        completed = False
        finalized = False

        async def finalize(status: str) -> None:
            nonlocal finalized
            if finalized:
                return
            finalized = True
            await upstream.aclose()
            await _finish_trace(trace, status=status)
            if lease is not None:
                lease.release()
            _end_request_once(trace)

        try:
            async for chunk in _iter_heartbeat(upstream, trace):
                if chunk == KEEPALIVE:
                    if dialect == "responses" and mapper_r is not None:
                        for ev in mapper_r.start_events():
                            yield ev
                    yield KEEPALIVE
                    continue
                if trace is not None and trace.get("gateway_ttft_ms") is None:
                    trace["gateway_ttft_ms"] = round(
                        (time.time() - trace["submitted_at"]) * 1000, 2
                    )
                stats["tokens_generated"] += chunk.count(b'"delta"')
                if dialect == "responses" and mapper_r is not None:
                    events, carry = map_chat_sse_chunk_to_responses(chunk, mapper_r, carry)
                    for ev in events:
                        if b"event: response.completed" in ev:
                            completed = True
                            await finalize("completed")
                        yield ev
                elif dialect == "anthropic" and mapper_a is not None:
                    frames, carry = split_sse_frames(carry + chunk)
                    for frame in frames:
                        for payload in sse_data_payloads(frame):
                            if payload == "[DONE]":
                                metrics = await _engine_last_request()
                                mapper_a.set_engine_usage(
                                    input_tokens=metrics.get("prompt_tokens"),
                                    output_tokens=metrics.get("generated_tokens"),
                                )
                                if trace is not None:
                                    trace.update(metrics)
                            for ev in mapper_a.feed(payload):
                                if b"event: message_stop" in ev:
                                    completed = True
                                    await finalize("completed")
                                yield ev
            if trace is not None and trace.get("cancel_requested"):
                return
            if dialect == "responses" and mapper_r is not None:
                if carry.strip():
                    events, _ = map_chat_sse_chunk_to_responses(b"\n\n", mapper_r, carry)
                    for ev in events:
                        if b"event: response.completed" in ev:
                            completed = True
                            await finalize("completed")
                        yield ev
                for ev in mapper_r.close():
                    if b"event: response.completed" in ev:
                        completed = True
                        await finalize("completed")
                    yield ev
                remember_turn(
                    mapper_r.final_response(),
                    chat_request,
                    {"choices": [{"message": mapper_r.assistant_chat_message()}]},
                )
            elif dialect == "anthropic" and mapper_a is not None:
                if carry.strip():
                    frames, _ = split_sse_frames(carry + b"\n\n")
                    for frame in frames:
                        for payload in sse_data_payloads(frame):
                            if payload == "[DONE]":
                                metrics = await _engine_last_request()
                                mapper_a.set_engine_usage(
                                    input_tokens=metrics.get("prompt_tokens"),
                                    output_tokens=metrics.get("generated_tokens"),
                                )
                                if trace is not None:
                                    trace.update(metrics)
                            for ev in mapper_a.feed(payload):
                                if b"event: message_stop" in ev:
                                    completed = True
                                    await finalize("completed")
                                yield ev
                for ev in mapper_a.close():
                    if b"event: message_stop" in ev:
                        completed = True
                        await finalize("completed")
                    yield ev
            completed = True
        finally:
            await finalize("completed" if completed else "cancelled")

    return StreamingResponse(
        gen(), status_code=200, media_type="text/event-stream", headers=_trace_headers(trace)
    )


def _error_from_upstream(r: httpx.Response) -> JSONResponse:
    try:
        payload = r.json()
    except ValueError:
        payload = {"error": {"message": r.text[:500], "type": "upstream_error"}}
    return JSONResponse(status_code=r.status_code, content=payload)


async def _engine_completion_watchdog(
    lease: _EngineLease,
    upstream: httpx.Response,
    trace: dict[str, Any],
) -> None:
    """Release inference capacity when generation ends, even if a client vanishes.

    Agent CLIs may stop consuming an SSE body immediately after their own turn
    completes, or disconnect while a queued request is being admitted.  The
    runtime metrics are the authoritative generation lifecycle, so capacity is
    released as soon as this request's engine id completes.  Body cleanup gets
    a separate drain window to avoid truncating normal slow consumers.
    """
    before_id = trace.get("engine_request_id_before")
    deadline = time.monotonic() + 600.0
    while lease.held and time.monotonic() < deadline:
        await asyncio.sleep(0.25)
        metrics = await _engine_last_request()
        after_id = metrics.get("engine_request_id")
        if after_id is None or after_id == before_id or not metrics.get("finish_reason"):
            continue
        trace["engine_completion_observed"] = True
        trace.update(metrics)
        lease.release()
        await asyncio.sleep(STREAM_DRAIN_TIMEOUT_S)
        if str(trace.get("request_id") or "") in _inflight:
            trace["stream_cleanup"] = "drain_timeout"
            await upstream.aclose()
            await _finish_trace(trace, status="completed")
            _end_request_once(trace)
        return


async def _begin_engine(
    chat: dict[str, Any], trace: dict[str, Any] | None = None,
) -> tuple[_EngineLease, httpx.Response]:
    lease = _EngineLease(trace)
    await lease.acquire()
    try:
        if trace is not None:
            previous = await _engine_last_request()
            trace["engine_request_id_before"] = previous.get("engine_request_id")
        request_id = str((trace or {}).get("request_id") or "")
        upstream_task = asyncio.create_task(_upstream_chat(chat))
        if request_id:
            _upstream_start_tasks[request_id] = upstream_task
        try:
            deadline_at = (trace or {}).get("deadline_at")
            timeout = max(0.01, float(deadline_at) - time.time()) if deadline_at else None
            upstream = await asyncio.wait_for(upstream_task, timeout=timeout)
        except asyncio.TimeoutError as exc:
            if trace is not None:
                trace["cancel_requested"] = True
                trace["cancel_reason"] = "deadline"
                stats["scheduler"]["cancelled_total"] += 1
            raise RequestCancelled("request deadline exceeded") from exc
        except asyncio.CancelledError as exc:
            if trace is not None and trace.get("cancel_requested"):
                raise RequestCancelled("request cancelled while starting upstream") from exc
            raise
        finally:
            if request_id:
                _upstream_start_tasks.pop(request_id, None)
        if trace is not None and bool(chat.get("stream")):
            asyncio.create_task(_engine_completion_watchdog(lease, upstream, trace))
        return lease, upstream
    except BaseException:
        lease.release()
        raise


async def _handle_chat(request: Request) -> Response:
    down = _runtime_ready()
    if down:
        return down
    body, err = await _read_json(request)
    if err:
        return err
    assert body is not None
    requested = body.get("model")
    body["model"] = _resolve_model_name(requested if isinstance(requested, str) else None)
    chat = sanitize_chat_body(body)
    chat.pop("_forced_tool", None)
    trace = _new_trace(request, dialect="chat_completions", body=body, chat=chat)
    _apply_request_policy(request, chat, trace)
    _begin_request()
    if duplicate := await _duplicate_response(trace):
        _end_request(error=True)
        return duplicate
    try:
        lease, upstream = await _begin_engine(chat, trace)
    except RequestCancelled:
        await _finish_trace(trace, status="cancelled", error_type="cancelled")
        _end_request(error=True)
        return _cancelled_response(trace)
    except AdmissionRejected as e:
        await _finish_trace(trace, status="rejected", error_type="queue_full")
        _end_request(error=True)
        return _queue_error(e, trace)
    except httpx.HTTPError as e:
        await _finish_trace(trace, status="error", error_type="upstream_transport")
        _end_request(error=True)
        return JSONResponse(status_code=502, content={"error": {
            "message": f"The runtime accepted the connection but the request failed: {e}. "
                       f"Check http://127.0.0.1:8787 → Logs.",
            "type": "upstream_error"}})
    if chat.get("stream"):
        return await _stream_chat_passthrough(upstream, lease=lease, trace=trace)
    try:
        if upstream.status_code == 404:
            st = read_state()
            await _finish_trace(trace, status="error", error_type="not_supported")
            _end_request(error=True)
            return JSONResponse(status_code=501, content={"error": {
                "message": "/v1/chat/completions is not supported by the current runtime engine "
                           f"({'dflash-mlx' if st.mode == 'fast' else 'mlx-lm'}).",
                "type": "not_supported"}})
        try:
            payload = upstream.json()
            usage = payload.get("usage") or {}
            stats["tokens_generated"] += int(usage.get("completion_tokens") or 0)
        except ValueError:
            payload = None
        await _finish_trace(
            trace,
            status="completed" if upstream.status_code < 400 else "error",
            error_type=None if upstream.status_code < 400 else "upstream_error",
        )
        _end_request()
        if payload is not None:
            return JSONResponse(
                status_code=upstream.status_code, content=payload, headers=_trace_headers(trace)
            )
        return Response(content=upstream.content, status_code=upstream.status_code,
                        media_type=upstream.headers.get("content-type"), headers=_trace_headers(trace))
    finally:
        if not chat.get("stream"):
            await upstream.aclose()
            lease.release()


async def _handle_responses(request: Request) -> Response:
    down = _runtime_ready()
    if down:
        return down
    body, err = await _read_json(request)
    if err:
        return err
    assert body is not None
    requested = body.get("model")
    public = _public_model(requested)
    try:
        chat = responses_to_chat(body)
    except ResponsesCompatError as e:
        return JSONResponse(status_code=400, content={"error": {"message": str(e), "type": "invalid_request_error"}})
    chat["model"] = _resolve_model_name(requested if isinstance(requested, str) else None)
    forced = chat.pop("_forced_tool", None)
    _ = forced
    trace = _new_trace(request, dialect="responses", body=body, chat=chat)
    _apply_request_policy(request, chat, trace)
    _begin_request()
    if duplicate := await _duplicate_response(trace):
        _end_request(error=True)
        return duplicate
    try:
        lease, upstream = await _begin_engine(chat, trace)
    except RequestCancelled:
        await _finish_trace(trace, status="cancelled", error_type="cancelled")
        _end_request(error=True)
        return _cancelled_response(trace)
    except AdmissionRejected as e:
        await _finish_trace(trace, status="rejected", error_type="queue_full")
        _end_request(error=True)
        return _queue_error(e, trace)
    except httpx.HTTPError as e:
        await _finish_trace(trace, status="error", error_type="upstream_transport")
        _end_request(error=True)
        return JSONResponse(status_code=502, content={"error": {
            "message": f"The runtime accepted the connection but the request failed: {e}. "
                       f"Check http://127.0.0.1:8787 → Logs.",
            "type": "upstream_error"}})
    if chat.get("stream"):
        if upstream.status_code >= 400:
            data = await upstream.aread()
            await upstream.aclose()
            await _finish_trace(trace, status="error", error_type="upstream_error")
            lease.release()
            _end_request(error=True)
            try:
                return JSONResponse(status_code=upstream.status_code, content=json.loads(data))
            except json.JSONDecodeError:
                return JSONResponse(status_code=upstream.status_code, content={"error": {"message": data.decode(errors="replace")[:500]}})
        return await _stream_mapped(
            upstream, dialect="responses", public_model=public, chat_request=chat,
            lease=lease, trace=trace,
        )
    try:
        if upstream.status_code >= 400:
            await _finish_trace(trace, status="error", error_type="upstream_error")
            _end_request(error=True)
            return _error_from_upstream(upstream)
        payload = upstream.json()
        usage = payload.get("usage") or {}
        stats["tokens_generated"] += int(usage.get("completion_tokens") or 0)
        resp = chat_to_responses(payload, public_model=public)
        remember_turn(resp, chat, payload)
        await _finish_trace(trace, status="completed")
        _end_request()
        return JSONResponse(content=resp, headers=_trace_headers(trace))
    except ValueError:
        await _finish_trace(trace, status="error", error_type="invalid_upstream_json")
        _end_request(error=True)
        return JSONResponse(status_code=502, content={"error": {
            "message": "Runtime returned a non-JSON chat completion.",
            "type": "upstream_error"}})
    finally:
        if not chat.get("stream"):
            await upstream.aclose()
            lease.release()


async def _handle_messages(request: Request) -> Response:
    down = _runtime_ready()
    if down:
        return down
    body, err = await _read_json(request)
    if err:
        return err
    assert body is not None
    requested = body.get("model")
    public = _public_model(requested)
    try:
        chat = messages_to_chat(body)
    except AnthropicCompatError as e:
        return JSONResponse(status_code=400, content={"error": {"type": "invalid_request_error", "message": str(e)}})
    chat["model"] = _resolve_model_name(requested if isinstance(requested, str) else None)
    chat.pop("_forced_tool", None)
    trace = _new_trace(request, dialect="anthropic_messages", body=body, chat=chat)
    _apply_request_policy(request, chat, trace)
    _begin_request()
    if duplicate := await _duplicate_response(trace):
        _end_request(error=True)
        return duplicate
    try:
        lease, upstream = await _begin_engine(chat, trace)
    except RequestCancelled:
        await _finish_trace(trace, status="cancelled", error_type="cancelled")
        _end_request(error=True)
        return _cancelled_response(trace)
    except AdmissionRejected as e:
        await _finish_trace(trace, status="rejected", error_type="queue_full")
        _end_request(error=True)
        return _queue_error(e, trace)
    except httpx.HTTPError as e:
        await _finish_trace(trace, status="error", error_type="upstream_transport")
        _end_request(error=True)
        return JSONResponse(status_code=502, content={"error": {
            "message": f"The runtime accepted the connection but the request failed: {e}. "
                       f"Check http://127.0.0.1:8787 → Logs.",
            "type": "upstream_error"}})
    if chat.get("stream"):
        if upstream.status_code >= 400:
            data = await upstream.aread()
            await upstream.aclose()
            await _finish_trace(trace, status="error", error_type="upstream_error")
            lease.release()
            _end_request(error=True)
            if upstream.status_code == 404:
                return _anthropic_error_from_upstream(upstream)
            try:
                return JSONResponse(status_code=upstream.status_code, content=json.loads(data))
            except json.JSONDecodeError:
                return JSONResponse(status_code=upstream.status_code, content={"error": {"message": data.decode(errors="replace")[:500]}})
        return await _stream_mapped(
            upstream, dialect="anthropic", public_model=public, chat_request=chat,
            lease=lease, trace=trace,
        )
    try:
        if upstream.status_code >= 400:
            await _finish_trace(trace, status="error", error_type="upstream_error")
            _end_request(error=True)
            return _anthropic_error_from_upstream(upstream)
        payload = upstream.json()
        usage = payload.get("usage") or {}
        stats["tokens_generated"] += int(usage.get("completion_tokens") or 0)
        await _finish_trace(trace, status="completed")
        _end_request()
        return JSONResponse(
            content=chat_to_messages(payload, public_model=public), headers=_trace_headers(trace)
        )
    except ValueError:
        await _finish_trace(trace, status="error", error_type="invalid_upstream_json")
        _end_request(error=True)
        return JSONResponse(status_code=502, content={"error": {
            "message": "Runtime returned a non-JSON chat completion.",
            "type": "upstream_error"}})
    finally:
        if not chat.get("stream"):
            await upstream.aclose()
            lease.release()


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    return await _handle_chat(request)


@app.post("/v1/completions")
async def completions(request: Request) -> Response:
    """Legacy completions: pass through. Agents should use chat / responses / messages."""
    down = _runtime_ready()
    if down:
        return down
    body, err = await _read_json(request)
    if err:
        return err
    assert body is not None
    if "model" in body:
        body["model"] = _resolve_model_name(body.get("model") if isinstance(body.get("model"), str) else None)
    trace = _new_trace(request, dialect="legacy_completions", body=body, chat=body)
    _begin_request()
    url = _upstream_base() + "/v1/completions"
    lease = _EngineLease(trace)
    try:
        await lease.acquire()
        if body.get("stream"):
            req = _client.build_request("POST", url, json=body, headers={"content-type": "application/json"})
            upstream = await _client.send(req, stream=True)
            return await _stream_chat_passthrough(upstream, lease=lease, trace=trace)
        r = await _client.post(url, json=body, headers={"content-type": "application/json"})
        await _finish_trace(
            trace, status="completed" if r.status_code < 400 else "error",
            error_type=None if r.status_code < 400 else "upstream_error",
        )
        _end_request()
        try:
            return JSONResponse(status_code=r.status_code, content=r.json(), headers=_trace_headers(trace))
        except ValueError:
            return Response(content=r.content, status_code=r.status_code, headers=_trace_headers(trace))
        finally:
            lease.release()
    except AdmissionRejected as e:
        await _finish_trace(trace, status="rejected", error_type="queue_full")
        _end_request(error=True)
        return _queue_error(e, trace)
    except httpx.HTTPError as e:
        lease.release()
        await _finish_trace(trace, status="error", error_type="upstream_transport")
        _end_request(error=True)
        return JSONResponse(status_code=502, content={"error": {
            "message": f"The runtime accepted the connection but the request failed: {e}.",
            "type": "upstream_error"}})


@app.post("/v1/responses")
async def responses(request: Request) -> Response:
    return await _handle_responses(request)


@app.post("/v1/messages")
async def anthropic_messages(request: Request) -> Response:
    return await _handle_messages(request)


def _estimate_input_tokens(body: dict[str, Any]) -> int:
    blob = json.dumps(body, ensure_ascii=False)
    return max(1, len(blob) // 4)


@app.post("/v1/messages/count_tokens")
async def anthropic_count_tokens(request: Request) -> Response:
    """Claude Code probes this before a turn. Return a cheap estimate, never 404."""
    _note_agent(request)
    body, err = await _read_json(request)
    if err:
        return err
    assert body is not None
    n = _estimate_input_tokens(body)
    return JSONResponse({
        "input_tokens": n,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    })


@app.api_route("/api/hello", methods=["GET", "HEAD"])
async def anthropic_hello() -> Response:
    """Claude Code pings this to see if the origin looks like Anthropic."""
    return JSONResponse({"ok": True})


def main() -> None:
    import uvicorn
    cfg = load_config()
    uvicorn.run("backend.gateway:app",
                host=cfg["api"]["host"], port=cfg["api"]["port"],
                log_level="warning")


if __name__ == "__main__":
    main()
