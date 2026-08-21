"""MLXRuntimeProvider — manages one local MLX inference server process.

FAST mode : dflash serve  (target + DFlash draft, speculative decoding)
SAFE mode : mlx_lm.server (target only)

The child is spawned in its own session so a control-plane crash/restart never
kills inference. On startup the manager re-attaches via the pid recorded in
data/runtime_state.json.
"""

from __future__ import annotations

import asyncio
import json
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
from backend.runtime.recipes import DEFAULT_SLOTS, RECIPE_IDS, serve_supports

RUNTIME_LOG = LOGS_DIR / "runtime.log"
START_TIMEOUT_S = 300  # first load of a 26 GB model from cold SSD can be slow
_LOG_ROTATE_BYTES = 20 * 1024 * 1024

_PROFILE_DIFF_FIELDS = (
    "mode",
    "recipe_id",
    "target_model",
    "draft_model",
    "verify_mode",
    "draft_quant",
    "runtime_block_size",
    "reasoning",
    "prefix_cache",
    "prefill_step_size",
    "draft_sink_size",
    "draft_window_size",
    "prefix_cache_l2",
    "prefix_cache_max_entries",
    "prefix_cache_max_bytes",
    "prefix_cache_l2_max_bytes",
    "cache_limit",
)


def _venv_bin(name: str) -> str:
    return str(PROJECT_ROOT / ".venv" / "bin" / name)


def _rotate_log() -> None:
    try:
        if RUNTIME_LOG.exists() and RUNTIME_LOG.stat().st_size > _LOG_ROTATE_BYTES:
            RUNTIME_LOG.rename(RUNTIME_LOG.with_suffix(".log.1"))
    except OSError:
        pass


def _chat_template_args(rt: dict[str, Any], df: dict[str, Any]) -> str | None:
    """Build tokenizer chat-template JSON. Skip when everything is the default."""
    import json
    args: dict[str, Any] = {}
    if not rt.get("enable_thinking", True):
        args["enable_thinking"] = False
    reason = str(df.get("reasoning") or "default")
    if reason not in ("", "default") and not serve_supports("--reasoning"):
        args["reasoning_effort"] = reason
    if not args:
        return None
    return json.dumps(args, separators=(",", ":"))


def _append_supported(cmd: list[str], flag: str, value: Any | None = None) -> None:
    """Append a dflash option only when the installed CLI advertises it."""
    if not serve_supports(flag):
        return
    cmd.append(flag)
    if value is not None:
        cmd.append(str(value))


def _flag_value(command: list[str], flag: str) -> str | None:
    try:
        index = command.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(command) or command[index + 1].startswith("--"):
        return None
    return command[index + 1]


def _as_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _recipe_for_command(
    cfg: dict[str, Any],
    target: str | None,
    draft: str | None,
    command: list[str],
) -> str | None:
    """Infer a legacy process recipe from its complete effective signature.

    Model pairs alone are insufficient because older UI flows allowed users to
    select the official pair while the Heretic slot was still active.
    """
    slots = (cfg.get("recipes") or {})
    actual_quant = _flag_value(command, "--draft-quant") or "engine-default"
    actual_verify = _flag_value(command, "--verify-mode")
    actual_block = _as_int(_flag_value(command, "--block-size")) or 0
    actual_reasoning = _flag_value(command, "--reasoning")
    template_args = _flag_value(command, "--chat-template-args")
    if actual_reasoning is None and template_args:
        try:
            actual_reasoning = json.loads(template_args).get("reasoning_effort")
        except (json.JSONDecodeError, AttributeError):
            pass
    actual_reasoning = actual_reasoning or "default"

    scores: list[tuple[int, str]] = []
    for recipe_id in RECIPE_IDS:
        slot = slots.get(recipe_id) or {}
        dflash = slot.get("dflash") or {}
        slot_quant = dflash.get("draft_quant") or "default"
        if slot_quant == "default":
            slot_quant = "engine-default"
        score = 0
        score += 4 if slot.get("target_model") == target else 0
        score += 4 if slot.get("draft_model") == draft else 0
        score += 3 if slot_quant == actual_quant else 0
        score += 1 if (dflash.get("verify_mode") or "adaptive") == actual_verify else 0
        score += 1 if int(dflash.get("runtime_block_size") or 0) == actual_block else 0
        score += 2 if (dflash.get("reasoning") or "default") == actual_reasoning else 0
        scores.append((score, recipe_id))
    scores.sort(reverse=True)
    if len(scores) > 1 and scores[0][0] == scores[1][0]:
        return None
    return scores[0][1] if scores and scores[0][0] >= 8 else None


