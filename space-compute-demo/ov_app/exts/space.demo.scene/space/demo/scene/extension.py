"""space.demo.scene — orchestrator for the Omniverse overview stage.

Stages (swapped via omni.usd.get_context().open_stage()):
    usd/overview.usda  — Earth + TLE-driven orbit ring + moving sat icon
    usd/satellite.usda — DGX close-up (no Earth)
    usd/interior.usda  — data-hall aisle

In the overview stage this extension is responsible for three motions:
  1. Earth self-rotation around +Z, driven from wall-clock sim time
     (independent of backend availability — Earth keeps turning).
  2. Orbit ring geometry — fetched from the backend's /orbits/<mode>
     endpoint (TLE + 128 SGP4 sample points per revolution) and
     rewritten into /World/OrbitGroup/OrbitLine on every orbit_type
     change. The orbit itself is not emissive.
  3. Satellite icon position — interpolated along the cached orbit
     ring using the backend's sim_time and the TLE's revolution period
     (scaled by /orbits' time_scale so a full revolution takes ~90 s
     of wall clock for LEO).
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import time
import urllib.request
from typing import Optional

try:
    import omni.ext  # type: ignore
    import omni.kit.app  # type: ignore
    import omni.usd  # type: ignore
    from pxr import Gf, UsdGeom, Vt  # type: ignore
    _HAS_KIT = True
except ImportError:
    _HAS_KIT = False

try:
    import carb  # type: ignore
    _HAS_CARB = True
except ImportError:
    _HAS_CARB = False


def _log(msg: str) -> None:
    print(f"[space.demo.scene] {msg}", flush=True)
    if _HAS_CARB:
        carb.log_info(f"[space.demo.scene] {msg}")


BACKEND_BASE = os.environ.get("SPACE_DEMO_BACKEND_HTTP", "http://localhost:8001").rstrip("/")
BACKEND_STATE_URL = f"{BACKEND_BASE}/state"
BACKEND_ORBIT_URL = f"{BACKEND_BASE}/orbits/{{mode}}"
POLL_HZ = 5.0

USD_ROOT_ENV = "SPACE_DEMO_USD_ROOT"

# Prim paths inside overview.usda.
EARTH_PATH      = "/World/Earth"
ORBIT_LINE_PATH = "/World/OrbitGroup/OrbitLine"
SAT_ICON_PATH   = "/World/OrbitGroup/SatelliteIcon"

# Scene scale — overview.usda is metersPerUnit = 100000 so 1 unit = 100 km.
SCENE_KM_PER_UNIT = 100.0

# Earth self-rotation period in wall-seconds. Independent of TLE — purely a
# visual choice so the planet's spin is clearly observable in the demo.
EARTH_ROTATION_PERIOD_S = 90.0


def _stage_paths() -> dict[str, str]:
    base = os.environ.get(USD_ROOT_ENV, "C:/Workspace/SpaceDC/space-compute-demo/usd")
    return {
        "overview":  os.path.join(base, "overview.usda"),
        "satellite": os.path.join(base, "satellite.usda"),
        "interior":  os.path.join(base, "interior.usda"),
    }


# ---------------------------------------------------------------------------
# HTTP helpers — backend is the source of truth for both state polling and
# the orbit catalog. urllib (stdlib) because Kit ships no async HTTP client.
# ---------------------------------------------------------------------------
def fetch_state() -> Optional[dict]:
    try:
        with urllib.request.urlopen(BACKEND_STATE_URL, timeout=0.5) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def fetch_orbit_catalog(mode: str) -> Optional[dict]:
    """One-shot fetch of /orbits/<mode>. ~1.5s timeout — orbit changes are rare,
    we can tolerate a brief blocking call inside the poll thread."""
    try:
        url = BACKEND_ORBIT_URL.format(mode=mode)
        with urllib.request.urlopen(url, timeout=1.5) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        _log(f"fetch_orbit_catalog({mode}) failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# USD write helpers.
# ---------------------------------------------------------------------------
def _km_to_units(pt_km: tuple[float, float, float]) -> tuple[float, float, float]:
    return (pt_km[0] / SCENE_KM_PER_UNIT,
            pt_km[1] / SCENE_KM_PER_UNIT,
            pt_km[2] / SCENE_KM_PER_UNIT)


def rebuild_orbit_line(stage, points_units: list[tuple[float, float, float]]) -> bool:
    """Rewrite /World/OrbitGroup/OrbitLine's points + curveVertexCounts so the
    BasisCurves traces one full revolution. Returns True on success."""
    prim = stage.GetPrimAtPath(ORBIT_LINE_PATH)
    if not prim or not prim.IsValid():
        return False
    curves = UsdGeom.BasisCurves(prim)
    if not points_units:
        return False
    # Close the loop visually by repeating the first point at the end. We use
    # "nonperiodic" wrap mode (set in USD) — closing manually is more
    # predictable across Hydra renderers than relying on periodic wrap.
    closed = list(points_units) + [points_units[0]]
    n = len(closed)
    pts = Vt.Vec3fArray([Gf.Vec3f(*p) for p in closed])
    curves.GetPointsAttr().Set(pts)
    curves.GetCurveVertexCountsAttr().Set(Vt.IntArray([n]))
    return True


def set_sat_icon_position(stage, x: float, y: float, z: float) -> None:
    prim = stage.GetPrimAtPath(SAT_ICON_PATH)
    if not prim or not prim.IsValid():
        return
    xform = UsdGeom.Xformable(prim)
    tr = None
    for op in xform.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
            tr = op
            break
    if tr is None:
        tr = xform.AddTranslateOp()
    tr.Set(Gf.Vec3d(x, y, z))


def set_earth_rotation(stage, sim_time_s: float) -> None:
    """Drive /World/Earth's xformOp:rotateZ from wall-clock sim_time."""
    prim = stage.GetPrimAtPath(EARTH_PATH)
    if not prim or not prim.IsValid():
        return
    xform = UsdGeom.Xformable(prim)
    rotZ = None
    for op in xform.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeRotateZ:
            rotZ = op
            break
    if rotZ is None:
        return
    angle_deg = (sim_time_s * 360.0 / EARTH_ROTATION_PERIOD_S) % 360.0
    rotZ.Set(angle_deg)


