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
    from pxr import Gf, Sdf, Usd, UsdGeom, Vt  # type: ignore
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


# 127.0.0.1, NOT localhost: Windows resolves localhost through an IPv6
# attempt first, costing ~0.2 s per request — at a 5 Hz poll that both
# throttles the loop and makes the eased orbital motion visibly lumpy.
BACKEND_BASE = os.environ.get("SPACE_DEMO_BACKEND_HTTP", "http://127.0.0.1:8001").rstrip("/")
BACKEND_STATE_URL          = f"{BACKEND_BASE}/state"
BACKEND_CONSTELLATION_URL  = f"{BACKEND_BASE}/constellations/{{id}}"
BACKEND_SAT_CONFIG_URL     = f"{BACKEND_BASE}/satellite_config"
POLL_HZ = 5.0

# Prim paths for the Twin page's swappable hardware (defined in
# usd/twin_satellite.usda). Each tuple is (prim_path, list_of_variant_sets).
# Currently only the body's built-in Panel subset recolours via the Bus
# solar_material variant — the procedural wings/radiators were removed
# pending a richer articulated model. Missing prims are skipped, so this
# list can grow again when that model lands.
SAT_VARIANT_TARGETS = [
    ("/World/Satellite/Bus", ("solar_material", "solar_size")),
]

# Satellite-stage lights authored in usd/satellite.usda. The sun-side
# lights (Key, Rim) and the earthshine bounce all scale with the backend's
# satellite.sun_factor so the body genuinely darkens in eclipse instead of
# staying washed-out by static fills. Each entry: (path, min, max) intensity.
SUN_LIGHT_PATH = "/World/Environment/Key"
# Twin-stage orbital context (usd/twin_satellite.usda /World/Celestial):
# the Earth sphere rotates with the live sub-satellite point and the visible
# sun disk + Key light sweep the zenith→sun angle — see update_twin_orbit.
TWIN_EARTH_PATH  = "/World/Celestial/Earth"
TWIN_SUN_PATH    = "/World/Celestial/Sun"
TWIN_SUN_DIST_CM = 50000.0   # mirrors gen_twin_satellite.SUN_DIST_CM
# Roll-out solar-array driver (redwire architecture only): the wings
# stretch from their deck-edge root with satellite.solar_deploy_frac —
# scaleY = f about the root pivot, i.e. translateY = ±ROOT·(1−f).
TWIN_WING_PATHS  = ("/World/Satellite/SolarArray/WingPosY",
                    "/World/Satellite/SolarArray/WingNegY")
TWIN_WING_ROOT_U = 0.71      # mirrors gen_twin_satellite.REDWIRE_WING_Y0
SUN_DRIVEN_LIGHTS = [
    # ONE blinding key with hard contrast — the space look. Low eclipse
    # floor: the dark side is genuinely dark; the static fills
    # (satellite.usda, 550/320) keep the silhouette barely readable.
    ("/World/Environment/Key",         250.0, 5200.0),
    # Subtle sun-side specular rim — an edge, not a second key.
    ("/World/Environment/Rim",         120.0, 800.0),
    # Faint blue earthshine from the planet below (−Z) — the only real
    # secondary source in LEO.
    ("/World/Environment/EarthBounce", 350.0, 950.0),
]

USD_ROOT_ENV = "SPACE_DEMO_USD_ROOT"

# Prim paths.
EARTH_PATH       = "/World/Earth"
CONSTEL_ROOT     = "/World/ConstellationGroup"
RINGS_ROOT       = f"{CONSTEL_ROOT}/Rings"
FLEET_POINTS     = f"{CONSTEL_ROOT}/Fleet"
FLEET_MAT        = f"{CONSTEL_ROOT}/Fleet/Mat"

# Scene scale — overview.usda is metersPerUnit = 100000 so 1 unit = 100 km.
SCENE_KM_PER_UNIT = 100.0
# Earth radius in scene units (6371 km / 100). Used to place the AOI +
# ground station markers on the surface for the 天数天算 mission.
EARTH_RADIUS_UNITS = 63.71

# 天数天算 mission choreography prims (authored at runtime under World).
MISSION_GROUP  = "/World/MissionGroup"
MISSION_LOOKS  = f"{MISSION_GROUP}/Looks"
MISSION_AOI    = f"{MISSION_GROUP}/AOI"
MISSION_PACKET = f"{MISSION_GROUP}/Packet"
MISSION_ISL    = f"{MISSION_GROUP}/ISLBeam"
MISSION_GSL    = f"{MISSION_GROUP}/GSLBeam"
# Hero satellite models for the two sats in the task (sensor + compute hub).
# The rest of the fleet stays as cheap Points; only these two render as the
# detailed Satellite_v022 body so the close-up shots show a real spacecraft.
MISSION_SENSOR_SAT = f"{MISSION_GROUP}/SensorSat"
MISSION_HUB_SAT    = f"{MISSION_GROUP}/HubSat"
# Satellite_v022 raw extent is ~168 (mm-space coords) which compose as-is
# into the 100 km/unit overview stage. Scale to ~5 units (~500 km — same
# deliberate over-scale as the 0.7-unit fleet points so it reads at orbit
# distance).
HERO_SAT_SCALE = 0.03
# Cinematic mission camera (authored at runtime on the overview stage).
MISSION_CAM    = "/World/Cameras/MissionCam"
# Packet widths (scene units) — big = raw 5 GB capture, small = 2 MB result.
# Sized for visibility against the ~64-unit Earth radius in the overview cam.
PACKET_BIG  = 7.0
PACKET_SMALL = 1.6

# Camera choreography. Close-up shots sit CAM_CLOSE_DIST units off the subject
# along CAM_OFFSET_DIR; the wide "downlink" shot pulls back to CAM_GLOBAL_EYE.
CAM_CLOSE_DIST = 22.0
CAM_OFFSET_DIR = (0.52, -0.52, 0.42)   # subject → camera direction (normalised below)
CAM_GLOBAL_EYE = (180.0, -180.0, 120.0)
CAM_LERP = 0.10   # per-frame easing toward the desired pose (dolly feel)

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
        "mission":   os.path.join(base, "mission.usda"),
    }


def _hero_sat_asset() -> str:
    """Absolute path to the Satellite_v022 body used for the mission hero
    sats (forward slashes so USD's asset resolver is happy on Windows)."""
    base = os.environ.get(USD_ROOT_ENV, "C:/Workspace/SpaceDC/space-compute-demo/usd")
    return os.path.join(base, "assets", "Satellite_v022.usdc").replace("\\", "/")


# ---------------------------------------------------------------------------
# HTTP helpers.
# ---------------------------------------------------------------------------
def fetch_state() -> Optional[dict]:
    try:
        with urllib.request.urlopen(BACKEND_STATE_URL, timeout=0.5) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def post_backend(path: str) -> bool:
    """Fire-and-forget POST to the backend (e.g. /mission/scene_ready)."""
    try:
        req = urllib.request.Request(f"{BACKEND_BASE}{path}", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=0.5):
            return True
    except Exception:
        return False


