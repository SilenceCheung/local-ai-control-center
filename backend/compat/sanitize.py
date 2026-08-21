"""Make Chat Completions bodies something dflash-mlx / mlx_lm will accept."""

from __future__ import annotations

from typing import Any

_DROP_KEYS = {
    "metadata",
    "store",
    "previous_response_id",
    "reasoning",
    "truncation",
    "include",
    "instructions",
    "max_output_tokens",
    "parallel_tool_calls",
    "service_tier",
    "prompt_cache_key",
    "safety_identifier",
    "modalities",
    "audio",
    "prediction",
    "web_search_options",
    "stream_options",
    "user",
    "logprobs",
    "top_logprobs",
    "logit_bias",
    "presence_penalty",
    "frequency_penalty",
    "reasoning_effort",
    "thinking",
}


def _thinking_policy(body: dict[str, Any]) -> bool | None:
    """Map agent reasoning controls to Qwen's per-request thinking switch.

    Local engines count hidden reasoning against ``max_tokens``.  A tiny
    completion can therefore return HTTP 200 with no visible text.  For
    tool-free requests capped at 64 tokens we prefer a useful answer over
    hidden reasoning, even when a client attaches its generic high-effort
    default.  Larger agent turns keep the client's explicit preference.
    """
    max_tokens = body.get("max_tokens")
    if isinstance(max_tokens, int) and max_tokens <= 64 and not body.get("tools"):
        return False

    reasoning = body.get("reasoning")
    effort: Any = body.get("reasoning_effort")
    if isinstance(reasoning, dict):
        effort = reasoning.get("effort", effort)
    elif isinstance(reasoning, str):
        effort = reasoning

    thinking = body.get("thinking")
    if isinstance(thinking, dict):
        kind = str(thinking.get("type") or "").strip().lower()
        if kind in {"disabled", "off", "none"}:
            return False
        if kind in {"enabled", "on"}:
            return True
    elif isinstance(thinking, bool):
        return thinking

    if isinstance(effort, str):
        low = effort.strip().lower()
        if low in {"none", "off", "disabled", "minimal"}:
            return False
        if low in {"low", "medium", "high", "xhigh", "x-high"}:
            return True
    return None


def _nudge_text(name: str) -> str:
    return f"Use the `{name}` tool for this request."


def _append_user_nudge(messages: list[Any], name: str) -> list[Any]:
    out = list(messages)
    out.append({"role": "user", "content": _nudge_text(name)})
    return out


def coalesce_system_messages(messages: list[Any]) -> list[Any]:
    """Qwen chat templates reject a system turn after a user turn.

    Claude Code / CodeG send system, user, then another system (claude.md /
    extra instructions). Fold every system block into one leading message.
    """
    if not isinstance(messages, list):
        return messages
    systems: list[str] = []
    others: list[Any] = []
    saw_system_after_other = False
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system":
            if others:
                saw_system_after_other = True
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                systems.append(content)
            elif isinstance(content, list):
                text = "".join(
                    (b.get("text") or "") if isinstance(b, dict) else str(b)
                    for b in content
                ).strip()
                if text:
                    systems.append(text)
        else:
            others.append(msg)
    if not systems:
        return messages
    if not saw_system_after_other and len(systems) == 1:
        return messages
    merged = {"role": "system", "content": "\n\n".join(systems)}
    return [merged, *others]


def function_tool_choice_name(tool_choice: Any) -> str | None:
    if not isinstance(tool_choice, dict):
        return None
    kind = str(tool_choice.get("type") or tool_choice.get("mode") or "").strip().lower()
    if kind not in {"function", "custom"}:
        return None
    fn = tool_choice.get("function")
    if isinstance(fn, dict) and isinstance(fn.get("name"), str) and fn["name"]:
        return fn["name"]
    if isinstance(tool_choice.get("name"), str) and tool_choice["name"]:
        return tool_choice["name"]
    return None


def sanitize_chat_body(body: dict[str, Any]) -> dict[str, Any]:
    """Return a copy the local engine can run. Never raises on extra fields."""
    if not isinstance(body, dict):
        return {"messages": [], "model": "default"}
    thinking = _thinking_policy(body)
    out = {k: v for k, v in body.items() if k not in _DROP_KEYS}
    if thinking is not None:
        raw_kwargs = out.get("chat_template_kwargs")
        kwargs = dict(raw_kwargs) if isinstance(raw_kwargs, dict) else {}
        kwargs["enable_thinking"] = thinking
        out["chat_template_kwargs"] = kwargs

    # dflash-mlx only uses speculative decoding for deterministic requests.
    # Agent clients often omit temperature for background probes, which would
    # otherwise inherit the engine's sampling default and fall back to slow
    # target-only AR. Explicit client sampling remains respected.
    if out.get("tools"):
        out["temperature"] = 0
    elif out.get("temperature") is None:
        out["temperature"] = 0

    n = out.get("n")
    if isinstance(n, int) and n != 1:
        out["n"] = 1

    tc = out.get("tool_choice")
    name = function_tool_choice_name(tc)
    if name:
        out["tool_choice"] = "auto"
        msgs = out.get("messages")
        if isinstance(msgs, list):
            out["messages"] = _append_user_nudge(msgs, name)
        out["_forced_tool"] = name
    elif isinstance(tc, str):
        low = tc.strip().lower()
        if low in {"required", "any"}:
            out["tool_choice"] = "auto"
        elif low not in {"auto", "none"}:
            out["tool_choice"] = "auto"
    elif isinstance(tc, dict):
        kind = str(tc.get("type") or "").strip().lower()
        if kind in {"required", "any"}:
            out["tool_choice"] = "auto"
        elif kind not in {"auto", "none", ""}:
            out["tool_choice"] = "auto"

    rf = out.get("response_format")
    if isinstance(rf, dict) and rf.get("type") not in {"text", "json_object", None}:
        out.pop("response_format", None)

    msgs = out.get("messages")
    if isinstance(msgs, list):
        out["messages"] = coalesce_system_messages(msgs)

    return out
