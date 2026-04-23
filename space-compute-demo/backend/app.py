"""FastAPI entry — serves /ws/state WebSocket + /health."""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from models import Envelope, StatePacket
from state_engine import StateEngine

log = logging.getLogger("space_compute_demo")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


class ConnectionManager:
    def __init__(self):
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        log.info("ws connected (n=%d)", len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)
        log.info("ws disconnected (n=%d)", len(self._clients))

    async def broadcast(self, msg: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_json(msg)
            except Exception:
                stale.append(ws)
        for ws in stale:
            await self.disconnect(ws)


manager = ConnectionManager()


def _envelope(type_: str, payload: dict[str, Any], request_id: str | None = None) -> dict[str, Any]:
    msg = {"type": type_, "ts": time.time(), "payload": payload}
    if request_id is not None:
        msg["request_id"] = request_id
    return msg


async def broadcast_state(pkt: StatePacket) -> None:
    await manager.broadcast(_envelope("state_update", pkt.model_dump()))


engine = StateEngine(on_state=broadcast_state)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await engine.start()
    log.info("state engine started")
    try:
        yield
    finally:
        await engine.stop()
        log.info("state engine stopped")


app = FastAPI(title="space-compute-demo backend", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"ok": True, "sim_time_s": engine.snapshot().sim_time_s}


@app.get("/state")
async def http_state():
    """Kit-side polling endpoint (Omniverse stdlib doesn't ship websockets)."""
    return engine.snapshot().model_dump()


@app.websocket("/ws/state")
async def ws_state(ws: WebSocket):
    await manager.connect(ws)
    # Push a snapshot immediately so the client has something to render.
    try:
        await ws.send_json(_envelope("state_update", engine.snapshot().model_dump()))
    except Exception:
        pass

    try:
        while True:
            raw = await ws.receive_json()
            try:
                env = Envelope(**raw)
            except Exception as e:
                await ws.send_json(_envelope("error", {"code": "bad_envelope", "message": str(e)}))
                continue

            await _handle(env, ws)
    except WebSocketDisconnect:
        await manager.disconnect(ws)


async def _handle(env: Envelope, ws: WebSocket) -> None:
    t = env.type
    p = env.payload or {}
    if t == "play":
        engine.play()
        await _ack(ws, env.request_id, True)
    elif t == "pause":
        engine.pause()
        await _ack(ws, env.request_id, True)
    elif t == "reset":
        engine.reset()
        await _ack(ws, env.request_id, True)
        await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
    elif t == "set_time":
        engine.set_time(float(p.get("sim_time_s", 0.0)))
        await _ack(ws, env.request_id, True)
    elif t == "set_parameters":
        engine.set_parameters(p)
        await _ack(ws, env.request_id, True)
    elif t == "set_mode":
        engine.set_mode(p.get("mode", "on_orbit"))
        await _ack(ws, env.request_id, True)
    elif t == "start_task":
        task = engine.start_task(p.get("case_id", "maritime_case_01"))
        await manager.broadcast(_envelope("task_update", {"task": task.model_dump()}))
        await _ack(ws, env.request_id, True)
    elif t == "select_object":
        prim = p.get("prim_path", "")
        await manager.broadcast(_envelope("selection_changed", {"prim_path": prim, "details": {}}))
        await _ack(ws, env.request_id, True)
    elif t == "change_camera":
        preset = p.get("preset", "overview")
        engine.set_camera_preset(preset)
        await manager.broadcast(_envelope("camera_changed", {"preset": preset}))
        await _ack(ws, env.request_id, True)
    else:
        await ws.send_json(_envelope("error", {"code": "unknown_type", "message": t}, env.request_id))


async def _ack(ws: WebSocket, request_id: str | None, ok: bool, detail: str | None = None) -> None:
    payload: dict[str, Any] = {"ok": ok}
    if detail:
        payload["detail"] = detail
    await ws.send_json(_envelope("ack", payload, request_id))
