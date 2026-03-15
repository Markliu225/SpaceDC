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
    from pxr import Usd, UsdGeom, UsdLux, Gf, Sdf
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

# ── Constants ───────────────────────────────────────────────

# Prims to **hide** in satellite (micro) view
_MACRO_ONLY_PRIMS = [
    "/World/Earth",
    "/World/Clouds",
    "/World/Atmosphere",
    "/World/OrbitRing",
    "/World/Sun",
    "/World/Stars",
    "/World/InfoLabel",
    "/World/Lights/Ambient",
]

# Child camera under the satellite — inherits satellite's world transform
MICRO_CAM_PATH = "/World/Satellite/MicroCam"

# Camera local offset from bus centre (in satellite-local cm)
# Works for both the original procedural craft and the larger imported model.
MICRO_CAM_LOCAL_POS = Gf.Vec3d(140, 96, 180) if HAS_USD else (140, 96, 180)

# Local light paths (children of Satellite so they move with it)
MICRO_LIGHT_PATH = "/World/Satellite/MicroKeyLight"
MICRO_FILL_PATH  = "/World/Satellite/MicroFillLight"

# Prims to frame when returning to orbit view
ORBIT_FRAME_PRIMS = ["/World/Earth", "/World/Satellite"]


def _camera_rotation_for_offset(offset):
    """Aim the camera's -Z axis back toward the satellite local origin."""
    x, y, z = float(offset[0]), float(offset[1]), float(offset[2])
    yaw = math.degrees(math.atan2(x, z))
    horiz = math.sqrt(x * x + z * z)
    pitch = -math.degrees(math.atan2(y, max(horiz, 1e-6)))
    if HAS_USD:
        return Gf.Vec3f(pitch, yaw, 0.0)
    return (pitch, yaw, 0.0)


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

    @property
    def mode(self) -> str:
        return self._mode

    # ── Public API ──────────────────────────────────────────

    def switch_to_orbit(self, stage: "Usd.Stage"):
        """Switch back to macro orbit view."""
        if self._mode == "orbit":
            return
        self._mode = "orbit"
        self._show_macro_prims(stage, True)
        self._set_micro_lights(stage, False)
        self._set_micro_cam_visible(stage, False)

        # Restore viewport to the original camera
        restore = self._original_cam_path or "/OmniverseKit_Persp"
        self._set_viewport_camera(restore)
        print(f"[SpaceDC] View → ORBIT  (camera={restore})")

    def switch_to_satellite(self, stage: "Usd.Stage", sat_pos: "Gf.Vec3d" = None):
        """Switch to micro satellite detail view."""
        if self._mode == "satellite":
            return
        self._mode = "satellite"

        # Remember current camera so we can restore on switch-back
        self._remember_original_camera()

        # Create the child camera under /World/Satellite (once)
        self._ensure_micro_cam(stage)

        self._show_macro_prims(stage, False)
        self._ensure_micro_lights(stage)
        self._set_micro_lights(stage, True)
        self._set_micro_cam_visible(stage, True)

        # Switch viewport to render through our child camera
        self._set_viewport_camera(MICRO_CAM_PATH)
        print(f"[SpaceDC] View → SATELLITE  (camera={MICRO_CAM_PATH})")

    def toggle(self, stage: "Usd.Stage", sat_pos: "Gf.Vec3d" = None):
        """Toggle between the two view modes."""
        if self._mode == "orbit":
            self.switch_to_satellite(stage, sat_pos)
        else:
            self.switch_to_orbit(stage)

    def update_micro_camera(self, stage: "Usd.Stage", sat_pos: "Gf.Vec3d"):
        """
        Called each scene tick in satellite mode.

        No-op: the child camera inherits the satellite's world transform
        automatically through USD's parent-child hierarchy. No manual
        camera positioning needed.
        """
        pass

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

        prim = stage.GetPrimAtPath(MICRO_CAM_PATH)
        if not prim.IsValid():
            cam = UsdGeom.Camera.Define(stage, MICRO_CAM_PATH)
            cam.GetFocalLengthAttr().Set(24.0)
            cam.GetClippingRangeAttr().Set(Gf.Vec2f(0.1, 10000.0))

            # Position the camera in satellite-local space
            # looking roughly toward the bus centre
            xf = UsdGeom.Xformable(cam.GetPrim())
            xf.ClearXformOpOrder()

            # Translate to offset position
            xf.AddTranslateOp().Set(MICRO_CAM_LOCAL_POS)

            # Rotate to look back at the satellite centre (origin in local)
            xf.AddRotateXYZOp().Set(_camera_rotation_for_offset(MICRO_CAM_LOCAL_POS))

            print(f"[SpaceDC] Created child camera: {MICRO_CAM_PATH}")

        self._micro_cam_created = True

    def _remember_original_camera(self):
        """Save the current viewport camera path so we can restore it."""
        if self._original_cam_path:
            return
        if HAS_VP:
            try:
                vp = vp_util.get_active_viewport()
                if vp:
                    self._original_cam_path = vp.camera_path
                    print(f"[SpaceDC] Remembered original camera: {self._original_cam_path}")
            except Exception:
                pass
        if not self._original_cam_path:
            self._original_cam_path = "/OmniverseKit_Persp"

    def _set_viewport_camera(self, cam_prim_path: str):
        """Switch the active Viewport to render through a specific camera."""
        if not HAS_VP:
            print("[SpaceDC] WARNING: omni.kit.viewport.utility unavailable")
            return
        try:
            vp = vp_util.get_active_viewport()
            if vp:
                vp.camera_path = cam_prim_path
                print(f"[SpaceDC] Viewport camera → {cam_prim_path}")
            else:
                print("[SpaceDC] WARNING: No active viewport found")
        except Exception as e:
            print(f"[SpaceDC] ERROR setting viewport camera: {e}")

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
