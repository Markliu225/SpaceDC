"""space.demo.scene — two-stage orchestrator.

Stages:
    usd/overview.usda  — Earth + orbit line + moving cyan SatelliteIcon
    usd/satellite.usda — standalone DGX close-up (no Earth)

On preset change we call ``omni.usd.get_context().open_stage()`` to swap
the active stage. Keeps the two scenes fully decoupled.

In the overview stage we update /World/SatelliteIcon's translation every
render frame using the SAME circular-orbit formula the backend uses, so
the icon rides exactly along the orbit line.
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
    from pxr import Gf, UsdGeom  # type: ignore
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


BACKEND_URL = os.environ.get("SPACE_DEMO_BACKEND_HTTP", "http://localhost:8001/state")
POLL_HZ = 5.0

ORBIT_RADIUS_UNITS = 69.21
ORBIT_INCLINATION_RAD = math.radians(60.0)
ORBIT_PERIOD_S = 90.0

# Earth self-rotation — same period as the demo orbit so a full rev fits
# the wall-clock cadence. Sun is fixed in world space, so spinning the
# planet sweeps every longitude through the day/night cycle.
EARTH_ROTATION_PERIOD_S = 90.0
EARTH_PATH = "/World/Earth"

USD_ROOT_ENV = "SPACE_DEMO_USD_ROOT"
SAT_ICON_PATH = "/World/SatelliteIcon"


def _stage_paths() -> dict[str, str]:
    base = os.environ.get(USD_ROOT_ENV, "C:/Workspace/SpaceDC/space-compute-demo/usd")
    return {
        "overview":  os.path.join(base, "overview.usda"),
        "satellite": os.path.join(base, "satellite.usda"),
        "interior":  os.path.join(base, "interior.usda"),
    }


def _orbit_xyz(sim_time_s: float) -> tuple[float, float, float]:
    theta = 2.0 * math.pi * sim_time_s / ORBIT_PERIOD_S
    cos_a = math.cos(ORBIT_INCLINATION_RAD)
    sin_a = math.sin(ORBIT_INCLINATION_RAD)
    return (
        ORBIT_RADIUS_UNITS * math.cos(theta),
        ORBIT_RADIUS_UNITS * math.sin(theta) * cos_a,
        ORBIT_RADIUS_UNITS * math.sin(theta) * sin_a,
    )


def fetch_state() -> Optional[dict]:
    try:
        with urllib.request.urlopen(BACKEND_URL, timeout=0.5) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def set_icon_position(stage, x: float, y: float, z: float) -> None:
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
    """Drive /World/Earth's xformOp:rotateZ from wall-clock sim_time so the
    planet spins smoothly even when Kit's USD timeline is stopped. The
    rotateZ op is declared in overview.usda's `over "Earth"` — if it's not
    present (e.g. a different stage is open) we just no-op."""
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


STAGE_CAMERAS = {
    "overview":  "/World/Cameras/Overview",
    "satellite": "/World/Cameras/Closeup",
    "interior":  "/World/Cameras/Aisle",
}


def _bind_active_camera(cam_path: str) -> None:
    """Force the viewport to use cam_path. Kit doesn't always honor
    customLayerData.cameraSettings.boundCamera on stage re-open."""
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
            # Defer the camera bind a few frames so the new stage is fully live
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


if _HAS_KIT:
    class SpaceDemoSceneExtension(omni.ext.IExt):  # type: ignore[misc]
        def on_startup(self, ext_id: str) -> None:
            _log(f"startup {ext_id} polling {BACKEND_URL}")
            self._running = True
            self._stages = _stage_paths()
            self._current_stage: Optional[str] = self._stages.get("overview")
            self._last_preset: Optional[str] = None
            self._anchor_sim_s: Optional[float] = None
            self._anchor_wall_s: float = time.monotonic()
            self._backend_running: bool = True

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

        async def _run_poll_loop(self) -> None:
            app = omni.kit.app.get_app()
            dt = 1.0 / POLL_HZ
            for _ in range(30):
                await app.next_update_async()
            while self._running:
                try:
                    state = await asyncio.to_thread(fetch_state)
                    if state is not None:
                        self._on_poll(state)
                except Exception as exc:  # noqa: BLE001
                    _log(f"poll error: {exc}")
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

        def _on_update(self, _event) -> None:
            if self._current_stage != self._stages.get("overview"):
                return
            if self._anchor_sim_s is None:
                return
            ctx = omni.usd.get_context()
            stage = ctx.get_stage()
            if stage is None:
                return
            sim_now = self._anchor_sim_s + (
                (time.monotonic() - self._anchor_wall_s) if self._backend_running else 0.0
            )
            x, y, z = _orbit_xyz(sim_now)
            set_icon_position(stage, x, y, z)
            set_earth_rotation(stage, sim_now)
else:
    class SpaceDemoSceneExtension:  # type: ignore[no-redef]
        pass