def interp_along_curve(points_units, t_in_period_s: float, period_s: float):
    """Linear interpolation around an N-sample closed curve where samples are
    uniformly spaced in time. period_s is the *real* (un-scaled) seconds for
    one revolution; t_in_period_s is in the same units."""
    n = len(points_units)
    if n == 0 or period_s <= 0:
        return (0.0, 0.0, 0.0)
    f = (t_in_period_s / period_s) * n
    i0 = int(f) % n
    i1 = (i0 + 1) % n
    a = f - math.floor(f)
    p0 = points_units[i0]
    p1 = points_units[i1]
    return (
        p0[0] + (p1[0] - p0[0]) * a,
        p0[1] + (p1[1] - p0[1]) * a,
        p0[2] + (p1[2] - p0[2]) * a,
    )


# ---------------------------------------------------------------------------
# Stage swap (preset → stage file).
# ---------------------------------------------------------------------------
STAGE_CAMERAS = {
    "overview":  "/World/Cameras/Overview",
    "satellite": "/World/Cameras/Closeup",
    "interior":  "/World/Cameras/Aisle",
}


def _bind_active_camera(cam_path: str) -> None:
    try:
        from omni.kit.viewport.utility import get_active_viewport_window  # type: ignore
        win = get_active_viewport_window()
        if win is not None and hasattr(win, "viewport_api"):
            vp_api = win.viewport_api
            if getattr(vp_api, "camera_path", None) != cam_path:
                vp_api.camera_path = cam_path
                _log(f"bound viewport camera -> {cam_path}")
    except Exception as exc:  # noqa: BLE001
        _log(f"camera bind error ({cam_path}): {exc}")