def _launch_profile(
    mode: str,
    cfg: dict[str, Any],
    command: list[str],
    *,
    target_model: str | None = None,
    draft_model: str | None = None,
    infer_recipe: bool = False,
) -> dict[str, Any]:
    """Return only settings proven by the actual launch command.

    This deliberately does not echo every value from config.yaml.  A knob that
    the installed engine does not advertise is absent from the command and
    therefore must not be shown as active in the product UI.
    """
    rt = cfg["runtime"]
    target = target_model or rt.get("target_model")
    draft = (draft_model or rt.get("draft_model")) if mode == "fast" else None
    recipe_id = None
    if mode == "fast":
        recipe_id = (
            _recipe_for_command(cfg, target, draft, command)
            if infer_recipe
            else (cfg.get("recipes") or {}).get("active")
        )
    generation = DEFAULT_SLOTS.get(recipe_id or "", {}).get("generation")

    reasoning = None
    if mode == "fast":
        reasoning = _flag_value(command, "--reasoning")
        template_args = _flag_value(command, "--chat-template-args")
        if reasoning is None and template_args:
            try:
                reasoning = json.loads(template_args).get("reasoning_effort")
            except (json.JSONDecodeError, AttributeError):
                pass

    return {
        "mode": mode,
        "recipe_id": recipe_id,
        "generation": generation,
        "target_model": target,
        "draft_model": draft,
        "verify_mode": _flag_value(command, "--verify-mode") if mode == "fast" else None,
        "draft_quant": (_flag_value(command, "--draft-quant") or "engine-default") if mode == "fast" else None,
        "runtime_block_size": _as_int(_flag_value(command, "--block-size")) if mode == "fast" else None,
        "runtime_block_source": (
            "override" if mode == "fast" and "--block-size" in command else
            "checkpoint" if mode == "fast" else None
        ),
        "draft_bits": _as_int(_flag_value(command, "--draft-bits")) if mode == "fast" else None,
        "reasoning": reasoning,
        "prefix_cache": ("--no-prefix-cache" not in command) if mode == "fast" else None,
        "prefill_step_size": _as_int(_flag_value(command, "--prefill-step-size")) if mode == "fast" else None,
        "draft_sink_size": _as_int(_flag_value(command, "--draft-sink-size")) if mode == "fast" else None,
        "draft_window_size": _as_int(_flag_value(command, "--draft-window-size")) if mode == "fast" else None,
        "prefix_cache_l2": (
            False if "--no-prefix-cache-l2" in command else
            True if "--prefix-cache-l2" in command else None
        ) if mode == "fast" else None,
        "prefix_cache_max_entries": _as_int(_flag_value(command, "--prefix-cache-max-entries")) if mode == "fast" else None,
        "prefix_cache_max_bytes": _flag_value(command, "--prefix-cache-max-bytes") if mode == "fast" else None,
        "prefix_cache_l2_max_bytes": _flag_value(command, "--prefix-cache-l2-max-bytes") if mode == "fast" else None,
        "cache_limit": _flag_value(command, "--cache-limit") if mode == "fast" else None,
        "applied_flags": sorted(flag for flag in command if flag.startswith("--")),
    }


def _process_command(pid: int | None) -> list[str] | None:
    if not pid:
        return None
    try:
        proc = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        raw = (proc.stdout or "").strip()
        # Our generated JSON arguments contain no spaces. New launches use the
        # persisted snapshot, so this is only a backward-compatible bridge for
        # processes started before launch_config existed.
        return raw.split() if raw else None
    except (OSError, subprocess.SubprocessError):
        return None


def _profile_changes(configured: dict[str, Any], running: dict[str, Any] | None) -> list[dict[str, Any]]:
    if running is None:
        return []
    return [
        {"field": field, "configured": configured.get(field), "running": running.get(field)}
        for field in _PROFILE_DIFF_FIELDS
        if configured.get(field) != running.get(field)
    ]


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
            bs = int(df.get("runtime_block_size") or 0)
            if bs > 0 and serve_supports("--block-size"):
                cmd += ["--block-size", str(bs)]
            dbits = int(df.get("draft_bits") or 0)
            if dbits > 0 and serve_supports("--draft-bits"):
                cmd += ["--draft-bits", str(dbits)]
            if not df.get("prefix_cache", True):
                _append_supported(cmd, "--no-prefix-cache")
            prefill_step = int(df.get("prefill_step_size") or 0)
            if prefill_step > 0:
                _append_supported(cmd, "--prefill-step-size", prefill_step)
            sink_size = int(df.get("draft_sink_size") or 0)
            _append_supported(cmd, "--draft-sink-size", sink_size)
            window_size = int(df.get("draft_window_size") or 0)
            if window_size > 0:
                _append_supported(cmd, "--draft-window-size", window_size)
            l2_enabled = bool(df.get("prefix_cache_l2", True))
            _append_supported(
                cmd,
                "--prefix-cache-l2" if l2_enabled else "--no-prefix-cache-l2",
            )
            cache_values = (
                ("--prefix-cache-max-entries", df.get("prefix_cache_max_entries")),
                ("--prefix-cache-max-bytes", df.get("prefix_cache_max_bytes")),
                ("--prefix-cache-l2-max-bytes", df.get("prefix_cache_l2_max_bytes")),
                ("--cache-limit", df.get("cache_limit")),
            )
            for flag, value in cache_values:
                if value not in (None, "", 0):
                    _append_supported(cmd, flag, value)
            tmpl = _chat_template_args(rt, df)
            if tmpl:
                cmd += ["--chat-template-args", tmpl]
            reason = str(df.get("reasoning") or "default")
            if reason not in ("", "default") and serve_supports("--reasoning"):
                cmd += ["--reasoning", reason]
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
                launch_config=_launch_profile(mode, cfg, cmd),
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
        cfg = load_config()
        configured_mode = cfg["runtime"]["mode"]
        configured_command, _ = self._build_command(configured_mode, cfg)
        configured = _launch_profile(configured_mode, cfg, configured_command)
        running = state.launch_config if alive else None
        if alive and running is None:
            legacy_command = _process_command(state.pid)
            if legacy_command:
                running = _launch_profile(
                    state.mode,
                    cfg,
                    legacy_command,
                    target_model=state.target_model,
                    draft_model=state.draft_model,
                    infer_recipe=True,
                )
        changes = _profile_changes(configured, running)
        d["configuration"] = {
            "configured": configured,
            "running": running,
            "in_sync": not changes if alive else True,
            "restart_required": bool(alive and changes),
            "changes": changes,
        }
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
