"""HTTP-level gateway adapter tests.

These hit FastAPI routes with a fake Chat Completions upstream so they prove
the wiring (sanitize, Responses, Anthropic, SSE) without loading 27B.
"""

from __future__ import annotations

import json
import asyncio
from typing import Any, AsyncIterator

import pytest
from fastapi.testclient import TestClient

import backend.gateway as gw


class FakeUpstream:
    def __init__(
        self,
        *,
        status: int = 200,
        payload: dict[str, Any] | None = None,
        chunks: list[bytes] | None = None,
        delay_first_s: float = 0,
    ) -> None:
        self.status_code = status
        self._payload = payload
        self._chunks = chunks or []
        self._delay_first_s = delay_first_s
        self.headers = {
            "content-type": "text/event-stream" if chunks is not None else "application/json",
        }
        self.content = json.dumps(payload or {}).encode()

    def json(self) -> dict[str, Any]:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    async def aread(self) -> bytes:
        return self.content

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        if self._delay_first_s:
            import asyncio
            await asyncio.sleep(self._delay_first_s)
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        return None


class HangingAfterDoneUpstream(FakeUpstream):
    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        import asyncio

        yield SSE_TEXT
        await asyncio.Event().wait()


class HangingWithoutDoneUpstream(FakeUpstream):
    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        import asyncio

        yield b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
        await asyncio.Event().wait()


TEXT_PAYLOAD = {
    "id": "chatcmpl_test",
    "object": "chat.completion",
    "model": "local",
    "choices": [{
        "index": 0,
        "finish_reason": "stop",
        "message": {"role": "assistant", "content": "ok"},
    }],
    "usage": {"prompt_tokens": 8, "completion_tokens": 1},
}

TOOL_PAYLOAD = {
    "id": "chatcmpl_tool",
    "object": "chat.completion",
    "model": "local",
    "choices": [{
        "index": 0,
        "finish_reason": "tool_calls",
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{\"path\":\"a.py\"}"},
            }],
        },
    }],
    "usage": {"prompt_tokens": 20, "completion_tokens": 12},
}

SSE_TEXT = (
    b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
    b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
    b"data: [DONE]\n\n"
)

SSE_TOOL = (
    b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"bash","arguments":""}}]}}]}\n\n'
    b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"command\\":\\"ls\\"}"}}]}}]}\n\n'
    b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
    b"data: [DONE]\n\n"
)


@pytest.fixture
def captured() -> dict[str, Any]:
    return {"chat": None}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> TestClient:
    monkeypatch.setattr(gw, "_runtime_ready", lambda: None)

    async def fake_upstream(chat: dict[str, Any]) -> FakeUpstream:
        captured["chat"] = json.loads(json.dumps(chat))
        if chat.get("stream"):
            chunks = [SSE_TOOL] if chat.get("tools") else [SSE_TEXT]
            return FakeUpstream(chunks=chunks)
        if chat.get("tools"):
            return FakeUpstream(payload=TOOL_PAYLOAD)
        return FakeUpstream(payload=TEXT_PAYLOAD)

    monkeypatch.setattr(gw, "_upstream_chat", fake_upstream)
    monkeypatch.setattr(gw, "_resolve_model_name", lambda requested: "served-model")

    async def fake_metrics() -> dict[str, Any]:
        return {
            "prompt_tokens": 8,
            "prefill_tokens_physical": 8,
            "prefill_tokens_restored": 0,
            "cache_status": "COLD",
            "prefill_ms": 12.0,
            "engine_ttft_ms": 15.0,
            "decode_tok_s": 70.0,
            "acceptance_rate": 0.8,
        }

    monkeypatch.setattr(gw, "_engine_last_request", fake_metrics)
    return TestClient(gw.app)


