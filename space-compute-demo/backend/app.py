"""FastAPI entry — serves /ws/state WebSocket + /health."""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from fastapi import HTTPException

from models import Envelope, StatePacket
from services import constellations, orbit_catalog
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


@app.get("/orbits")
async def http_orbits():
    """List available orbit modes (LEO / SSO / MEO / GEO + metadata)."""
    return {"modes": orbit_catalog.list_modes()}


@app.get("/constellations")
async def http_constellations():
    """List all constellation presets + their headline parameters."""
    return {
        "active": engine.constellation_id,
        "presets": constellations.list_presets(),
    }


@app.get("/constellations/{preset_id}")
async def http_constellation_detail(preset_id: str):
    """Return one preset's params + the precomputed base orbit ring (128 ECI
    km samples). The Kit renderer uses the ring + Walker params to lay out
    every sat without round-tripping per-sat positions."""
    preset = constellations.get_preset(preset_id)
    if preset is None:
        raise HTTPException(404, f"unknown constellation preset {preset_id!r}")
    return {
        "id": preset.id,
        "name": preset.name,
        "description": preset.description,
        "planes": preset.planes,
        "sats_per_plane": preset.sats_per_plane,
        "phasing": preset.phasing,
        "total_sats": preset.total_sats,
        "inclination_deg": preset.inclination_deg,
        "altitude_km": preset.altitude_km,
        "period_s": preset.period_s,
        "time_scale": constellations.TIME_SCALE,
        "ring_eci_km": preset.ring_eci_km(),
    }


@app.post("/constellation/{preset_id}")
async def http_set_constellation(preset_id: str):
    """Swap the active constellation. The next 1Hz state_update broadcast
    will carry the new fleet snapshot."""
    if not engine.set_constellation(preset_id):
        raise HTTPException(404, f"unknown constellation preset {preset_id!r}")
    return {"ok": True, "constellation_id": preset_id}


@app.get("/satellite_config")
async def http_get_satellite_config():
    """Current hardware loadout — Kit polls this each tick to know which
    USD VariantSet selections to apply, so Web's `/satellite` page stays
    in lock-step with the rendered 3D model."""
    return engine.satellite_config.model_dump()


@app.post("/satellite_config")
async def http_post_satellite_config(patch: dict[str, Any]):
    """Merge a partial config and immediately broadcast a fresh state_update
    so any connected Web clients see the new derived numbers in <1 s."""
    try:
        new_cfg = engine.set_config(patch)
    except Exception as e:
        raise HTTPException(422, f"invalid satellite_config patch: {e}") from e
    await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
    return {"ok": True, "satellite_config": new_cfg.model_dump()}


@app.post("/mission/start")
async def http_start_mission():
    """Kick the 天数天算 mission + broadcast so Web/Kit react immediately."""
    m = engine.start_mission()
    await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
    return {"ok": True, "mission": m.model_dump()}


@app.post("/mission/stop")
async def http_stop_mission():
    engine.stop_mission()
    await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
    return {"ok": True}


@app.post("/mission/scene_ready")
async def http_mission_scene_ready():
    """Kit calls this once the target scene geometry is resident, releasing
    the load gate so the cinematic timeline begins."""
    engine.mission_scene_ready()
    await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
    return {"ok": True, "mission": engine.mission.model_dump()}


@app.post("/selection")
async def http_selection(payload: dict[str, Any]):
    """Kit calls this when the user changes the USD viewport selection (clicks
    a prim in the WebRTC stream). The backend just re-broadcasts as the same
    `selection_changed` envelope already produced by the WS select_object
    path, so all web clients update their selectedPrim in lockstep."""
    prim = str(payload.get("prim_path", ""))
    await manager.broadcast(_envelope("selection_changed", {"prim_path": prim, "details": {}}))
    return {"ok": True, "prim_path": prim}


@app.post("/orbit_type/{mode}")
async def http_set_orbit_type(mode: str):
    """Convenience HTTP control for swapping orbit mode without a WebSocket."""
    if orbit_catalog.get_entry(mode) is None:
        raise HTTPException(404, f"unknown orbit mode {mode!r}")
    engine.set_parameters({"orbit_type": mode})
    return {"ok": True, "orbit_type": mode}


@app.get("/orbits/{mode}")
async def http_orbit(mode: str, n_points: int = 128):
    """Return TLE strings + ECI sample points tracing one full revolution.

    Points are in km. The Kit scene divides by 100 to land in the
    `metersPerUnit = 100000` overview stage's coordinate system.
    """
    entry = orbit_catalog.get_entry(mode)
    if entry is None:
        raise HTTPException(404, f"unknown orbit mode {mode!r}")
    pts = orbit_catalog.sample_orbit(mode, max(16, min(n_points, 512)))
    return {
        "mode": entry.mode,
        "name": entry.name,
        "description": entry.description,
        "period_s": entry.period_s,
        "inclination_deg": entry.inclination_deg,
        "tle": [entry.line1, entry.line2],
        "time_scale": orbit_catalog.TIME_SCALE,
        "points_km": pts,
    }


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
    elif t == "set_config":
        try:
            engine.set_config(p)
        except Exception as e:
            await ws.send_json(_envelope("error",
                {"code": "bad_satellite_config", "message": str(e)}, env.request_id))
            return
        await _ack(ws, env.request_id, True)
        # Broadcast the new snapshot so all clients see the recomputed
        # solar / payload / temp in the next sub-second instead of waiting
        # for the next 1Hz tick.
        await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
    elif t == "start_mission":
        engine.start_mission()
        await _ack(ws, env.request_id, True)
        await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
    elif t == "stop_mission":
        engine.stop_mission()
        await _ack(ws, env.request_id, True)
        await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
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
