"""Live multi-turn agent loops through the public gateway.

Skipped when 8080/runtime are down. The secret token is only in the tool
result — the model must call the tool and use the returned value.
"""

from __future__ import annotations

import json

import httpx
import pytest

GATEWAY = "http://127.0.0.1:8080"
SECRET = "TOKEN-ALPHA-7"
MODEL = "Qwen3.8-27B-Heretic-8bit"
PROMPT = (
    "You are a tool-using agent. Call lookup_code with name exactly 'alpha'. "
    "After you receive the tool result, reply with only that token."
)


def _runtime_up() -> bool:
    try:
        h = httpx.get(GATEWAY + "/health", timeout=2, trust_env=False).json()
    except (httpx.HTTPError, ValueError):
        return False
    return h.get("runtime", {}).get("status") == "running"


requires_runtime = pytest.mark.skipif(not _runtime_up(), reason="runtime not running")

CHAT_TOOLS = [{
    "type": "function",
    "function": {
        "name": "lookup_code",
        "description": "Look up a named access token. Use name=alpha.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
}]
RESP_TOOLS = [{
    "type": "function",
    "name": "lookup_code",
    "description": "Look up a named access token. Use name=alpha.",
    "parameters": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
}]
ANTHROPIC_TOOLS = [{
    "name": "lookup_code",
    "description": "Look up a named access token. Use name=alpha.",
    "input_schema": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
}]


def _run_tool(name: str, arguments: str | dict | None) -> str:
    if name != "lookup_code":
        return json.dumps({"error": f"unknown tool {name}"})
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            args = {}
    elif isinstance(arguments, dict):
        args = arguments
    else:
        args = {}
    value = str(args.get("name") or "").strip().lower()
    return SECRET if value == "alpha" else "unknown"


def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(180.0, connect=5.0), trust_env=False)


def _completed_from_sse(raw: str) -> dict:
    last = None
    for block in raw.split("\n\n"):
        if "response.completed" not in block:
            continue
        for line in block.split("\n"):
            if line.startswith("data:"):
                last = json.loads(line[5:].strip())
    assert last is not None, f"no response.completed in stream: {raw[:400]!r}"
    return last.get("response") or last



