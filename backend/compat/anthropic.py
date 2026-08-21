"""Anthropic Messages API → Chat Completions, and the reverse."""

from __future__ import annotations

import json
import uuid
from typing import Any

from backend.compat.sanitize import sanitize_chat_body
from backend.compat.stream import sse_bytes

from backend.compat.responses import _content_to_text, _message_text


class AnthropicCompatError(ValueError):
    pass


def messages_to_chat(body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise AnthropicCompatError("Request should be a JSON dictionary")
    messages: list[dict[str, Any]] = []
    system = body.get("system")
    sys_text = _system_text(system)
    if sys_text:
        messages.append({"role": "system", "content": sys_text})
    for msg in body.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        messages.extend(_one_message(msg))
    if not any(m.get("role") == "user" for m in messages):
        raise AnthropicCompatError("/v1/messages requires a user message")

    chat: dict[str, Any] = {
        "model": body.get("model") or "default",
        "messages": messages,
        "stream": bool(body.get("stream")),
    }
    if "max_tokens" in body:
        chat["max_tokens"] = body["max_tokens"]
    tools = _tools_to_chat(body.get("tools"))
    if tools:
        chat["tools"] = tools
    if "tool_choice" in body:
        chat["tool_choice"] = _tool_choice(body.get("tool_choice"))
    if "thinking" in body:
        chat["thinking"] = body["thinking"]
    for key in ("temperature", "top_p", "stop_sequences"):
        if key not in body:
            continue
        if key == "stop_sequences":
            chat["stop"] = body[key]
        else:
            chat[key] = body[key]
    return sanitize_chat_body(chat)


def chat_to_messages(
    body: dict[str, Any],
    *,
    public_model: str | None = None,
) -> dict[str, Any]:
    choice = (body.get("choices") or [{}])[0] if isinstance(body.get("choices"), list) else {}
    if not isinstance(choice, dict):
        choice = {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    text = _message_text(message)
    blocks: list[dict[str, Any]] = []
    if text:
        blocks.append({"type": "text", "text": text})
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") if isinstance(call.get("function"), dict) else {}
        name = fn.get("name") or "tool"
        raw_args = fn.get("arguments") or "{}"
        try:
            inp = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            inp = {}
        if not isinstance(inp, dict):
            inp = {}
        blocks.append({
            "type": "tool_use",
            "id": call.get("id") or f"toolu_{uuid.uuid4().hex}",
            "name": name,
            "input": inp,
        })
    finish = choice.get("finish_reason")
    if finish == "length":
        stop = "max_tokens"
    elif finish == "tool_calls" or any(b.get("type") == "tool_use" for b in blocks):
        stop = "tool_use"
    else:
        stop = "end_turn"
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    return {
        "id": f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "model": public_model or body.get("model"),
        "content": blocks or [{"type": "text", "text": ""}],
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
        },
    }


class AnthropicStreamMapper:
    def __init__(self, *, model: str | None, input_tokens: int = 0) -> None:
        self.model = model
        self.msg_id = f"msg_{uuid.uuid4().hex}"
        self.started = False
        self.text_open = False
        self.thinking_open = False
        self.thinking_index = 0
        self.text_index = 0
        self.tools: dict[int, dict[str, Any]] = {}
        self.block_i = 0
        self.finished = False
        self.text = ""
        self.finish_reason: str | None = None
        self.usage: dict[str, Any] = {"prompt_tokens": max(0, int(input_tokens))}

    def set_engine_usage(self, *, input_tokens: Any = None, output_tokens: Any = None) -> None:
        if isinstance(input_tokens, (int, float)) and input_tokens >= 0:
            self.usage["prompt_tokens"] = int(input_tokens)
        if isinstance(output_tokens, (int, float)) and output_tokens >= 0:
            self.usage["completion_tokens"] = int(output_tokens)

    def start(self) -> list[bytes]:
        if self.started:
            return []
        self.started = True
        payload = {
            "type": "message_start",
            "message": {
                "id": self.msg_id,
                "type": "message",
                "role": "assistant",
                "model": self.model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {
                    "input_tokens": int(self.usage.get("prompt_tokens") or 0),
                    "output_tokens": 0,
                },
            },
        }
        return [sse_bytes("message_start", payload)]

    def feed(self, obj: Any) -> list[bytes]:
        events = self.start()
        if obj == "[DONE]":
            events.extend(self.close())
            return events
        if not isinstance(obj, dict):
            return events
        if isinstance(obj.get("usage"), dict):
            self.usage = obj["usage"]
        choices = obj.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return events
        choice = choices[0]
        if choice.get("finish_reason"):
            self.finish_reason = str(choice["finish_reason"])
        delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
        reasoning = delta.get("reasoning_content")
        if not isinstance(reasoning, str):
            reasoning = delta.get("reasoning") if isinstance(delta.get("reasoning"), str) else None
        if isinstance(reasoning, str) and reasoning:
            if not self.thinking_open:
                events.append(sse_bytes("content_block_start", {
                    "type": "content_block_start",
                    "index": self.block_i,
                    "content_block": {"type": "thinking", "thinking": ""},
                }))
                self.thinking_index = self.block_i
                self.thinking_open = True
                self.block_i += 1
            events.append(sse_bytes("content_block_delta", {
                "type": "content_block_delta",
                "index": self.thinking_index,
                "delta": {"type": "thinking_delta", "thinking": reasoning},
            }))
        content = delta.get("content")
        if isinstance(content, str) and content:
            if not self.text_open:
                events.append(sse_bytes("content_block_start", {
                    "type": "content_block_start",
                    "index": self.block_i,
                    "content_block": {"type": "text", "text": ""},
                }))
                self.text_index = self.block_i
                self.text_open = True
                self.block_i += 1
            self.text += content
            events.append(sse_bytes("content_block_delta", {
                "type": "content_block_delta",
                "index": self.text_index,
                "delta": {"type": "text_delta", "text": content},
            }))
        for tc in delta.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            idx = int(tc.get("index") or 0)
            slot = self.tools.setdefault(idx, {
                "id": tc.get("id") or f"toolu_{uuid.uuid4().hex}",
                "name": "",
                "arguments": "",
                "index": None,
                "opened": False,
            })
            if tc.get("id"):
                slot["id"] = tc["id"]
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            if not slot["opened"] and slot["name"]:
                slot["index"] = self.block_i
                events.append(sse_bytes("content_block_start", {
                    "type": "content_block_start",
                    "index": self.block_i,
                    "content_block": {
                        "type": "tool_use",
                        "id": slot["id"],
                        "name": slot["name"],
                        "input": {},
                    },
                }))
                slot["opened"] = True
                self.block_i += 1
            if isinstance(fn.get("arguments"), str) and fn["arguments"] and slot["opened"]:
                slot["arguments"] += fn["arguments"]
                events.append(sse_bytes("content_block_delta", {
                    "type": "content_block_delta",
                    "index": slot["index"],
                    "delta": {"type": "input_json_delta", "partial_json": fn["arguments"]},
                }))
        return events

    def close(self) -> list[bytes]:
        if self.finished:
            return []
        self.finished = True
        events: list[bytes] = []
        if self.thinking_open:
            events.append(sse_bytes("content_block_stop", {
                "type": "content_block_stop",
                "index": self.thinking_index,
            }))
        if self.text_open:
            events.append(sse_bytes("content_block_stop", {
                "type": "content_block_stop",
                "index": self.text_index,
            }))
        for slot in self.tools.values():
            if slot.get("opened"):
                events.append(sse_bytes("content_block_stop", {
                    "type": "content_block_stop",
                    "index": slot["index"],
                }))
        if self.finish_reason == "length":
            stop = "max_tokens"
        elif self.tools or self.finish_reason == "tool_calls":
            stop = "tool_use"
        else:
            stop = "end_turn"
        events.append(sse_bytes("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": stop, "stop_sequence": None},
            "usage": {
                "output_tokens": int(self.usage.get("completion_tokens") or 0),
            },
        }))
        events.append(sse_bytes("message_stop", {"type": "message_stop"}))
        return events