def _stage_loading_done() -> tuple[bool, str]:
    """Best-effort 'is the open stage fully resident' check for the load gate.
    get_stage_loading_status() returns (message, files_loaded, files_loading);
    done when nothing is still loading. Returns (done, debug_string)."""
    try:
        st = omni.usd.get_context().get_stage_loading_status()
        if isinstance(st, (tuple, list)) and len(st) >= 3:
            return (int(st[2]) == 0, str(st))
        return (True, str(st))
    except Exception as exc:  # noqa: BLE001
        return (True, f"err:{exc}")


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


def fetch_satellite_config() -> Optional[dict]:
    """Pulls the current hardware loadout. Returns None if backend offline."""
    try:
        with urllib.request.urlopen(BACKEND_SAT_CONFIG_URL, timeout=0.5) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
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
# 天数天算 mission choreography.
# ---------------------------------------------------------------------------
def _latlon_to_units(lat_deg: float, lon_deg: float, radius: float) -> tuple[float, float, float]:
    """Lat/lon (deg) → ECI-frame point on a sphere of the given radius
    (scene units). Not Earth-rotation-coupled — the markers are abstract
    glow points, and the data-flow beams read fine without texture lock."""
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    return (
        radius * math.cos(lat) * math.cos(lon),
        radius * math.cos(lat) * math.sin(lon),
        radius * math.sin(lat),
    )


def _author_emissive_material(stage, path: "Sdf.Path", color: tuple[float, float, float]) -> None:
    from pxr import UsdShade  # type: ignore
    mat = UsdShade.Material.Define(stage, path)
    sh = UsdShade.Shader.Define(stage, Sdf.Path(f"{path}/Shader"))
    sh.CreateIdAttr("UsdPreviewSurface")
    sh.CreateInput("diffuseColor",  Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0, 0, 0))
    sh.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    sh.CreateInput("metallic",      Sdf.ValueTypeNames.Float).Set(0.0)
    sh.CreateInput("roughness",     Sdf.ValueTypeNames.Float).Set(1.0)
    sh.CreateInput("useSpecularWorkflow", Sdf.ValueTypeNames.Int).Set(0)
    mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")


def _set_visibility(prim, visible: bool) -> None:
    if prim and prim.IsValid():
        UsdGeom.Imageable(prim).GetVisibilityAttr().Set(
            "inherited" if visible else "invisible"
        )


def _place_hero_sat(stage, path: str, pos, visible: bool, spin_deg: float = 0.0) -> None:
    """Move a hero-sat model to `pos` (scene units) and toggle visibility.
    The scale op stays baked; we only update translate (+ optional spin)."""
    prim = stage.GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        return
    xform = UsdGeom.Xformable(prim)
    for op in xform.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
            op.Set(Gf.Vec3d(float(pos[0]), float(pos[1]), float(pos[2])))
            break
    _set_visibility(prim, visible)


def author_mission_prims(stage) -> bool:
    """Create /World/MissionGroup (AOI · Packet · ISL/GSL beams) once. The
    group starts invisible; the per-frame driver shows it while a mission
    runs. Idempotent — skips if already authored."""
    if not _HAS_KIT or stage is None:
        return False
    if stage.GetPrimAtPath(MISSION_GROUP).IsValid():
        return True

    UsdGeom.Xform.Define(stage, Sdf.Path(MISSION_GROUP))

    # Materials: amber AOI, warm-white packet, cyan ISL, green GSL.
    _author_emissive_material(stage, Sdf.Path(f"{MISSION_LOOKS}/AOIMat"),    (1.60, 0.95, 0.20))
    _author_emissive_material(stage, Sdf.Path(f"{MISSION_LOOKS}/PacketMat"), (0.30, 1.80, 2.20))
    _author_emissive_material(stage, Sdf.Path(f"{MISSION_LOOKS}/ISLMat"),    (0.20, 1.40, 2.40))
    _author_emissive_material(stage, Sdf.Path(f"{MISSION_LOOKS}/GSLMat"),    (0.30, 1.80, 0.60))

    # AOI — a single fat point on the Earth surface.
    aoi = UsdGeom.Points.Define(stage, Sdf.Path(MISSION_AOI))
    aoi.GetPointsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(0, 0, EARTH_RADIUS_UNITS)]))
    aoi.CreateWidthsAttr(Vt.FloatArray([6.0])).SetMetadata("interpolation", "vertex")
    aoi.GetPrim().CreateAttribute("primvars:doNotCastShadows", Sdf.ValueTypeNames.Bool, custom=False).Set(True)
    _bind_material(stage, aoi.GetPrim(), Sdf.Path(f"{MISSION_LOOKS}/AOIMat"))

    # Packet — the travelling data blob.
    pkt = UsdGeom.Points.Define(stage, Sdf.Path(MISSION_PACKET))
    pkt.GetPointsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(0, 0, 0)]))
    pkt.CreateWidthsAttr(Vt.FloatArray([PACKET_BIG])).SetMetadata("interpolation", "vertex")
    pkt.GetPrim().CreateAttribute("primvars:doNotCastShadows", Sdf.ValueTypeNames.Bool, custom=False).Set(True)
    _bind_material(stage, pkt.GetPrim(), Sdf.Path(f"{MISSION_LOOKS}/PacketMat"))

    # ISL + GSL beams — 2-CV linear curves, repositioned each frame.
    for beam_path, mat in ((MISSION_ISL, "ISLMat"), (MISSION_GSL, "GSLMat")):
        c = UsdGeom.BasisCurves.Define(stage, Sdf.Path(beam_path))
        c.GetTypeAttr().Set("linear")
        c.GetWrapAttr().Set("nonperiodic")
        c.GetCurveVertexCountsAttr().Set(Vt.IntArray([2]))
        c.GetPointsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(0, 0, 0), Gf.Vec3f(0, 0, 1)]))
        c.CreateWidthsAttr(Vt.FloatArray([1.4])).SetMetadata("interpolation", "constant")
        c.GetPrim().CreateAttribute("primvars:doNotCastShadows", Sdf.ValueTypeNames.Bool, custom=False).Set(True)
        _bind_material(stage, c.GetPrim(), Sdf.Path(f"{MISSION_LOOKS}/{mat}"))

    # Cinematic mission camera (sibling of the static Overview camera).
    if not stage.GetPrimAtPath(MISSION_CAM).IsValid():
        cam = UsdGeom.Camera.Define(stage, Sdf.Path(MISSION_CAM))
        cam.CreateFocalLengthAttr(30.0)
        cam.CreateClippingRangeAttr(Gf.Vec2f(1.0, 6000.0))
        cam.AddTransformOp()
        _set_camera_lookat(stage, MISSION_CAM, CAM_GLOBAL_EYE, (0.0, 0.0, 0.0))

    # Hero sat models — Sensor + Hub render as the detailed Satellite_v022
    # body (the rest of the fleet stays as Points). translate updated every
    # frame; scale baked once. Start invisible.
    asset = _hero_sat_asset()
    for path in (MISSION_SENSOR_SAT, MISSION_HUB_SAT):
        if stage.GetPrimAtPath(path).IsValid():
            continue
        xf = UsdGeom.Xform.Define(stage, Sdf.Path(path))
        xf.GetPrim().GetReferences().AddReference(asset)
        xf.AddTranslateOp().Set(Gf.Vec3d(0, 0, EARTH_RADIUS_UNITS + 6))
        xf.AddScaleOp().Set(Gf.Vec3f(HERO_SAT_SCALE, HERO_SAT_SCALE, HERO_SAT_SCALE))
        _set_visibility(xf.GetPrim(), False)

    _set_visibility(stage.GetPrimAtPath(MISSION_GROUP), False)
    _log("authored mission group (AOI / Packet / ISL / GSL / MissionCam / hero sats)")
    return True


