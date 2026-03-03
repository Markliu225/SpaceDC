"""
============================================================
  satellite_builder.py — Parametric USD Satellite (Space DC) model
  Migrated from: js/satellite3d.js (Detail3D.buildSat)
============================================================

  Builds the ORBITAL DC-1 spacecraft as a USD prim hierarchy:

  /World/Satellite
    /Bus                — Main server-rack style body
    /GoldBand           — MLI thermal blanket band
    /ServerFace         — Front grille with rack-unit LEDs
    /SolarWings
      /Left/Wing_0..N   — Per-wing sub-panels + frames
      /Right/Wing_0..M
    /Radiators
      /Left/Panel_0..N  — Per-panel geometry + heat pipes
      /Right/Panel_0..M
    /Antenna            — High-gain dish + secondary comm
    /StarTrackers       — ±X star tracker boxes
    /Thrusters          — 4× corner nozzles
    /DockingRing        — Torus geometry
"""
from __future__ import annotations

import math
from typing import Optional

try:
    from pxr import Usd, UsdGeom, UsdShade, Sdf, Gf, Vt
    HAS_USD = True
except ImportError:
    HAS_USD = False


# ── Visual scaling ──────────────────────────────────────────
# JS original: bus 0.14×0.10×0.16 with earth r=2.0
# Omniverse: uniform ×100 → bus 14×10×16 cm, earth r=200 cm
BUS_X, BUS_Y, BUS_Z = 14.0, 10.0, 16.0    # cm (Kit default unit)


# ── Xform helper (Kit-safe, replaces XformCommonAPI) ───────

def _xform(schema_or_prim, translate=None, rotate=None, scale=None):
    """Set translate / rotate / scale via Xformable ops.

    Works with *any* typed schema (UsdGeom.Cube, Sphere …) or raw Prim.
    """
    prim = schema_or_prim.GetPrim() if hasattr(schema_or_prim, "GetPrim") else schema_or_prim
    xf = UsdGeom.Xformable(prim)
    xf.ClearXformOpOrder()
    if translate is not None:
        xf.AddTranslateOp().Set(Gf.Vec3d(*translate))
    if rotate is not None:
        xf.AddRotateXYZOp().Set(Gf.Vec3f(*rotate))
    if scale is not None:
        xf.AddScaleOp().Set(Gf.Vec3d(*scale))


def build_satellite(
    stage: "Usd.Stage",
    root_path: str = "/World/Satellite",
    wing_count: int = 8,
    wing_area: float = 350.0,
    rad_count: int = 6,
    rad_area: float = 143.3,
) -> None:
    """
    Build (or rebuild) the full satellite model at ``root_path``.
    If the prim already exists its **model children** are cleared first,
    but camera and light prims created by ViewSwitcher are preserved so
    that the micro-view camera survives a parameter-change rebuild.
    """
    if not HAS_USD:
        raise RuntimeError("pxr (OpenUSD) not available — run inside Omniverse Kit")

    # ── Selective clear: remove only model sub-prims, keep camera/lights ──
    _KEEP_SUFFIXES = ("MicroCam", "MicroKeyLight", "MicroFillLight")

    existing = stage.GetPrimAtPath(root_path)
    if existing.IsValid():
        children_to_remove = []
        for child in existing.GetChildren():
            name = child.GetName()
            if name not in _KEEP_SUFFIXES:
                children_to_remove.append(child.GetPath())
        for cpath in children_to_remove:
            stage.RemovePrim(cpath)

    root = UsdGeom.Xform.Define(stage, root_path)

    mats = _create_materials(stage, root_path)

    _build_bus(stage, root_path, mats)
    _build_solar_wings(stage, root_path, mats, wing_count, wing_area)
    _build_radiators(stage, root_path, mats, rad_count, rad_area)
    _build_antenna(stage, root_path, mats)
    _build_star_trackers(stage, root_path, mats)
    _build_thrusters(stage, root_path, mats)
    _build_docking_ring(stage, root_path, mats)


# ── Materials ───────────────────────────────────────────────

