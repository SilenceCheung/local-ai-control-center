"""Identify which agent is calling from User-Agent / Referer / x-title."""

from __future__ import annotations

import re
from typing import Iterable

AGENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("cursor", re.compile(r"cursor", re.I)),
    ("codex", re.compile(r"codex", re.I)),
    ("grok", re.compile(r"grok", re.I)),
    ("opencode", re.compile(r"opencode", re.I)),
    ("cline", re.compile(r"cline", re.I)),
    ("roo-code", re.compile(r"roo", re.I)),
    ("claude-code", re.compile(r"claude", re.I)),
    ("openai-sdk", re.compile(r"openai", re.I)),
]


def detect_agent(
    user_agent: str = "",
    referer: str = "",
    title: str = "",
    extra: Iterable[str] = (),
) -> str | None:
    extras = [str(e).strip() for e in extra if e and str(e).strip()]
    blob = " ".join([user_agent, referer, title, *extras])
    for name, pat in AGENT_PATTERNS:
        if pat.search(blob):
            return name
    # Claude Code often sends anthropic-version without "claude" in User-Agent.
    if extras:
        return "claude-code"
    return None