@requires_runtime
def test_live_chat_agent_tool_loop():
    """Cursor-style Chat Completions: tool_calls → role=tool → final text."""
    messages = [{"role": "user", "content": PROMPT}]
    with _client() as c:
        r1 = c.post(GATEWAY + "/v1/chat/completions", json={
            "model": MODEL,
            "messages": messages,
            "tools": CHAT_TOOLS,
            "tool_choice": "auto",
            "max_tokens": 256,
            "temperature": 0,
            "stream": False,
        }, headers={"User-Agent": "cursor-agent"})
        assert r1.status_code == 200, r1.text[:800]
        msg = r1.json()["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        assert calls, f"model did not call a tool: {msg}"
        fn = (calls[0].get("function") or {})
        result = _run_tool(fn.get("name") or "", fn.get("arguments"))
        messages.append(msg)
        messages.append({
            "role": "tool",
            "tool_call_id": calls[0]["id"],
            "content": result,
        })
        r2 = c.post(GATEWAY + "/v1/chat/completions", json={
            "model": MODEL,
            "messages": messages,
            "tools": CHAT_TOOLS,
            "tool_choice": "none",
            "max_tokens": 128,
            "temperature": 0,
            "stream": False,
        }, headers={"User-Agent": "cursor-agent"})
        assert r2.status_code == 200, r2.text[:800]
        final = (r2.json()["choices"][0]["message"].get("content") or "")
        reasoning = r2.json()["choices"][0]["message"].get("reasoning_content") or ""
        blob = final + "\n" + reasoning
        assert SECRET in blob, f"agent did not use tool result: {blob[:500]!r}"


@requires_runtime
def test_live_responses_agent_previous_id_loop():
    """Codex-style Responses: tool call → previous_response_id + output."""
    with _client() as c:
        r1 = c.post(GATEWAY + "/v1/responses", json={
            "model": MODEL,
            "stream": False,
            "instructions": "You are a tool-using agent.",
            "input": PROMPT,
            "tools": RESP_TOOLS,
            "max_output_tokens": 256,
        }, headers={"User-Agent": "codex-cli"})
        assert r1.status_code == 200, r1.text[:800]
        body = r1.json()
        assert body.get("object") == "response"
        fcs = [o for o in (body.get("output") or []) if o.get("type") == "function_call"]
        assert fcs, f"no function_call in output: {body.get('output')}"
        fc = fcs[0]
        result = _run_tool(fc.get("name") or "", fc.get("arguments"))
        r2 = c.post(GATEWAY + "/v1/responses", json={
            "model": MODEL,
            "stream": False,
            "previous_response_id": body["id"],
            "input": [{
                "type": "function_call_output",
                "call_id": fc["call_id"],
                "output": result,
            }],
            "tools": RESP_TOOLS,
            "max_output_tokens": 128,
        }, headers={"User-Agent": "codex-cli"})
        assert r2.status_code == 200, r2.text[:800]
        done = r2.json()
        text = done.get("output_text") or ""
        for item in done.get("output") or []:
            if item.get("type") == "message":
                for part in item.get("content") or []:
                    text += part.get("text") or ""
        assert SECRET in text, f"agent did not use tool result: {text[:500]!r} output={done.get('output')}"


@requires_runtime
def test_live_responses_stream_previous_id_loop():
    """Codex default: stream the first turn so memory must keep tool_calls."""
    with _client() as c:
        with c.stream("POST", GATEWAY + "/v1/responses", json={
            "model": MODEL,
            "stream": True,
            "instructions": "You are a tool-using agent.",
            "input": PROMPT,
            "tools": RESP_TOOLS,
            "max_output_tokens": 256,
        }, headers={"User-Agent": "codex-cli"}) as r1:
            assert r1.status_code == 200, r1.read()[:800]
            raw = b"".join(r1.iter_bytes()).decode(errors="replace")
        body = _completed_from_sse(raw)
        fcs = [o for o in (body.get("output") or []) if o.get("type") == "function_call"]
        assert fcs, f"no function_call in stream: {raw[:600]!r}"
        fc = fcs[0]
        result = _run_tool(fc.get("name") or "", fc.get("arguments"))
        r2 = c.post(GATEWAY + "/v1/responses", json={
            "model": MODEL,
            "stream": False,
            "previous_response_id": body["id"],
            "input": [{
                "type": "function_call_output",
                "call_id": fc["call_id"],
                "output": result,
            }],
            "tools": RESP_TOOLS,
            "max_output_tokens": 128,
        }, headers={"User-Agent": "codex-cli"})
        assert r2.status_code == 200, r2.text[:800]
        done = r2.json()
        text = done.get("output_text") or ""
        for item in done.get("output") or []:
            if item.get("type") == "message":
                for part in item.get("content") or []:
                    text += part.get("text") or ""
        assert SECRET in text, f"stream memory lost the tool call: {text[:500]!r} output={done.get('output')}"



@requires_runtime
def test_live_responses_agent_replay_loop():
    """Grok-style Responses: resend function_call + function_call_output together."""
    with _client() as c:
        r1 = c.post(GATEWAY + "/v1/responses", json={
            "model": MODEL,
            "stream": False,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": PROMPT}]}],
            "tools": RESP_TOOLS,
            "max_output_tokens": 256,
        }, headers={"User-Agent": "Grok/1.0"})
        assert r1.status_code == 200, r1.text[:800]
        body = r1.json()
        fcs = [o for o in (body.get("output") or []) if o.get("type") == "function_call"]
        assert fcs, f"no function_call in output: {body.get('output')}"
        fc = fcs[0]
        result = _run_tool(fc.get("name") or "", fc.get("arguments"))
        r2 = c.post(GATEWAY + "/v1/responses", json={
            "model": MODEL,
            "stream": False,
            "input": [
                {"role": "user", "content": [{"type": "input_text", "text": PROMPT}]},
                {
                    "type": "function_call",
                    "call_id": fc["call_id"],
                    "name": fc["name"],
                    "arguments": fc.get("arguments") or "{}",
                },
                {
                    "type": "function_call_output",
                    "call_id": fc["call_id"],
                    "output": result,
                },
            ],
            "tools": RESP_TOOLS,
            "max_output_tokens": 128,
        }, headers={"User-Agent": "Grok/1.0"})
        assert r2.status_code == 200, r2.text[:800]
        text = r2.json().get("output_text") or ""
        for item in r2.json().get("output") or []:
            if item.get("type") == "message":
                for part in item.get("content") or []:
                    text += part.get("text") or ""
        assert SECRET in text, f"agent did not use tool result: {text[:500]!r}"


@requires_runtime
def test_live_anthropic_agent_tool_loop():
    """Claude Code: tool_use → tool_result → final text."""
    messages = [{"role": "user", "content": [{"type": "text", "text": PROMPT}]}]
    with _client() as c:
        r1 = c.post(GATEWAY + "/v1/messages", json={
            "model": MODEL,
            "max_tokens": 256,
            "system": "You are a tool-using agent.",
            "tools": ANTHROPIC_TOOLS,
            "messages": messages,
        }, headers={"anthropic-version": "2023-06-01", "User-Agent": "claude-cli/1.0"})
        assert r1.status_code == 200, r1.text[:800]
        body = r1.json()
        assert body.get("type") == "message"
        uses = [b for b in (body.get("content") or []) if b.get("type") == "tool_use"]
        assert uses, f"no tool_use: {body.get('content')}"
        use = uses[0]
        result = _run_tool(use.get("name") or "", use.get("input"))
        messages.append({"role": "assistant", "content": body["content"]})
        messages.append({"role": "user", "content": [{
            "type": "tool_result",
            "tool_use_id": use["id"],
            "content": result,
        }]})
        r2 = c.post(GATEWAY + "/v1/messages", json={
            "model": MODEL,
            "max_tokens": 128,
            "system": "You are a tool-using agent. After the tool result, reply with only the token.",
            "tools": ANTHROPIC_TOOLS,
            "messages": messages,
        }, headers={"anthropic-version": "2023-06-01", "User-Agent": "claude-cli/1.0"})
        assert r2.status_code == 200, r2.text[:800]
        done = r2.json()
        texts = [b.get("text") or "" for b in (done.get("content") or []) if b.get("type") == "text"]
        blob = "\n".join(texts)
        assert SECRET in blob, f"agent did not use tool result: {blob[:500]!r} stop={done.get('stop_reason')} content={done.get('content')}"