def test_chat_function_tool_choice_is_sanitized(client: TestClient, captured: dict[str, Any]) -> None:
    r = client.post("/v1/chat/completions", json={
        "model": "Qwen3.8-27B-Heretic-8bit",
        "messages": [{"role": "user", "content": "open a.py"}],
        "tool_choice": {"type": "function", "function": {"name": "read_file"}},
        "tools": [{
            "type": "function",
            "function": {"name": "read_file", "parameters": {"type": "object"}},
        }],
        "stream": False,
    }, headers={"User-Agent": "Grok/1.0"})
    assert r.status_code == 200, r.text
    chat = captured["chat"]
    assert chat is not None
    assert chat["tool_choice"] == "auto"
    assert chat["temperature"] == 0
    assert chat["messages"][-1]["content"] == "Use the `read_file` tool for this request."
    assert "_forced_tool" not in chat
    data = r.json()
    assert data["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "read_file"
    assert gw.stats["agents_seen"].get("grok")


def test_responses_grok_body_becomes_chat_and_returns_response(
    client: TestClient, captured: dict[str, Any],
) -> None:
    r = client.post("/v1/responses", json={
        "model": "Qwen3.8-27B-Heretic-8bit",
        "stream": False,
        "tool_choice": {"type": "function", "name": "read_file"},
        "reasoning": {"effort": "high"},
        "store": True,
        "previous_response_id": "resp_missing",
        "instructions": "You are a coding agent.",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "open a.py"}]}],
        "tools": [{
            "type": "function",
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        }],
        "max_output_tokens": 256,
    })
    assert r.status_code == 200, r.text
    chat = captured["chat"]
    assert chat["stream"] is False
    assert chat["tool_choice"] == "auto"
    assert chat["max_tokens"] == 256
    assert "reasoning" not in chat
    assert chat["chat_template_kwargs"]["enable_thinking"] is False
    assert r.headers["x-localai-profile"] == "production"
    assert r.headers["x-localai-max-tokens"] == "256"
    assert "store" not in chat
    body = r.json()
    assert body["object"] == "response"
    kinds = [o["type"] for o in body["output"]]
    assert "function_call" in kinds


def test_tiny_response_disables_thinking_to_protect_visible_output(
    client: TestClient, captured: dict[str, Any],
) -> None:
    r = client.post("/v1/responses", json={
        "model": "local",
        "input": "Reply with exactly: pong",
        "reasoning": {"effort": "high"},
        "max_output_tokens": 32,
    })
    assert r.status_code == 200, r.text
    assert captured["chat"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert r.headers["x-localai-request-id"].startswith("req_")
    assert float(r.headers["x-localai-queue-wait-ms"]) >= 0
    trace = gw.stats["recent_requests"][-1]
    assert trace["dialect"] == "responses"
    assert trace["prefill_ms"] == 12.0
    assert trace["prompt_fingerprint"]
    assert "request_content" not in trace
    assert captured["chat"]["temperature"] == 0


def test_responses_stream_emits_text_delta_and_completed(client: TestClient) -> None:
    with client.stream("POST", "/v1/responses", json={
        "model": "local",
        "stream": True,
        "input": "hi",
    }) as r:
        assert r.status_code == 200, r.read()
        text = b"".join(r.iter_bytes()).decode()
    assert "response.output_text.delta" in text
    assert "hel" in text
    assert "response.completed" in text


def test_responses_stream_maps_tool_call_arguments(client: TestClient) -> None:
    with client.stream("POST", "/v1/responses", json={
        "model": "local",
        "stream": True,
        "input": "list files",
        "tools": [{"type": "function", "name": "bash", "parameters": {}}],
    }) as r:
        assert r.status_code == 200, r.read()
        text = b"".join(r.iter_bytes()).decode()
    assert "response.function_call_arguments.delta" in text
    assert "ls" in text
    assert "response.completed" in text


def test_anthropic_messages_tool_use(client: TestClient, captured: dict[str, Any]) -> None:
    r = client.post(
        "/v1/messages",
        json={
            "model": "Qwen3.8-27B-Heretic-8bit",
            "max_tokens": 128,
            "system": "Be brief.",
            "tool_choice": {"type": "tool", "name": "read_file"},
            "tools": [{
                "name": "read_file",
                "description": "Read a file",
                "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
            }],
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "open a.py"}]},
            ],
        },
        headers={"anthropic-version": "2023-06-01", "User-Agent": "claude-cli/1.0"},
    )
    assert r.status_code == 200, r.text
    chat = captured["chat"]
    assert chat["tool_choice"] == "auto"
    assert chat["messages"][0]["role"] == "system"
    body = r.json()
    assert body["type"] == "message"
    assert body["stop_reason"] == "tool_use"
    assert body["content"][0]["type"] == "tool_use"
    assert body["content"][0]["name"] == "read_file"
    assert gw.stats["agents_seen"].get("claude-code")


def test_anthropic_messages_stream(client: TestClient) -> None:
    with client.stream(
        "POST",
        "/v1/messages",
        json={
            "model": "local",
            "max_tokens": 32,
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"anthropic-version": "2023-06-01"},
    ) as r:
        assert r.status_code == 200, r.read()
        text = b"".join(r.iter_bytes()).decode()
    assert "message_start" in text
    assert "content_block_delta" in text
    assert "message_stop" in text


def test_normalize_asgi_scope_splits_embedded_query() -> None:
    scope = {
        "path": "/v1/messages?beta=true",
        "raw_path": b"/v1/messages?beta=true",
        "query_string": b"",
    }
    gw.normalize_asgi_scope(scope)
    assert scope["path"] == "/v1/messages"
    assert scope["query_string"] == b"beta=true"
    assert scope["raw_path"] == b"/v1/messages"


