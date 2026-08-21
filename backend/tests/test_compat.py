"""Protocol adapter contracts — no live 27B runtime."""

from backend.compat.anthropic import AnthropicStreamMapper, chat_to_messages, messages_to_chat
from backend.compat.identity import detect_agent
from backend.compat.responses import chat_to_responses, responses_to_chat
from backend.compat.sanitize import sanitize_chat_body
from backend.compat.store import ResponseMemory
from backend.compat.stream import ResponsesStreamMapper, map_chat_sse_chunk_to_responses


def test_trailing_system_message_moves_to_front():
    body = sanitize_chat_body({
        "messages": [
            {"role": "system", "content": "You are a coding agent."},
            {"role": "user", "content": "hi"},
            {"role": "system", "content": "Extra project rules."},
        ]
    })
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user"]
    assert "You are a coding agent." in body["messages"][0]["content"]
    assert "Extra project rules." in body["messages"][0]["content"]
    assert body["messages"][1]["content"] == "hi"


def test_anthropic_trailing_system_is_coalesced():
    chat = messages_to_chat({
        "model": "Qwen3.8-27B-Heretic-8bit",
        "max_tokens": 32,
        "system": "Main system",
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "system", "content": "Trailing system"},
        ],
    })
    roles = [m["role"] for m in chat["messages"]]
    assert roles[0] == "system"
    assert "user" in roles
    assert roles.count("system") == 1
    assert "Main system" in chat["messages"][0]["content"]
    assert "Trailing system" in chat["messages"][0]["content"]
    body = sanitize_chat_body({
        "model": "Qwen3.8-27B-Heretic-8bit",
        "messages": [{"role": "user", "content": "hi"}],
        "tool_choice": {"type": "function", "function": {"name": "read_file"}},
        "tools": [{"type": "function", "function": {"name": "read_file", "parameters": {}}}],
    })
    assert body["tool_choice"] == "auto"
    assert body["messages"][-1]["content"] == "Use the `read_file` tool for this request."
    assert body["_forced_tool"] == "read_file"


def test_grok_responses_body_does_not_400():
    chat = responses_to_chat({
        "model": "Qwen3.8-27B-Heretic-8bit",
        "stream": True,
        "tool_choice": {"type": "function", "name": "bash"},
        "reasoning": {"effort": "high"},
        "store": True,
        "previous_response_id": "resp_missing",
        "instructions": "You are a coding agent.",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "list files"}]}],
        "tools": [{
            "type": "function",
            "name": "bash",
            "description": "run a shell command",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
        }],
        "max_output_tokens": 256,
    })
    assert chat["stream"] is True
    assert chat["tool_choice"] == "auto"
    assert chat["max_tokens"] == 256
    assert chat["tools"][0]["function"]["name"] == "bash"
    assert chat["messages"][0]["role"] == "system"
    assert any("list files" in (m.get("content") or "") for m in chat["messages"])
    assert "reasoning" not in chat
    assert "store" not in chat


def test_chat_sse_maps_to_responses_text_events():
    mapper = ResponsesStreamMapper(model="local", response_id="resp_test")
    chunk = (
        b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )
    events, rest = map_chat_sse_chunk_to_responses(chunk, mapper, b"")
    assert rest == b""
    joined = b"".join(events).decode()
    assert "response.output_text.delta" in joined
    assert "hello" in joined
    assert "response.completed" in joined


def test_previous_response_id_prepends_cached_turn():
    store = ResponseMemory()
    store.put("resp_1", {
        "messages": [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok"},
        ]
    })
    chat = responses_to_chat(
        {"model": "x", "input": "second", "previous_response_id": "resp_1"},
        store=store,
    )
    roles = [m["role"] for m in chat["messages"]]
    assert roles[:3] == ["user", "assistant", "user"]
    assert chat["messages"][-1]["content"] == "second"


def test_function_call_output_becomes_tool_message():
    from backend.compat.responses import remember_turn

    store = ResponseMemory()
    first = responses_to_chat({
        "model": "x",
        "input": "lookup alpha",
        "tools": [{"type": "function", "name": "lookup_code", "parameters": {}}],
    }, store=store)
    assistant = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": "call_secret",
            "type": "function",
            "function": {"name": "lookup_code", "arguments": "{\"name\":\"alpha\"}"},
        }],
    }
    resp = chat_to_responses({
        "id": "chatcmpl_loop",
        "choices": [{"finish_reason": "tool_calls", "message": assistant}],
    })
    remember_turn(resp, first, {"choices": [{"message": assistant}]}, store=store)

    second = responses_to_chat({
        "model": "x",
        "previous_response_id": resp["id"],
        "input": [{
            "type": "function_call_output",
            "call_id": "call_secret",
            "output": "TOKEN-ALPHA-7",
        }],
    }, store=store)
    roles = [m["role"] for m in second["messages"]]
    assert roles[-3:] == ["user", "assistant", "tool"]
    assert second["messages"][-1]["tool_call_id"] == "call_secret"
    assert second["messages"][-1]["content"] == "TOKEN-ALPHA-7"
    assert second["messages"][-2]["tool_calls"][0]["id"] == "call_secret"


