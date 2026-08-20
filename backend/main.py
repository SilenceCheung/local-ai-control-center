"""Control-plane entry point (dashboard backend, default 127.0.0.1:8787).

Run: .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8787
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router
from backend.core.config import PROJECT_ROOT, ensure_dirs, load_config
from backend.database.db import init_db
from backend.models.registry import scan_models
from backend.monitoring.sampler import sampler
from backend.runtime.manager import runtime_manager

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("lacc")

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    init_db()
    await asyncio.to_thread(scan_models)
    await runtime_manager.on_boot()
    sampler.start()
    cfg = load_config()
    log.info("Local AI Control Center backend up — dashboard http://%s:%s",
             cfg["dashboard"]["host"], cfg["dashboard"]["port"])
    yield
    sampler.stop()
    await runtime_manager.shutdown()


app = FastAPI(title="Local AI Control Center", lifespan=lifespan,
              docs_url=None, redoc_url=None)
app.include_router(router)


@app.get("/health")
async def root_health():
    """Structured health at the root, per the /health contract."""
    from backend.api.routes import health as api_health
    return await api_health()


# ---- static frontend (built SPA). API routes take precedence. ----
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/")
    async def no_frontend():
        return JSONResponse({
            "app": "Local AI Control Center",
            "note": "frontend build not found — run: cd frontend && pnpm build",
            "api": "/api/health",
        })


def main() -> None:
    import uvicorn
    cfg = load_config()
    uvicorn.run("backend.main:app", host=cfg["dashboard"]["host"],
                port=cfg["dashboard"]["port"], log_level="info")


if __name__ == "__main__":
    main()