def test_normalize_asgi_scope_decodes_percent_question() -> None:
    scope = {
        "path": "/v1/messages%3Fbeta%3Dtrue",
        "raw_path": b"/v1/messages%3Fbeta%3Dtrue",
        "query_string": b"",
    }
    gw.normalize_asgi_scope(scope)
    assert scope["path"] == "/v1/messages"
    assert b"beta=true" in scope["query_string"]


def test_normalize_asgi_scope_collapses_double_slash() -> None:
    scope = {"path": "//v1/messages", "raw_path": b"//v1/messages", "query_string": b""}
    gw.normalize_asgi_scope(scope)
    assert scope["path"] == "/v1/messages"


def test_anthropic_messages_beta_query(client: TestClient) -> None:
    r = client.post(
        "/v1/messages?beta=true",
        json={
            "model": "local",
            "max_tokens": 32,
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"anthropic-version": "2023-06-01"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["type"] == "message"


def test_anthropic_count_tokens(client: TestClient) -> None:
    r = client.post(
        "/v1/messages/count_tokens",
        json={
            "model": "local",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"anthropic-version": "2023-06-01"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["input_tokens"] >= 1


def test_anthropic_hello(client: TestClient) -> None:
    assert client.get("/api/hello").status_code == 200
    assert client.head("/api/hello").status_code == 200


def test_anthropic_engine_404_becomes_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gw, "_runtime_ready", lambda: None)
    monkeypatch.setattr(gw, "_resolve_model_name", lambda requested: "served-model")

    async def fake_404(chat: dict[str, Any]) -> FakeUpstream:
        return FakeUpstream(status=404, payload={"error": {"message": "not found"}})

    monkeypatch.setattr(gw, "_upstream_chat", fake_404)
    c = TestClient(gw.app)
    r = c.post(
        "/v1/messages?beta=true",
        json={
            "model": "Qwen3.8-27B-Heretic-8bit",
            "max_tokens": 8,
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"anthropic-version": "2023-06-01"},
    )
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["type"] == "error"
    assert "missing-model" in body["error"]["message"]


def test_sse_heartbeat_during_prefill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gw, "_runtime_ready", lambda: None)
    monkeypatch.setattr(gw, "HEARTBEAT_S", 0.12)
    monkeypatch.setattr(gw, "_resolve_model_name", lambda requested: "served-model")

    async def slow_upstream(chat: dict[str, Any]) -> FakeUpstream:
        return FakeUpstream(chunks=[SSE_TEXT], delay_first_s=0.35)

    monkeypatch.setattr(gw, "_upstream_chat", slow_upstream)
    c = TestClient(gw.app)
    with c.stream("POST", "/v1/chat/completions", json={
        "model": "local",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }) as r:
        assert r.status_code == 200, r.read()
        text = b"".join(r.iter_bytes()).decode()
    assert ": keepalive" in text
    assert "hel" in text


def test_sse_done_releases_even_if_upstream_keeps_socket_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gw, "_runtime_ready", lambda: None)
    monkeypatch.setattr(gw, "_resolve_model_name", lambda requested: "served-model")

    async def hanging_upstream(chat: dict[str, Any]) -> FakeUpstream:
        return HangingAfterDoneUpstream(chunks=[SSE_TEXT])

    async def fake_metrics() -> dict[str, Any]:
        return {}

    monkeypatch.setattr(gw, "_upstream_chat", hanging_upstream)
    monkeypatch.setattr(gw, "_engine_last_request", fake_metrics)
    c = TestClient(gw.app)
    with c.stream("POST", "/v1/chat/completions", json={
        "model": "local",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }) as r:
        assert r.status_code == 200
        text = b"".join(r.iter_bytes()).decode()
    assert "[DONE]" in text
    assert gw.stats["scheduler"]["active"] == 0
    assert not gw._chat_lock.locked()


def test_sse_synthesizes_done_when_matching_engine_request_finished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gw, "_runtime_ready", lambda: None)
    monkeypatch.setattr(gw, "_resolve_model_name", lambda requested: "served-model")
    monkeypatch.setattr(gw, "STREAM_COMPLETION_PROBE_S", 0.01)

    async def hanging_upstream(chat: dict[str, Any]) -> FakeUpstream:
        return HangingWithoutDoneUpstream(chunks=[])

    calls = 0

    async def fake_metrics() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"engine_request_id": 40, "finish_reason": "stop"}
        return {"engine_request_id": 41, "finish_reason": "length"}

    monkeypatch.setattr(gw, "_upstream_chat", hanging_upstream)
    monkeypatch.setattr(gw, "_engine_last_request", fake_metrics)
    c = TestClient(gw.app)
    with c.stream("POST", "/v1/chat/completions", json={
        "model": "local",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }) as r:
        assert r.status_code == 200
        text = b"".join(r.iter_bytes()).decode()
    assert "ok" in text
    assert "[DONE]" in text
    assert gw.stats["recent_requests"][-1]["synthetic_done"] is True
    assert gw.stats["scheduler"]["active"] == 0


