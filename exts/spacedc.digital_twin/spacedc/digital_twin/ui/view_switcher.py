"""
============================================================
  view_switcher.py — Macro / Micro camera-view switcher
============================================================

  Two view modes:
    ORBIT      — The default wide view showing Earth + satellite + orbit ring.
    SATELLITE  — Close-up on the satellite, Earth/orbit/stars hidden,
                 local lighting added for detail inspection.

  **KEY DESIGN — Child Camera under Satellite**:
    The only reliable way to make the camera *follow* the satellite while
    still allowing the user to tumble / pan / zoom is to make the camera
    a *child prim* of the satellite:

      /World/Satellite/MicroCam   (UsdGeom.Camera)

    When the satellite prim moves (via update_satellite_position), the
    child camera inherits that translation automatically through USD's
    transform hierarchy.  Meanwhile Kit's Viewport Orbit Controller
    operates in the camera's *local* coordinate space, so the user
    can freely rotate and zoom without us fighting the controller.

    On switch:
      → Satellite mode: viewport.camera_path = "/World/Satellite/MicroCam"
      → Orbit mode:     viewport.camera_path = <original camera>
"""
from __future__ import annotations

import math
from typing import Optional

try:
    from pxr import Usd, UsdGeom, UsdLux, UsdShade, Gf, Sdf, Vt
    HAS_USD = True
except ImportError:
    HAS_USD = False

try:
    import omni.usd
    HAS_KIT = True
except ImportError:
    HAS_KIT = False

try:
    import omni.kit.viewport.utility as vp_util
    HAS_VP = True
except ImportError:
    HAS_VP = False

from ..scene.environment import get_background_texture_path, set_view_lighting_mode

# ── Constants ───────────────────────────────────────────────

# Prims to **hide** in satellite (micro) view
_MACRO_ONLY_PRIMS = [
    "/World/Earth",
    "/World/EarthNightMask",
    "/World/Clouds",
    "/World/Atmosphere",
    "/World/OrbitRing",
    "/World/Constellation",
    "/World/BusinessConstellation",
    "/World/Mission",
    "/World/Mission/DemandLinks",
    "/World/Sun",
    "/World/Stars",
    "/World/InfoLabel",
    "/World/Lights/Ambient",
]

# Child camera under the satellite — inherits satellite's world transform
MICRO_CAM_PATH = "/World/Satellite/MicroCam"

# Camera local offset from bus centre (in satellite-local cm)
# Works for both the original procedural craft and the larger imported model.
MICRO_CAM_LOCAL_POS = Gf.Vec3d(220, 340, 6200) if HAS_USD else (220, 340, 6200)
MICRO_CAM_INSPECT_POS = Gf.Vec3d(0, 8, 148) if HAS_USD else (0, 8, 148)

# Local light paths (children of Satellite so they move with it)
MICRO_LIGHT_PATH = "/World/Satellite/MicroKeyLight"
MICRO_FILL_PATH  = "/World/Satellite/MicroFillLight"

# Prims to frame when returning to orbit view
ORBIT_FRAME_PRIMS = ["/World/Earth", "/World/Satellite"]
ORBIT_CAM_PATH = "/World/OrbitCam"
BACKDROP_CARD_NAME = "CameraBackdrop"
BACKDROP_DISTANCE = 9000.0
BACKDROP_WIDTH = 22000.0
BACKDROP_HEIGHT = 11000.0
ORBIT_CAM_DEFAULT_POS = Gf.Vec3d(0.0, 0.0, 980.0) if HAS_USD else (0.0, 0.0, 980.0)
ORBIT_CAM_DEFAULT_FOCAL = 42.0


def _camera_rotation_for_offset(offset):
    """Aim the camera's -Z axis back toward the satellite local origin."""
    x, y, z = float(offset[0]), float(offset[1]), float(offset[2])
    yaw = math.degrees(math.atan2(x, z))
    horiz = math.sqrt(x * x + z * z)
    pitch = -math.degrees(math.atan2(y, max(horiz, 1e-6)))
    if HAS_USD:
        return Gf.Vec3f(pitch, yaw, 0.0)
    return (pitch, yaw, 0.0)