def _create_materials(stage, root_path: str) -> dict:
    """Create and return a dict of UsdPreviewSurface materials."""
    mat_root = f"{root_path}/Materials"

    def _mat(name, color, metallic=0.5, roughness=0.45):
        path = f"{mat_root}/{name}"
        m = UsdShade.Material.Define(stage, path)
        s = UsdShade.Shader.Define(stage, f"{path}/Shader")
        s.CreateIdAttr("UsdPreviewSurface")
        s.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(*color)
        )
        s.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(metallic)
        s.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
        m.CreateSurfaceOutput().ConnectToSource(s.ConnectableAPI(), "surface")
        return m

    return {
        "bus":     _mat("BusMat",     (0.10, 0.11, 0.13), 0.55, 0.45),
        "busEdge": _mat("BusEdgeMat", (0.16, 0.18, 0.20), 0.60, 0.38),
        "gold":    _mat("GoldMat",    (0.78, 0.65, 0.19), 0.72, 0.28),
        "grille":  _mat("GrilleMat",  (0.06, 0.06, 0.08), 0.40, 0.70),
        "solar":   _mat("SolarMat",   (0.03, 0.03, 0.16), 0.42, 0.24),
        "frame":   _mat("FrameMat",   (0.33, 0.34, 0.37), 0.60, 0.35),
        "rad":     _mat("RadMat",     (0.89, 0.89, 0.93), 0.05, 0.85),
        "copper":  _mat("CopperMat",  (0.72, 0.45, 0.20), 0.80, 0.32),
        "dark":    _mat("DarkMat",    (0.07, 0.07, 0.07), 0.50, 0.60),
        "antenna": _mat("AntennaMat", (0.73, 0.73, 0.73), 0.55, 0.35),
        "nozzle":  _mat("NozzleMat",  (0.23, 0.23, 0.24), 0.65, 0.40),
        "accent":  _mat("AccentMat",  (0.11, 0.20, 0.28), 0.50, 0.40),
        "led_green": _mat("LedGreen", (0.2, 0.93, 0.4),   0.0,  0.1),
        "led_blue":  _mat("LedBlue",  (0.0, 0.73, 1.0),   0.0,  0.1),
        "led_amber": _mat("LedAmber", (1.0, 0.67, 0.13),  0.0,  0.1),
    }


def _bind(stage, prim_path: str, mat: "UsdShade.Material"):
    """Bind a material to a prim."""
    prim = stage.GetPrimAtPath(prim_path)
    if prim.IsValid():
        UsdShade.MaterialBindingAPI(prim).Bind(mat)


# ── Bus ─────────────────────────────────────────────────────

def _build_bus(stage, root_path: str, mats: dict):
    bus_path = f"{root_path}/Bus"
    bus = UsdGeom.Cube.Define(stage, bus_path)
    bus.GetSizeAttr().Set(1.0)
    _xform(bus, scale=(BUS_X, BUS_Y, BUS_Z))
    _bind(stage, bus_path, mats["bus"])

    # Gold MLI band (2.5% of bus height)
    band_path = f"{root_path}/GoldBand"
    band = UsdGeom.Cube.Define(stage, band_path)
    band.GetSizeAttr().Set(1.0)
    bh = BUS_Y * 0.18
    _xform(band,
           translate=(0, BUS_Y / 2 - bh, 0),
           scale=(BUS_X * 1.02, bh, BUS_Z * 1.02))
    _bind(stage, band_path, mats["gold"])

    # Server face grille
    grille_path = f"{root_path}/ServerFace"
    grille = UsdGeom.Cube.Define(stage, grille_path)
    grille.GetSizeAttr().Set(1.0)
    _xform(grille,
           translate=(0, -BUS_Y * 0.04, BUS_Z / 2 + BUS_Z * 0.01),
           scale=(BUS_X * 0.88, BUS_Y * 0.75, BUS_Z * 0.015))
    _bind(stage, grille_path, mats["grille"])

    # Rack-unit LED strips (8 units)
    led_w = BUS_X * 0.04
    led_h = BUS_Y * 0.02
    led_d = BUS_Z * 0.004
    for ru in range(8):
        ry = -BUS_Y * 0.35 + (ru / 7) * BUS_Y * 0.70
        led_path = f"{root_path}/ServerFace/RackLed_{ru}"
        led = UsdGeom.Cube.Define(stage, led_path)
        led.GetSizeAttr().Set(1.0)
        _xform(led,
               translate=(-BUS_X * 0.36, ry + BUS_Y * 0.03, BUS_Z / 2 + BUS_Z * 0.02),
               scale=(led_w, led_h, led_d))
        color_mat = mats["led_green"] if ru % 3 != 2 else mats["led_blue"]
        _bind(stage, led_path, color_mat)


# ── Solar Wings ─────────────────────────────────────────────