def test_anthropic_tool_result_roundtrip():
    chat = messages_to_chat({
        "model": "x",
        "max_tokens": 64,
        "messages": [
            {"role": "user", "content": "lookup alpha"},
            {"role": "assistant", "content": [{
                "type": "tool_use", "id": "toolu_1", "name": "lookup_code",
                "input": {"name": "alpha"},
            }]},
            {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": "toolu_1", "content": "TOKEN-ALPHA-7",
            }]},
        ],
    })
    roles = [m["role"] for m in chat["messages"]]
    assert roles == ["user", "assistant", "tool"]
    assert chat["messages"][-1]["content"] == "TOKEN-ALPHA-7"


def test_stream_mapper_remembers_tool_calls():
    mapper = ResponsesStreamMapper(model="local", response_id="resp_loop")
    chunk = (
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_secret","function":{"name":"lookup_code","arguments":""}}]}}]}\n\n'
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"name\\":\\"alpha\\"}"}}]}}]}\n\n'
        b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
        b"data: [DONE]\n\n"
    )
    events, _ = map_chat_sse_chunk_to_responses(chunk, mapper, b"")
    joined = b"".join(events).decode()
    assert "response.function_call_arguments.delta" in joined
    msg = mapper.assistant_chat_message()
    assert msg["tool_calls"][0]["id"] == "call_secret"
    assert "alpha" in msg["tool_calls"][0]["function"]["arguments"]

    resp = chat_to_responses({
        "id": "chatcmpl_1",
        "model": "local",
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "bash", "arguments": "{\"command\":\"ls\"}"},
                }],
            },
        }],
    })
    kinds = [o["type"] for o in resp["output"]]
    assert "function_call" in kinds
    fc = next(o for o in resp["output"] if o["type"] == "function_call")
    assert fc["name"] == "bash"
    assert fc["call_id"] == "call_1"


def test_anthropic_messages_roundtrip_tools():
    chat = messages_to_chat({
        "model": "Qwen3.8-27B-Heretic-8bit",
        "max_tokens": 128,
        "system": "Be brief.",
        "tool_choice": {"type": "tool", "name": "Read"},
        "tools": [{
            "name": "Read",
            "description": "Read a file",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
        }],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "open foo.py"}]},
        ],
    })
    assert chat["messages"][0]["role"] == "system"
    assert chat["tool_choice"] == "auto"
    assert chat["_forced_tool"] == "Read"
    assert chat["tools"][0]["function"]["name"] == "Read"

    out = chat_to_messages({
        "model": "local",
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "toolu_1",
                    "type": "function",
                    "function": {"name": "Read", "arguments": "{\"path\":\"foo.py\"}"},
                }],
            },
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
    })
    assert out["stop_reason"] == "tool_use"
    assert out["content"][0]["type"] == "tool_use"
    assert out["content"][0]["input"]["path"] == "foo.py"


def test_anthropic_stream_maps_reasoning_usage_and_length_stop():
    mapper = AnthropicStreamMapper(model="local", input_tokens=321)
    events = mapper.feed({
        "choices": [{
            "delta": {"reasoning_content": "check constraints"},
            "finish_reason": None,
        }],
    })
    assert "thinking_delta" in b"".join(events).decode()
    # A finish_reason is not the protocol terminator; usage may arrive later.
    events = mapper.feed({"choices": [{"delta": {}, "finish_reason": "length"}]})
    assert "message_stop" not in b"".join(events).decode()
    mapper.set_engine_usage(input_tokens=333, output_tokens=77)
    closed = b"".join(mapper.feed("[DONE]")).decode()
    assert '"stop_reason":"max_tokens"' in closed
    assert '"output_tokens":77' in closed


def test_anthropic_non_stream_length_maps_to_max_tokens():
    out = chat_to_messages({
        "model": "local",
        "choices": [{
            "finish_reason": "length",
            "message": {"role": "assistant", "content": "partial"},
        }],
        "usage": {"prompt_tokens": 5, "completion_tokens": 9},
    })
    assert out["stop_reason"] == "max_tokens"


def test_detect_grok_user_agent():
    assert detect_agent(user_agent="Grok/1.0") == "grok"
    assert detect_agent(user_agent="cursor-agent") == "cursor"
    assert detect_agent(user_agent="codex-cli") == "codex"
    assert detect_agent(user_agent="claude-cli/1.0") == "claude-code"
    assert detect_agent(user_agent="", extra=["2023-06-01"]) == "claude-code"


def test_agent_catalog_lists_grok_and_native_claude():
    from backend.integrations.agents import agent_catalog
    rows = {a["id"]: a for a in agent_catalog()}
    assert "grok" in rows
    assert rows["claude-code"].get("not_supported_natively") is not True
    assert "/v1" not in rows["claude-code"]["config"]["base_url"] or rows["claude-code"]["config"]["base_url"].endswith(":8080")