def _lerp3(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def _norm3(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def _set_camera_lookat(stage, cam_path: str, eye, target) -> None:
    """Point the camera at `target` from `eye` (Z-up look-at). Writes the
    camera-to-world matrix into its xformOp:transform."""
    cam = stage.GetPrimAtPath(cam_path)
    if not cam or not cam.IsValid():
        return
    fwd = _norm3((target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]))
    # right = fwd × worldUp(0,0,1); up = right × fwd
    rx = fwd[1] * 1.0 - fwd[2] * 0.0
    ry = fwd[2] * 0.0 - fwd[0] * 1.0
    rz = fwd[0] * 0.0 - fwd[1] * 0.0
    right = _norm3((rx, ry, rz))
    up = (
        right[1] * fwd[2] - right[2] * fwd[1],
        right[2] * fwd[0] - right[0] * fwd[2],
        right[0] * fwd[1] - right[1] * fwd[0],
    )
    m = Gf.Matrix4d(
        right[0], right[1], right[2], 0.0,
        up[0],    up[1],    up[2],    0.0,
        -fwd[0],  -fwd[1],  -fwd[2],  0.0,
        eye[0],   eye[1],   eye[2],   1.0,
    )
    xform = UsdGeom.Xformable(cam)
    op = None
    for o in xform.GetOrderedXformOps():
        if o.GetOpType() == UsdGeom.XformOp.TypeTransform:
            op = o
            break
    if op is None:
        op = xform.AddTransformOp()
    op.Set(m)


def mission_camera_pose(mission: dict, fleet_positions: list):
    """Desired (eye, target) for the current mission phase:
      acquire/capture → close-up on the sensor sat;
      route           → follow the data packet sensor→hub;
      compute         → close-up on the compute hub;
      downlink/deliver→ pull back to the global Earth view.
    Returns None when no sensible pose (idle / empty fleet)."""
    n = len(fleet_positions)
    s_idx = int(mission.get("sensor_idx", 0))
    h_idx = int(mission.get("hub_idx", 0))
    if n == 0:
        return None
    sensor = fleet_positions[s_idx] if 0 <= s_idx < n else fleet_positions[0]
    hub    = fleet_positions[h_idx] if 0 <= h_idx < n else fleet_positions[0]
    phase  = mission.get("phase", "idle")
    prog   = float(mission.get("phase_progress", 0.0))
    udir   = _norm3(CAM_OFFSET_DIR)

    # Route pulls back further so the packet reads as a blob travelling
    # along the beam with the hub + Earth for context — at the close
    # distance the long ISL beam just fills the frame as a slab.
    if phase in ("acquire", "capture"):
        tgt, dist = sensor, CAM_CLOSE_DIST
    elif phase == "route":
        tgt, dist = _lerp3(sensor, hub, prog), CAM_CLOSE_DIST * 1.9
    elif phase == "compute":
        tgt, dist = hub, CAM_CLOSE_DIST
    elif phase in ("downlink", "deliver"):
        return (CAM_GLOBAL_EYE, (0.0, 0.0, 0.0))
    else:
        return None
    eye = (tgt[0] + udir[0] * dist, tgt[1] + udir[1] * dist, tgt[2] + udir[2] * dist)
    return (eye, tgt)


def update_mission(stage, mission: dict, fleet_positions: list, wall_t: float) -> None:
    """Per-frame choreography. `fleet_positions` are scene-unit sat points
    (from compute_fleet_positions). Places the AOI + packet + beams per the
    mission phase/progress."""
    if not _HAS_KIT or stage is None:
        return
    group = stage.GetPrimAtPath(MISSION_GROUP)
    if not group.IsValid():
        return

    active = bool(mission.get("active")) or mission.get("phase", "idle") != "idle"
    _set_visibility(group, active)
    if not active:
        return

    phase = mission.get("phase", "idle")
    prog  = float(mission.get("phase_progress", 0.0))

    # Cast positions. Sensor/hub from the live fleet; AOI/ground from lat/lon.
    n = len(fleet_positions)
    s_idx = int(mission.get("sensor_idx", 0))
    h_idx = int(mission.get("hub_idx", 0))
    sensor = fleet_positions[s_idx] if 0 <= s_idx < n else (0.0, 0.0, EARTH_RADIUS_UNITS + 6)
    hub    = fleet_positions[h_idx] if 0 <= h_idx < n else (0.0, 0.0, EARTH_RADIUS_UNITS + 6)
    aoi    = _latlon_to_units(mission.get("aoi_lat", 0.0), mission.get("aoi_lon", 0.0), EARTH_RADIUS_UNITS + 0.5)
    ground = _latlon_to_units(mission.get("ground_lat", 0.0), mission.get("ground_lon", 0.0), EARTH_RADIUS_UNITS + 0.5)

    # Hero sat models — Sensor + Hub render as detailed Satellite_v022
    # bodies during the close-up phases; hidden in the wide downlink/deliver
    # shot (the fleet Points carry the global view).
    close_phase = phase in ("acquire", "capture", "route", "compute")
    _place_hero_sat(stage, MISSION_SENSOR_SAT, sensor, close_phase)
    _place_hero_sat(stage, MISSION_HUB_SAT, hub, close_phase)

    # AOI marker — pulse strongest during acquire/capture.
    aoi_prim = UsdGeom.Points(stage.GetPrimAtPath(MISSION_AOI))
    if aoi_prim:
        aoi_prim.GetPointsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*aoi)]))
        pulse = 1.0 + 0.4 * math.sin(wall_t * 4.0)
        base = 7.0 if phase in ("acquire", "capture") else 3.5
        aoi_prim.GetWidthsAttr().Set(Vt.FloatArray([base * pulse]))

    # Packet position + size by phase.
    packet_pos = sensor
    packet_size = PACKET_BIG
    packet_vis = True
    if phase == "acquire":
        packet_vis = False
    elif phase == "capture":
        packet_pos, packet_size = sensor, PACKET_BIG
    elif phase == "route":
        packet_pos, packet_size = _lerp3(sensor, hub, prog), PACKET_BIG
    elif phase == "compute":
        packet_pos = hub
        packet_size = PACKET_BIG + (PACKET_SMALL - PACKET_BIG) * prog
    elif phase == "downlink":
        packet_pos, packet_size = _lerp3(hub, ground, prog), PACKET_SMALL
    elif phase == "deliver":
        packet_pos, packet_size = ground, PACKET_SMALL

    pkt = UsdGeom.Points(stage.GetPrimAtPath(MISSION_PACKET))
    if pkt:
        pkt.GetPointsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*packet_pos)]))
        pkt.GetWidthsAttr().Set(Vt.FloatArray([max(0.2, packet_size)]))
        _set_visibility(pkt.GetPrim(), packet_vis)

    # Beams: ISL (sensor→hub) during route+compute; GSL (hub→ground) during
    # downlink+deliver.
    isl = UsdGeom.BasisCurves(stage.GetPrimAtPath(MISSION_ISL))
    if isl:
        isl.GetPointsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*sensor), Gf.Vec3f(*hub)]))
        _set_visibility(isl.GetPrim(), phase in ("route", "compute"))
    gsl = UsdGeom.BasisCurves(stage.GetPrimAtPath(MISSION_GSL))
    if gsl:
        gsl.GetPointsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*hub), Gf.Vec3f(*ground)]))
        _set_visibility(gsl.GetPrim(), phase in ("downlink", "deliver"))