def swap_stage(path: str, preset: str | None = None) -> bool:
    try:
        omni.usd.get_context().open_stage(path)
        _log(f"opened stage {path}")
        if preset and preset in STAGE_CAMERAS:
            asyncio.ensure_future(_deferred_bind(STAGE_CAMERAS[preset]))
        return True
    except Exception as exc:  # noqa: BLE001
        _log(f"failed to open {path}: {exc}")
        return False


async def _deferred_bind(cam_path: str) -> None:
    app = omni.kit.app.get_app()
    for tick in range(30):
        await app.next_update_async()
        if tick in (3, 10, 20):
            _bind_active_camera(cam_path)


# ---------------------------------------------------------------------------
# Extension.
# ---------------------------------------------------------------------------
if _HAS_KIT:
    class SpaceDemoSceneExtension(omni.ext.IExt):  # type: ignore[misc]
        def on_startup(self, ext_id: str) -> None:
            _log(f"startup {ext_id} polling {BACKEND_STATE_URL}")
            self._running = True
            self._stages = _stage_paths()
            self._current_stage: Optional[str] = self._stages.get("overview")
            self._last_preset: Optional[str] = None
            self._anchor_sim_s: Optional[float] = None
            self._anchor_wall_s: float = time.monotonic()
            self._backend_running: bool = True

            # Earth spin — separate wall-clock anchor, no backend dependency.
            self._earth_anchor_wall_s: float = time.monotonic()
            self._earth_rotation_logged: bool = False

            # Orbit catalog cache. _orbit_mode is the mode currently rendered.
            # _pending_orbit_mode is set when the poll loop notices a change
            # in state.satellite.orbit_type; the poll loop fetches the new
            # catalog asynchronously, stores it, and the next render frame
            # picks it up to rebuild the BasisCurves.
            self._orbit_mode: Optional[str] = None
            self._pending_orbit_mode: Optional[str] = "LEO"  # bootstrap fetch on first tick
            self._orbit_points_units: list[tuple[float, float, float]] = []
            self._orbit_period_s: float = 90.0       # real seconds (not scaled)
            self._orbit_time_scale: float = 60.0
            self._orbit_dirty: bool = False          # set when new points arrived

            self._poll_task: Optional[asyncio.Task] = asyncio.ensure_future(self._run_poll_loop())
            app = omni.kit.app.get_app()
            self._update_sub = app.get_update_event_stream().create_subscription_to_pop(
                self._on_update, name="space.demo.scene.update"
            )

        def on_shutdown(self) -> None:
            _log("shutdown")
            self._running = False
            if self._poll_task and not self._poll_task.done():
                self._poll_task.cancel()
            self._update_sub = None

        # ---- poll loop ----------------------------------------------------
        async def _run_poll_loop(self) -> None:
            app = omni.kit.app.get_app()
            dt = 1.0 / POLL_HZ
            # Wait for the first stage to settle.
            for _ in range(30):
                await app.next_update_async()
            while self._running:
                # Backend state poll.
                try:
                    state = await asyncio.to_thread(fetch_state)
                    if state is not None:
                        self._on_poll(state)
                except Exception as exc:  # noqa: BLE001
                    _log(f"poll error: {exc}")

                # Orbit catalog fetch — only when a mode change is pending.
                if self._pending_orbit_mode is not None:
                    pending = self._pending_orbit_mode
                    cat = await asyncio.to_thread(fetch_orbit_catalog, pending)
                    if cat is not None:
                        try:
                            pts_km = cat.get("points_km", [])
                            pts_units = [_km_to_units(tuple(p)) for p in pts_km]
                            if pts_units:
                                self._orbit_points_units = pts_units
                                self._orbit_period_s = float(cat.get("period_s", 5574.0))
                                self._orbit_time_scale = float(cat.get("time_scale", 60.0))
                                self._orbit_mode = pending
                                self._orbit_dirty = True
                                _log(f"orbit catalog cached: {pending} "
                                     f"({len(pts_units)} pts, period={self._orbit_period_s:.0f}s, "
                                     f"scale=x{self._orbit_time_scale:.0f})")
                        except Exception as exc:  # noqa: BLE001
                            _log(f"orbit catalog parse error: {exc}")
                    # Clear pending whether successful or not — next state poll
                    # that still disagrees will set it again.
                    if self._pending_orbit_mode == pending:
                        self._pending_orbit_mode = None

                await asyncio.sleep(dt)

        def _on_poll(self, state: dict) -> None:
            backend_sim = float(state.get("sim_time_s", 0.0))
            backend_running = bool(state.get("running", True))

            local_sim = (
                self._anchor_sim_s + (time.monotonic() - self._anchor_wall_s)
                if self._anchor_sim_s is not None
                else None
            )
            needs_resync = (
                self._anchor_sim_s is None
                or self._backend_running != backend_running
                or (local_sim is not None and abs(backend_sim - local_sim) > 1.5)
            )
            if needs_resync:
                self._anchor_sim_s = backend_sim
                self._anchor_wall_s = time.monotonic()
            self._backend_running = backend_running

            # Stage preset.
            preset = state.get("camera_preset", "overview")
            if preset not in ("overview", "satellite", "interior"):
                preset = "overview"
            if preset != self._last_preset:
                _log(f"preset -> {preset}")
                self._last_preset = preset
                target = self._stages.get(preset)
                if target and target != self._current_stage:
                    if swap_stage(target, preset):
                        self._current_stage = target

            # Orbit mode change detection.
            sat = state.get("satellite") or {}
            new_mode = sat.get("orbit_type")
            if new_mode and new_mode != self._orbit_mode and new_mode != self._pending_orbit_mode:
                _log(f"orbit mode change requested: {self._orbit_mode} -> {new_mode}")
                self._pending_orbit_mode = new_mode

        # ---- per-frame update --------------------------------------------
        def _on_update(self, _event) -> None:
            if self._current_stage != self._stages.get("overview"):
                return
            ctx = omni.usd.get_context()
            stage = ctx.get_stage()
            if stage is None:
                return

            # Earth spin — wall clock, never gated on the backend.
            earth_sim_s = time.monotonic() - self._earth_anchor_wall_s
            set_earth_rotation(stage, earth_sim_s)
            if not self._earth_rotation_logged:
                _log("earth rotation driver tick — overview stage active")
                self._earth_rotation_logged = True

            # Rebuild orbit ring if a new catalog landed since last frame.
            if self._orbit_dirty:
                if rebuild_orbit_line(stage, self._orbit_points_units):
                    _log(f"orbit line rebuilt: mode={self._orbit_mode} "
                         f"({len(self._orbit_points_units)} verts)")
                self._orbit_dirty = False

            # Drive the satellite icon along the cached orbit. We need
            # backend sim_time so the position stays consistent across
            # restarts; if backend isn't up yet, park the icon at points[0].
            if not self._orbit_points_units:
                return
            if self._anchor_sim_s is None:
                p0 = self._orbit_points_units[0]
                set_sat_icon_position(stage, *p0)
                return

            sim_now = self._anchor_sim_s + (
                (time.monotonic() - self._anchor_wall_s) if self._backend_running else 0.0
            )
            scaled = sim_now * self._orbit_time_scale
            t_in_period = scaled % self._orbit_period_s
            x, y, z = interp_along_curve(
                self._orbit_points_units, t_in_period, self._orbit_period_s
            )
            set_sat_icon_position(stage, x, y, z)
else:
    class SpaceDemoSceneExtension:  # type: ignore[no-redef]
        pass
