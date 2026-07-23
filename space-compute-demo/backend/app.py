"""FastAPI entry — serves /ws/state WebSocket + /health."""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import hashlib

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from fastapi import HTTPException

import compare_sim
import design_presets
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


def _restore_geometry_from_disk() -> None:
    """Boot coherence: usd/twin_satellite.usda on disk was generated from the
    last session's twin_params.json, and Kit will happily show that model.
    Seed the engine's geometry from the same file (no version bump — nothing
    changed on disk) so the physics areas match the model in the viewport
    instead of silently reverting to the 2-cluster defaults."""
    try:
        params = json.loads(_TWIN_PARAMS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    try:
        engine.set_twin_geometry(
            {k: params.get(k) for k in
             ("architecture", "solar_clusters_per_side",
              "radiator_long", "radiator_ratio")},
            mark_custom=False)
        log.info("twin geometry restored from disk: %s",
                 engine.twin_geometry.model_dump())
    except Exception as e:  # noqa: BLE001
        log.warning("could not restore twin geometry: %s", e)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _restore_geometry_from_disk()
    await engine.start()
    log.info("state engine started")
    prewarm = asyncio.create_task(_prewarm_previews())
    try:
        yield
    finally:
        prewarm.cancel()
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


# --- Twin deployable geometry (Feature 3) ---------------------------------
# usd/twin_params.json drives tools/gen_twin_satellite.py; regenerating the
# .usda lets Kit reload the layer with the new solar count / radiator size.
_REPO_ROOT   = Path(__file__).resolve().parent.parent
_TWIN_PARAMS = _REPO_ROOT / "usd" / "twin_params.json"
_GEN_SCRIPT  = _REPO_ROOT / "tools" / "gen_twin_satellite.py"
# Serialize regens: rapid stepper clicks (or a design apply racing a manual
# edit) must not interleave twin_params.json writes with gen subprocesses.
_regen_lock = asyncio.Lock()


async def _regenerate_twin_latest() -> bool:
    """Regenerate the live twin USD from the engine's CURRENT geometry,
    one regen at a time. Sampling the geometry inside the lock means queued
    regens converge on the latest state regardless of arrival order. The
    version bump (Kit's reload trigger) happens strictly AFTER the file is
    on disk so Kit can never reload a stale or half-written layer."""
    async with _regen_lock:
        ok = await asyncio.to_thread(
            _regenerate_twin, engine.twin_geometry.model_dump())
        if ok:
            engine.bump_twin_version()
        return ok


def _regenerate_twin(geom: dict[str, Any]) -> bool:
    """Write twin_params.json and re-run the USD generator with this Python
    (the backend venv has pxr). Returns True on a clean regenerate."""
    try:
        _TWIN_PARAMS.write_text(json.dumps({
            "architecture": geom.get("architecture", "truss"),
            "solar_clusters_per_side": geom["solar_clusters_per_side"],
            "radiator_long": geom["radiator_long"],
            "radiator_ratio": geom["radiator_ratio"],
        }, indent=2), encoding="utf-8")
        r = subprocess.run([sys.executable, str(_GEN_SCRIPT)],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            log.error("twin regen failed: %s", r.stderr[-500:])
            return False
        log.info("twin regen ok: %s", r.stdout.strip().splitlines()[-1] if r.stdout else "")
        return True
    except Exception as e:  # noqa: BLE001
        log.error("twin regen error: %s", e)
        return False


@app.get("/twin_geometry")
async def http_get_twin_geometry():
    return engine.twin_geometry.model_dump()


@app.post("/twin_geometry")
async def http_post_twin_geometry(patch: dict[str, Any]):
    """Set deployable geometry → regenerate the USD → broadcast so Web sees the
    new numbers and Kit can reload the bumped layer version."""
    try:
        engine.set_twin_geometry(patch)
    except Exception as e:
        raise HTTPException(422, f"invalid twin_geometry patch: {e}") from e
    regen_ok = await _regenerate_twin_latest()
    await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
    return {"ok": True, "regenerated": regen_ok,
            "twin_geometry": engine.twin_geometry.model_dump()}


# --- Design presets (design gallery) ---------------------------------------
# A preset switches hardware config + deployable geometry + workload profile
# together. Geometry switches regenerate the USD (same pipeline as
# /twin_geometry); the preview thumbnails are software-rendered offline via
# tools/render_usd.py from a per-design stage that never touches the live
# usd/twin_satellite.usda.
_RENDER_SCRIPT = _REPO_ROOT / "tools" / "render_usd.py"
_PREVIEW_DIR   = _REPO_ROOT / "usd" / "_design_previews"
_PREVIEW_SIZE  = 560
# One render at a time — the software rasterizer is CPU-bound and every
# design's PNG is cached after its first render anyway.
_preview_semaphore = asyncio.Semaphore(1)


# Bump when the render pipeline itself changes (view, filters, lite mode…)
# so cached PNGs from the old look regenerate.
_PREVIEW_PIPELINE_V = 3


def _design_fingerprint(preset: design_presets.DesignPreset) -> str:
    """Cache key for the thumbnail — geometry is the only preset input the
    render can show, so hash exactly that (+ renderer settings)."""
    blob = (json.dumps(preset.geometry_patch(), sort_keys=True)
            + f"|{_PREVIEW_SIZE}|v{_PREVIEW_PIPELINE_V}")
    return hashlib.md5(blob.encode()).hexdigest()[:10]


def _render_design_preview(preset: design_presets.DesignPreset) -> Path | None:
    """Blocking: generate the per-design stage (procedural blades — the DGX
    asset is too heavy for thumbnails) and software-render an iso PNG.
    Cached by geometry fingerprint; returns the PNG path or None.

    The renderer writes to a temp name that is os.replace'd into the cache
    only on success — a killed/failed render can never leave a truncated PNG
    that png.exists() would then serve forever."""
    _PREVIEW_DIR.mkdir(exist_ok=True)
    fp = _design_fingerprint(preset)
    png = _PREVIEW_DIR / f"{preset.id}_{fp}.png"
    if png.exists():
        return png
    # .png suffix retained so PIL picks the encoder from the extension.
    tmp = _PREVIEW_DIR / f"_tmp_{preset.id}_{fp}.png"
    stage = _REPO_ROOT / "usd" / f"_preview_design_{preset.id}.usda"
    try:
        params = _PREVIEW_DIR / f"{preset.id}_{fp}.params.json"
        params.write_text(json.dumps({**preset.geometry_patch(),
                                      "use_dgx": False, "preview_lite": True},
                                     indent=2), encoding="utf-8")
        # The stage must sit directly in usd/ so its ./assets and ./textures
        # references resolve; the _preview_ prefix is git-ignored.
        r = subprocess.run([sys.executable, str(_GEN_SCRIPT),
                            "--params", str(params), "--out", str(stage)],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            log.error("preview gen failed (%s): %s", preset.id, r.stderr[-500:])
            return None
        # --only keeps the satellite body (backbone parts / servers / wings /
        # radiators / the LUMID + dish hulls) and drops the celestial context
        # spheres, which would otherwise dominate the auto-framing.
        r = subprocess.run([sys.executable, str(_RENDER_SCRIPT), str(stage), str(tmp),
                            "--view", "iso", "--size", str(_PREVIEW_SIZE),
                            "--only", "part,Server,Wing,Radiator,Hull,LUMID,Satellite"],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0 or not tmp.exists():
            log.error("preview render failed (%s): %s", preset.id, r.stderr[-500:])
            return None
        tmp.replace(png)
        _prune_preview_artifacts(preset.id, keep_fp=fp)
        log.info("design preview rendered: %s", png.name)
        return png
    except Exception as e:  # noqa: BLE001
        log.error("preview error (%s): %s", preset.id, e)
        return None
    finally:
        tmp.unlink(missing_ok=True)
        stage.unlink(missing_ok=True)   # ~550 KB scratch, regenerable


def _prune_preview_artifacts(design_id: str, keep_fp: str) -> None:
    """Drop superseded {id}_{fp}.* cache entries (old geometry / pipeline
    versions) so edited presets don't accumulate stale thumbnails."""
    keep = {f"{design_id}_{keep_fp}.png", f"{design_id}_{keep_fp}.params.json"}
    for p in _PREVIEW_DIR.glob(f"{design_id}_*"):
        if p.name not in keep:
            try:
                p.unlink()
            except OSError:
                pass


async def _preview_path(preset: design_presets.DesignPreset) -> Path | None:
    async with _preview_semaphore:
        return await asyncio.to_thread(_render_design_preview, preset)


async def _prewarm_previews() -> None:
    """Render any missing thumbnails in the background so the first gallery
    open doesn't wait ~10 s per design. The preview PNGs ship in git, so this
    is normally a no-op; the delay keeps the CPU free during the launch
    window when Kit + the web dev server + the browser are all starting."""
    await asyncio.sleep(45.0)
    missing = [p for p in design_presets.PRESETS.values()
               if not (_PREVIEW_DIR / f"{p.id}_{_design_fingerprint(p)}.png").exists()]
    if missing:
        log.info("prewarming %d design preview(s): %s",
                 len(missing), [p.id for p in missing])
    for preset in missing:
        await _preview_path(preset)


@app.get("/designs")
async def http_list_designs():
    """Gallery payload: every preset with derived stats + preview URL, plus
    which design is currently applied ("custom" after manual edits). The
    preview URL carries the cache fingerprint as ?v= so the browser cache
    (Cache-Control max-age) invalidates in lockstep with the disk cache."""
    designs = design_presets.list_summaries()
    for d in designs:
        preset = design_presets.get_preset(d["id"])
        if preset is not None:
            d["preview_url"] += f"?v={_design_fingerprint(preset)}"
    return {"active": engine.design_id, "designs": designs}


@app.post("/designs/{design_id}/apply")
async def http_apply_design(design_id: str):
    """Switch the whole satellite design: config + geometry + workload +
    platform constants, then regenerate the USD (Kit reloads on the version
    bump) and broadcast so every web client re-renders the new numbers."""
    preset = design_presets.get_preset(design_id)
    if preset is None:
        raise HTTPException(404, f"unknown design {design_id!r}")
    engine.apply_design(preset)
    regen_ok = await _regenerate_twin_latest()
    await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
    return {
        "ok": True,
        "design_id": design_id,
        "regenerated": regen_ok,
        "satellite_config": engine.satellite_config.model_dump(),
        "twin_geometry": engine.twin_geometry.model_dump(),
        "workload_profile": engine.workload_profile,
    }


@app.get("/designs/{design_id}/preview.png")
async def http_design_preview(design_id: str):
    preset = design_presets.get_preset(design_id)
    if preset is None:
        raise HTTPException(404, f"unknown design {design_id!r}")
    png = await _preview_path(preset)
    if png is None:
        raise HTTPException(503, "preview render failed — see backend log")
    return FileResponse(png, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})


# --- Workload profiles (workload selector) ---------------------------------
@app.get("/workload_profiles")
async def http_workload_profiles():
    """Every schedule the GPUs can fly, each annotated with how the CURRENT
    design would cope: average demand vs solar supply, thermal peak vs the
    radiator ceiling, a fit verdict, and the expected outputs of one cycle
    (tokens / frames / payload kWh on the fitted GPUs)."""
    import state_engine as _se
    return {
        "active": engine.workload_profile,
        "profiles": [engine.workload_adaptation(pid)
                     for pid in _se._WORKLOAD_PROFILES],
    }


@app.post("/workload_profile")
async def http_set_workload_profile(body: dict[str, Any]):
    """Switch the GPU job schedule. The physics demand side, the design
    checks and the output counters all follow on the next tick; a manual
    switch degrades the active design to 'custom'."""
    profile = str(body.get("profile", ""))
    try:
        applied = engine.set_workload_profile(profile)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
    return {"ok": True, "workload_profile": applied,
            "adaptation": engine.workload_adaptation(applied)}


# --- Orbit designer (Overview page) ----------------------------------------
@app.get("/orbit_design")
async def http_get_orbit_design():
    """The ACTIVE constellation's classical orbital elements + Walker
    parameters — the designer displays these for any preset, then edits
    them into a custom design."""
    preset = (constellations.get_preset(engine.constellation_id)
              or constellations.get_preset("single_iss"))
    return {
        "active": preset.id,
        "name": preset.name,
        "elements": constellations.preset_elements(preset),
        "walker": {"planes": preset.planes,
                   "sats_per_plane": preset.sats_per_plane,
                   "phasing": preset.phasing,
                   "total_sats": preset.total_sats},
    }


@app.post("/orbit_design")
async def http_post_orbit_design(body: dict[str, Any]):
    """Design a constellation from the six classical orbital elements +
    Walker parameters: synthesize the reference TLE, register the design as
    the 'custom_design' preset and make it active — the whole pipeline
    (engine tick, Kit rings, web fallback propagator, coverage map) follows
    on the next poll/broadcast."""
    try:
        preset = constellations.make_custom_preset(
            altitude_km=float(body.get("altitude_km", 550.0)),
            eccentricity=float(body.get("eccentricity", 0.001)),
            inclination_deg=float(body.get("inclination_deg", 53.0)),
            raan_deg=float(body.get("raan_deg", 0.0)) % 360.0,
            arg_perigee_deg=float(body.get("arg_perigee_deg", 0.0)) % 360.0,
            mean_anomaly_deg=float(body.get("mean_anomaly_deg", 0.0)) % 360.0,
            planes=int(body.get("planes", 3)),
            sats_per_plane=int(body.get("sats_per_plane", 8)),
            phasing=int(body.get("phasing", 1)),
        )
    except (TypeError, ValueError) as e:
        raise HTTPException(422, f"invalid orbit design: {e}") from e
    engine.set_constellation(constellations.CUSTOM_ID)
    await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
    return {
        "ok": True,
        "active": preset.id,
        "name": preset.name,
        "elements": constellations.preset_elements(preset),
        "walker": {"planes": preset.planes,
                   "sats_per_plane": preset.sats_per_plane,
                   "phasing": preset.phasing,
                   "total_sats": preset.total_sats},
    }


# --- Ground-station target + communication visibility ----------------------
@app.get("/comms_bands")
async def http_comms_bands():
    """The communication-band catalog: per-band throughput + elevation-mask
    requirement (the Overview config selector + band-comparison curves)."""
    return {
        "default": constellations.DEFAULT_BAND,
        "bands": [{"id": bid, **b} for bid, b in constellations.COMMS_BANDS.items()],
    }


@app.post("/ground_target")
async def http_ground_target(body: Optional[dict[str, Any]] = None):
    """Mark (enabled=true) or clear (enabled=false) the ground station on
    the Earth, with its comms config. Defaults to Singapore / X-band.
    Accepts elevation_mask_deg, band (UHF|S|X|Ka), solar_bin (5|10). While
    marked, every fleet tick computes visibility, the active band's
    aggregate bandwidth, an elevation CDF and a solar histogram — all ride
    StatePacket.ground_target."""
    b = body or {}
    enabled = bool(b.get("enabled", True))
    try:
        gt = engine.set_ground_target(
            enabled,
            name=str(b.get("name", "Singapore")),
            lat=float(b.get("lat", 1.3521)),
            lon=float(b.get("lon", 103.8198)),
            elevation_mask_deg=float(b.get("elevation_mask_deg",
                                           b.get("min_elevation_deg", 10.0))),
            band=str(b.get("band", "X")),
            solar_bin=int(b.get("solar_bin", 10)),
        )
    except (TypeError, ValueError) as e:
        raise HTTPException(422, f"invalid ground target: {e}") from e
    await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
    return {"ok": True,
            "ground_target": gt.model_dump() if gt is not None else None}


@app.get("/ground_visibility")
async def http_ground_visibility(orbits: float = 1.0):
    """Pass analysis for the marked ground station over the ACTIVE
    constellation: sample fleet↔ground elevation across `orbits` orbital
    periods starting NOW, return the visibility series + merged pass
    windows. Blocking fleet propagation runs in a worker thread."""
    gt = engine.ground_target
    if gt is None or not gt.enabled:
        raise HTTPException(422, "no ground target marked — POST /ground_target first")
    preset = (constellations.get_preset(engine.constellation_id)
              or constellations.get_preset("single_iss"))
    orbits = max(0.25, min(3.0, float(orbits)))
    # One real period = period_s/TIME_SCALE sim-seconds at the demo scale.
    duration_sim = preset.period_s / constellations.TIME_SCALE * orbits
    step_sim = max(0.5, duration_sim / 140.0)
    t0 = engine.snapshot().sim_time_s
    result = await asyncio.to_thread(
        constellations.ground_visibility_series,
        preset, gt.lat, gt.lon, t0, duration_sim, step_sim,
        gt.min_elevation_deg, orbit_catalog.eci_to_lat_lon_alt,
    )
    return {
        "target": {"name": gt.name, "lat": gt.lat, "lon": gt.lon,
                   "min_elevation_deg": gt.min_elevation_deg},
        "constellation": preset.id,
        "total_sats": preset.total_sats,
        "period_s_real": round(preset.period_s, 1),
        "duration_s": round(duration_sim, 1),
        "time_scale": constellations.TIME_SCALE,
        **result,
    }


# --- What-if comparison (Twin page Compare panel) --------------------------
@app.get("/compare/options")
async def http_compare_options():
    """Comparable dimensions (every Configurator knob + whole designs), each
    with its choices and the live loadout's current value, plus the metric
    catalog the chart can plot."""
    return compare_sim.options(engine)


@app.post("/compare/start")
async def http_compare_start(body: dict[str, Any]):
    """Start a LIVE what-if comparison: 2–4 variant loadouts seeded from the
    engine's current state, then stepped in lockstep with every 1 Hz physics
    tick. Each variant's current sample rides StatePacket.compare_live, so
    the Twin page's telemetry strip overlays the curves as they evolve and
    diverge in real time. Starting again replaces the running comparison;
    the live satellite and the USD model are never touched."""
    dimension = str(body.get("dimension", ""))
    values = body.get("values")
    # Snapshot + construction both run HERE, on the event loop — the 1 Hz
    # tick runs on this same loop, so the synchronous reads can never
    # interleave with a tick and every variant seeds from the identical
    # instant (same orbit phase / SOC / structure temperature).
    snap = compare_sim.live_snapshot(engine)
    try:
        session = compare_sim.LiveCompareSession(
            snap, dimension, values if isinstance(values, list) else [])
    except compare_sim.CompareError as e:
        raise HTTPException(422, str(e)) from e
    engine.set_compare_session(session)
    await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
    return {"ok": True, "compare_live": session.payload().model_dump()}


@app.post("/compare/stop")
async def http_compare_stop():
    """Stop the live comparison and clear compare_live from the state."""
    engine.set_compare_session(None)
    await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
    return {"ok": True}


@app.post("/solar_deploy")
async def http_solar_deploy(body: Optional[dict[str, Any]] = None):
    """Animate the roll-out solar array — a mock of a flexible blanket
    array unrolling off the bay edges. action: 'deploy' | 'retract' |
    'toggle' (default). The engine slews satellite.solar_deploy_frac 0↔1
    over ~12 s; solar production scales with it and the Kit close-up
    stretches the wings from their root anchors in lockstep."""
    action = str((body or {}).get("action", "toggle"))
    try:
        r = engine.set_solar_deploy(action)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
    return {"ok": True, **r}


@app.post("/attitude_mode")
async def http_attitude_mode(body: Optional[dict[str, Any]] = None):
    """Set the satellite's attitude pointing mode: 'free' (reaction wheels),
    'sun' (panels to the Sun), 'nadir' (payload to Earth), 'velocity' (ram),
    or 'inertial' (fixed). A non-free mode zeroes the wheels; the Kit close-up
    orients the body to the target."""
    mode = str((body or {}).get("mode", "free"))
    try:
        r = engine.set_attitude_mode(mode)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
    return {"ok": True, **r}


@app.post("/attitude_spin")
async def http_attitude_spin(body: Optional[dict[str, Any]] = None):
    """Reaction-wheel demo: toggle a slow 360° rotation of the whole body
    about any centre-of-mass axis. action: 'start' | 'stop' | 'toggle'
    (default); axis: 'x' | 'y' | 'z' (default) — axes combine into a
    tumble. The Kit close-up integrates satellite.attitude_spin_dps per
    frame; physics is untouched (sun-tracking arrays keep their model)."""
    action = str((body or {}).get("action", "toggle"))
    axis = str((body or {}).get("axis", "z"))
    try:
        r = engine.set_attitude_spin(action, axis)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
    return {"ok": True, **r}


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