# ---------------------------------------------------------------------------
# Mission HERO stage (usd/mission.usda) — clean black-space set, no Earth /
# no rings. Sats are at FIXED staged positions (matching the generator);
# the driver animates the packet, beams, sat visibility, and follow-cam.
# ---------------------------------------------------------------------------
HERO_CAM    = "/World/Cameras/MissionHero"
HERO_CITY   = "/World/TargetScene"   # referenced AEC City Tower pack
HERO_CUBE   = "/World/CaptureCube"   # the "captured data" block
# Must match tools/gen_mission_stage.py.
HERO_SENSOR_POS = (-9.0, 0.0, 0.0)
HERO_HUB_POS    = (9.0, 1.5, 2.0)
HERO_GROUND_POS = (-3.0, -10.0, -32.0)
HERO_CITY_POS   = (0.0, 6.0, -24.0)
HERO_CITY_SCALE = 0.0011
HERO_CITY_TGT   = (0.0, 6.0, -13.0)   # camera aim — tower mid-height
HERO_CUBE_FORM  = (0.0, 4.0, -14.0)   # where the data cube condenses (framed)
HERO_PACKET_CUBES = 8
HERO_GPU_CARDS    = 8

# capture sub-phase fractions (phase_progress within the 'capture' phase,
# which now runs ~30 s so the sweep is a slow flythrough, not a rush):
#   0   .. 0.80  slow camera sweep over the city (~24 s)
#   0.80.. 0.95  the city shrinks *into* the data cube (scale→0, origin slides
#                to the cube point) while a big bright cube grows there
#   0.95.. 1.0   the cube flies from the cube point to the sensor sat
_CAP_SWEEP_END    = 0.80
_CAP_COLLAPSE_END = 0.95

# Per-phase durations (s) — MUST mirror web/src/data/missionPlan.ts and the
# backend MissionEngine. The driver polls /state at only POLL_HZ, so within a
# phase it advances phase_progress locally by wall-clock against these so the
# camera + collapse animate at framerate instead of in ~1Hz steps.
_MISSION_PHASE_DUR = {
    "acquire": 3.0, "capture": 30.0, "route": 5.0,
    "compute": 6.0, "downlink": 4.0, "deliver": 3.0,
}


def _set_xform_ts(stage, path: str, pos=None, scale=None) -> None:
    """Set the translate and/or uniform scale on an xform's existing ops."""
    prim = stage.GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        return
    xf = UsdGeom.Xformable(prim)
    for op in xf.GetOrderedXformOps():
        t = op.GetOpType()
        if t == UsdGeom.XformOp.TypeTranslate and pos is not None:
            op.Set(Gf.Vec3d(float(pos[0]), float(pos[1]), float(pos[2])))
        elif t == UsdGeom.XformOp.TypeScale and scale is not None:
            op.Set(Gf.Vec3f(float(scale), float(scale), float(scale)))


def mission_hero_camera_pose(mission: dict):
    """Follow-cam poses on the hero stage (metres). Returns (eye, target)."""
    phase = mission.get("phase", "idle")
    prog  = float(mission.get("phase_progress", 0.0))
    sensor, hub, ground = HERO_SENSOR_POS, HERO_HUB_POS, HERO_GROUND_POS
    sensor_eye = (sensor[0] + 4.0, sensor[1] - 9.0, sensor[2] + 3.0)
    if phase == "acquire":
        # Establishing shot — a high 3/4 over the city skyline.
        tgt = (0.0, 4.0, -14.0)
        eye = (2.0, -23.0, 6.0)
    elif phase == "capture":
        if prog < _CAP_SWEEP_END:
            # Slow flyover across the city skyline (缓缓扫过) — ~24 s: pan
            # laterally while drifting forward + descending a touch.
            s = prog / _CAP_SWEEP_END
            tgt = (0.0, 4.0, -14.0)
            eye = (-11.0 + 22.0 * s, -22.0 + 5.0 * s, 6.5 - 2.0 * s)
        else:
            # Fixed wide shot framing BOTH the cube-form point and the sensor
            # sat, so the cube condenses then flies left into the sat without
            # the eased camera ever chasing it out of frame.
            tgt = (-4.0, 2.0, -8.0)
            eye = (-4.0, -30.0, 9.0)
    elif phase == "route":
        # Follow the packet-cube stream toward the hub, pulled back enough
        # to read the individual blocks travelling, not a wall of light.
        tgt = _lerp3(sensor, hub, prog)
        eye = (tgt[0] + 6.0, tgt[1] - 20.0, tgt[2] + 8.5)
    elif phase == "compute":
        tgt = HERO_HUB_POS
        eye = (tgt[0] - 1.0, tgt[1] - 8.5, tgt[2] + 3.5)    # beauty 3/4, GPU rack in view
    elif phase == "downlink":
        # Follow the result cubes DOWN to the ground station.
        tgt = _lerp3(hub, (ground[0], ground[1], ground[2] + 2.5), prog)
        eye = (tgt[0] + 9.0, tgt[1] - 13.0, tgt[2] + 8.0)
    elif phase == "deliver":
        tgt = (ground[0], ground[1], ground[2] + 2.5)       # framed on the dish
        eye = (ground[0] + 8.0, ground[1] - 11.0, ground[2] + 7.0)
    else:
        tgt = (0.0, 0.0, 1.0)
        eye = (0.0, -28.0, 12.0)
    return (eye, tgt)