def _get_detail_bus_prim(stage: "Usd.Stage"):
    if not HAS_USD:
        return None
    for path in ("/World/Satellite/Bus", "/World/Satellite/Bus/Fit", "/World/Satellite/Bus/Fit/AssetRoot"):
        prim = stage.GetPrimAtPath(path)
        if prim and prim.IsValid():
            return prim
    return None


def _get_dynamic_micro_offset(stage: "Usd.Stage"):
    if not HAS_USD:
        return MICRO_CAM_LOCAL_POS
    prim = _get_detail_bus_prim(stage)
    if not prim:
        return MICRO_CAM_LOCAL_POS
    try:
        half_x = float(prim.GetAttribute("spacedc:model_half_x").Get() or 0.0)
        half_y = float(prim.GetAttribute("spacedc:model_half_y").Get() or 0.0)
        half_z = float(prim.GetAttribute("spacedc:model_half_z").Get() or 0.0)
    except Exception:
        return MICRO_CAM_LOCAL_POS
    if half_x <= 0.0 or half_z <= 0.0:
        return MICRO_CAM_LOCAL_POS

    # Frame the full spacecraft width, not just the bus core.
    # The mesh asset has extremely long solar wings; the previous camera was
    # still too close, which made the body shell fill the whole frame and left
    # the wings effectively invisible in close-up.
    x = max(half_x * 0.14, 220.0)
    y = max(half_y * 0.34, 260.0)
    z = max(half_x * 4.8, half_z * 5.4, 6200.0)
    return Gf.Vec3d(x, y, z)


def _create_camera_backdrop(stage: "Usd.Stage", camera_path: str, texture_asset: str):
    """Create a textured quad as a child of the camera so it stays fixed in view."""
    card_path = f"{camera_path}/{BACKDROP_CARD_NAME}"
    mesh = UsdGeom.Mesh.Define(stage, card_path)
    half_w = BACKDROP_WIDTH * 0.5
    half_h = BACKDROP_HEIGHT * 0.5
    z = -BACKDROP_DISTANCE

    mesh.GetPointsAttr().Set(Vt.Vec3fArray([
        Gf.Vec3f(-half_w, -half_h, z),
        Gf.Vec3f(half_w, -half_h, z),
        Gf.Vec3f(half_w, half_h, z),
        Gf.Vec3f(-half_w, half_h, z),
    ]))
    mesh.GetFaceVertexCountsAttr().Set(Vt.IntArray([4]))
    mesh.GetFaceVertexIndicesAttr().Set(Vt.IntArray([0, 1, 2, 3]))
    mesh.GetSubdivisionSchemeAttr().Set("none")
    mesh.GetDoubleSidedAttr().Set(True)
    mesh.CreateExtentAttr().Set(Vt.Vec3fArray([
        Gf.Vec3f(-half_w, -half_h, z),
        Gf.Vec3f(half_w, half_h, z),
    ]))

    primvars = UsdGeom.PrimvarsAPI(mesh.GetPrim())
    st = primvars.CreatePrimvar("st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying)
    st.Set(Vt.Vec2fArray([
        Gf.Vec2f(0.0, 1.0),
        Gf.Vec2f(1.0, 1.0),
        Gf.Vec2f(1.0, 0.0),
        Gf.Vec2f(0.0, 0.0),
    ]))
    mesh.GetPrim().CreateAttribute(
        "primvars:doNotCastShadows",
        Sdf.ValueTypeNames.Bool,
        custom=False,
    ).Set(True)

    mat_path = f"{card_path}/Material"
    material = UsdShade.Material.Define(stage, mat_path)
    shader = UsdShade.Shader.Define(stage, f"{mat_path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.0, 0.0, 0.0))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(1.0)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    shader.CreateInput("specularColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.0, 0.0, 0.0))

    uv_reader = UsdShade.Shader.Define(stage, f"{mat_path}/UVReader")
    uv_reader.CreateIdAttr("UsdPrimvarReader_float2")
    uv_reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
    uv_reader.CreateOutput("result", Sdf.ValueTypeNames.Float2)

    tex_reader = UsdShade.Shader.Define(stage, f"{mat_path}/Texture")
    tex_reader.CreateIdAttr("UsdUVTexture")
    tex_reader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(texture_asset)
    tex_reader.CreateInput("wrapS", Sdf.ValueTypeNames.Token).Set("repeat")
    tex_reader.CreateInput("wrapT", Sdf.ValueTypeNames.Token).Set("repeat")
    tex_reader.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(
        uv_reader.ConnectableAPI(), "result"
    )
    tex_reader.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)

    shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(
        tex_reader.ConnectableAPI(), "rgb"
    )
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    UsdShade.MaterialBindingAPI(mesh.GetPrim()).Bind(material)