def test_grok_auxiliary_request_yields_engine_to_main_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gw, "AUXILIARY_GRACE_S", 0.05)

    async def scenario() -> None:
        aux = gw._EngineLease({
            "agent": "grok",
            "max_tokens": 100,
            "tool_count": 1,
            "request_bytes": 1_000,
        })
        main = gw._EngineLease({
            "agent": "grok",
            "max_tokens": 4_096,
            "tool_count": 24,
            "request_bytes": 80_000,
        })
        aux_task = asyncio.create_task(aux.acquire())
        await asyncio.sleep(0.01)
        await main.acquire()
        assert main.held is True
        assert aux.held is False
        main.release()
        await aux_task
        assert aux.held is True
        aux.release()

    asyncio.run(scenario())


def test_parallel_anthropic_streams_use_one_engine_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    """CodeG probes in parallel. The engine slot must cover SSE, not just POST."""
    monkeypatch.setattr(gw, "_runtime_ready", lambda: None)
    monkeypatch.setattr(gw, "_resolve_model_name", lambda requested: "served-model")
    stream_n = 0
    stream_peak = 0

    class CountingUpstream(FakeUpstream):
        async def aiter_bytes(self) -> AsyncIterator[bytes]:
            nonlocal stream_n, stream_peak
            stream_n += 1
            stream_peak = max(stream_peak, stream_n)
            try:
                async for chunk in super().aiter_bytes():
                    yield chunk
            finally:
                stream_n -= 1

    async def tracked(chat: dict[str, Any]) -> CountingUpstream:
        return CountingUpstream(chunks=[SSE_TEXT], delay_first_s=0.12)

    monkeypatch.setattr(gw, "_upstream_chat", tracked)

    async def _run() -> None:
        transport = httpx.ASGITransport(app=gw.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gw") as ac:
            headers = {"anthropic-version": "2023-06-01"}

            async def one(i: int) -> None:
                payload = {
                    "model": "local",
                    "max_tokens": 32,
                    "stream": True,
                    "messages": [{"role": "user", "content": f"hi {i}"}],
                }
                async with ac.stream("POST", "/v1/messages", json=payload, headers=headers) as r:
                    assert r.status_code == 200
                    await r.aread()

            await asyncio.gather(one(1), one(2))

    import asyncio
    import httpx
    asyncio.run(_run())
    assert stream_peak == 1, stream_peak
    assert not gw._chat_lock.locked()


def test_duplicate_anthropic_request_is_not_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gw, "_runtime_ready", lambda: None)
    monkeypatch.setattr(gw, "_resolve_model_name", lambda requested: "served-model")

    async def tracked(chat: dict[str, Any]) -> FakeUpstream:
        return FakeUpstream(chunks=[SSE_TEXT], delay_first_s=0.15)

    monkeypatch.setattr(gw, "_upstream_chat", tracked)

    async def _run() -> list[int]:
        import httpx
        transport = httpx.ASGITransport(app=gw.app)
        payload = {
            "model": "local", "max_tokens": 32, "stream": True,
            "messages": [{"role": "user", "content": "same request"}],
        }
        async with httpx.AsyncClient(transport=transport, base_url="http://gw") as ac:
            async def one() -> int:
                async with ac.stream("POST", "/v1/messages", json=payload) as response:
                    await response.aread()
                    return response.status_code
            return await asyncio.gather(one(), one())

    statuses = asyncio.run(_run())
    assert sorted(statuses) == [200, 409]


def test_nonstream_request_can_be_cancelled_by_request_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gw, "_runtime_ready", lambda: None)
    monkeypatch.setattr(gw, "_resolve_model_name", lambda requested: "served-model")
    entered = asyncio.Event()

    async def hanging(chat: dict[str, Any]) -> FakeUpstream:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(gw, "_upstream_chat", hanging)

    async def _run() -> None:
        import httpx
        transport = httpx.ASGITransport(app=gw.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gw") as ac:
            pending = asyncio.create_task(ac.post("/v1/messages", json={
                "model": "local", "max_tokens": 64,
                "messages": [{"role": "user", "content": "long task"}],
            }))
            await asyncio.wait_for(entered.wait(), timeout=1)
            active = next(row for row in gw._inflight.values() if row.get("status") == "running")
            cancelled = await ac.post(f"/gateway/requests/{active['request_id']}/cancel")
            assert cancelled.status_code == 200
            result = await asyncio.wait_for(pending, timeout=1)
            assert result.status_code == 409
            assert result.json()["error"]["code"] == "request_cancelled"

    asyncio.run(_run())
    assert not gw._chat_lock.locked()
