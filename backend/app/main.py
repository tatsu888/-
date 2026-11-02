"""FastAPI entry point.

Run (dev, from backend/):   uvicorn app.main:app --reload --port 8000
OpenAPI docs:               http://localhost:8000/docs   (see also docs/API.md)
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import api_analysis, api_excel, api_framework, api_trinity, api_harness, api_macro, api_market, api_research
from .config import settings
from .hub import Client, Hub
from .providers.tv_web import TVWeb
from .state import S

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("terminal")


async def _excel_watch() -> None:
    """Push 'excel_changed' to browsers when a viewed workbook is saved (e.g. in Excel)."""
    while True:
        await asyncio.sleep(1.5)
        try:
            for fid, mtime in S.excel.changed_files():
                await S.hub.broadcast({"type": "excel_changed", "id": fid, "mtime": mtime})
        except Exception as e:  # noqa: BLE001
            log.debug("excel watch: %s", e)


async def _indicator_alerts() -> None:
    """Evaluate indicator alerts (RSI, SMA cross, golden cross …) once a minute on cached history."""
    while True:
        await asyncio.sleep(60)
        try:
            for a in await S.alerts.evaluate_indicators(lambda s, iv, n: S.history(s, iv, n)):
                await S.hub.broadcast({"type": "alert", "alert": a})
        except Exception as e:  # noqa: BLE001
            log.debug("indicator alerts: %s", e)


@asynccontextmanager
async def lifespan(_: FastAPI):
    saved = (S.store.get("settings") or {}).get("provider")
    if saved and not os.environ.get("TERMINAL_PROVIDER"):
        S.registry.active_name = saved  # remember the last manual switch
    S.web = TVWeb()  # fresh HTTP client per app lifetime
    prov = await S.registry.get()
    S.hub = Hub(prov, settings.push_interval_sec, S.alerts)
    await S.hub.start()
    await S.hub.resync()
    watch = asyncio.create_task(_excel_watch())
    ind = asyncio.create_task(_indicator_alerts())
    trin = asyncio.create_task(api_trinity.loop(settings.trinity_first_delay_sec)) if settings.trinity_auto else None
    log.info("active provider=%s", prov.name)
    yield
    watch.cancel()
    ind.cancel()
    if trin:
        trin.cancel()
    await S.hub.stop()
    await S.registry.stop_all()
    await S.web.close()


app = FastAPI(title="Analyst Terminal API", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"],
                   allow_headers=["*"])
for r in (api_market.router, api_analysis.router, api_excel.router, api_harness.router, api_macro.router, api_research.router,
          api_framework.router, api_trinity.router):
    app.include_router(r)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    client = Client(ws)
    await S.hub.add(client)
    await ws.send_json({"type": "hello", **S.hub.provider.health()})
    try:
        while client.alive:
            msg = await ws.receive_json()
            if isinstance(msg, dict):
                try:
                    await S.hub.handle(client, msg)
                except (KeyError, TypeError) as e:
                    await ws.send_json({"type": "error", "message": f"bad message: {e}"})
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        await S.hub.remove(client)


# production: serve the built frontend (frontend/dist) at "/"
if settings.static_dir.is_dir() and (settings.static_dir / "index.html").is_file():
    if (settings.static_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=settings.static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        f = (settings.static_dir / path).resolve()
        if path and f.is_file() and settings.static_dir.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(settings.static_dir / "index.html")
