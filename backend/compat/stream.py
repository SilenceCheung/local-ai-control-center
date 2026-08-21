"""SSE helpers: parse Chat Completions streams, emit Responses / Anthropic, heartbeat."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from backend.compat.responses import (
    _chat_tool_calls_to_items,
    _message_text,
    _text_item,
    _usage,
    chat_to_responses,
)

KEEPALIVE = b": keepalive\n\n"
HEARTBEAT_S = 15.0


def sse_bytes(event: str, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n".encode()


def split_sse_frames(buffer: bytes) -> tuple[list[bytes], bytes]:
    frames: list[bytes] = []
    start = 0
    while True:
        idx = buffer.find(b"\n\n", start)
        if idx < 0:
            break
        frame = buffer[start:idx]
        start = idx + 2
        if frame.strip():
            frames.append(frame)
    return frames, buffer[start:]


def sse_data_payloads(frame: bytes) -> list[Any]:
    out: list[Any] = []
    for raw_line in frame.split(b"\n"):
        line = raw_line.strip()
        if not line.startswith(b"data:"):
            continue
        data = line[5:].strip()
        if data == b"[DONE]":
            out.append("[DONE]")
            continue
        try:
            out.append(json.loads(data))
        except json.JSONDecodeError:
            continue
    return out


class ResponsesStreamMapper:
    """Map Chat Completions SSE JSON objects to Responses SSE bytes."""

    def __init__(self, *, model: str | None, response_id: str | None = None) -> None:
        self.model = model
        self.response_id = response_id or f"resp_{uuid.uuid4().hex}"
        self.created_at = int(time.time())
        self.started = False
        self.text_open = False
        self.text = ""
        self.msg_id = f"msg_{uuid.uuid4().hex}"
        self.tools: dict[int, dict[str, Any]] = {}
        self.finished = False
        self.usage: dict[str, Any] | None = None
        self.finish_reason: str | None = None

    def _skeleton(self, status: str = "in_progress") -> dict[str, Any]:
        return {
            "id": self.response_id,
            "object": "response",
            "created_at": self.created_at,
            "model": self.model,
            "status": status,
            "output": [],
            "output_text": self.text,
        }

    def start_events(self) -> list[bytes]:
        if self.started:
            return []
        self.started = True
        created = self._skeleton("in_progress")
        return [
            sse_bytes("response.created", {"type": "response.created", "response": created}),
            sse_bytes("response.in_progress", {"type": "response.in_progress", "response": created}),
        ]

    def _open_text(self) -> list[bytes]:
        if self.text_open:
            return []
        self.text_open = True
        item = {
            "id": self.msg_id,
            "type": "message",
            "status": "in_progress",
            "role": "assistant",
            "content": [],
        }
        part = {"type": "output_text", "text": ""}
        return [
            sse_bytes("response.output_item.added", {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": item,
            }),
            sse_bytes("response.content_part.added", {
                "type": "response.content_part.added",
                "output_index": 0,
                "content_index": 0,
                "part": part,
            }),
        ]

    def feed(self, obj: Any) -> list[bytes]:
        events = self.start_events()
        if obj == "[DONE]":
            events.extend(self.close())
            return events
        if not isinstance(obj, dict):
            return events
        if isinstance(obj.get("usage"), dict):
            self.usage = obj["usage"]
        choices = obj.get("choices")
        if not isinstance(choices, list) or not choices:
            return events
        choice = choices[0]
        if not isinstance(choice, dict):
            return events
        if choice.get("finish_reason"):
            self.finish_reason = str(choice["finish_reason"])
        delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
        content = delta.get("content")
        if isinstance(content, str) and content:
            events.extend(self._open_text())
            self.text += content
            events.append(sse_bytes("response.output_text.delta", {
                "type": "response.output_text.delta",
                "output_index": 0,
                "content_index": 0,
                "delta": content,
            }))
        for tc in delta.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            idx = int(tc.get("index") or 0)
            slot = self.tools.setdefault(idx, {
                "id": tc.get("id") or f"call_{uuid.uuid4().hex}",
                "name": "",
                "arguments": "",
                "item_id": f"fc_{uuid.uuid4().hex}",
                "opened": False,
            })
            if tc.get("id"):
                slot["id"] = tc["id"]
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            if isinstance(fn.get("arguments"), str) and fn["arguments"]:
                if not slot["opened"]:
                    events.append(sse_bytes("response.output_item.added", {
                        "type": "response.output_item.added",
                        "output_index": 1 + idx,
                        "item": {
                            "id": slot["item_id"],
                            "type": "function_call",
                            "status": "in_progress",
                            "call_id": slot["id"],
                            "name": slot["name"] or "tool",
                            "arguments": "",
                        },
                    }))
                    slot["opened"] = True
                slot["arguments"] += fn["arguments"]
                events.append(sse_bytes("response.function_call_arguments.delta", {
                    "type": "response.function_call_arguments.delta",
                    "output_index": 1 + idx,
                    "delta": fn["arguments"],
                }))
            elif fn.get("name") and not slot["opened"]:
                events.append(sse_bytes("response.output_item.added", {
                    "type": "response.output_item.added",
                    "output_index": 1 + idx,
                    "item": {
                        "id": slot["item_id"],
                        "type": "function_call",
                        "status": "in_progress",
                        "call_id": slot["id"],
                        "name": slot["name"],
                        "arguments": "",
                    },
                }))
                slot["opened"] = True
        message = choice.get("message") if isinstance(choice.get("message"), dict) else None
        if message:
            text = _message_text(message)
            if text and not self.text:
                events.extend(self._open_text())
                self.text = text
                events.append(sse_bytes("response.output_text.delta", {
                    "type": "response.output_text.delta",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": text,
                }))
            for item in _chat_tool_calls_to_items(message.get("tool_calls")):
                events.append(sse_bytes("response.output_item.added", {
                    "type": "response.output_item.added",
                    "output_index": len(self.tools),
                    "item": item,
                }))
        if self.finish_reason and not self.finished:
            events.extend(self.close())
        return events

    def close(self) -> list[bytes]:
        if self.finished:
            return []
        self.finished = True
        events: list[bytes] = []
        if self.text_open:
            events.append(sse_bytes("response.output_text.done", {
                "type": "response.output_text.done",
                "output_index": 0,
                "content_index": 0,
                "text": self.text,
            }))
            events.append(sse_bytes("response.content_part.done", {
                "type": "response.content_part.done",
                "output_index": 0,
                "content_index": 0,
                "part": {"type": "output_text", "text": self.text},
            }))
            events.append(sse_bytes("response.output_item.done", {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "id": self.msg_id,
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": self.text}],
                },
            }))
        for idx, slot in sorted(self.tools.items()):
            events.append(sse_bytes("response.function_call_arguments.done", {
                "type": "response.function_call_arguments.done",
                "output_index": 1 + idx,
                "arguments": slot["arguments"],
            }))
            events.append(sse_bytes("response.output_item.done", {
                "type": "response.output_item.done",
                "output_index": 1 + idx,
                "item": {
                    "id": slot["item_id"],
                    "type": "function_call",
                    "status": "completed",
                    "call_id": slot["id"],
                    "name": slot["name"] or "tool",
                    "arguments": slot["arguments"],
                },
            }))
        output: list[dict[str, Any]] = []
        if self.text:
            output.append(_text_item(self.text))
            output[-1]["id"] = self.msg_id
        for idx, slot in sorted(self.tools.items()):
            output.append({
                "id": slot["item_id"],
                "type": "function_call",
                "status": "completed",
                "call_id": slot["id"],
                "name": slot["name"] or "tool",
                "arguments": slot["arguments"],
            })
        completed = {
            "id": self.response_id,
            "object": "response",
            "created_at": self.created_at,
            "model": self.model,
            "status": "completed",
            "output": output,
            "output_text": self.text,
        }
        if self.usage:
            completed["usage"] = _usage(self.usage)
        if self.finish_reason:
            completed["finish_reason"] = self.finish_reason
        events.append(sse_bytes("response.completed", {
            "type": "response.completed",
            "response": completed,
        }))
        return events

    def assistant_chat_message(self) -> dict[str, Any]:
        """Chat-shaped assistant turn for previous_response_id memory."""
        message: dict[str, Any] = {"role": "assistant", "content": self.text}
        calls = [
            {
                "id": slot["id"],
                "type": "function",
                "function": {"name": slot["name"] or "tool", "arguments": slot["arguments"]},
            }
            for _, slot in sorted(self.tools.items())
        ]
        if calls:
            message["tool_calls"] = calls
        return message

    def final_response(self) -> dict[str, Any]:
        fake = {
            "id": self.response_id,
            "model": self.model,
            "created": self.created_at,
            "choices": [{
                "finish_reason": self.finish_reason or "stop",
                "message": self.assistant_chat_message(),
            }],
            "usage": self.usage or {},
        }
        return chat_to_responses(fake, request_id=self.response_id, public_model=self.model)


def map_chat_sse_chunk_to_responses(
    chunk: bytes,
    mapper: ResponsesStreamMapper,
    carry: bytes,
) -> tuple[list[bytes], bytes]:
    frames, rest = split_sse_frames(carry + chunk)
    events: list[bytes] = []
    for frame in frames:
        for payload in sse_data_payloads(frame):
            events.extend(mapper.feed(payload))
    return events, rest


def keepalive_due(last_emit: float, now: float | None = None, interval: float = HEARTBEAT_S) -> bool:
    t = time.time() if now is None else now
    return (t - last_emit) >= interval
