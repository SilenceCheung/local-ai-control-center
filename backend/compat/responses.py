"""OpenAI Responses API → Chat Completions, and the reverse."""

from __future__ import annotations

import time
import uuid
from typing import Any

from backend.compat.sanitize import sanitize_chat_body
from backend.compat.store import ResponseMemory, memory as default_memory


class ResponsesCompatError(ValueError):
    pass


def responses_to_chat(
    body: dict[str, Any],
    *,
    store: ResponseMemory | None = None,
) -> dict[str, Any]:
    """Translate a Grok/Codex Responses body into engine Chat Completions.

    Unknown / unimplemented Responses fields are ignored, never 400.
    """
    if not isinstance(body, dict):
        raise ResponsesCompatError("Request should be a JSON dictionary")
    raw_input = body.get("input")
    if raw_input is None:
        raise ResponsesCompatError("/v1/responses requires an input field")

    messages = _input_to_messages(raw_input)
    prev_id = body.get("previous_response_id")
    cache = store if store is not None else default_memory
    if isinstance(prev_id, str) and prev_id:
        prior = cache.get(prev_id)
        if prior and isinstance(prior.get("messages"), list):
            messages = list(prior["messages"]) + messages

    instructions = body.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        messages = [{"role": "system", "content": instructions}] + messages

    chat: dict[str, Any] = {
        "model": body.get("model") or "default",
        "messages": messages,
        "stream": bool(body.get("stream")),
    }
    if "max_output_tokens" in body:
        chat["max_tokens"] = body["max_output_tokens"]
    elif "max_tokens" in body:
        chat["max_tokens"] = body["max_tokens"]
    if "tools" in body:
        chat["tools"] = _tools_to_chat_tools(body.get("tools"))
    if "tool_choice" in body:
        chat["tool_choice"] = body["tool_choice"]
    if "reasoning" in body:
        chat["reasoning"] = body["reasoning"]
    if "reasoning_effort" in body:
        chat["reasoning_effort"] = body["reasoning_effort"]
    for key in ("temperature", "top_p", "stop", "seed"):
        if key in body:
            chat[key] = body[key]
    return sanitize_chat_body(chat)


def chat_to_responses(
    body: dict[str, Any],
    *,
    request_id: str | None = None,
    public_model: str | None = None,
) -> dict[str, Any]:
    choice = _first_choice(body)
    message = dict(choice.get("message") or {})
    content = _message_text(message)
    tool_items = _chat_tool_calls_to_items(message.get("tool_calls"))
    response_id = request_id or _response_id(body.get("id"))
    created_at = body.get("created")
    if created_at is None:
        created_at = int(time.time())

    output: list[dict[str, Any]] = []
    if content:
        output.append(_text_item(content))
    output.extend(tool_items)

    status = "completed"
    finish = choice.get("finish_reason")
    if finish == "tool_calls":
        status = "completed"

    response: dict[str, Any] = {
        "id": response_id,
        "object": "response",
        "created_at": int(created_at),
        "model": public_model or body.get("model"),
        "status": status,
        "output": output,
        "output_text": content,
    }
    if "usage" in body:
        response["usage"] = _usage(body.get("usage"))
    if finish is not None:
        response["finish_reason"] = finish
    return response


def remember_turn(
    response: dict[str, Any],
    chat_request: dict[str, Any],
    chat_response: dict[str, Any],
    *,
    store: ResponseMemory | None = None,
) -> None:
    cache = store if store is not None else default_memory
    rid = response.get("id")
    if not isinstance(rid, str):
        return
    msgs = list(chat_request.get("messages") or [])
    choice = (chat_response.get("choices") or [{}])[0]
    message = (choice or {}).get("message") if isinstance(choice, dict) else None
    if isinstance(message, dict):
        msgs = msgs + [message]
    cache.put(rid, {"messages": msgs, "response": response})


def _text_item(content: str) -> dict[str, Any]:
    return {
        "id": f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": content}],
    }


def _usage(usage: Any) -> dict[str, Any]:
    if not isinstance(usage, dict):
        return {}
    inp = usage.get("prompt_tokens")
    out = usage.get("completion_tokens")
    total = usage.get("total_tokens")
    mapped: dict[str, Any] = dict(usage)
    if inp is not None:
        mapped.setdefault("input_tokens", inp)
    if out is not None:
        mapped.setdefault("output_tokens", out)
    if total is not None:
        mapped.setdefault("total_tokens", total)
    return mapped