def _build_solar_wings(stage, root_path: str, mats: dict, wing_count: int, wing_area: float):
    wings_root = f"{root_path}/SolarWings"
    UsdGeom.Xform.Define(stage, wings_root)

    # JS ref: single panel 0.34×0.12 at earth r=2 → ×100 = 34×12
    # Scale panel size from wing_area parameter (default 350 m²)
    wing_scale = 0.16
    single_w = max(3, min(18, math.sqrt(wing_area) * wing_scale * 1.4))
    single_h = max(2, min(12, math.sqrt(wing_area) * wing_scale * 1.0))
    sub_panels_per_wing = 3
    arm_len = BUS_X * 0.4
    gap = BUS_Z * 0.06

    left_count = math.ceil(wing_count / 2)
    right_count = wing_count - left_count

    def layout_side(count, side, side_name):
        side_root = f"{wings_root}/{side_name}"
        UsdGeom.Xform.Define(stage, side_root)

        cols = 1 if count <= 2 else (2 if count <= 6 else 3)
        rows = math.ceil(count / cols)

        for idx in range(count):
            col = idx // rows
            row = idx % rows

            wing_path = f"{side_root}/Wing_{idx}"
            wing_xf = UsdGeom.Xform.Define(stage, wing_path)

            col_offset = col * (single_w * sub_panels_per_wing + gap)
            wing_start_x = BUS_X / 2 + arm_len + 0.2 + col_offset
            total_wing_w = single_w * sub_panels_per_wing

            # Arm
            arm_path = f"{wing_path}/Arm"
            arm = UsdGeom.Cube.Define(stage, arm_path)
            arm.GetSizeAttr().Set(1.0)
            full_arm = arm_len + col_offset
            arm_thick = BUS_Y * 0.06
            _xform(arm,
                   translate=(side * (BUS_X / 2 + full_arm / 2), 0, 0),
                   scale=(full_arm, arm_thick, arm_thick))
            _bind(stage, arm_path, mats["frame"])

            # Sub-panels
            for pi in range(sub_panels_per_wing):
                panel_path = f"{wing_path}/Panel_{pi}"
                panel = UsdGeom.Cube.Define(stage, panel_path)
                panel.GetSizeAttr().Set(1.0)
                px = side * (wing_start_x + pi * single_w + single_w / 2)
                panel_thick = BUS_Y * 0.03
                _xform(panel,
                       translate=(px, 0, 0),
                       scale=(single_w - 0.2, panel_thick, single_h))
                _bind(stage, panel_path, mats["solar"])

            # Frame rails
            rail_thick = BUS_Y * 0.05
            rail_depth = BUS_Y * 0.04
            for rs in [-1, 1]:
                rail_path = f"{wing_path}/Rail_{0 if rs == -1 else 1}"
                rail = UsdGeom.Cube.Define(stage, rail_path)
                rail.GetSizeAttr().Set(1.0)
                _xform(rail,
                       translate=(side * (wing_start_x + total_wing_w / 2), 0,
                                  rs * single_h / 2),
                       scale=(total_wing_w + 0.4, rail_thick, rail_depth))
                _bind(stage, rail_path, mats["frame"])

            # Position row along Z
            total_z = rows * single_h + (rows - 1) * gap
            start_z = -total_z / 2 + single_h / 2
            z_pos = start_z + row * (single_h + gap)
            _xform(wing_xf, translate=(0, 0, z_pos))

    layout_side(left_count,  -1, "Left")
    layout_side(right_count,  1, "Right")


# ── Radiators ───────────────────────────────────────────────

def _build_radiators(stage, root_path: str, mats: dict, rad_count: int, rad_area: float):
    rad_root = f"{root_path}/Radiators"
    UsdGeom.Xform.Define(stage, rad_root)

    # JS ref: single rad 0.04×0.10 → ×100 = 4×10
    rad_scale = 0.28
    single_w = max(2, min(10, math.sqrt(rad_area) * rad_scale * 1.2))
    single_h = max(1.5, min(8, math.sqrt(rad_area) * rad_scale * 0.9))
    rad_gap = BUS_Z * 0.05
    y_offset = -BUS_Y / 2 - BUS_Y * 0.08

    left_count = math.ceil(rad_count / 2)
    right_count = rad_count - left_count

    def layout_side(count, side, side_name):
        side_root = f"{rad_root}/{side_name}"
        UsdGeom.Xform.Define(stage, side_root)

        cols = 1 if count <= 2 else (2 if count <= 6 else 3)
        rows = max(1, math.ceil(count / cols))

        for idx in range(count):
            col = idx // rows
            row = idx % rows

            panel_path = f"{side_root}/Panel_{idx}"
            panel = UsdGeom.Cube.Define(stage, panel_path)
            panel.GetSizeAttr().Set(1.0)

            col_offset = col * (single_w + rad_gap)
            rx = side * (BUS_X / 2 + single_w / 2 + 0.6 + col_offset)

            total_z = rows * single_h + (rows - 1) * rad_gap
            start_z = -total_z / 2 + single_h / 2
            rz = start_z + row * (single_h + rad_gap)

            panel_thick = BUS_Y * 0.02
            _xform(panel,
                   translate=(rx, y_offset, rz),
                   scale=(single_w, panel_thick, single_h))
            _bind(stage, panel_path, mats["rad"])

            # Heat pipes (3 per panel)
            pipe_r = BUS_Y * 0.012
            for hi in range(3):
                pipe_path = f"{side_root}/Panel_{idx}/Pipe_{hi}"
                pipe = UsdGeom.Cylinder.Define(stage, pipe_path)
                pipe.GetRadiusAttr().Set(pipe_r)
                pipe.GetHeightAttr().Set(single_h - 0.4)
                _xform(pipe,
                       translate=(rx + (hi - 1) * single_w * 0.28, y_offset, rz),
                       rotate=(90, 0, 0))
                _bind(stage, pipe_path, mats["copper"])

    layout_side(left_count,  -1, "Left")
    layout_side(right_count,  1, "Right")


