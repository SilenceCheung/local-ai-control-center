#!/usr/bin/env python3
"""Drive Claude ACP the same way CodeG.app does (stdio JSON-RPC)."""
from __future__ import annotations

import json
import os
import select
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NODE = Path(os.environ.get("NODE_BINARY") or shutil.which("node") or "node")
ACP = Path(os.environ.get("CLAUDE_ACP_ENTRY") or (
    Path.home()
    / ".local/node/lib/node_modules/@agentclientprotocol/claude-agent-acp/dist/index.js"
))
DB = Path(os.environ.get("CODEG_DB") or (
    Path.home() / "Library/Application Support/app.codeg/codeg.db"
))
LOG_DIR = PROJECT_ROOT / "logs"
WS = LOG_DIR / "codeg-probe-ws"
TRACE = LOG_DIR / "codeg_acp_e2e.trace.jsonl"
RESULT = LOG_DIR / "codeg_acp_e2e.result.json"


def load_codeg_claude_env() -> dict[str, str]:
    con = sqlite3.connect(DB)
    row = con.execute(
        "SELECT env_json FROM agent_setting WHERE agent_type LIKE '%claude_code%'"
    ).fetchone()
    con.close()
    raw = json.loads(row[0]) if row and row[0] else {}
    env = {
        "HOME": os.path.expanduser("~"),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "USER": os.environ.get("USER", "localai"),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "LANG": "en_US.UTF-8",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "CLAUDE_CONFIG_DIR": str(LOG_DIR / "codeg-acp-home"),
    }
    env.update({k: str(v) for k, v in raw.items()})
    env.setdefault("ANTHROPIC_BASE_URL", "http://127.0.0.1:8080")
    env.setdefault("ANTHROPIC_AUTH_TOKEN", "local")
    env.setdefault("ANTHROPIC_API_KEY", "local")
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["no_proxy"] = "127.0.0.1,localhost"
    return env


