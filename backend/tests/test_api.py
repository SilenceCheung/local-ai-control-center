"""Integration tests against the live control backend + gateway + runtime.

These require the stack to be running (skipped otherwise) — they verify the
real contracts, not mocks.
"""

import httpx
import pytest

BACKEND = "http://127.0.0.1:8787"
GATEWAY = "http://127.0.0.1:8080"


def _up(url: str) -> bool:
    try:
        return httpx.get(url, timeout=2).status_code < 500
    except httpx.HTTPError:
        return False


requires_backend = pytest.mark.skipif(not _up(BACKEND + "/api/health"),
                                      reason="control backend not running")
requires_gateway = pytest.mark.skipif(not _up(GATEWAY + "/health"),
                                      reason="gateway not running")


@requires_backend
def test_health_contract():
    d = httpx.get(BACKEND + "/api/health", timeout=5).json()
    assert d["backend"] == "ok"
    for key in ("status", "mode", "model_loaded", "draft_loaded"):
        assert key in d["runtime"]
    assert d["ports"]["api"] == 8080


@requires_backend
def test_models_registry():
    models = httpx.get(BACKEND + "/api/models", timeout=10).json()
    assert isinstance(models, list)
    roles = {m["role"] for m in models}
    ids = {m["id"] for m in models}
    assert "McG-221/Qwen3.8-27B-heretic-ara-mlx-8Bit" in ids
    assert "target" in roles and "draft" in roles


@requires_backend
def test_settings_rejects_unknown_section():
    r = httpx.put(BACKEND + "/api/settings", json={"hacker": True}, timeout=5)
    assert r.status_code == 422


@requires_backend
def test_benchmark_history_shape():
    hist = httpx.get(BACKEND + "/api/benchmark/history", timeout=5).json()
    assert isinstance(hist, list)
    if hist:
        assert {"kind", "results", "created_at"} <= set(hist[0])


@requires_gateway
def test_gateway_models_alias():
    from backend.core.config import load_config
    d = httpx.get(GATEWAY + "/v1/models", timeout=5).json()
    ids = [m["id"] for m in d["data"]]
    assert load_config()["api"]["alias"] in ids


@requires_gateway
def test_gateway_health_structured():
    d = httpx.get(GATEWAY + "/health", timeout=5).json()
    assert d["gateway"] == "ok"
    assert "model_loaded" in d["runtime"]


@requires_gateway
def test_chat_completion_via_alias():
    """Real inference through the public path — skipped if runtime stopped."""
    h = httpx.get(GATEWAY + "/health", timeout=5).json()
    if h["runtime"]["status"] != "running":
        pytest.skip("runtime not running")
    r = httpx.post(GATEWAY + "/v1/chat/completions", json={
        "model": "qwen3.8-27b-local",
        "messages": [{"role": "user", "content": "Reply with the word: pong"}],
        "max_tokens": 120, "temperature": 0, "stream": False,
    }, timeout=180)
    assert r.status_code == 200
    data = r.json()
    msg = data["choices"][0]["message"]
    assert msg["role"] == "assistant"
    assert (msg.get("content") or "").strip() or msg.get("reasoning_content")


@requires_gateway
def test_live_responses_does_not_400():
    """Grok-style Responses body must be translated, not forwarded as 400."""
    h = httpx.get(GATEWAY + "/health", timeout=5).json()
    if h["runtime"]["status"] != "running":
        pytest.skip("runtime not running")
    r = httpx.post(GATEWAY + "/v1/responses", json={
        "model": "qwen3.8-27b-local",
        "stream": False,
        "reasoning": {"effort": "high"},
        "store": True,
        "input": "Reply with exactly the word: pong",
        "max_output_tokens": 32,
    }, timeout=180, headers={"User-Agent": "Grok/1.0"})
    assert r.status_code == 200, r.text[:800]
    data = r.json()
    assert data.get("object") == "response"
    assert data.get("status") in {"completed", "incomplete", None} or "output" in data
    text = ""
    for item in data.get("output") or []:
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if part.get("type") in {"output_text", "text"}:
                    text += part.get("text") or ""
        if item.get("type") == "output_text":
            text += item.get("text") or ""
    assert data.get("output_text") or text or data.get("output")


@requires_gateway
def test_live_chat_function_tool_choice_does_not_400():
    h = httpx.get(GATEWAY + "/health", timeout=5).json()
    if h["runtime"]["status"] != "running":
        pytest.skip("runtime not running")
    r = httpx.post(GATEWAY + "/v1/chat/completions", json={
        "model": "qwen3.8-27b-local",
        "messages": [{"role": "user", "content": "Call get_time now."}],
        "tools": [{
            "type": "function",
            "function": {
                "name": "get_time",
                "description": "Return the current time",
                "parameters": {"type": "object", "properties": {}},
            },
        }],
        "tool_choice": {"type": "function", "function": {"name": "get_time"}},
        "max_tokens": 128,
        "temperature": 0,
        "stream": False,
    }, timeout=180, headers={"User-Agent": "Grok/1.0"})
    assert r.status_code == 200, r.text[:800]
    msg = r.json()["choices"][0]["message"]
    assert msg.get("tool_calls") or (msg.get("content") or "").strip()


@requires_gateway
def test_live_responses_stream_events():
    h = httpx.get(GATEWAY + "/health", timeout=5).json()
    if h["runtime"]["status"] != "running":
        pytest.skip("runtime not running")
    with httpx.stream("POST", GATEWAY + "/v1/responses", json={
        "model": "qwen3.8-27b-local",
        "stream": True,
        "input": "Reply with exactly: ok",
        "max_output_tokens": 24,
    }, timeout=180, headers={"User-Agent": "codex-cli"}) as r:
        assert r.status_code == 200, r.read()[:800]
        body = b"".join(r.iter_bytes()).decode(errors="replace")
    assert "response.created" in body or "response.output_text.delta" in body
    assert "response.completed" in body


@requires_gateway
def test_live_anthropic_messages():
    h = httpx.get(GATEWAY + "/health", timeout=5).json()
    if h["runtime"]["status"] != "running":
        pytest.skip("runtime not running")
    r = httpx.post(
        GATEWAY + "/v1/messages",
        json={
            "model": "qwen3.8-27b-local",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
        },
        timeout=180,
        headers={"anthropic-version": "2023-06-01", "User-Agent": "claude-cli/1.0"},
    )
    assert r.status_code == 200, r.text[:800]
    data = r.json()
    assert data.get("type") == "message"
    assert data.get("role") == "assistant"
    blocks = data.get("content") or []
    assert blocks
    assert any(b.get("type") in {"text", "tool_use"} for b in blocks)


@requires_gateway
def test_stopped_runtime_gives_structured_error():
    """The gateway must explain failures, not just 500."""
    h = httpx.get(GATEWAY + "/health", timeout=5).json()
    if h["runtime"]["status"] == "running":
        pytest.skip("runtime is running; error path not reachable")
    r = httpx.post(GATEWAY + "/v1/chat/completions", json={
        "model": "qwen3.8-27b-local",
        "messages": [{"role": "user", "content": "hi"}],
    }, timeout=10)
    assert r.status_code == 503
    err = r.json()["error"]
    assert err["code"] == "runtime_unavailable"
    assert "how_to_fix" in err