# ── Antenna ─────────────────────────────────────────────────

def _build_antenna(stage, root_path: str, mats: dict):
    ant_root = f"{root_path}/Antenna"
    UsdGeom.Xform.Define(stage, ant_root)

    # JS ref: pole r=0.003 h=0.07, dish r=0.022 → ×100
    pole_r = BUS_X * 0.02
    pole_h = BUS_Y * 0.5
    dish_r = BUS_X * 0.16

    # Main pole
    pole_path = f"{ant_root}/Pole"
    pole = UsdGeom.Cylinder.Define(stage, pole_path)
    pole.GetRadiusAttr().Set(pole_r)
    pole.GetHeightAttr().Set(pole_h)
    _xform(pole, translate=(BUS_X * 0.25, BUS_Y / 2 + pole_h / 2, -BUS_Z * 0.2))
    _bind(stage, pole_path, mats["antenna"])

    # Dish
    dish_path = f"{ant_root}/Dish"
    dish = UsdGeom.Sphere.Define(stage, dish_path)
    dish.GetRadiusAttr().Set(dish_r)
    _xform(dish, translate=(BUS_X * 0.25, BUS_Y / 2 + pole_h + dish_r * 0.3, -BUS_Z * 0.2))
    _bind(stage, dish_path, mats["antenna"])

    # Feed
    feed_path = f"{ant_root}/Feed"
    feed = UsdGeom.Cylinder.Define(stage, feed_path)
    feed.GetRadiusAttr().Set(pole_r * 0.8)
    feed.GetHeightAttr().Set(pole_h * 0.2)
    _xform(feed, translate=(BUS_X * 0.25, BUS_Y / 2 + pole_h * 0.7, -BUS_Z * 0.2))
    _bind(stage, feed_path, mats["dark"])


# ── Star Trackers ───────────────────────────────────────────

def _build_star_trackers(stage, root_path: str, mats: dict):
    st_w = BUS_X * 0.07
    st_h = BUS_Y * 0.06
    st_d = BUS_Z * 0.07
    for i, sx in enumerate([-1, 1]):
        st_path = f"{root_path}/StarTracker_{i}"
        st = UsdGeom.Cube.Define(stage, st_path)
        st.GetSizeAttr().Set(1.0)
        _xform(st,
               translate=(sx * BUS_X * 0.4, BUS_Y / 2 + st_h * 0.5, BUS_Z * 0.3),
               scale=(st_w, st_h, st_d))
        _bind(stage, st_path, mats["dark"])


# ── Thrusters ───────────────────────────────────────────────

def _build_thrusters(stage, root_path: str, mats: dict):
    nz_r = BUS_X * 0.03
    nz_h = BUS_Y * 0.06
    corners = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
    for i, (cx, cz) in enumerate(corners):
        nz_path = f"{root_path}/Thruster_{i}"
        nz = UsdGeom.Cone.Define(stage, nz_path)
        nz.GetRadiusAttr().Set(nz_r)
        nz.GetHeightAttr().Set(nz_h)
        _xform(nz,
               translate=(cx * (BUS_X / 2 - nz_r), -BUS_Y / 2 - nz_h * 0.5,
                          cz * (BUS_Z / 2 - nz_r)),
               rotate=(180, 0, 0))
        _bind(stage, nz_path, mats["nozzle"])


# ── Docking Ring ────────────────────────────────────────────

def _build_docking_ring(stage, root_path: str, mats: dict):
    ring_r = BUS_X * 0.15
    ring_h = BUS_Z * 0.02
    ring_path = f"{root_path}/DockingRing"
    ring = UsdGeom.Cylinder.Define(stage, ring_path)
    ring.GetRadiusAttr().Set(ring_r)
    ring.GetHeightAttr().Set(ring_h)
    _xform(ring,
           translate=(0, 0, BUS_Z / 2 + ring_h / 2),
           rotate=(90, 0, 0))
    _bind(stage, ring_path, mats["frame"])