class AcpClient:
    def __init__(self, proc: subprocess.Popen[bytes], trace: Any):
        self.proc = proc
        self.trace = trace
        self._id = 0
        self._pending: dict[int, dict[str, Any] | None] = {}
        self.buf = b""
        self.texts: list[str] = []
        self.errors: list[str] = []
        self.methods: list[str] = []
        self.session_id: str | None = None
        self.stop_reason: str | None = None

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def send(self, obj: dict[str, Any]) -> None:
        line = json.dumps(obj, ensure_ascii=False) + "\n"
        self.trace.write(json.dumps({"t": time.time(), "dir": "c2a", "msg": obj}, ensure_ascii=False) + "\n")
        assert self.proc.stdin is not None
        self.proc.stdin.write(line.encode())
        self.proc.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None) -> int:
        rid = self._next_id()
        self._pending[rid] = None
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        self.send(msg)
        return rid

    def wait(self, rid: int, timeout: float) -> dict[str, Any]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._pending.get(rid) is not None:
                return self._pending[rid]  # type: ignore[return-value]
            self.pump(max(0.05, min(1.0, deadline - time.time())))
        raise TimeoutError(f"timed out waiting for id={rid}")

    def handle_incoming_request(self, msg: dict[str, Any]) -> None:
        method = msg.get("method") or ""
        params = msg.get("params") or {}
        mid = msg.get("id")
        self.methods.append(method)
        result: Any = {}
        if method == "session/request_permission":
            options = params.get("options") or []
            option_id = None
            for opt in options:
                oid = str(opt.get("optionId") or opt.get("option_id") or "")
                kind = str(opt.get("kind") or "")
                if "allow" in oid.lower() or kind in {"allow_once", "allow_always", "selected"}:
                    option_id = oid or kind
                    if "always" in oid.lower() or kind == "allow_always":
                        break
            if not option_id and options:
                option_id = str(options[0].get("optionId") or options[0].get("id") or "allow-once")
            result = {"outcome": {"outcome": "selected", "optionId": option_id or "allow-once"}}
        elif method in {"fs/read_text_file", "fs/readTextFile"}:
            path = params.get("path") or ""
            try:
                text = Path(path).read_text(encoding="utf-8", errors="replace")[:200_000]
                result = {"content": text}
            except Exception as exc:
                result = {"content": f"# unreadable: {exc}"}
        elif method in {"fs/write_text_file", "fs/writeTextFile"}:
            path = params.get("path") or ""
            content = params.get("content") or ""
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(content, encoding="utf-8")
            result = {}
        elif method.startswith("terminal/"):
            result = {"output": "", "exitCode": 0}
        else:
            result = {}
        self.send({"jsonrpc": "2.0", "id": mid, "result": result})

    def handle_notification(self, msg: dict[str, Any]) -> None:
        method = msg.get("method") or ""
        params = msg.get("params") or {}
        self.methods.append(method)
        if method != "session/update":
            return
        update = params.get("update") or params
        kind = update.get("sessionUpdate") or update.get("session_update") or ""
        if kind in {"agent_message_chunk", "agent_thought_chunk"}:
            chunk = update.get("content") or {}
            if isinstance(chunk, dict) and chunk.get("type") == "text":
                self.texts.append(chunk.get("text") or "")
        if "stopReason" in update or "stop_reason" in update:
            self.stop_reason = update.get("stopReason") or update.get("stop_reason")

    def pump(self, timeout: float) -> None:
        assert self.proc.stdout is not None
        r, _, _ = select.select([self.proc.stdout], [], [], timeout)
        if not r:
            return
        chunk = self.proc.stdout.read1(65536)  # type: ignore[attr-defined]
        if not chunk:
            return
        self.buf += chunk
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                msg = json.loads(line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                self.errors.append(line.decode("utf-8", errors="replace")[:400])
                continue
            self.trace.write(json.dumps({"t": time.time(), "dir": "a2c", "msg": msg}, ensure_ascii=False) + "\n")
            if "method" in msg and "id" in msg and "result" not in msg and "error" not in msg:
                self.handle_incoming_request(msg)
            elif "method" in msg and "id" not in msg:
                self.handle_notification(msg)
            elif "id" in msg and ("result" in msg or "error" in msg):
                self._pending[msg["id"]] = msg
                if "error" in msg:
                    self.errors.append(json.dumps(msg["error"], ensure_ascii=False)[:800])


def main() -> int:
    if not NODE.exists() and shutil.which(str(NODE)) is None:
        raise FileNotFoundError("node was not found; set NODE_BINARY")
    if not ACP.is_file():
        raise FileNotFoundError("Claude ACP entry was not found; set CLAUDE_ACP_ENTRY")
    if not DB.is_file():
        raise FileNotFoundError("CodeG database was not found; set CODEG_DB")
    WS.mkdir(parents=True, exist_ok=True)
    (WS / "README.txt").write_text("lacc codeg probe workspace\n", encoding="utf-8")
    cfg = Path(LOG_DIR / "codeg-acp-home")
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "settings.json").write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "http://127.0.0.1:8080",
                    "ANTHROPIC_AUTH_TOKEN": "local",
                    "ANTHROPIC_API_KEY": "local",
                    "ANTHROPIC_MODEL": "Qwen3.8-27B-Heretic-8bit",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "Qwen3.8-27B-Heretic-8bit",
                    "ANTHROPIC_DEFAULT_SONNET_MODEL": "Qwen3.8-27B-Heretic-8bit",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL": "Qwen3.8-27B-Heretic-8bit",
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                },
                "permissions": {"defaultMode": "bypassPermissions"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    env = load_codeg_claude_env()
    env["CLAUDE_CONFIG_DIR"] = str(cfg)

    started = time.time()
    proc = subprocess.Popen(
        [str(NODE), str(ACP)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=open(LOG_DIR / "codeg_acp_e2e.stderr.log", "wb"),
        env=env,
        cwd=str(WS),
    )
    with TRACE.open("w", encoding="utf-8") as trace:
        client = AcpClient(proc, trace)
        try:
            iid = client.request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": True, "writeTextFile": True},
                    },
                    "clientInfo": {"name": "codeg", "version": "0.26.2"},
                },
            )
            init = client.wait(iid, 20)
            if "error" in init:
                raise RuntimeError(init)
            sid = client.request(
                "session/new",
                {
                    "cwd": str(WS),
                    "mcpServers": [],
                },
            )
            new = client.wait(sid, 60)
            if "error" in new:
                raise RuntimeError(new)
            client.session_id = (new.get("result") or {}).get("sessionId")
            modes = ((new.get("result") or {}).get("modes") or {})
            available = modes.get("availableModes") or []
            bypass = None
            for mode in available:
                mid = str(mode.get("id") or "")
                name = str(mode.get("name") or "").lower()
                if "bypass" in mid.lower() or "bypass" in name:
                    bypass = mid
            if bypass and client.session_id:
                mid = client.request(
                    "session/set_mode",
                    {"sessionId": client.session_id, "modeId": bypass},
                )
                client.wait(mid, 20)
            pid = client.request(
                "session/prompt",
                {
                    "sessionId": client.session_id,
                    "prompt": [
                        {
                            "type": "text",
                            "text": "Reply with exactly the word pong and nothing else.",
                        }
                    ],
                },
            )
            prompt = client.wait(pid, 180)
            text = "".join(client.texts).strip()
            out = {
                "ok": "error" not in prompt and "pong" in text.lower(),
                "elapsed_s": round(time.time() - started, 2),
                "session_id": client.session_id,
                "prompt_result": prompt.get("result") or prompt.get("error"),
                "text": text[:2000],
                "errors": client.errors[:20],
                "methods": sorted(set(client.methods)),
            }
        except Exception as exc:
            out = {
                "ok": False,
                "elapsed_s": round(time.time() - started, 2),
                "exception": repr(exc),
                "text": "".join(client.texts)[:2000],
                "errors": client.errors[:20],
                "methods": sorted(set(client.methods)),
            }
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
    RESULT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
