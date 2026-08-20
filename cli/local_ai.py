#!/usr/bin/env python3
"""local-ai — CLI for Local AI Control Center.

Talks to the same control backend as the web dashboard. If the backend is not
running, start/stop fall back to direct process management.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND = "http://127.0.0.1:8787"
VENV_PY = PROJECT_ROOT / ".venv" / "bin" / "python"


def _req(method: str, path: str, body: dict | None = None, timeout: int = 330):
    url = BACKEND + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _backend_up() -> bool:
    try:
        _req("GET", "/api/health", timeout=3)
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _start_backend_processes() -> None:
    logs = PROJECT_ROOT / "logs"
    logs.mkdir(exist_ok=True)
    for module, port in (("backend.main:app", 8787), ("backend.gateway:app", 8080)):
        check = subprocess.run(["lsof", f"-tiTCP:{port}", "-sTCP:LISTEN"], capture_output=True)
        if check.stdout.strip():
            continue
        logf = open(logs / ("backend.log" if port == 8787 else "gateway.log"), "a")
        subprocess.Popen(
            [str(VENV_PY), "-m", "uvicorn", module, "--host", "127.0.0.1", "--port", str(port)],
            cwd=str(PROJECT_ROOT), stdout=logf, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    for _ in range(30):
        if _backend_up():
            return
        time.sleep(0.5)
    print("warning: backend did not respond within 15 s — check logs/backend.log", file=sys.stderr)


def cmd_start() -> int:
    if not _backend_up():
        print("starting control backend + gateway…")
        _start_backend_processes()
    print("starting runtime (model load may take up to a few minutes)…")
    d = _req("POST", "/api/runtime/start")
    print(f"runtime: {d['status']} · mode={d['mode']} · engine={d.get('engine')} · healthy={d['http_healthy']}")
    return 0 if d["status"] == "running" else 1


def cmd_stop() -> int:
    d = _req("POST", "/api/runtime/stop")
    print(f"runtime: {d['status']}")
    return 0


def cmd_restart() -> int:
    d = _req("POST", "/api/runtime/restart")
    print(f"runtime: {d['status']} · mode={d['mode']} · healthy={d['http_healthy']}")
    return 0 if d["status"] == "running" else 1


def cmd_status() -> int:
    if not _backend_up():
        print("control backend : not running (http://127.0.0.1:8787)")
        return 1
    h = _req("GET", "/api/health", timeout=10)
    rt = h["runtime"]
    print(f"control backend : ok (http://127.0.0.1:8787)")
    print(f"api gateway     : {'ok' if h['api']['ok'] else 'DOWN'} (http://127.0.0.1:{h['ports']['api']}/v1)")
    print(f"runtime         : {rt['status']} · mode={rt['mode']} · model_loaded={rt['model_loaded']} · draft_loaded={rt['draft_loaded']}")
    if rt.get("error"):
        print(f"error           : {rt['error']}")
    return 0


def cmd_benchmark() -> int:
    print("running quick benchmark (coding_long)…")
    r = _req("POST", "/api/benchmark/quick", {"prompt_key": "coding_long"})
    if not r.get("ok"):
        print(f"could not start: {r.get('error')}")
        return 1
    while True:
        time.sleep(3)
        j = _req("GET", "/api/benchmark/job", timeout=10)
        if not j["busy"]:
            res = (j["job"] or {}).get("result") or {}
            if res.get("ok"):
                print(f"tokens={res['tokens']} tok/s={res['tok_s']} ttft={res['ttft_s']}s "
                      f"acceptance={res.get('acceptance_rate')}")
                return 0
            print(f"benchmark failed: {res.get('error') or (j['job'] or {}).get('error')}")
            return 1
        sys.stdout.write(".")
        sys.stdout.flush()


def cmd_logs() -> int:
    d = _req("GET", "/api/logs?category=runtime&lines=60&important_only=true", timeout=10)
    print("\n".join(d.get("lines", [])))
    return 0


def cmd_open() -> int:
    subprocess.run(["open", "http://127.0.0.1:8787"])
    return 0


def cmd_app() -> int:
    app = PROJECT_ROOT / "dist" / "Local AI.app"
    if not app.exists():
        print("error: Local AI.app is not built yet\n"
              "       run: bash scripts/build_app.sh", file=sys.stderr)
        return 1
    subprocess.run(["open", str(app)])
    return 0


def main() -> int:
    cmds = {
        "start": cmd_start, "stop": cmd_stop, "restart": cmd_restart,
        "status": cmd_status, "benchmark": cmd_benchmark,
        "logs": cmd_logs, "open": cmd_open, "app": cmd_app,
    }
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("usage: local-ai {start|stop|restart|status|benchmark|logs|open|app}")
        return 2
    try:
        return cmds[sys.argv[1]]()
    except urllib.error.URLError:
        print("error: control backend is not reachable at http://127.0.0.1:8787\n"
              "       run 'local-ai start' or check logs/backend.log", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