def _flow_cubes(stage, start, end, n_show: int, wall_t: float, size: float,
                speed: float = 0.22) -> None:
    """Stream the packet-cube pool from `start` to `end`: the first `n_show`
    cubes flow along the path at staggered phase, the rest are hidden."""
    n_show = max(1, min(HERO_PACKET_CUBES, n_show))
    pulse = 1.0 + 0.12 * math.sin(wall_t * 8.0)
    for i in range(HERO_PACKET_CUBES):
        prim = stage.GetPrimAtPath(f"/World/Packets/Cube_{i:02d}")
        if not prim or not prim.IsValid():
            continue
        if i >= n_show:
            _set_visibility(prim, False)
            continue
        frac = (wall_t * speed + i / n_show) % 1.0
        pos = _lerp3(start, end, frac)
        xf = UsdGeom.Xformable(prim)
        for op in xf.GetOrderedXformOps():
            if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
                op.Set(Gf.Vec3d(*pos))
            elif op.GetOpType() == UsdGeom.XformOp.TypeScale:
                sc = size * pulse
                op.Set(Gf.Vec3f(sc, sc, sc))
        _set_visibility(prim, True)


def _hide_cubes(stage) -> None:
    for i in range(HERO_PACKET_CUBES):
        _set_visibility(stage.GetPrimAtPath(f"/World/Packets/Cube_{i:02d}"), False)


def _update_capture_scene(stage, mission: dict) -> None:
    """Image acquisition: show the AEC city scene during acquire/capture, then
    collapse it into the data cube and fly the cube up to the sensor sat."""
    phase = mission.get("phase", "idle")
    active = bool(mission.get("active")) or phase != "idle"
    prog = float(mission.get("phase_progress", 0.0))
    city = stage.GetPrimAtPath(HERO_CITY)
    cube = stage.GetPrimAtPath(HERO_CUBE)

    # NOTE: the heavy referenced city does NOT respond to per-frame scale /
    # translate writes through the usdrt/Fabric delegate (only visibility
    # toggles reliably). So the "city → cube" is staged with the city held at
    # its authored pose and toggled, while the lightweight CaptureCube (a plain
    # prim that DOES transform) carries the grow / condense / fly animation.
    if not active or phase not in ("acquire", "capture"):
        _set_visibility(cube, False)
        _set_visibility(city, False)
        return

    if phase == "acquire" or prog < _CAP_SWEEP_END:
        # City fully present; cube not yet formed.
        _set_visibility(city, True)
        _set_visibility(cube, False)
    elif prog < _CAP_COLLAPSE_END:
        # The data cube materialises over the city and grows to engulf it,
        # then condenses to a compact block. The city is cut under cover of
        # the big cube so it reads as "captured into" the cube.
        k = (prog - _CAP_SWEEP_END) / (_CAP_COLLAPSE_END - _CAP_SWEEP_END)
        if k < 0.6:
            cube_scale = 0.4 + (3.4 - 0.4) * (k / 0.6)       # grow to engulf
            _set_visibility(city, True)
        else:
            cube_scale = 3.4 - (3.4 - 1.2) * ((k - 0.6) / 0.4)  # condense
            _set_visibility(city, False)
        _set_xform_ts(stage, HERO_CUBE, pos=HERO_CUBE_FORM, scale=cube_scale)
        _set_visibility(cube, True)
    else:
        # The compact cube flies to the sensor sat and docks (方块给任务卫星).
        _set_visibility(city, False)
        k = (prog - _CAP_COLLAPSE_END) / (1.0 - _CAP_COLLAPSE_END)
        pos = _lerp3(HERO_CUBE_FORM, HERO_SENSOR_POS, k)
        cube_scale = 1.2 * (1.0 - 0.70 * k)                  # 1.2 -> 0.36
        _set_xform_ts(stage, HERO_CUBE, pos=pos, scale=cube_scale)
        _set_visibility(cube, True)