def _system_text(system: Any) -> str:
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "".join(
            (b.get("text") or "") if isinstance(b, dict) else str(b)
            for b in system
        )
    return ""


def _one_message(msg: dict[str, Any]) -> list[dict[str, Any]]:
    role = msg.get("role") or "user"
    content = msg.get("content")
    if role == "assistant":
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(str(block.get("text") or ""))
                elif btype == "tool_use":
                    tool_calls.append({
                        "id": block.get("id") or f"toolu_{uuid.uuid4().hex}",
                        "type": "function",
                        "function": {
                            "name": block.get("name") or "tool",
                            "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                        },
                    })
        out: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts)}
        if tool_calls:
            out["tool_calls"] = tool_calls
        return [out]
    if role == "user":
        if isinstance(content, str):
            return [{"role": "user", "content": content}]
        if not isinstance(content, list):
            return [{"role": "user", "content": _content_to_text(content)}]
        texts: list[str] = []
        tool_msgs: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                tool_msgs.append({
                    "role": "tool",
                    "tool_call_id": str(block.get("tool_use_id") or "toolu_unknown"),
                    "content": _content_to_text(block.get("content") or ""),
                })
            elif block.get("type") in {"text", None}:
                texts.append(str(block.get("text") or ""))
        out_msgs: list[dict[str, Any]] = []
        if texts:
            out_msgs.append({"role": "user", "content": "".join(texts)})
        out_msgs.extend(tool_msgs)
        return out_msgs or [{"role": "user", "content": ""}]
    return [{"role": str(role), "content": _content_to_text(content)}]


def _tools_to_chat(tools: Any) -> list[dict[str, Any]]:
    if not isinstance(tools, list):
        return []
    out: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            continue
        fn: dict[str, Any] = {"name": name}
        if tool.get("description"):
            fn["description"] = tool["description"]
        schema = tool.get("input_schema") or tool.get("parameters")
        if schema is not None:
            fn["parameters"] = schema
        out.append({"type": "function", "function": fn})
    return out


def _tool_choice(value: Any) -> Any:
    if isinstance(value, str):
        if value in {"auto", "none"}:
            return value
        if value == "any":
            return "auto"
        return "auto"
    if isinstance(value, dict):
        kind = str(value.get("type") or "").lower()
        if kind == "tool":
            name = value.get("name")
            if isinstance(name, str) and name:
                return {"type": "function", "function": {"name": name}}
        if kind in {"auto", "any"}:
            return "auto"
        if kind == "none":
            return "none"
    return value