def _input_to_messages(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        return [{"role": "user", "content": value}]
    if not isinstance(value, list):
        raise ResponsesCompatError("/v1/responses input must be a string or list")
    messages: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            messages.append({"role": "user", "content": item})
            continue
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in {"function_call", "tool_call"}:
            messages.append(_function_call_to_assistant(item))
            continue
        if item_type in {"function_call_output", "tool_result"}:
            messages.append(_function_output_to_tool(item))
            continue
        role = item.get("role") or "user"
        if not isinstance(role, str):
            role = "user"
        messages.append({"role": role, "content": _content_to_text(item.get("content", ""))})
    if not messages:
        raise ResponsesCompatError("/v1/responses input must not be empty")
    return messages


def _function_call_to_assistant(item: dict[str, Any]) -> dict[str, Any]:
    name = item.get("name") or ""
    call_id = item.get("call_id") or item.get("id") or f"call_{uuid.uuid4().hex}"
    arguments = item.get("arguments", "{}")
    if not isinstance(arguments, str):
        arguments = "{}"
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": str(call_id),
            "type": "function",
            "function": {"name": str(name) or "tool", "arguments": arguments},
        }],
    }


def _function_output_to_tool(item: dict[str, Any]) -> dict[str, Any]:
    call_id = item.get("call_id") or item.get("id") or "call_unknown"
    return {
        "role": "tool",
        "tool_call_id": str(call_id),
        "content": _content_to_text(item.get("output") or item.get("content") or ""),
    }


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return _content_item_to_text(content)
    if isinstance(content, list):
        return "".join(_content_item_to_text(item) for item in content)
    return str(content)


def _content_item_to_text(item: Any) -> str:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return ""
    item_type = item.get("type")
    if item_type in {"input_text", "output_text", "text", None} or "text" in item:
        text = item.get("text", "")
        return text if isinstance(text, str) else ""
    return ""


def _tools_to_chat_tools(tools: Any) -> list[dict[str, Any]]:
    if not isinstance(tools, list):
        return []
    out: list[dict[str, Any]] = []
    for tool in tools:
        converted = _tool_to_chat_tool(tool)
        if converted:
            out.append(converted)
    return out


def _tool_to_chat_tool(tool: Any) -> dict[str, Any] | None:
    if not isinstance(tool, dict):
        return None
    if isinstance(tool.get("function"), dict):
        fn = dict(tool["function"])
        name = fn.get("name")
        if not isinstance(name, str) or not name:
            return None
        return {"type": "function", "function": fn}
    name = tool.get("name")
    if not isinstance(name, str) or not name:
        return None
    function: dict[str, Any] = {"name": name}
    params = tool.get("parameters") or tool.get("input_schema")
    if params is not None:
        function["parameters"] = params
    for key in ("description", "strict"):
        if key in tool:
            function[key] = tool[key]
    return {"type": "function", "function": function}


def _chat_tool_calls_to_items(tool_calls: Any) -> list[dict[str, Any]]:
    if not isinstance(tool_calls, list):
        return []
    items: list[dict[str, Any]] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") if isinstance(call.get("function"), dict) else {}
        name = fn.get("name") or call.get("name") or "tool"
        arguments = fn.get("arguments", "{}")
        if not isinstance(arguments, str):
            arguments = "{}"
        call_id = call.get("id") or f"call_{uuid.uuid4().hex}"
        items.append({
            "id": f"fc_{uuid.uuid4().hex}",
            "type": "function_call",
            "status": "completed",
            "call_id": str(call_id),
            "name": str(name),
            "arguments": arguments,
        })
    return items


def _first_choice(body: dict[str, Any]) -> dict[str, Any]:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return {"message": {"content": ""}, "finish_reason": "stop"}
    return choices[0]


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return _content_to_text(content)
    return ""


def _response_id(chat_id: Any) -> str:
    if isinstance(chat_id, str) and chat_id.startswith("resp_"):
        return chat_id
    if isinstance(chat_id, str) and chat_id:
        return f"resp_{chat_id}"
    return f"resp_{uuid.uuid4().hex}"
