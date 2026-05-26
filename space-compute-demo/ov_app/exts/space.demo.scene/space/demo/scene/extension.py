"""space.demo.scene — orchestrator for the Omniverse overview stage.

Three motions in the overview stage:
  1. Earth self-rotation around +Z (wall-clock, backend-independent).
  2. Constellation rings — one BasisCurves per orbital plane, rebuilt
     whenever the active preset changes.
  3. Fleet positions — every sat's ECI point written into a UsdGeom.Points
     prim each frame, derived from the cached base ring + per-sat Walker
     phase offsets (no SGP4 in Kit).

The backend's /constellations/{id} endpoint returns the base orbit ring
(128 ECI km samples for plane 0 / sat 0) and the Walker params. From
those everything else is derived in Kit:
  * Ring K = base ring rotated about +Z by k × 360°/P.
  * Sat (k, j) at sim_t = ring point at phase
        (sim_t × time_scale × 360° / period
         + j × 360° / sats_per_plane
         + k × phasing × 360° / total) mod 360°
    interpolated linearly along the (rotated) ring.
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
    from pxr import Gf, Sdf, UsdGeom, Vt  # type: ignore
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
BACKEND_STATE_URL          = f"{BACKEND_BASE}/state"
BACKEND_CONSTELLATION_URL  = f"{BACKEND_BASE}/constellations/{{id}}"
POLL_HZ = 5.0

USD_ROOT_ENV = "SPACE_DEMO_USD_ROOT"

# Prim paths.
EARTH_PATH       = "/World/Earth"
CONSTEL_ROOT     = "/World/ConstellationGroup"
RINGS_ROOT       = f"{CONSTEL_ROOT}/Rings"
FLEET_POINTS     = f"{CONSTEL_ROOT}/Fleet"
FLEET_MAT        = f"{CONSTEL_ROOT}/Fleet/Mat"

# Scene scale — overview.usda is metersPerUnit = 100000 so 1 unit = 100 km.
SCENE_KM_PER_UNIT = 100.0

EARTH_ROTATION_PERIOD_S = 90.0

# Ring palette — 6 hues, cycled per orbital plane. Matches the Web Three.js
# fallback's `tokens.colors.ribbons` (magenta / cyan / amber / emerald /
# violet / rose) so the constellation looks identical in both views.
RING_HUES: list[tuple[float, float, float]] = [
    (0.91, 0.47, 0.98),  # E879F9 magenta
    (0.13, 0.83, 0.93),  # 22D3EE cyan
    (0.98, 0.75, 0.14),  # FBBF24 amber
    (0.20, 0.83, 0.60),  # 34D399 emerald
    (0.65, 0.55, 0.98),  # A78BFA violet
    (0.98, 0.44, 0.52),  # FB7185 rose
]


def _stage_paths() -> dict[str, str]:
    base = os.environ.get(USD_ROOT_ENV, "C:/Workspace/SpaceDC/space-compute-demo/usd")
    return {
        "overview":  os.path.join(base, "overview.usda"),
        "satellite": os.path.join(base, "satellite.usda"),
        "interior":  os.path.join(base, "interior.usda"),
    }


# ---------------------------------------------------------------------------
# HTTP helpers.
# ---------------------------------------------------------------------------
def fetch_state() -> Optional[dict]:
    try:
        with urllib.request.urlopen(BACKEND_STATE_URL, timeout=0.5) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def fetch_constellation(preset_id: str) -> Optional[dict]:
    """One-shot fetch of /constellations/{id}. The response includes the
    base orbit ring (128 ECI km samples) + Walker params we need to lay
    out the whole fleet."""
    try:
        url = BACKEND_CONSTELLATION_URL.format(id=preset_id)
        with urllib.request.urlopen(url, timeout=2.0) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        _log(f"fetch_constellation({preset_id}) failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# USD authoring.
# ---------------------------------------------------------------------------
def _km_to_units(p: tuple[float, float, float]) -> tuple[float, float, float]:
    return (p[0] / SCENE_KM_PER_UNIT, p[1] / SCENE_KM_PER_UNIT, p[2] / SCENE_KM_PER_UNIT)


def _rotate_z(pt: tuple[float, float, float], angle_rad: float) -> tuple[float, float, float]:
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    x, y, z = pt
    return (c * x - s * y, s * x + c * y, z)


def rebuild_constellation(
    stage,
    base_ring_units: list[tuple[float, float, float]],
    planes: int,
    sats_per_plane: int,
    phasing: int,
) -> bool:
    """Author P rings under /Rings + initial Walker positions in /Fleet."""
    rings_prim = stage.GetPrimAtPath(RINGS_ROOT)
    if not rings_prim or not rings_prim.IsValid():
        _log(f"rebuild_constellation: missing {RINGS_ROOT}")
        return False
    fleet_prim = stage.GetPrimAtPath(FLEET_POINTS)
    if not fleet_prim or not fleet_prim.IsValid():
        _log(f"rebuild_constellation: missing {FLEET_POINTS}")
        return False

    # 1. Tear down any existing ring children.
    for child in list(rings_prim.GetChildren()):
        stage.RemovePrim(child.GetPath())

    if not base_ring_units:
        _log("rebuild_constellation: empty base ring")
        return False
    n_pts = len(base_ring_units)

    planes = max(1, int(planes))
    sats_per_plane = max(1, int(sats_per_plane))
    total_sats = planes * sats_per_plane

    # 3. Author 6 ring materials (one per hue) under /Rings, reusable
    #    across planes. Then author P plane rings, each bound to
    #    RingMat_(k % 6) so successive planes cycle through the palette.
    ring_mat_paths = [
        Sdf.Path(f"{RINGS_ROOT}/RingMat_{i}") for i in range(len(RING_HUES))
    ]
    for i, mp in enumerate(ring_mat_paths):
        if not stage.GetPrimAtPath(mp):
            _author_ring_material(stage, mp, RING_HUES[i])
    for k in range(planes):
        angle = k * 2.0 * math.pi / planes
        pts_rot = [_rotate_z(p, angle) for p in base_ring_units]
        closed = pts_rot + [pts_rot[0]]
        ring_path = Sdf.Path(f"{RINGS_ROOT}/Ring_{k:03d}")
        curves = UsdGeom.BasisCurves.Define(stage, ring_path)
        curves.GetTypeAttr().Set("linear")
        curves.GetWrapAttr().Set("nonperiodic")
        curves.GetCurveVertexCountsAttr().Set(Vt.IntArray([len(closed)]))
        curves.GetPointsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*p) for p in closed]))
        curves.CreateWidthsAttr(Vt.FloatArray([0.3])).SetMetadata("interpolation", "constant")
        hue_idx = k % len(RING_HUES)
        # displayColor primvar matches the bound material's diffuse so
        # the legacy Hydra path still draws something even if MDL isn't
        # available; the bound MDL material wins when it is.
        UsdGeom.PrimvarsAPI(curves).CreatePrimvar(
            "displayColor", Sdf.ValueTypeNames.Color3fArray,
            interpolation="constant",
        ).Set(Vt.Vec3fArray([Gf.Vec3f(*RING_HUES[hue_idx])]))
        # Rings are decorative — they MUST NOT cast shadows on the Earth.
        # Without this primvar the thin BasisCurves drop a faint band across
        # the surface every time the sun grazes them.
        curves.GetPrim().CreateAttribute(
            "primvars:doNotCastShadows", Sdf.ValueTypeNames.Bool,
            custom=False,
        ).Set(True)
        _bind_material(stage, curves.GetPrim(), ring_mat_paths[hue_idx])
    _log(f"authored {planes} ring(s) under {RINGS_ROOT} (palette of {len(RING_HUES)} hues)")

    # 4. Initial fleet positions (sim_t=0) — the per-frame driver overwrites
    # this; we set something sensible so the points appear immediately even
    # before the first _on_update tick.
    positions = compute_fleet_positions(base_ring_units, planes, sats_per_plane, phasing, sim_phase_rad=0.0)
    _set_fleet_points(stage, positions)

    _log(f"fleet authored: {total_sats} sats ({n_pts}-pt base ring)")
    return True


def _author_ring_material(stage, path: Sdf.Path, hue: tuple[float, float, float]) -> None:
    """UsdPreviewSurface for one orbit ring at the given hue. Diffuse picks
    up sun + ambient; a small same-hue emissive keeps the line readable on
    the night side without making the orbit itself look like a light source."""
    from pxr import UsdShade  # type: ignore
    mat = UsdShade.Material.Define(stage, path)
    sh = UsdShade.Shader.Define(stage, Sdf.Path(f"{path}/Shader"))
    sh.CreateIdAttr("UsdPreviewSurface")
    sh.CreateInput("diffuseColor",  Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*hue))
    # Emissive at ~45% of the hue colour — strong enough that the line's
    # tint is unambiguous against the dim sky on the night side, but well
    # below 1.0 so the orbit doesn't visually compete with the warm-white
    # satellite dots.
    sh.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(
        Gf.Vec3f(hue[0] * 0.45, hue[1] * 0.45, hue[2] * 0.45)
    )
    sh.CreateInput("metallic",      Sdf.ValueTypeNames.Float).Set(0.0)
    sh.CreateInput("roughness",     Sdf.ValueTypeNames.Float).Set(1.0)
    sh.CreateInput("useSpecularWorkflow", Sdf.ValueTypeNames.Int).Set(0)
    mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")


def _bind_material(stage, prim, mat_path: Sdf.Path) -> None:
    from pxr import UsdShade  # type: ignore
    mat_prim = stage.GetPrimAtPath(mat_path)
    if not mat_prim or not mat_prim.IsValid():
        return
    UsdShade.MaterialBindingAPI.Apply(prim).Bind(UsdShade.Material(mat_prim))


def compute_fleet_positions(
    base_ring_units: list[tuple[float, float, float]],
    planes: int,
    sats_per_plane: int,
    phasing: int,
    sim_phase_rad: float,
) -> list[tuple[float, float, float]]:
    """Walker layout. Each sat sits at a phase offset along its plane's
    (rotated) base ring. `sim_phase_rad` advances every frame so the whole
    fleet drifts in sync without per-sat propagation."""
    n = len(base_ring_units)
    total = planes * sats_per_plane
    positions: list[tuple[float, float, float]] = []
    for k in range(planes):
        plane_angle = k * 2.0 * math.pi / planes
        for j in range(sats_per_plane):
            walker_phase = (
                sim_phase_rad
                + j * 2.0 * math.pi / sats_per_plane
                + k * phasing * 2.0 * math.pi / total
            )
            # Sample base ring at that phase.
            t = (walker_phase % (2.0 * math.pi)) / (2.0 * math.pi)
            f = t * n
            i0 = int(f) % n
            i1 = (i0 + 1) % n
            a = f - math.floor(f)
            p0 = base_ring_units[i0]
            p1 = base_ring_units[i1]
            lerped = (
                p0[0] + (p1[0] - p0[0]) * a,
                p0[1] + (p1[1] - p0[1]) * a,
                p0[2] + (p1[2] - p0[2]) * a,
            )
            positions.append(_rotate_z(lerped, plane_angle))
    return positions


def _set_fleet_points(stage, positions: list[tuple[float, float, float]]) -> None:
    prim = stage.GetPrimAtPath(FLEET_POINTS)
    if not prim or not prim.IsValid():
        return
    pts = UsdGeom.Points(prim)
    pts.GetPointsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*p) for p in positions]))


def set_earth_rotation(stage, sim_time_s: float) -> None:
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


# ---------------------------------------------------------------------------
# Stage swap.
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

            # Earth spin — separate wall-clock anchor.
            self._earth_anchor_wall_s: float = time.monotonic()
            self._earth_rotation_logged: bool = False

            # Constellation cache.
            self._constellation_id: Optional[str] = None
            self._pending_constellation: Optional[str] = "single_iss"   # bootstrap
            self._base_ring_units: list[tuple[float, float, float]] = []
            self._planes: int = 1
            self._sats_per_plane: int = 1
            self._phasing: int = 0
            self._period_s: float = 5574.0
            self._time_scale: float = 60.0
            self._constellation_dirty: bool = False

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
            for _ in range(30):
                await app.next_update_async()
            while self._running:
                # Backend state poll — detects constellation/preset changes.
                try:
                    state = await asyncio.to_thread(fetch_state)
                    if state is not None:
                        self._on_poll(state)
                except Exception as exc:  # noqa: BLE001
                    _log(f"poll error: {exc}")

                # Constellation catalog fetch.
                if self._pending_constellation is not None:
                    pending = self._pending_constellation
                    detail = await asyncio.to_thread(fetch_constellation, pending)
                    if detail is not None:
                        try:
                            pts_km = detail.get("ring_eci_km", [])
                            if pts_km:
                                self._base_ring_units = [_km_to_units(tuple(p)) for p in pts_km]
                                self._planes         = int(detail.get("planes", 1))
                                self._sats_per_plane = int(detail.get("sats_per_plane", 1))
                                self._phasing        = int(detail.get("phasing", 0))
                                self._period_s       = float(detail.get("period_s", 5574.0))
                                self._time_scale     = float(detail.get("time_scale", 60.0))
                                self._constellation_id = pending
                                self._constellation_dirty = True
                                _log(f"constellation cached: {pending} "
                                     f"({self._planes}p × {self._sats_per_plane}s, "
                                     f"period={self._period_s:.0f}s, scale=x{self._time_scale:.0f})")
                        except Exception as exc:  # noqa: BLE001
                            _log(f"constellation parse error: {exc}")
                    if self._pending_constellation == pending:
                        self._pending_constellation = None

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

            # Camera preset / stage swap.
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

            # Constellation change detection.
            constel = state.get("constellation") or {}
            cid = constel.get("constellation_id")
            if cid and cid != self._constellation_id and cid != self._pending_constellation:
                _log(f"constellation change requested: {self._constellation_id} -> {cid}")
                self._pending_constellation = cid

        # ---- per-frame update --------------------------------------------
        def _on_update(self, _event) -> None:
            if self._current_stage != self._stages.get("overview"):
                return
            ctx = omni.usd.get_context()
            stage = ctx.get_stage()
            if stage is None:
                return

            # Earth spin — wall-clock, unaffected by backend.
            earth_sim_s = time.monotonic() - self._earth_anchor_wall_s
            set_earth_rotation(stage, earth_sim_s)
            if not self._earth_rotation_logged:
                _log("earth rotation driver tick — overview stage active")
                self._earth_rotation_logged = True

            # Constellation rebuild on first cache or any switch.
            if self._constellation_dirty and self._base_ring_units:
                rebuild_constellation(
                    stage, self._base_ring_units,
                    self._planes, self._sats_per_plane, self._phasing,
                )
                self._constellation_dirty = False

            # Per-frame fleet position update.
            if not self._base_ring_units or self._anchor_sim_s is None:
                return
            sim_now = self._anchor_sim_s + (
                (time.monotonic() - self._anchor_wall_s) if self._backend_running else 0.0
            )
            sim_phase_rad = (sim_now * self._time_scale * 2.0 * math.pi / self._period_s) % (2.0 * math.pi)
            positions = compute_fleet_positions(
                self._base_ring_units, self._planes, self._sats_per_plane, self._phasing,
                sim_phase_rad=sim_phase_rad,
            )
            _set_fleet_points(stage, positions)
else:
    class SpaceDemoSceneExtension:  # type: ignore[no-redef]
        pass
