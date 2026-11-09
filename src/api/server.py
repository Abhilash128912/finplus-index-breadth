"""
FinPlus+ Index Breadth & BTST Engine Web Gateway
================================================
Module: finplus_index_breadth.api.server
Author: FinPlus+ Enterprise Infrastructure
Standard: ISO-8601, FastAPI, WebSocket Live Streaming

Serves REST endpoints, WebSocket broadcasts, and static frontend dashboard with Document PiP Floater.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import sys
from pathlib import Path

# Ensure root and src directories are in sys.path
_CURRENT_FILE = Path(__file__).resolve()
_APP_ROOT = _CURRENT_FILE.parent.parent.parent
_SRC_DIR = _CURRENT_FILE.parent.parent

for _p in [str(_APP_ROOT), str(_SRC_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import finplus_index_breadth
except ImportError:
    import src as _src
    sys.modules["finplus_index_breadth"] = _src

from typing import Any, Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from finplus_core.utils.logger import get_finplus_logger
from finplus_index_breadth.analytics.index_btst_engine import IndexBTSTEngine
from finplus_index_breadth.notifications.ntfy_dispatcher import NTFYDispatcher
from finplus_index_breadth.scheduler.market_scheduler import MarketScheduler

logger = get_finplus_logger("APIServer")

app = FastAPI(
    title="FinPlus+ Index Breadth & BTST Engine",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# Shared scheduler and connection manager
scheduler = MarketScheduler()
active_connections: List[WebSocket] = []


def on_new_snapshot(snapshot: Dict[str, Any]) -> None:
    """Dispatches new breadth snapshot to all connected WebSockets."""
    data_str = json.dumps(snapshot)
    for ws in list(active_connections):
        try:
            asyncio.create_task(ws.send_text(data_str))
        except Exception:
            pass


scheduler.register_listener(on_new_snapshot)


@app.on_event("startup")
async def startup_event() -> None:
    """Launches the background market poller upon server boot."""
    logger.info("Booting FinPlus+ Index Breadth Web Gateway...")
    # Launch background loop (executes first refresh asynchronously via worker thread)
    asyncio.create_task(scheduler.run_loop())


@app.on_event("shutdown")
def shutdown_event() -> None:
    """Terminates background workers upon shutdown."""
    scheduler.stop()


@app.get("/")
async def serve_index() -> FileResponse:
    """Serves the institutional dashboard frontend."""
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/cockpit")
async def serve_cockpit() -> FileResponse:
    """Serves the Master Multi-Pane Cockpit HUD."""
    return FileResponse(FRONTEND_DIR / "cockpit.html")


@app.get("/api/status")
async def get_health_status() -> Dict[str, Any]:
    """Health check endpoint and Render keep-alive ping."""
    return {
        "status": "HEALTHY",
        "service": "FinPlus+ Index Breadth & BTST Engine",
        "timestamp": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).isoformat(),
        "environment": os.getenv("FINPLUS_ENVIRONMENT", "production"),
        "ntfy_topics": scheduler.dispatcher.topics,
    }


@app.get("/api/regime")
async def get_market_regime() -> Dict[str, Any]:
    """Returns the intraday market trend regime and equity/option trading directives."""
    if not scheduler.latest_regime_result:
        scheduler.refresh_breadth()
    return scheduler.latest_regime_result


@app.get("/api/breadth")
async def get_breadth_data() -> Dict[str, Any]:
    """Returns the most recent exchange-wide, Nifty 50, Sensex 30, and market regime snapshot."""
    if not scheduler.latest_nifty_breadth:
        scheduler.refresh_breadth()
    return {
        "timestamp": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).isoformat(),
        "broad_market": scheduler.latest_broad_market,
        "nifty": scheduler.latest_nifty_breadth,
        "sensex": scheduler.latest_sensex_breadth,
        "market_regime": scheduler.latest_regime_result,
    }


@app.get("/api/btst")
async def get_btst_status() -> Dict[str, Any]:
    """Returns the current BTST decision (evaluated strictly for Nifty/Sensex with exact ATM options)."""
    if not scheduler.latest_btst_result:
        scheduler.refresh_breadth()
    return scheduler.latest_btst_result


@app.post("/api/trigger-test-alert")
async def trigger_test_alert(mode: str = "both", topic: str = "") -> Dict[str, Any]:
    """
    Manually triggers test push notifications to registered NTFY topics (Finplus-Delta & Finplus-Breadth).
    """
    snapshot = scheduler.refresh_breadth()
    dispatcher = scheduler.dispatcher
    if topic:
        dispatcher.topics = [topic]

    dispatched = []
    if mode in ("pulse", "both"):
        p_ok = dispatcher.send_periodic_breadth_pulse(snapshot)
        dispatched.append({"type": "breadth_pulse", "success": p_ok, "topics": dispatcher.topics})

    if mode in ("btst", "both"):
        btst_test = IndexBTSTEngine.evaluate_btst(
            scheduler.latest_nifty_breadth,
            scheduler.latest_sensex_breadth,
            broad_market=scheduler.latest_broad_market,
            force_evaluation=True,
        )
        b_ok = dispatcher.send_btst_recommendation(btst_test)
        dispatched.append({"type": "btst_recommendation", "success": b_ok, "topics": dispatcher.topics, "data": btst_test})

    return {
        "status": "DISPATCH_COMPLETED",
        "topics": dispatcher.topics,
        "results": dispatched,
    }


@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Streams live market breadth snapshots to UI and desktop floaters."""
    await websocket.accept()
    active_connections.append(websocket)
    logger.info("New WebSocket client connected (%d active)", len(active_connections))

    # Send initial snapshot immediately (complete with broad market and regime directives)
    initial_data = {
        "timestamp": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).isoformat(),
        "broad_market": scheduler.latest_broad_market,
        "nifty": scheduler.latest_nifty_breadth,
        "sensex": scheduler.latest_sensex_breadth,
        "market_regime": scheduler.latest_regime_result,
        "btst": scheduler.latest_btst_result,
    }
    await websocket.send_text(json.dumps(initial_data))

    try:
        while True:
            # Keep socket alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)
        logger.info("WebSocket client disconnected (%d remaining)", len(active_connections))

