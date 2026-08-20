"""MLXRuntimeProvider — manages one local MLX inference server process.

FAST mode : dflash serve  (target + DFlash draft, speculative decoding)
SAFE mode : mlx_lm.server (target only)

The child is spawned in its own session so a control-plane crash/restart never
kills inference. On startup the manager re-attaches via the pid recorded in
data/runtime_state.json.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from backend.core.config import LOGS_DIR, PROJECT_ROOT, load_config
from backend.core.state import RuntimeState, pid_alive, read_state, write_state
from backend.database.db import add_event
from backend.models.registry import resolve_path
from backend.runtime.base import RuntimeProvider

RUNTIME_LOG = LOGS_DIR / "runtime.log"
START_TIMEOUT_S = 300  # first load of a 26 GB model from cold SSD can be slow
_LOG_ROTATE_BYTES = 20 * 1024 * 1024


def _venv_bin(name: str) -> str:
    return str(PROJECT_ROOT / ".venv" / "bin" / name)


def _rotate_log() -> None:
    try:
        if RUNTIME_LOG.exists() and RUNTIME_LOG.stat().st_size > _LOG_ROTATE_BYTES:
            RUNTIME_LOG.rename(RUNTIME_LOG.with_suffix(".log.1"))
    except OSError:
        pass


class MLXRuntimeProvider(RuntimeProvider):
    name = "mlx"

    def __init__(self) -> None:
        self._start_lock = asyncio.Lock()

    # ---------- command construction ----------

    def _build_command(self, mode: str, cfg: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
        rt = cfg["runtime"]
        target_path = resolve_path(rt["target_model"]) or rt["target_model"]
        host, port = rt["internal_host"], rt["internal_port"]

        if mode == "fast":
            df = cfg["dflash"]
            draft_path = resolve_path(rt["draft_model"]) or rt["draft_model"]
            cmd = [
                _venv_bin("dflash"), "serve",
                "--model", target_path,
                "--draft-model", draft_path,
                "--host", host, "--port", str(port),
                "--verify-mode", df.get("verify_mode", "adaptive"),
                "--max-tokens", str(rt.get("default_max_tokens", 4096)),
                "--dflash-max-ctx", str(rt.get("max_context", 65536)),
                "--log-level", cfg["logging"]["level"],
            ]
            if int(df.get("verify_len_cap") or 0) > 0:
                cmd += ["--verify-len-cap", str(df["verify_len_cap"])]
            if int(df.get("fastpath_max_tokens") or 0) > 0:
                cmd += ["--fastpath-max-tokens", str(df["fastpath_max_tokens"])]
            dq = df.get("draft_quant", "default")
            if dq and dq != "default":
                cmd += ["--draft-quant", dq]
            if not df.get("prefix_cache", True):
                cmd += ["--no-prefix-cache"]
            if not rt.get("enable_thinking", True):
                cmd += ["--chat-template-args", '{"enable_thinking": false}']
        elif mode == "safe":
            cmd = [
                _venv_bin("python"), "-m", "mlx_lm", "server",
                "--model", target_path,
                "--host", host, "--port", str(port),
                "--max-tokens", str(rt.get("default_max_tokens", 4096)),
                "--log-level", cfg["logging"]["level"],
            ]
        else:
            raise ValueError(f"unknown mode: {mode}")

        env = dict(os.environ)
        env.setdefault("HF_HUB_OFFLINE", "0")
        return cmd, env

    # ---------- lifecycle ----------

    async def start(self, mode: str) -> dict[str, Any]:
        async with self._start_lock:
            state = read_state()
            if state.status == "running" and pid_alive(state.pid):
                if state.mode == mode:
                    return await self.status()
                await self._terminate(state)

            cfg = load_config()
            rt = cfg["runtime"]
            cmd, env = self._build_command(mode, cfg)

            _rotate_log()
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            log_f = open(RUNTIME_LOG, "a", buffering=1)
            log_f.write(f"\n===== [{time.strftime('%F %T')}] starting mode={mode}: {' '.join(cmd)} =====\n")

            proc = subprocess.Popen(
                cmd, stdout=log_f, stderr=subprocess.STDOUT,
                env=env, start_new_session=True, cwd=str(PROJECT_ROOT),
            )

            state = RuntimeState(
                status="starting", mode=mode, provider=self.name, pid=proc.pid,
                internal_host=rt["internal_host"], internal_port=rt["internal_port"],
                alias=cfg["api"]["alias"],
                target_model=rt["target_model"],
                target_path=resolve_path(rt["target_model"]),
                draft_model=rt["draft_model"] if mode == "fast" else None,
                draft_path=resolve_path(rt["draft_model"]) if mode == "fast" else None,
                started_at=time.time(),
            )
            write_state(state)
            add_event("start", {"mode": mode, "pid": proc.pid})

            ok, err = await self._wait_healthy(state, proc)
            state = read_state()
            if ok:
                state.status = "running"
                state.error = None
            else:
                state.status = "error"
                state.error = err
                add_event("crash", {"mode": mode, "error": err})
            write_state(state)
            return await self.status()

    async def _wait_healthy(self, state: RuntimeState, proc: subprocess.Popen) -> tuple[bool, str | None]:
        deadline = time.time() + START_TIMEOUT_S
        url_base = f"http://{state.internal_host}:{state.internal_port}"
        async with httpx.AsyncClient(timeout=3) as client:
            while time.time() < deadline:
                if proc.poll() is not None:
                    return False, f"process exited with code {proc.returncode} during startup (see runtime.log)"
                for probe in ("/v1/models", "/metrics", "/health"):
                    try:
                        r = await client.get(url_base + probe)
                        if r.status_code < 500:
                            return True, None
                    except httpx.HTTPError:
                        pass
                await asyncio.sleep(1.5)
        return False, f"inference server did not become healthy within {START_TIMEOUT_S}s"

    async def _terminate(self, state: RuntimeState) -> None:
        if not pid_alive(state.pid):
            return
        try:
            os.killpg(os.getpgid(state.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(state.pid, signal.SIGTERM)
            except OSError:
                pass
        for _ in range(40):  # up to 20 s graceful
            if not pid_alive(state.pid):
                return
            await asyncio.sleep(0.5)
        try:
            os.killpg(os.getpgid(state.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(state.pid, signal.SIGKILL)
            except OSError:
                pass
        for _ in range(20):
            if not pid_alive(state.pid):
                return
            await asyncio.sleep(0.5)

    async def stop(self) -> dict[str, Any]:
        async with self._start_lock:
            state = read_state()
            if state.pid and pid_alive(state.pid):
                state.status = "stopping"
                write_state(state)
                await self._terminate(state)
                add_event("stop", {"pid": state.pid, "mode": state.mode})
            state = read_state()
            state.status = "stopped"
            state.pid = None
            state.error = None
            write_state(state)
            return await self.status()

    async def restart(self, mode: str | None = None) -> dict[str, Any]:
        state = read_state()
        target_mode = mode or state.mode
        await self.stop()
        add_event("restart", {"mode": target_mode})
        return await self.start(target_mode)

    # ---------- inspection ----------

    async def status(self) -> dict[str, Any]:
        state = read_state()
        alive = pid_alive(state.pid)
        health = await self.health() if alive else {"ok": False, "reason": "process not running"}

        # Reconcile: state says running but process is gone -> crashed
        if state.status == "running" and not alive:
            state.status = "error"
            state.error = "inference process is no longer running (crashed or killed externally)"
            write_state(state)
            add_event("crash", {"mode": state.mode, "detail": "process disappeared"})

        d = state.to_dict()
        d["process_alive"] = alive
        d["http_healthy"] = health.get("ok", False)
        d["health"] = health
        d["engine"] = "dflash-mlx" if state.mode == "fast" else "mlx-lm"
        d["uptime_s"] = (time.time() - state.started_at) if (alive and state.started_at) else None
        return d

    async def health(self) -> dict[str, Any]:
        state = read_state()
        base = f"http://{state.internal_host}:{state.internal_port}"
        async with httpx.AsyncClient(timeout=2) as client:
            for probe in ("/v1/models", "/metrics", "/health"):
                try:
                    r = await client.get(base + probe)
                    if r.status_code < 500:
                        return {"ok": True, "probe": probe, "status_code": r.status_code}
                except httpx.HTTPError:
                    continue
        return {"ok": False, "reason": "no HTTP response from inference server"}

    async def metrics(self) -> dict[str, Any]:
        """dflash serve exposes /metrics; mlx_lm.server does not."""
        state = read_state()
        if state.status != "running":
            return {"available": False, "reason": "runtime not running"}
        if state.mode != "fast":
            return {"available": False, "reason": "mlx-lm server does not expose runtime metrics"}
        base = f"http://{state.internal_host}:{state.internal_port}"
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(base + "/metrics")
                r.raise_for_status()
                data = r.json()
                return {"available": True, "data": data}
        except (httpx.HTTPError, ValueError) as e:
            return {"available": False, "reason": f"metrics fetch failed: {e}"}

    def logs(self, lines: int = 200) -> list[str]:
        if not RUNTIME_LOG.exists():
            return []
        try:
            text = RUNTIME_LOG.read_text(errors="replace")
        except OSError:
            return []
        return text.splitlines()[-lines:]
