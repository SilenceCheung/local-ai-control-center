"""launchd integration: generate + install/uninstall LaunchAgents.

Two services:
- com.localai.controlcenter.backend  : control plane (8787)
- com.localai.controlcenter.gateway  : inference gateway (8080)

The heavy model runtime is NOT a login item by default: the backend starts it
on demand (or automatically when runtime.auto_load is true), so logging in
never silently pins 30 GB of unified memory.

RunAtLoad is False: Local AI.app (or `local-ai start`) brings the control plane
up. A clean Quit from the app bootouts these jobs so ports 8787/8080 do not
stay occupied. KeepAlive only restarts a crash while the job is loaded.

"""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path
from typing import Any

from backend.core.config import LOGS_DIR, PROJECT_ROOT

LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"

SERVICES: dict[str, dict[str, Any]] = {
    "backend": {
        "label": "com.localai.controlcenter.backend",
        "args": [str(PROJECT_ROOT / ".venv" / "bin" / "python"), "-m", "uvicorn",
                 "backend.main:app", "--host", "127.0.0.1", "--port", "8787"],
        "log": "backend.log",
    },
    "gateway": {
        "label": "com.localai.controlcenter.gateway",
        "args": [str(PROJECT_ROOT / ".venv" / "bin" / "python"), "-m", "uvicorn",
                 "backend.gateway:app", "--host", "127.0.0.1", "--port", "8080"],
        "log": "gateway.log",
    },
}


def plist_content(service: str) -> dict[str, Any]:
    spec = SERVICES[service]
    return {
        "Label": spec["label"],
        "ProgramArguments": spec["args"],
        "WorkingDirectory": str(PROJECT_ROOT),
        "RunAtLoad": False,  # App owns the session. Login starts Local AI.app, not a headless 8787.
        "KeepAlive": {"SuccessfulExit": False},  # crash recovery only while the job is loaded
        "StandardOutPath": str(LOGS_DIR / spec["log"]),
        "StandardErrorPath": str(LOGS_DIR / spec["log"]),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
        "ProcessType": "Background",
    }


def plist_path(service: str) -> Path:
    return LAUNCH_AGENTS_DIR / f"{SERVICES[service]['label']}.plist"


def write_plists(dest_dir: Path | None = None) -> list[Path]:
    """Write plist files (to launchd/ in the repo, or straight to LaunchAgents)."""
    out = []
    for service in SERVICES:
        dest = (dest_dir or (PROJECT_ROOT / "launchd")) / f"{SERVICES[service]['label']}.plist"
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            plistlib.dump(plist_content(service), f)
        out.append(dest)
    return out


def _launchctl(*args: str) -> tuple[int, str]:
    p = subprocess.run(["launchctl", *args], capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def install(service: str) -> dict[str, Any]:
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = plist_path(service)
    with open(dest, "wb") as f:
        plistlib.dump(plist_content(service), f)
    uid = subprocess.run(["id", "-u"], capture_output=True, text=True).stdout.strip()
    _launchctl("bootout", f"gui/{uid}", str(dest))  # ignore failure: may not be loaded
    code, out = _launchctl("bootstrap", f"gui/{uid}", str(dest))
    return {"ok": code == 0, "plist": str(dest), "output": out}


def uninstall(service: str) -> dict[str, Any]:
    dest = plist_path(service)
    uid = subprocess.run(["id", "-u"], capture_output=True, text=True).stdout.strip()
    code, out = _launchctl("bootout", f"gui/{uid}", str(dest))
    if dest.exists():
        dest.unlink()
    return {"ok": True, "unloaded": code == 0, "output": out}


def status(service: str) -> dict[str, Any]:
    label = SERVICES[service]["label"]
    code, out = _launchctl("list", label)
    installed = plist_path(service).exists()
    running = code == 0
    pid = None
    if running:
        for line in out.splitlines():
            if '"PID"' in line:
                try:
                    pid = int(line.split("=")[1].strip().rstrip(";"))
                except (ValueError, IndexError):
                    pass
    return {"service": service, "label": label, "installed": installed,
            "loaded": running, "pid": pid}