class ViewSwitcher:
    """
    Manages switching between orbit (macro) and satellite (micro) camera
    views.

    Strategy:
      - Create a UsdGeom.Camera as a **child of /World/Satellite**
        so it automatically follows the satellite's orbital motion.
      - Switch the Viewport to render through that child camera.
      - Kit's Orbit Controller works in the camera's local space →
        the user can freely tumble / pan / zoom.
      - On switch-back, restore the Viewport to the original camera.
    """

    def __init__(self):
        self._mode: str = "orbit"
        self._micro_lights_exist: bool = False
        self._micro_cam_created: bool = False
        self._original_cam_path: Optional[str] = None
        self._orbit_cam_initialized: bool = False

    @property
    def mode(self) -> str:
        return self._mode

    # ── Public API ──────────────────────────────────────────

    def switch_to_orbit(self, stage: "Usd.Stage"):
        """Switch back to macro orbit view."""
        self._mode = "orbit"
        self.ensure_background_cards(stage)
        self._show_macro_prims(stage, True)
        set_view_lighting_mode(stage, micro_view=False)
        self._set_micro_lights(stage, False)
        self._set_micro_cam_visible(stage, False)
        self._set_backdrop_visible(stage, ORBIT_CAM_PATH, False)
        self._set_backdrop_visible(stage, MICRO_CAM_PATH, False)

        # Always use our own macro camera so backdrop, framing, and lighting
        # stay stable regardless of Kit's default editor camera state.
        self._set_viewport_camera(ORBIT_CAM_PATH)
        print(f"[SpaceDC] View → ORBIT  (camera={ORBIT_CAM_PATH})")

    def switch_to_satellite(self, stage: "Usd.Stage", sat_pos: "Gf.Vec3d" = None):
        """Switch to micro satellite detail view."""
        self._mode = "satellite"

        # Remember current camera so we can restore on switch-back
        self._remember_original_camera()

        # Always recreate the micro camera when entering close-up. Reusing the
        # previous camera prim let stale orbit-controller transforms linger,
        # which is why the user kept seeing the same giant bus shell even
        # after the asset and framing math changed.
        self._recreate_micro_cam(stage)
        self.set_micro_camera_inspection(stage, False)
        self.ensure_background_cards(stage)

        self._show_macro_prims(stage, False)
        set_view_lighting_mode(stage, micro_view=True)
        self._ensure_micro_lights(stage)
        self._set_micro_lights(stage, True)
        self._set_micro_cam_visible(stage, True)
        self._set_backdrop_visible(stage, ORBIT_CAM_PATH, False)
        self._set_backdrop_visible(stage, MICRO_CAM_PATH, True)

        # Switch viewport to render through our child camera
        self._set_viewport_camera(MICRO_CAM_PATH)
        print(f"[SpaceDC] View → SATELLITE  (camera={MICRO_CAM_PATH})")

    def toggle(self, stage: "Usd.Stage", sat_pos: "Gf.Vec3d" = None):
        """Toggle between the two view modes."""
        current_cam = self._get_viewport_camera_path()
        if current_cam == MICRO_CAM_PATH:
            self._mode = "satellite"
            self.switch_to_orbit(stage)
        else:
            self._mode = "orbit"
            self.switch_to_satellite(stage, sat_pos)

    def update_micro_camera(self, stage: "Usd.Stage", sat_pos: "Gf.Vec3d"):
        """
        Called each scene tick in satellite mode.

        No-op: the child camera inherits the satellite's world transform
        automatically through USD's parent-child hierarchy. No manual
        camera positioning needed.
        """
        pass

    def set_micro_camera_inspection(self, stage: "Usd.Stage", enabled: bool):
        """Swap between the default close-up camera and a front-on payload inspection view."""
        if not HAS_USD:
            return
        self._ensure_micro_cam(stage)
        prim = stage.GetPrimAtPath(MICRO_CAM_PATH)
        if not prim.IsValid():
            return
        cam = UsdGeom.Camera.Define(stage, MICRO_CAM_PATH)
        offset = MICRO_CAM_INSPECT_POS if enabled else _get_dynamic_micro_offset(stage)
        xf = UsdGeom.Xformable(cam.GetPrim())
        xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(offset)
        xf.AddRotateXYZOp().Set(_camera_rotation_for_offset(offset))
        focal_attr = cam.GetFocalLengthAttr()
        if not focal_attr or not focal_attr.IsValid():
            focal_attr = cam.GetPrim().CreateAttribute(
                "focalLength",
                Sdf.ValueTypeNames.Float,
                custom=False,
            )
        focal_attr.Set(24.0 if enabled else 8.0)
        print(
            "[SpaceDC] Micro camera frame:",
            f"inspection={enabled}",
            f"offset=({float(offset[0]):.1f}, {float(offset[1]):.1f}, {float(offset[2]):.1f})",
        )

    def ensure_background_cards(self, stage: "Usd.Stage"):
        """Create background cards for the orbit and micro cameras if needed."""
        if not HAS_USD:
            return
        self._remember_original_camera()
        self._ensure_orbit_camera(stage)
        self._ensure_micro_cam(stage)
        self._ensure_camera_backdrop(stage, MICRO_CAM_PATH)

    def on_satellite_rebuilt(self, stage: "Usd.Stage"):
        """
        Must be called after build_satellite() rebuilds /World/Satellite.

        Since build_satellite() now preserves MicroCam and MicroLights
        (selective child removal), the camera prim is never destroyed.
        We only need to re-check micro lights because the satellite
        model geometry is brand new.
        """
        # Micro lights might have survived the selective clear,
        # but re-check just in case a future change removes them.
        if self._mode == "satellite":
            if not stage.GetPrimAtPath(MICRO_LIGHT_PATH).IsValid():
                self._micro_lights_exist = False
                self._ensure_micro_lights(stage)
                self._set_micro_lights(stage, True)
            print("[SpaceDC] Satellite rebuilt — micro view intact (camera preserved)")

    def before_satellite_rebuild(self):
        """
        No longer needed — build_satellite() now preserves the MicroCam
        prim during rebuilds.  Kept as a no-op for backward compatibility.
        """
        pass

    # ── Camera management ───────────────────────────────────

    def _ensure_micro_cam(self, stage: "Usd.Stage"):
        """Create /World/Satellite/MicroCam (child of Satellite) once."""
        if self._micro_cam_created or not HAS_USD:
            return

        existed = stage.GetPrimAtPath(MICRO_CAM_PATH).IsValid()
        cam = UsdGeom.Camera.Define(stage, MICRO_CAM_PATH)

        focal_attr = cam.GetFocalLengthAttr()
        if not focal_attr or not focal_attr.IsValid():
            focal_attr = cam.GetPrim().CreateAttribute(
                "focalLength",
                Sdf.ValueTypeNames.Float,
                custom=False,
            )
        focal_attr.Set(8.0)

        clip_attr = cam.GetClippingRangeAttr()
        if not clip_attr or not clip_attr.IsValid():
            clip_attr = cam.GetPrim().CreateAttribute(
                "clippingRange",
                Sdf.ValueTypeNames.Float2,
                custom=False,
            )
        clip_attr.Set(Gf.Vec2f(0.1, 10000.0))

        # Position the camera in satellite-local space looking toward the bus centre.
        xf = UsdGeom.Xformable(cam.GetPrim())
        xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(_get_dynamic_micro_offset(stage))
        xf.AddRotateXYZOp().Set(_camera_rotation_for_offset(_get_dynamic_micro_offset(stage)))

        if not existed:
            print(f"[SpaceDC] Created child camera: {MICRO_CAM_PATH}")

        self._micro_cam_created = True

    def _recreate_micro_cam(self, stage: "Usd.Stage"):
        """Force a fresh micro camera so stale local view transforms can't persist."""
        if not HAS_USD:
            return
        if stage.GetPrimAtPath(MICRO_CAM_PATH).IsValid():
            stage.RemovePrim(MICRO_CAM_PATH)
        self._micro_cam_created = False
        self._ensure_micro_cam(stage)

    def _remember_original_camera(self):
        """Save the current viewport camera path so we can restore it."""
        if self._original_cam_path:
            return
        cam_path = self._get_viewport_camera_path()
        if cam_path:
            self._original_cam_path = cam_path
            print(f"[SpaceDC] Remembered original camera: {self._original_cam_path}")
        if not self._original_cam_path:
            self._original_cam_path = "/OmniverseKit_Persp"

    def _get_viewport_camera_path(self) -> Optional[str]:
        if not HAS_VP:
            return None
        try:
            vp = vp_util.get_active_viewport()
            if vp:
                return vp.camera_path
        except Exception:
            return None
        return None

    def _ensure_orbit_camera(self, stage: "Usd.Stage"):
        """Create and initialize a dedicated macro camera for the orbit view."""
        if self._orbit_cam_initialized or not HAS_USD:
            return

        cam = UsdGeom.Camera.Define(stage, ORBIT_CAM_PATH)
        cam.GetFocalLengthAttr().Set(ORBIT_CAM_DEFAULT_FOCAL)
        cam.GetClippingRangeAttr().Set(Gf.Vec2f(1.0, 50000.0))

        xf = UsdGeom.Xformable(cam.GetPrim())
        xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(Gf.Vec3d(*ORBIT_CAM_DEFAULT_POS))
        xf.AddRotateXYZOp().Set(_camera_rotation_for_offset(ORBIT_CAM_DEFAULT_POS))
        self._orbit_cam_initialized = True
        print(f"[SpaceDC] Orbit camera initialized: pos={tuple(float(v) for v in ORBIT_CAM_DEFAULT_POS)}")

    def _set_viewport_camera(self, cam_prim_path: str):
        """Switch the active Viewport to render through a specific camera."""
        if not HAS_VP:
            print("[SpaceDC] WARNING: omni.kit.viewport.utility unavailable")
            return
        try:
            vp = vp_util.get_active_viewport()
            if vp:
                vp.camera_path = cam_prim_path
                self._mode = "satellite" if cam_prim_path == MICRO_CAM_PATH else "orbit"
                print(f"[SpaceDC] Viewport camera → {cam_prim_path}")
            else:
                print("[SpaceDC] WARNING: No active viewport found")
        except Exception as e:
            print(f"[SpaceDC] ERROR setting viewport camera: {e}")

    def _ensure_camera_backdrop(self, stage: "Usd.Stage", camera_path: str):
        """Create a textured backdrop card as a child of the given camera."""
        texture_asset = get_background_texture_path()
        if not texture_asset:
            return

        camera_prim = stage.GetPrimAtPath(camera_path)
        if not camera_prim.IsValid():
            return

        card_path = f"{camera_path}/{BACKDROP_CARD_NAME}"
        if stage.GetPrimAtPath(card_path).IsValid():
            return

        _create_camera_backdrop(stage, camera_path, texture_asset)
        print(f"[SpaceDC] Camera backdrop created: {card_path}")

    def _set_backdrop_visible(self, stage: "Usd.Stage", camera_path: str, visible: bool):
        """Show or hide the camera backdrop card without deleting it."""
        if not HAS_USD:
            return
        card_prim = stage.GetPrimAtPath(f"{camera_path}/{BACKDROP_CARD_NAME}")
        if not card_prim.IsValid():
            return
        img = UsdGeom.Imageable(card_prim)
        if visible:
            img.MakeVisible()
        else:
            img.MakeInvisible()

    # ── Scene visibility ────────────────────────────────────

    def _show_macro_prims(self, stage: "Usd.Stage", visible: bool):
        """Toggle visibility of all orbit-scene prims."""
        if not HAS_USD:
            return
        for path_str in _MACRO_ONLY_PRIMS:
            prim = stage.GetPrimAtPath(path_str)
            if prim.IsValid():
                img = UsdGeom.Imageable(prim)
                if visible:
                    img.MakeVisible()
                else:
                    img.MakeInvisible()

    def sync_scene_visibility(self, stage: "Usd.Stage"):
        """
        Enforce visibility from the *actual* active viewport camera.

        Some scene updates can rebuild or restyle prims after a view switch.
        Re-applying the visibility contract each frame keeps close-up mode
        deterministic: MicroCam means Earth/orbits/constellations stay hidden.
        """
        if not HAS_USD:
            return
        active_cam = self._get_viewport_camera_path()
        in_micro = active_cam == MICRO_CAM_PATH or self._mode == "satellite"
        self._mode = "satellite" if in_micro else "orbit"
        self._show_macro_prims(stage, not in_micro)
        self._set_micro_lights(stage, in_micro)
        self._set_micro_cam_visible(stage, in_micro)
        self._set_backdrop_visible(stage, ORBIT_CAM_PATH, False)
        self._set_backdrop_visible(stage, MICRO_CAM_PATH, in_micro)

    def _set_micro_cam_visible(self, stage: "Usd.Stage", visible: bool):
        """Hide the MicroCam prim so its wireframe doesn't show in orbit view."""
        if not HAS_USD:
            return
        for path_str in [MICRO_CAM_PATH, MICRO_LIGHT_PATH, MICRO_FILL_PATH]:
            prim = stage.GetPrimAtPath(path_str)
            if prim.IsValid():
                img = UsdGeom.Imageable(prim)
                if visible:
                    img.MakeVisible()
                else:
                    img.MakeInvisible()

    # ── Micro-view lighting ─────────────────────────────────

    def _ensure_micro_lights(self, stage: "Usd.Stage"):
        """Create local lights parented to satellite (once)."""
        if self._micro_lights_exist or not HAS_USD:
            return

        key_prim = stage.GetPrimAtPath(MICRO_LIGHT_PATH)
        if not key_prim.IsValid():
            key = UsdLux.DistantLight.Define(stage, MICRO_LIGHT_PATH)
            key.GetIntensityAttr().Set(8000.0)
            key.GetColorAttr().Set(Gf.Vec3f(1.0, 0.97, 0.92))
            xf = UsdGeom.Xformable(key.GetPrim())
            xf.ClearXformOpOrder()
            xf.AddRotateXYZOp().Set(Gf.Vec3f(-35, 45, 0))

        fill_prim = stage.GetPrimAtPath(MICRO_FILL_PATH)
        if not fill_prim.IsValid():
            fill = UsdLux.DistantLight.Define(stage, MICRO_FILL_PATH)
            fill.GetIntensityAttr().Set(1200.0)
            fill.GetColorAttr().Set(Gf.Vec3f(0.96, 0.95, 0.92))
            xf = UsdGeom.Xformable(fill.GetPrim())
            xf.ClearXformOpOrder()
            xf.AddRotateXYZOp().Set(Gf.Vec3f(20, -135, 0))

        self._micro_lights_exist = True

    def _set_micro_lights(self, stage: "Usd.Stage", enabled: bool):
        """Show/hide the micro-view local lights."""
        if not HAS_USD:
            return
        for lpath in [MICRO_LIGHT_PATH, MICRO_FILL_PATH]:
            prim = stage.GetPrimAtPath(lpath)
            if prim.IsValid():
                img = UsdGeom.Imageable(prim)
                if enabled:
                    img.MakeVisible()
                else:
                    img.MakeInvisible()

    def destroy(self):
        """Cleanup."""
        pass