def update_mission_hero(stage, mission: dict, wall_t: float) -> None:
    """Drive the hero-stage props from the mission phase:
      acquire/capture → AEC city scene sweep, then collapse into a data cube;
      route    → packet cubes stream sensor → hub;
      compute  → GPU rack flickers beside the hub;
      downlink → packet cubes stream hub → ground station;
      deliver  → all data props cleared (camera frames the station).
    (Camera is eased separately so it can keep smoothing state.)"""
    if not _HAS_KIT or stage is None:
        return
    phase = mission.get("phase", "idle")
    active = bool(mission.get("active")) or phase != "idle"
    sensor, hub, ground = HERO_SENSOR_POS, HERO_HUB_POS, HERO_GROUND_POS

    # 1. Image acquisition — AEC city scene sweep → collapse into a data cube.
    _update_capture_scene(stage, mission)

    # 2. Packet cubes.
    if phase == "route":
        _flow_cubes(stage, sensor, hub, HERO_PACKET_CUBES, wall_t, 0.34, speed=0.28)
    elif phase == "downlink":
        _flow_cubes(stage, hub, (ground[0], ground[1], ground[2] + 3.0),
                    max(3, HERO_PACKET_CUBES // 2), wall_t, 0.22, speed=0.34)
    else:
        _hide_cubes(stage)

    # 3. GPU rack — flicker the cards during compute (server activity).
    compute_on = active and phase == "compute"
    for i in range(HERO_GPU_CARDS):
        card = stage.GetPrimAtPath(f"/World/ComputeCore/Card_{i:02d}")
        if not card or not card.IsValid():
            continue
        if compute_on:
            # Mostly on, each card blinking at its own rate → rack activity.
            lit = math.sin(wall_t * 11.0 + i * 1.7) > -0.45
            _set_visibility(card, lit)
        else:
            _set_visibility(card, False)


# ---------------------------------------------------------------------------
# Stage swap.
# ---------------------------------------------------------------------------
STAGE_CAMERAS = {
    "overview":  "/World/Cameras/Overview",
    "satellite": "/World/Cameras/Closeup",
    "interior":  "/World/Cameras/Aisle",
    "mission":   "/World/Cameras/MissionHero",
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


def apply_sun(sun_factor: float, sim_now_s: float | None = None,
              is_dawn_dusk: bool = False) -> bool:
    """Drive the satellite-stage Sun (DistantLight) INTENSITY + colour from
    the backend's normalised solar incidence (0 eclipse → 1 solar noon).
    The light's DIRECTION is no longer written here — the per-frame orbital
    driver (`update_twin_orbit`) owns it, sweeping the true zenith→sun angle
    from the backend's `sun_cos` so day/night passes match the physics.
    Returns True iff the light attributes were written."""
    del sim_now_s  # direction is owned by the per-frame orbital driver now
    if not _HAS_KIT:
        return False
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        return False
    f = 1.0 if is_dawn_dusk else max(0.0, min(1.0, sun_factor))
    wrote = False
    for path, lo, hi in SUN_DRIVEN_LIGHTS:
        light = stage.GetPrimAtPath(path)
        if not light.IsValid():
            continue
        attr = light.GetAttribute("inputs:intensity")
        if attr.IsValid():
            attr.Set(float(lo + (hi - lo) * f))
            wrote = True

    sun = stage.GetPrimAtPath(SUN_LIGHT_PATH)
    if sun.IsValid():
        # Warm the key colour toward white at noon, cooler near terminator.
        color_attr = sun.GetAttribute("inputs:color")
        if color_attr.IsValid():
            color_attr.Set(Gf.Vec3f(1.0, 0.93 + 0.05 * f, 0.88 + 0.10 * f))
    return wrote


def update_twin_orbit(stage, tgt: dict, sm: dict, dt: float) -> None:
    """Per-frame orbital-motion driver for the satellite close-up stage.

    The camera stays satellite-centred, so orbital motion is conveyed by the
    CONTEXT sweeping past:
      * the Earth sphere under the satellite rotates so the live sub-satellite
        point (lat, lon from /state) faces the satellite — the ground track
        visibly slides by;
      * the Sun disk + Key light sweep with the zenith→sun angle
        (θ = acos(sun_cos)); in eclipse the sun dips below the −Z horizon and
        the Earth visually blocks it, in lockstep with the physics dimming.

    `tgt` holds the latest 5 Hz poll targets {lat, lon, sun_cos}; `sm` is the
    persistent smoothing state (exponentially eased toward the targets so the
    5 Hz steps glide at frame rate). Missing prims are skipped, so stages
    generated before the animatable-Celestial layout are simply inert.

    Math (verified against USD's own op composition in tools tests):
      Earth:  rotateY = lat − 90, rotateZ = −lon  (op order translate,Y,Z)
              maps P(lat,lon) to local +Z = toward the satellite.
      Light:  rotateXYZ = (0, θ°, 0) points the DistantLight's −Z emission
              along −d where d = (sinθ, 0, cosθ) is the sun direction.
    """
    tgt_lat = float(tgt.get("lat", 0.0))
    tgt_lon = float(tgt.get("lon", 0.0))
    tgt_cos = float(tgt.get("sun_cos", 1.0))
    tgt_dep = float(tgt.get("deploy", 1.0))
    dlat_raw = abs(tgt_lat - sm.get("lat", tgt_lat))
    dlon_raw = abs((tgt_lon - sm.get("lon", tgt_lon) + 180.0) % 360.0 - 180.0)
    if not sm or dlat_raw > 20.0 or dlon_raw > 40.0:
        # First sample OR a discontinuous jump (backend restart, design
        # switch, sim reset) — snap instead of whip-panning the Earth
        # through physically meaningless intermediate poses.
        sm.update({"lat": tgt_lat, "lon": tgt_lon, "sun_cos": tgt_cos,
                   "deploy": tgt_dep})
    sm.setdefault("deploy", tgt_dep)
    # Exponential easing toward the 5 Hz targets (τ ≈ 0.35 s).
    alpha = 1.0 - math.exp(-max(0.0, dt) / 0.35)
    sm["lat"] += (tgt_lat - sm["lat"]) * alpha
    # Longitude wraps — ease along the shortest arc.
    dlon = (tgt_lon - sm["lon"] + 180.0) % 360.0 - 180.0
    sm["lon"] = ((sm["lon"] + dlon * alpha + 180.0) % 360.0) - 180.0
    sm["sun_cos"] += (tgt_cos - sm["sun_cos"]) * alpha
    sm["deploy"] += (tgt_dep - sm["deploy"]) * alpha

    # Only stages generated with the animatable-Celestial layout are driven —
    # the Earth Xform ops double as the layout marker, so pre-layout stages
    # keep their baked static pose AND their authored Key-light aim.
    earth = stage.GetPrimAtPath(TWIN_EARTH_PATH)
    if not earth.IsValid():
        return
    ry = earth.GetAttribute("xformOp:rotateY")
    rz = earth.GetAttribute("xformOp:rotateZ")
    if not (ry.IsValid() and rz.IsValid()):
        return

    # All writes go to the SESSION layer: they are per-run animation, never
    # part of the document — the stage stays clean for saving, Ctrl+S can't
    # bake a frame-frozen orbital pose into the version-controlled usda, and
    # a twin-layer Reload() can't collide with them.
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        # --- Earth: aim the sub-satellite point at the satellite ------------
        ry.Set(float(sm["lat"] - 90.0))
        rz.Set(float(-sm["lon"]))
        if not sm.get("_logged"):
            sm["_logged"] = True
            _log(f"twin orbit driver active (lat={sm['lat']:.1f}, "
                 f"lon={sm['lon']:.1f}, sun_cos={sm['sun_cos']:.2f})")

        # --- Sun disk + Key light: sweep the zenith→sun angle ---------------
        c = max(-1.0, min(1.0, sm["sun_cos"]))
        theta = math.acos(c)
        d = (math.sin(theta), 0.0, c)             # unit sun direction (stage frame)
        sun_disk = stage.GetPrimAtPath(TWIN_SUN_PATH)
        if sun_disk.IsValid():
            tr = sun_disk.GetAttribute("xformOp:translate")
            if tr.IsValid():
                tr.Set(Gf.Vec3d(d[0] * TWIN_SUN_DIST_CM, 0.0, d[2] * TWIN_SUN_DIST_CM))
        key = stage.GetPrimAtPath(SUN_LIGHT_PATH)
        if key.IsValid():
            rot = key.GetAttribute("xformOp:rotateXYZ")
            if rot.IsValid():
                rot.Set(Gf.Vec3f(0.0, math.degrees(theta), 0.0))

        # --- Roll-out wings (redwire): stretch from the root anchors --------
        # The flexible-blanket mock: scaleY = f about the deck-edge pivot
        # (translateY = ±ROOT·(1−f), points transform scale-then-translate),
        # so at f→0 the blanket is reeled into the bay edge and at f=1 it is
        # exactly the authored geometry. Ops are created lazily in the
        # SESSION layer — the saved stage never carries an animation pose.
        if tgt.get("deploy_wings"):
            f = max(0.001, min(1.0, float(sm["deploy"])))
            for path in TWIN_WING_PATHS:
                wing = stage.GetPrimAtPath(path)
                if not wing.IsValid():
                    continue
                sign = 1.0 if path.endswith("PosY") else -1.0
                tr_attr = wing.GetAttribute("xformOp:translate")
                sc_attr = wing.GetAttribute("xformOp:scale")
                if not (tr_attr.IsValid() and sc_attr.IsValid()):
                    xf = UsdGeom.Xformable(wing)
                    tr_attr = xf.AddTranslateOp().GetAttr()
                    sc_attr = xf.AddScaleOp().GetAttr()
                tr_attr.Set(Gf.Vec3d(0.0, sign * TWIN_WING_ROOT_U * (1.0 - f), 0.0))
                sc_attr.Set(Gf.Vec3f(1.0, f, 1.0))


def _dump_satellite_materials() -> str:
    """Return a one-line summary of the bindings on the key panels — used
    for debugging variant-override propagation."""
    if not _HAS_KIT:
        return ""
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        return ""
    try:
        from pxr import UsdShade  # type: ignore
    except ImportError:
        return ""
    bits = []
    for p in (
        "/World/Satellite/Bus/Mesh/Panel",
    ):
        prim = stage.GetPrimAtPath(p)
        if not prim.IsValid():
            bits.append(f"{p.split('/')[-1]}=missing")
            continue
        mat = UsdShade.MaterialBindingAPI(prim).GetDirectBinding().GetMaterialPath()
        bits.append(f"{p.split('/')[-1]}={mat.name if mat else 'none'}")
    return " | ".join(bits)


def apply_satellite_config(cfg: dict) -> bool:
    """Map a SatelliteConfig dict onto the satellite stage's VariantSets.
    No-op when the active stage isn't the satellite one (the prim paths
    won't be valid). Returns True iff at least one variant was set."""
    if not _HAS_KIT:
        return False
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        return False
    applied = False
    for prim_path, vset_names in SAT_VARIANT_TARGETS:
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            continue
        for vset_name in vset_names:
            # Maps the VariantSet name to the SatelliteConfig field of the
            # same name (the contract is intentional 1:1).
            value = cfg.get(vset_name)
            if not value:
                continue
            vset = prim.GetVariantSet(vset_name)
            if not vset.IsValid():
                continue
            if vset.GetVariantSelection() != value:
                vset.SetVariantSelection(value)
                applied = True
    return applied


def reload_twin_layer() -> bool:
    """Reload usd/twin_satellite.usda (a sublayer of the satellite stage) after
    the backend regenerates it (Feature 3 — solar count / radiator size), so
    the new geometry shows in the live viewport without reopening the stage."""
    if not _HAS_KIT:
        return False
    try:
        from pxr import Sdf  # type: ignore
        base = os.environ.get(USD_ROOT_ENV, "C:/Workspace/SpaceDC/space-compute-demo/usd")
        twin_path = os.path.join(base, "twin_satellite.usda").replace("\\", "/")
        layer = Sdf.Layer.FindOrOpen(twin_path)
        if layer is None:
            _log(f"twin layer not resident, skip reload: {twin_path}")
            return False
        layer.Reload(force=True)
        _log(f"reloaded twin layer {twin_path}")
        return True
    except Exception as exc:  # noqa: BLE001
        _log(f"twin reload error: {exc}")
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

            # Satellite Twin hardware loadout — pulled at the same 5Hz poll
            # as /state. Re-applied to the satellite stage every time it
            # changes OR the satellite stage is (re)opened.
            self._sat_config: Optional[dict] = None
            self._geom_version: int = -1   # twin_geometry.version last reloaded
            # Orbital-context driver state for the satellite close-up stage:
            # latest 5 Hz targets {lat, lon, sun_cos} + per-frame smoothing.
            self._twin_orbit_tgt: Optional[dict] = None
            self._twin_orbit_sm: dict = {}
            self._twin_orbit_wall: Optional[float] = None
            # 天数天算 mission snapshot (from /state.mission) — drives the
            # overview-stage choreography (AOI / data packet / ISL-GSL beams)
            # and the cinematic MissionCam.
            self._mission: Optional[dict] = None
            self._mission_rx_wall: Optional[float] = None  # monotonic ts of last mission poll
            self._mission_authored: bool = False
            # Load gate — POST /mission/scene_ready once per mission, after the
            # target scene geometry is resident, so the backend starts the
            # cinematic clock (it holds on 'acquire' until then).
            self._scene_ready_posted: bool = False
            # Smoothed camera pose + whether MissionCam currently owns the
            # viewport (so we bind/unbind only on transitions).
            self._cam_eye: tuple[float, float, float] = CAM_GLOBAL_EYE
            self._cam_target: tuple[float, float, float] = (0.0, 0.0, 0.0)
            self._mission_cam_active: bool = False

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

        def _interp_mission(self) -> dict:
            """The cached mission snapshot with phase_progress advanced by
            wall-clock since the last poll, so the hero choreography animates
            smoothly at framerate rather than stepping at POLL_HZ. The phase
            itself only ever changes on a real poll (authoritative); we just
            clamp progress to 1.0 so we never run past the phase end early."""
            m = self._mission
            if not m:
                return {"phase": "idle", "phase_progress": 0.0, "active": False}
            prog = float(m.get("phase_progress", 0.0))
            dur = _MISSION_PHASE_DUR.get(m.get("phase", "idle"))
            if dur and m.get("active") and self._mission_rx_wall is not None:
                prog = min(1.0, prog + (time.monotonic() - self._mission_rx_wall) / dur)
            out = dict(m)
            out["phase_progress"] = prog
            return out

        def _update_mission_stage(self, stage) -> None:
            """Per-frame driver for the HERO mission stage (usd/mission.usda):
            animates the packet + beams + sat visibility and eases the
            follow-cam through the phase shots. Sats are at fixed staged
            positions; no Earth / fleet involved."""
            mission = self._interp_mission()
            phase = mission.get("phase", "idle")
            active = bool(mission.get("active")) or phase != "idle"

            # Load gate — once the city geometry is resident, tell the backend
            # so it releases 'acquire' and starts the cinematic clock. Posted
            # once per mission; reset when the mission goes idle.
            if not active:
                self._scene_ready_posted = False
            elif phase == "acquire" and not self._scene_ready_posted:
                done, info = _stage_loading_done()
                city = stage.GetPrimAtPath(HERO_CITY)
                if done and city and city.IsValid() and city.GetChildren():
                    if post_backend("/mission/scene_ready"):
                        self._scene_ready_posted = True
                        _log(f"mission scene_ready posted (loading={info})")

            update_mission_hero(stage, mission, time.monotonic())
            # Ease the hero camera toward the per-phase pose.
            eye, tgt = mission_hero_camera_pose(mission)
            self._cam_eye = _lerp3(self._cam_eye, eye, CAM_LERP)
            self._cam_target = _lerp3(self._cam_target, tgt, CAM_LERP)
            _set_camera_lookat(stage, HERO_CAM, self._cam_eye, self._cam_target)

        async def _deferred_apply_config(self) -> None:
            """Wait a few ticks for the satellite stage to finish loading,
            then push the cached SatelliteConfig onto its VariantSets."""
            app = omni.kit.app.get_app()
            for _ in range(30):
                await app.next_update_async()
            cfg = self._sat_config
            if cfg is None:
                return
            if apply_satellite_config(cfg):
                _log(f"deferred-applied satellite config after stage swap: {cfg}")

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
                        # Feature 3: when the deployable-geometry version bumps,
                        # the backend has regenerated twin_satellite.usda —
                        # reload that layer so the live stage picks up the new
                        # solar count / radiator size.
                        geom = state.get("twin_geometry")
                        if geom is not None:
                            v = int(geom.get("version", 0))
                            if v != self._geom_version:
                                if self._geom_version >= 0 and \
                                   self._current_stage == self._stages.get("satellite"):
                                    reload_twin_layer()
                                self._geom_version = v
                except Exception as exc:  # noqa: BLE001
                    _log(f"poll error: {exc}")

                # Satellite Twin config — pulled every tick (cheap; backend
                # serves it from memory in <1ms). On change, immediately
                # apply to the satellite stage if it's the active one.
                try:
                    new_cfg = await asyncio.to_thread(fetch_satellite_config)
                    if new_cfg is not None and new_cfg != self._sat_config:
                        prev = self._sat_config
                        self._sat_config = new_cfg
                        if self._current_stage == self._stages.get("satellite"):
                            if apply_satellite_config(new_cfg):
                                _log(f"applied satellite config: {prev} -> {new_cfg}")
                except Exception as exc:  # noqa: BLE001
                    _log(f"satellite_config poll error: {exc}")

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
            if preset not in ("overview", "satellite", "interior", "mission"):
                preset = "overview"
            if preset != self._last_preset:
                _log(f"preset -> {preset}")
                self._last_preset = preset
                target = self._stages.get(preset)
                if target and target != self._current_stage:
                    if swap_stage(target, preset):
                        self._current_stage = target
                        # When we land on the satellite stage, re-apply the
                        # cached hardware loadout. The stage swap closed the
                        # previous stage's variant selections so we have to
                        # re-issue them on the freshly opened one. Defer a
                        # few ticks so the new stage finishes loading first.
                        if preset == "satellite" and self._sat_config is not None:
                            asyncio.ensure_future(self._deferred_apply_config())

            # Pick up any satellite_config the snapshot brought along —
            # state_update is broadcast as soon as backend mutates, so this
            # path lets us react without waiting for the next config poll.
            packet_cfg = state.get("satellite_config")
            if packet_cfg and packet_cfg != self._sat_config:
                prev = self._sat_config
                self._sat_config = packet_cfg
                if self._current_stage == self._stages.get("satellite"):
                    ok = apply_satellite_config(packet_cfg)
                    _log(f"on_poll cfg snapshot {prev} -> {packet_cfg} applied={ok}")
                    _log(f"  bindings after apply: {_dump_satellite_materials()}")
                else:
                    _log(f"on_poll cfg snapshot {prev} -> {packet_cfg} (not satellite stage, deferred)")

            # Orbit-tracking Sun. Only matters on the satellite stage; the
            # overview stage has no /World/Environment/Key so this no-ops.
            if self._current_stage == self._stages.get("satellite"):
                sat = state.get("satellite", {})
                sun_factor = float(sat.get("sun_factor", 1.0))
                is_dawn_dusk = bool(sat.get("is_dawn_dusk", False))
                apply_sun(sun_factor, None, is_dawn_dusk)
                # Targets for the per-frame orbital-context driver
                # (update_twin_orbit eases toward these at frame rate).
                # Wing deployment is driven only on the redwire hull — the
                # other architectures' wings hang on yokes/booms whose
                # root pivot doesn't match, and their designs never move
                # solar_deploy_frac off 1.0 anyway.
                self._twin_orbit_tgt = {
                    "lat": float(sat.get("lat", 0.0)),
                    "lon": float(sat.get("lon", 0.0)),
                    "sun_cos": float(sat.get(
                        "sun_cos",
                        sun_factor if sat.get("sunlit", True) else -0.3)),
                    "deploy": float(sat.get("solar_deploy_frac", 1.0)),
                    "deploy_wings": (state.get("twin_geometry", {})
                                     .get("architecture") == "redwire"),
                }

            # Cache the mission snapshot + the wall time it arrived, so the
            # per-frame driver can interpolate phase_progress between polls.
            self._mission = state.get("mission")
            self._mission_rx_wall = time.monotonic()

            # Constellation change detection.
            constel = state.get("constellation") or {}
            cid = constel.get("constellation_id")
            if cid and cid != self._constellation_id and cid != self._pending_constellation:
                _log(f"constellation change requested: {self._constellation_id} -> {cid}")
                self._pending_constellation = cid

        # ---- per-frame update --------------------------------------------
        def _on_update(self, _event) -> None:
            ctx = omni.usd.get_context()
            stage = ctx.get_stage()
            if stage is None:
                return

            # HERO mission stage — its own choreography (packet / beams /
            # follow-cam). No Earth, no fleet.
            if self._current_stage == self._stages.get("mission"):
                self._update_mission_stage(stage)
                return

            # Satellite close-up — drive the orbital context (Earth rotation
            # under the sub-satellite point, sun disk + key light sweep) at
            # frame rate, eased toward the latest 5 Hz /state targets.
            if self._current_stage == self._stages.get("satellite"):
                # Belief (self._current_stage) can go stale if the user opens
                # another stage from Kit's Content browser — verify the stage
                # that is ACTUALLY open is the satellite stage before writing.
                root_id = stage.GetRootLayer().identifier.replace("\\", "/")
                want = str(self._current_stage).replace("\\", "/")
                if not root_id.endswith(want.split("/")[-1]):
                    return
                now = time.monotonic()
                dt = min(0.25, max(0.0, now - (self._twin_orbit_wall or now)))
                self._twin_orbit_wall = now
                if self._twin_orbit_tgt is not None:
                    try:
                        update_twin_orbit(stage, self._twin_orbit_tgt,
                                          self._twin_orbit_sm, dt)
                    except Exception as exc:  # noqa: BLE001 — never spam the 60 fps loop
                        if not getattr(self, "_twin_orbit_err_logged", False):
                            self._twin_orbit_err_logged = True
                            _log(f"twin orbit driver error (logged once): {exc}")
                return

            if self._current_stage != self._stages.get("overview"):
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
            # Mission choreography now lives on the dedicated hero stage
            # (usd/mission.usda) — the overview stage stays Earth + fleet.
else:
    class SpaceDemoSceneExtension:  # type: ignore[no-redef]
        pass
