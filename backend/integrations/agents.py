"""Agent integration descriptors: per-tool config snippets + live status.

Status semantics (honest):
- connected      : the gateway has seen requests from this client recently
- unknown        : no traffic observed — we cannot know if it is configured
- not_configured : never seen and no local config detected
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from backend.core.config import GATEWAY_STATS_PATH, load_config

RECENT_S = 30 * 60


def _base_url() -> str:
    cfg = load_config()
    return f"http://{cfg['api']['host']}:{cfg['api']['port']}/v1"


def _alias() -> str:
    return load_config()["api"]["alias"]


def _agents_seen() -> dict[str, float]:
    try:
        with open(GATEWAY_STATS_PATH) as f:
            return (json.load(f).get("agents_seen")) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def agent_catalog() -> list[dict[str, Any]]:
    base, alias, key = _base_url(), _alias(), load_config()["api"]["api_key"]
    seen = _agents_seen()
    now = time.time()

    def status_of(gateway_name: str) -> str:
        ts = seen.get(gateway_name)
        if ts and now - ts < RECENT_S:
            return "connected"
        if ts:
            return "seen_before"
        return "unknown"

    return [
        {
            "id": "cursor",
            "name": "Cursor",
            "status": status_of("cursor"),
            "protocol": "openai",
            "instructions": (
                "Cursor Settings → Models → API Keys → enable 'Override OpenAI Base URL', "
                f"set Base URL to {base} and API key to '{key}'. Then add a custom model "
                f"named '{alias}'. Note: some Cursor features route through Cursor's cloud "
                "and cannot use a purely local endpoint."
            ),
            "config": {"base_url": base, "api_key": key, "model": alias},
        },
        {
            "id": "codex",
            "name": "Codex CLI",
            "status": status_of("codex"),
            "protocol": "openai",
            "instructions": "Add a model provider to ~/.codex/config.toml (do not remove existing entries):",
            "config_snippet": (
                f'[model_providers.local]\nname = "Local AI"\nbase_url = "{base}"\n'
                f'env_key = "LOCAL_AI_KEY"   # export LOCAL_AI_KEY={key}\n\n'
                f'[profiles.local]\nmodel_provider = "local"\nmodel = "{alias}"'
            ),
            "config": {"base_url": base, "api_key": key, "model": alias},
        },
        {
            "id": "opencode",
            "name": "OpenCode",
            "status": status_of("opencode"),
            "protocol": "openai",
            "instructions": "Add to ~/.config/opencode/opencode.json under \"provider\":",
            "config_snippet": json.dumps({
                "provider": {
                    "local-ai": {
                        "npm": "@ai-sdk/openai-compatible",
                        "name": "Local AI",
                        "options": {"baseURL": base, "apiKey": key},
                        "models": {alias: {"name": "Qwen3.8 27B (local)"}},
                    }
                }
            }, indent=2),
            "config": {"base_url": base, "api_key": key, "model": alias},
        },
        {
            "id": "cline",
            "name": "Cline",
            "status": status_of("cline"),
            "protocol": "openai",
            "instructions": (
                "Cline Settings → API Provider → 'OpenAI Compatible'. "
                f"Base URL: {base} · API Key: {key} · Model ID: {alias}"
            ),
            "config": {"base_url": base, "api_key": key, "model": alias},
        },
        {
            "id": "roo-code",
            "name": "Roo Code",
            "status": status_of("roo-code"),
            "protocol": "openai",
            "instructions": (
                "Roo Code Settings → Providers → 'OpenAI Compatible'. "
                f"Base URL: {base} · API Key: {key} · Model: {alias}"
            ),
            "config": {"base_url": base, "api_key": key, "model": alias},
        },
        {
            "id": "claude-code",
            "name": "Claude Code",
            "status": status_of("claude-code"),
            "protocol": "anthropic",
            "instructions": (
                "Claude Code speaks the Anthropic API, not the OpenAI API. A compatibility "
                "gateway (e.g. LiteLLM `litellm --model openai/" + alias + "`) can bridge it "
                "to this server, but it is NOT bundled in this first version. Status here "
                "will stay 'not supported natively' until a gateway is configured."
            ),
            "not_supported_natively": True,
            "config": {"base_url": base, "api_key": key, "model": alias},
        },
    ]


async def test_connection() -> dict[str, Any]:
    """Real end-to-end test through the gateway: list models + tiny completion."""
    base = _base_url()
    out: dict[str, Any] = {"base_url": base}
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.get(base + "/models")
            out["models_ok"] = r.status_code == 200
            out["models"] = [m["id"] for m in r.json().get("data", [])] if out["models_ok"] else []
            t0 = time.perf_counter()
            r2 = await client.post(base + "/chat/completions", json={
                "model": _alias(),
                "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
                "max_tokens": 40, "temperature": 0, "stream": False,
            })
            out["chat_status"] = r2.status_code
            if r2.status_code == 200:
                data = r2.json()
                out["chat_ok"] = True
                out["reply"] = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")[:200]
                out["elapsed_s"] = round(time.perf_counter() - t0, 2)
            else:
                out["chat_ok"] = False
                out["error"] = r2.text[:300]
    except httpx.HTTPError as e:
        out["chat_ok"] = False
        out["error"] = str(e)
    out["ok"] = bool(out.get("models_ok") and out.get("chat_ok"))
    return out
