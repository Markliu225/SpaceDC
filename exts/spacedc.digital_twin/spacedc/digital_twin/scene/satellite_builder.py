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
import os
from typing import Optional

try:
    from pxr import Usd, UsdGeom, UsdShade, Sdf, Gf, Vt
    HAS_USD = True
except ImportError:
    HAS_USD = False


# ── Visual scaling ──────────────────────────────────────────
# JS original: bus 0.14×0.10×0.16 with earth r=2.0
# Omniverse: uniform ×100 → bus 14×10×16 cm, earth r=200 cm
BUS_X, BUS_Y, BUS_Z = 24.0, 16.0, 32.0

# Ship a higher-fidelity USDZ asset and fall back to the procedural model if it
# is missing or cannot be referenced. These values are intentionally easy to tune.
BEAUTY_MODEL_FILE = "compute_satellite_hero_blender.usda"
BEAUTY_MODEL_PRIMS = ("/ComputeSatelliteHero",)
BEAUTY_MODEL_ROTATE = (0.0, 0.0, 0.0)
BEAUTY_MODEL_TARGET_SIZE = 3000.0  # cm, longest side after auto-fit
BEAUTY_MODEL_HIDE_TOKENS = ()
BEAUTY_MODEL_USE_SOURCE_MATERIALS = True
BEAUTY_MODEL_BODY_HALF = (92.0, 56.0, 72.0)  # cm, used for close-up framing


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


def _get_model_path(filename: str) -> str:
    """Resolve an absolute path inside data/models/."""
    this_dir = os.path.dirname(os.path.abspath(__file__))
    ext_root = os.path.normpath(os.path.join(this_dir, "..", "..", ".."))
    rel_path = filename.replace("/", os.sep)
    return os.path.join(ext_root, "data", "models", rel_path)


def _compute_local_bbox(prim) -> Optional["Gf.Range3d"]:
    """Return an aligned local-space bbox for a prim, or None if empty."""
    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy],
    )
    bbox = bbox_cache.ComputeLocalBound(prim)
    aligned = bbox.ComputeAlignedRange()
    if aligned.IsEmpty():
        return None
    return aligned


def _find_first_bbox_in_subtree(root_prim):
    """Return the first non-empty bbox found in a referenced subtree."""
    direct = _compute_local_bbox(root_prim)
    if direct is not None:
        return str(root_prim.GetPath()), direct

    for prim in Usd.PrimRange(root_prim):
        if not prim.IsValid():
            continue
        bbox = _compute_local_bbox(prim)
        if bbox is not None:
            return str(prim.GetPath()), bbox
    return None, None


def _prepare_imported_subtree(root_prim) -> None:
    """Force referenced geometry to be render-visible in the current stage."""
    for prim in Usd.PrimRange(root_prim):
        if not prim.IsValid():
            continue
        if prim.IsA(UsdGeom.Xformable):
            xformable = UsdGeom.Xformable(prim)
            try:
                if xformable.GetResetXformStack():
                    xformable.SetResetXformStack(False)
            except Exception:
                pass
        if prim.IsA(UsdGeom.Imageable):
            imageable = UsdGeom.Imageable(prim)
            imageable.MakeVisible()
            purpose_attr = imageable.GetPurposeAttr()
            if purpose_attr:
                purpose_attr.Set(UsdGeom.Tokens.default_)
        if prim.IsA(UsdGeom.Gprim):
            gprim = UsdGeom.Gprim(prim)
            gprim.GetDoubleSidedAttr().Set(True)
            prim.CreateAttribute(
                "primvars:doNotCastShadows",
                Sdf.ValueTypeNames.Bool,
                custom=False,
            ).Set(True)


def _hide_imported_prims_by_name(root_prim, tokens) -> None:
    token_set = tuple(t.lower() for t in tokens)
    for prim in Usd.PrimRange(root_prim):
        if not prim.IsValid():
            continue
        name = prim.GetName().lower()
        if any(token in name for token in token_set) and prim.IsA(UsdGeom.Imageable):
            try:
                UsdGeom.Imageable(prim).MakeInvisible()
            except Exception:
                pass


def _compute_filtered_local_bbox(root_prim, hidden_tokens) -> Optional["Gf.Range3d"]:
    hidden_tokens = tuple(t.lower() for t in hidden_tokens)
    combined = None
    for prim in Usd.PrimRange(root_prim):
        if not prim.IsValid() or not prim.IsA(UsdGeom.Gprim):
            continue
        name = prim.GetName().lower()
        if any(token in name for token in hidden_tokens):
            continue
        bbox = _compute_local_bbox(prim)
        if bbox is None:
            continue
        if combined is None:
            combined = Gf.Range3d(bbox.GetMin(), bbox.GetMax())
        else:
            combined.UnionWith(bbox)
    return combined


def _create_preview_material(
    stage,
    path: str,
    color,
    metallic=0.35,
    roughness=0.45,
    specular_color=None,
    clearcoat=None,
    clearcoat_roughness=None,
):
    mat = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, f"{path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(metallic)
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
    if specular_color is not None:
        shader.CreateInput("specularColor", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(*specular_color)
        )
    if clearcoat is not None:
        shader.CreateInput("clearcoat", Sdf.ValueTypeNames.Float).Set(clearcoat)
    if clearcoat_roughness is not None:
        shader.CreateInput("clearcoatRoughness", Sdf.ValueTypeNames.Float).Set(clearcoat_roughness)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return mat


def _srgb_channel_to_linear(channel: float) -> float:
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def _hex_color(hex_value: str):
    """Convert an sRGB #RRGGBB color string to linear 0-1 RGB."""
    hex_value = hex_value.strip().lstrip("#")
    if len(hex_value) != 6:
        raise ValueError(f"Expected 6 hex digits, got: {hex_value}")
    rgb = tuple(
        _srgb_channel_to_linear(int(hex_value[i:i + 2], 16) / 255.0)
        for i in range(0, 6, 2)
    )
    return rgb


def _get_direct_binding_targets(prim) -> list[str]:
    try:
        rel = UsdShade.MaterialBindingAPI(prim).GetDirectBindingRel()
        if not rel:
            return []
        return [str(t).lower() for t in rel.GetTargets()]
    except Exception:
        return []


def _get_imported_context_text(prim, stop_prim) -> str:
    """Collect names + direct bindings from a prim and its ancestor chain."""
    tokens = []
    current = prim
    stop_path = stop_prim.GetPath() if stop_prim and stop_prim.IsValid() else None

    while current and current.IsValid():
        tokens.append(current.GetName().lower())
        tokens.extend(_get_direct_binding_targets(current))
        if stop_path and current.GetPath() == stop_path:
            break
        parent = current.GetParent()
        if not parent or not parent.IsValid() or parent == current:
            break
        current = parent

    return " ".join(tokens)


def _classify_imported_material(prim_path: str, binding_text: str) -> str:
    text = (binding_text or prim_path).lower()
    if any(token in text for token in ("transparent", "clear")):
        return "transparent"
    if any(token in text for token in ("shiny_panel", "shiny panel", "tex_01", "tex 01", "tex_02", "tex 02", "solar", "panel", "array")):
        return "solar"
    if any(token in text for token in ("black_krinkle", "black krinkle", "krinkle", "black")):
        return "black"
    if any(token in text for token in ("foil_gold", "foil gold", "gold", "mli", "blanket", "body", "bus", "core")):
        return "gold"
    if any(token in text for token in ("foil_silver2", "foil silver antenna", "antenna", "dish", "boom", "hinge")):
        return "silver"
    if any(token in text for token in ("foil_silver", "foil silver", "silver")):
        return "metal"
    return "metal"


def _apply_fallback_imported_colors(stage: "Usd.Stage", root_path: str, root_prim) -> None:
    """Apply simple preview materials when the source asset materials don't bind."""
    mat_root = f"{root_path}/ImportedFallbackMaterials"
    mats = {
        "solar": _create_preview_material(
            stage,
            f"{mat_root}/Solar",
            _hex_color("#0E3E63"),
            0.9,
            0.10,
            specular_color=_hex_color("#6D8FB5"),
            clearcoat=0.82,
            clearcoat_roughness=0.08,
        ),
        # Kapton-style MLI: bright amber-gold base with stronger metallic sheen.
        "gold": _create_preview_material(
            stage,
            f"{mat_root}/Gold",
            _hex_color("#EC8714"),
            0.89,
            0.02,
            specular_color=_hex_color("#E9AE0B"),
            clearcoat=0.9,
            clearcoat_roughness=0.5,
        ),
        "silver": _create_preview_material(
            stage,
            f"{mat_root}/Silver",
            _hex_color("#D0D3D8"),
            0.82,
            0.10,
            specular_color=_hex_color("#FFF1A0"),
            clearcoat=0.18,
            clearcoat_roughness=0.06,
        ),
        "black": _create_preview_material(
            stage,
            f"{mat_root}/Black",
            _hex_color("#1A1A1A"),
            0.9,
            0.02,
            specular_color=_hex_color("#5C6470"),
            clearcoat=0.88,
            clearcoat_roughness=0.5,
        ),
        "metal": _create_preview_material(
            stage,
            f"{mat_root}/Metal",
            _hex_color("#8B9098"),
            0.74,
            0.12,
            specular_color=_hex_color("#E8ECF0"),
            clearcoat=0.14,
            clearcoat_roughness=0.07,
        ),
        "transparent": _create_preview_material(stage, f"{mat_root}/Transparent", (0.0, 0.0, 0.0), 0.0, 1.0),
    }
    transparent_shader = UsdShade.Shader.Get(stage, f"{mat_root}/Transparent/Shader")
    transparent_shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(0.02)

    bound_subset_count = 0
    bound_gprim_count = 0
    class_counts = {}
    samples = []

    for prim in Usd.PrimRange(root_prim):
        if not prim.IsValid():
            continue

        prim_path = str(prim.GetPath()).lower()
        binding_text = _get_imported_context_text(prim, root_prim)

        # Preserve sub-mesh material splits by binding fallback materials to
        # subsets first, then only tint bare gprims that don't already have
        # more specific material-bound children.
        if prim.IsA(UsdGeom.Subset) and _get_direct_binding_targets(prim):
            mat_key = _classify_imported_material(prim_path, binding_text)
            UsdShade.MaterialBindingAPI(prim).Bind(mats[mat_key])
            bound_subset_count += 1
            class_counts[mat_key] = class_counts.get(mat_key, 0) + 1
            if len(samples) < 6:
                samples.append(f"{prim.GetName()}->{mat_key}")
            continue

        if not prim.IsA(UsdGeom.Gprim):
            continue

        has_bound_subset_child = False
        for child in prim.GetChildren():
            if child.IsA(UsdGeom.Subset) and _get_direct_binding_targets(child):
                has_bound_subset_child = True
                break
        if has_bound_subset_child:
            continue

        mat_key = _classify_imported_material(prim_path, binding_text)
        UsdShade.MaterialBindingAPI(prim).Bind(mats[mat_key])
        bound_gprim_count += 1
        class_counts[mat_key] = class_counts.get(mat_key, 0) + 1
        if len(samples) < 6:
            samples.append(f"{prim.GetName()}->{mat_key}")

    print(
        "[SpaceDC] Applied imported fallback colors:",
        f"subsets={bound_subset_count}",
        f"gprims={bound_gprim_count}",
        "classes=" + ",".join(f"{k}:{v}" for k, v in sorted(class_counts.items())),
        "samples=" + ",".join(samples),
    )


def _build_imported_satellite(stage: "Usd.Stage", root_path: str) -> bool:
    """
    Reference a packaged spacecraft asset under /World/Satellite/Bus.

    The imported asset is treated as a higher-fidelity full spacecraft model.
    When it loads successfully, the procedural satellite geometry is skipped.
    """
    if os.environ.get("SPACEDC_DISABLE_BEAUTY_MODEL", "").lower() in {"1", "true", "yes"}:
        return False
    if not BEAUTY_MODEL_FILE:
        return False

    model_path = _get_model_path(BEAUTY_MODEL_FILE)
    if not os.path.isfile(model_path):
        return False

    beauty_root = UsdGeom.Xform.Define(stage, f"{root_path}/Bus")
    beauty_prim = beauty_root.GetPrim()
    fit_xf = UsdGeom.Xform.Define(stage, f"{root_path}/Bus/Fit")
    asset_root = UsdGeom.Xform.Define(stage, f"{root_path}/Bus/Fit/AssetRoot")
    ref_prim = asset_root.GetPrim()

    bbox = None
    chosen_prim = None
    bbox_source = None
    for prim_path in BEAUTY_MODEL_PRIMS:
        ref_prim.GetReferences().ClearReferences()
        try:
            ref_prim.GetReferences().AddReference(
                model_path.replace("\\", "/"),
                primPath=Sdf.Path(prim_path),
            )
        except Exception:
            continue

        _prepare_imported_subtree(ref_prim)
        _hide_imported_prims_by_name(ref_prim, BEAUTY_MODEL_HIDE_TOKENS)
        bbox = _compute_filtered_local_bbox(ref_prim, BEAUTY_MODEL_HIDE_TOKENS)
        bbox_source = str(ref_prim.GetPath())
        if bbox is not None:
            chosen_prim = prim_path
            break

    if bbox is None:
        print(f"[SpaceDC] WARNING: Imported model bbox is empty for all prim candidates: {model_path}")
        return False

    _prepare_imported_subtree(asset_root.GetPrim())
    _hide_imported_prims_by_name(asset_root.GetPrim(), BEAUTY_MODEL_HIDE_TOKENS)
    materials_mode = "source_materials"
    if not BEAUTY_MODEL_USE_SOURCE_MATERIALS:
        _apply_fallback_imported_colors(stage, root_path, asset_root.GetPrim())
        materials_mode = "fallback_preview"

    size = bbox.GetSize()
    center = bbox.GetMidpoint()
    longest = max(size[0], size[1], size[2], 1e-5)
    fit_scale = BEAUTY_MODEL_TARGET_SIZE / longest

    # Center the imported geometry under /World/Satellite so the orbit
    # translation, micro camera and zoom all share the same local origin.
    _xform(asset_root, translate=(-center[0], -center[1], -center[2]))
    _xform(fit_xf, scale=(fit_scale, fit_scale, fit_scale))
    _xform(beauty_root, rotate=BEAUTY_MODEL_ROTATE)

    body_half_x = size[0] * fit_scale * 0.5
    body_half_y = size[1] * fit_scale * 0.5
    body_half_z = size[2] * fit_scale * 0.5
    model_half_x = body_half_x
    model_half_y = body_half_y
    model_half_z = body_half_z
    if BEAUTY_MODEL_BODY_HALF is not None:
        body_half_x, body_half_y, body_half_z = BEAUTY_MODEL_BODY_HALF

    beauty_prim.CreateAttribute("spacedc:body_half_x", Sdf.ValueTypeNames.Float).Set(body_half_x)
    beauty_prim.CreateAttribute("spacedc:body_half_y", Sdf.ValueTypeNames.Float).Set(body_half_y)
    beauty_prim.CreateAttribute("spacedc:body_half_z", Sdf.ValueTypeNames.Float).Set(body_half_z)
    beauty_prim.CreateAttribute("spacedc:model_half_x", Sdf.ValueTypeNames.Float).Set(model_half_x)
    beauty_prim.CreateAttribute("spacedc:model_half_y", Sdf.ValueTypeNames.Float).Set(model_half_y)
    beauty_prim.CreateAttribute("spacedc:model_half_z", Sdf.ValueTypeNames.Float).Set(model_half_z)

    print(
        "[SpaceDC] Imported beauty model bbox:",
        f"prim={chosen_prim}",
        f"bbox_source={bbox_source}",
        f"size=({size[0]:.3f}, {size[1]:.3f}, {size[2]:.3f})",
        f"center=({center[0]:.3f}, {center[1]:.3f}, {center[2]:.3f})",
        f"scale={fit_scale:.3f}",
        f"model_half=({model_half_x:.3f}, {model_half_y:.3f}, {model_half_z:.3f})",
        f"materials_mode={materials_mode}",
    )
    return True


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

    beauty_loaded = False
    try:
        beauty_loaded = _build_imported_satellite(stage, root_path)
        if beauty_loaded:
            print(f"[SpaceDC] Beauty satellite asset loaded: {BEAUTY_MODEL_FILE}")
    except Exception as exc:
        print(f"[SpaceDC] WARNING: Failed to load beauty satellite asset: {exc}")

    mats = _create_materials(stage, root_path)

    if not beauty_loaded:
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
        "bus":     _mat("BusMat",     (0.09, 0.10, 0.12), 0.62, 0.34),
        "busEdge": _mat("BusEdgeMat", (0.18, 0.20, 0.22), 0.68, 0.22),
        "shell":   _mat("ShellMat",   (0.12, 0.13, 0.16), 0.58, 0.30),
        "gold":    _mat("GoldMat",    _hex_color("#ECA414"), 0.52, 0.10),
        "grille":  _mat("GrilleMat",  (0.05, 0.05, 0.06), 0.25, 0.74),
        "solar":   _mat("SolarMat",   _hex_color("#0B3B60"), 0.18, 0.08),
        "frame":   _mat("FrameMat",   (0.34, 0.35, 0.38), 0.68, 0.22),
        "rad":     _mat("RadMat",     (0.88, 0.89, 0.92), 0.12, 0.48),
        "radDark": _mat("RadDarkMat", (0.60, 0.64, 0.70), 0.18, 0.34),
        "copper":  _mat("CopperMat",  (0.72, 0.45, 0.20), 0.84, 0.24),
        "dark":    _mat("DarkMat",    (0.07, 0.07, 0.07), 0.54, 0.46),
        "rack":    _mat("RackMat",    (0.13, 0.15, 0.18), 0.58, 0.26),
        "glass":   _mat("GlassMat",   (0.18, 0.34, 0.46), 0.05, 0.08),
        "antenna": _mat("AntennaMat", (0.73, 0.73, 0.73), 0.55, 0.28),
        "nozzle":  _mat("NozzleMat",  (0.23, 0.23, 0.24), 0.72, 0.28),
        "accent":  _mat("AccentMat",  (0.12, 0.22, 0.32), 0.56, 0.24),
        "led_green": _mat("LedGreen", (0.2, 0.93, 0.4),   0.0,  0.1),
        "led_blue":  _mat("LedBlue",  (0.0, 0.73, 1.0),   0.0,  0.1),
        "led_amber": _mat("LedAmber", (1.0, 0.67, 0.13),  0.0,  0.1),
    }


def _bind(stage, prim_path: str, mat: "UsdShade.Material"):
    """Bind a material to a prim."""
    prim = stage.GetPrimAtPath(prim_path)
    if prim.IsValid():
        UsdShade.MaterialBindingAPI(prim).Bind(mat)
        _disable_cast_shadows(stage, prim_path)


def _disable_cast_shadows(stage, prim_path: str):
    """Disable RTX cast shadows on a geometry prim."""
    prim = stage.GetPrimAtPath(prim_path)
    if prim.IsValid():
        prim.CreateAttribute(
            "primvars:doNotCastShadows",
            Sdf.ValueTypeNames.Bool,
            custom=False,
        ).Set(True)


def _box(stage, path: str, translate, scale, mat, rotate=None):
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(1.0)
    _xform(cube, translate=translate, rotate=rotate, scale=scale)
    _bind(stage, path, mat)
    return cube


def _cylinder(stage, path: str, radius: float, height: float, translate, mat, rotate=None):
    cyl = UsdGeom.Cylinder.Define(stage, path)
    cyl.GetRadiusAttr().Set(radius)
    cyl.GetHeightAttr().Set(height)
    _xform(cyl, translate=translate, rotate=rotate)
    _bind(stage, path, mat)
    return cyl


def _sphere(stage, path: str, radius: float, translate, mat, rotate=None):
    sphere = UsdGeom.Sphere.Define(stage, path)
    sphere.GetRadiusAttr().Set(radius)
    _xform(sphere, translate=translate, rotate=rotate)
    _bind(stage, path, mat)
    return sphere


def _cone(stage, path: str, radius: float, height: float, translate, mat, rotate=None):
    cone = UsdGeom.Cone.Define(stage, path)
    cone.GetRadiusAttr().Set(radius)
    cone.GetHeightAttr().Set(height)
    _xform(cone, translate=translate, rotate=rotate)
    _bind(stage, path, mat)
    return cone


def _wing_profile(wing_count: int, wing_area: float) -> dict:
    segments = max(6, min(12, int(max(wing_count, 1))))
    area_scale = max(0.75, min(1.65, math.sqrt(max(wing_area, 80.0) / 350.0)))
    segment_len = 5.4 * area_scale
    panel_chord = 8.8 * area_scale
    panel_gap = 0.34
    boom_len = BUS_X * 0.78
    mast_height = BUS_Y * 0.26
    root_x = BUS_X / 2 + boom_len
    total_span = segments * segment_len + (segments - 1) * panel_gap
    return {
        "segments": segments,
        "segment_len": segment_len,
        "panel_chord": panel_chord,
        "panel_gap": panel_gap,
        "boom_len": boom_len,
        "mast_height": mast_height,
        "root_x": root_x,
        "total_span": total_span,
        "panel_thickness": BUS_Y * 0.018,
        "radiator_thickness": BUS_Y * 0.014,
    }


def _long_sail_profile(count_hint: int, area_hint: float) -> dict:
    segments = max(18, min(28, int(max(count_hint, 8)) * 2 + 2))
    area_scale = max(1.00, min(1.55, math.sqrt(max(area_hint, 360.0) / 520.0)))
    panel_gap = 1.10
    target_span = BUS_X * 36.0 * area_scale
    segment_len = max(18.0, (target_span - (segments - 1) * panel_gap) / segments)
    panel_chord = BUS_Z * 1.45 * area_scale
    boom_len = BUS_X * 1.28
    mast_height = BUS_Y * 0.54
    root_x = BUS_X / 2 + boom_len
    total_span = segments * segment_len + (segments - 1) * panel_gap
    return {
        "segments": segments,
        "segment_len": segment_len,
        "panel_chord": panel_chord,
        "panel_gap": panel_gap,
        "boom_len": boom_len,
        "mast_height": mast_height,
        "root_x": root_x,
        "total_span": total_span,
        "panel_thickness": BUS_Y * 0.008,
        "radiator_thickness": BUS_Y * 0.012,
    }


def _build_compute_core(stage, root_path: str, mats: dict):
    core_root = f"{root_path}/ComputeCore"
    UsdGeom.Xform.Define(stage, core_root)

    bus_prim = stage.GetPrimAtPath(f"{root_path}/Bus")
    body_half_x = BUS_X * 0.5
    body_half_y = BUS_Y * 0.5
    body_half_z = BUS_Z * 0.5
    if bus_prim and bus_prim.IsValid():
        try:
            body_half_x = float(bus_prim.GetAttribute("spacedc:body_half_x").Get() or body_half_x)
            body_half_y = float(bus_prim.GetAttribute("spacedc:body_half_y").Get() or body_half_y)
            body_half_z = float(bus_prim.GetAttribute("spacedc:body_half_z").Get() or body_half_z)
        except Exception:
            pass

    deck_y = -body_half_y * 0.22
    rack_z = body_half_z * 0.46
    bay_depth = body_half_z * 0.42
    rack_w = max(10.0, body_half_x * 0.18)
    rack_h = max(8.0, body_half_y * 0.22)
    rack_d = max(8.0, bay_depth * 0.65)

    _box(
        stage,
        f"{core_root}/BaseDeck",
        (0, deck_y - body_half_y * 0.34, body_half_z * 0.02),
        (body_half_x * 1.05, BUS_Y * 0.06, body_half_z * 0.84),
        mats["frame"],
    )
    _box(
        stage,
        f"{core_root}/UpperCanopy",
        (0, deck_y + body_half_y * 0.48, body_half_z * 0.00),
        (body_half_x * 1.00, BUS_Y * 0.04, body_half_z * 0.76),
        mats["dark"],
    )
    _box(
        stage,
        f"{core_root}/RearBulkhead",
        (0, deck_y, rack_z - bay_depth * 0.62),
        (body_half_x * 0.98, body_half_y * 0.82, BUS_Y * 0.05),
        mats["shell"],
    )
    for side_name, sx in (("Port", -1), ("Starboard", 1)):
        _box(
            stage,
            f"{core_root}/{side_name}Rail",
            (sx * body_half_x * 0.96, deck_y, rack_z - bay_depth * 0.02),
            (BUS_Y * 0.04, body_half_y * 0.78, bay_depth * 0.98),
            mats["frame"],
        )

    cols = 4
    rows = 3
    col_spacing = body_half_x * 0.52 / max(cols - 1, 1)
    row_spacing = body_half_y * 0.48 / max(rows - 1, 1)
    start_x = -col_spacing * 1.5
    start_y = deck_y - row_spacing

    rack_index = 0
    for row in range(rows):
        for col in range(cols):
            x_pos = start_x + col * col_spacing
            y_pos = start_y + row * row_spacing
            rack_root = f"{core_root}/ServerRack_{rack_index}"
            UsdGeom.Xform.Define(stage, rack_root)
            _box(stage, f"{rack_root}/Cabinet", (x_pos, y_pos, rack_z), (rack_w, rack_h, rack_d), mats["rack"])
            _box(stage, f"{rack_root}/DoorFrame", (x_pos, y_pos, rack_z + rack_d * 0.53), (rack_w * 0.94, rack_h * 0.94, BUS_Y * 0.010), mats["frame"])
            _box(stage, f"{rack_root}/Glass", (x_pos, y_pos, rack_z + rack_d * 0.55), (rack_w * 0.76, rack_h * 0.80, BUS_Y * 0.006), mats["glass"])
            for blade in range(8):
                blade_y = y_pos - rack_h * 0.34 + blade * rack_h * 0.10
                _box(
                    stage,
                    f"{rack_root}/Blade_{blade}",
                    (x_pos, blade_y, rack_z + rack_d * 0.28),
                    (rack_w * 0.72, rack_h * 0.038, BUS_Y * 0.007),
                    mats["dark"],
                )
            for led_idx in range(6):
                led_y = y_pos - rack_h * 0.30 + led_idx * rack_h * 0.12
                led_mat = mats["led_blue"] if led_idx % 2 == 0 else mats["led_amber"]
                _box(
                    stage,
                    f"{rack_root}/Led_{led_idx}",
                    (x_pos - rack_w * 0.26, led_y, rack_z + rack_d * 0.58),
                    (rack_w * 0.05, rack_h * 0.03, BUS_Y * 0.006),
                    led_mat,
                )
            _box(
                stage,
                f"{rack_root}/ColdPlate",
                (x_pos, y_pos - rack_h * 0.38, rack_z - rack_d * 0.16),
                (rack_w * 0.88, rack_h * 0.05, rack_d * 0.76),
                mats["radDark"],
            )
            rack_index += 1

    for side_name, sx in (("Port", -1), ("Starboard", 1)):
        manifold_x = sx * body_half_x * 0.72
        _cylinder(
            stage,
            f"{core_root}/{side_name}CoolantManifold",
            BUS_Y * 0.018,
            body_half_y * 1.05,
            (manifold_x, deck_y, rack_z - bay_depth * 0.02),
            mats["copper"],
        )
        for row in range(rows):
            y_pos = start_y + row * row_spacing
            _cylinder(
                stage,
                f"{core_root}/{side_name}Branch_{row}",
                BUS_Y * 0.008,
                body_half_x * 0.78,
                (0, y_pos, rack_z - bay_depth * 0.20),
                mats["copper"],
                rotate=(0, 0, 90),
            )

    _box(
        stage,
        f"{core_root}/FrontHeader",
        (0, deck_y + body_half_y * 0.50, rack_z + rack_d * 0.32),
        (body_half_x * 0.86, BUS_Y * 0.028, BUS_Y * 0.030),
        mats["frame"],
    )
    _sphere(
        stage,
        f"{core_root}/StatusNode",
        BUS_Y * 0.030,
        (0, deck_y + body_half_y * 0.50, rack_z + rack_d * 0.56),
        mats["led_green"],
    )


# ── Bus ─────────────────────────────────────────────────────

def _build_bus(stage, root_path: str, mats: dict):
    bus_root = f"{root_path}/Bus"
    UsdGeom.Xform.Define(stage, bus_root)
    deck_t = BUS_Y * 0.030
    rail_t = BUS_Y * 0.020
    frame_r = BUS_Y * 0.024
    cavity_x = BUS_X * 0.72
    cavity_y = BUS_Y * 0.70
    cavity_z = BUS_Z * 0.82
    half_x = cavity_x * 0.5
    half_y = cavity_y * 0.5
    half_z = cavity_z * 0.5
    open_z = BUS_Z / 2 - BUS_Z * 0.045
    aft_z = -BUS_Z / 2 + BUS_Z * 0.06

    _box(stage, f"{bus_root}/TopDeck", (0, half_y, -BUS_Z * 0.04), (BUS_X * 0.88, deck_t, BUS_Z * 0.74), mats["shell"])
    _box(stage, f"{bus_root}/BottomDeck", (0, -half_y, -BUS_Z * 0.02), (BUS_X * 0.90, deck_t, BUS_Z * 0.82), mats["bus"])
    _box(stage, f"{bus_root}/MidKeel", (0, -BUS_Y * 0.06, -BUS_Z * 0.06), (BUS_X * 0.16, BUS_Y * 0.52, BUS_Z * 0.78), mats["busEdge"])

    for ix, sx in enumerate((-1, 1)):
        for iz, sz in enumerate((-1, 1)):
            _cylinder(
                stage,
                f"{bus_root}/Longeron_{ix}_{iz}",
                frame_r,
                cavity_y,
                (sx * half_x, 0, sz * half_z),
                mats["frame"],
            )

    for iy, sy in enumerate((-1, 1)):
        y_pos = sy * half_y
        for iz, sz in enumerate((-1, 1)):
            _cylinder(
                stage,
                f"{bus_root}/CrossTube_{iy}_{iz}",
                frame_r * 0.88,
                cavity_x,
                (0, y_pos, sz * half_z),
                mats["frame"],
                rotate=(0, 0, 90),
            )
        for ix, sx in enumerate((-1, 1)):
            _cylinder(
                stage,
                f"{bus_root}/SideRail_{iy}_{ix}",
                frame_r * 0.88,
                cavity_z,
                (sx * half_x, y_pos, 0),
                mats["frame"],
                rotate=(90, 0, 0),
            )

    for side_name, sx in (("Port", -1), ("Starboard", 1)):
        for idx, sy in enumerate((-1, 1)):
            angle = -28 * sx * sy
            _box(
                stage,
                f"{bus_root}/{side_name}Facet_{idx}",
                (sx * (BUS_X * 0.47), sy * (BUS_Y * 0.15), -BUS_Z * 0.02),
                (BUS_X * 0.03, BUS_Y * 0.34, BUS_Z * 0.70),
                mats["gold"],
                rotate=(0, 0, angle),
            )
    _box(stage, f"{bus_root}/AftBlanket", (0, 0, aft_z), (BUS_X * 0.78, BUS_Y * 0.70, BUS_Z * 0.028), mats["gold"])
    _box(stage, f"{bus_root}/TopBlanket", (0, BUS_Y * 0.34, -BUS_Z * 0.02), (BUS_X * 0.82, BUS_Y * 0.06, BUS_Z * 0.64), mats["gold"])
    _box(stage, f"{bus_root}/LowerChine", (0, -BUS_Y * 0.28, BUS_Z * 0.02), (BUS_X * 0.82, BUS_Y * 0.05, BUS_Z * 0.70), mats["shell"], rotate=(10, 0, 0))

    band_root = f"{root_path}/GoldBand"
    UsdGeom.Xform.Define(stage, band_root)
    _box(stage, f"{band_root}/SunCanopy", (0, BUS_Y * 0.38, BUS_Z * 0.06), (BUS_X * 0.74, BUS_Y * 0.030, BUS_Z * 0.42), mats["gold"], rotate=(-12, 0, 0))
    _box(stage, f"{band_root}/PortSkirt", (-BUS_X * 0.44, 0, -BUS_Z * 0.02), (BUS_X * 0.018, BUS_Y * 0.56, BUS_Z * 0.62), mats["gold"], rotate=(0, 0, -22))
    _box(stage, f"{band_root}/StarboardSkirt", (BUS_X * 0.44, 0, -BUS_Z * 0.02), (BUS_X * 0.018, BUS_Y * 0.56, BUS_Z * 0.62), mats["gold"], rotate=(0, 0, 22))
    for seam_idx, z_pos in enumerate((-BUS_Z * 0.20, 0.0, BUS_Z * 0.20)):
        _box(
            stage,
            f"{band_root}/BlanketSeam_{seam_idx}",
            (0, BUS_Y * 0.34, z_pos),
            (BUS_X * 0.72, BUS_Y * 0.010, BUS_Y * 0.018),
            mats["frame"],
        )

    for side_name, sx in (("Port", -1), ("Starboard", 1)):
        root_root = f"{bus_root}/{side_name}ArrayRoot"
        UsdGeom.Xform.Define(stage, root_root)
        root_x = sx * (BUS_X * 0.40)
        _box(stage, f"{root_root}/Base", (root_x, 0, -BUS_Z * 0.06), (BUS_X * 0.08, BUS_Y * 0.28, BUS_Z * 0.26), mats["busEdge"])
        _cylinder(stage, f"{root_root}/Pivot", BUS_Y * 0.05, BUS_Y * 0.34, (root_x + sx * BUS_X * 0.02, BUS_Y * 0.04, 0), mats["frame"], rotate=(0, 0, 90))
        _box(stage, f"{root_root}/UpperFork", (root_x + sx * BUS_X * 0.06, BUS_Y * 0.14, 0), (BUS_X * 0.10, BUS_Y * 0.018, BUS_Z * 0.58), mats["frame"], rotate=(0, 0, sx * 10))
        _box(stage, f"{root_root}/LowerFork", (root_x + sx * BUS_X * 0.06, -BUS_Y * 0.14, 0), (BUS_X * 0.10, BUS_Y * 0.018, BUS_Z * 0.58), mats["frame"], rotate=(0, 0, -sx * 10))
        _cylinder(stage, f"{root_root}/Actuator", BUS_Y * 0.014, BUS_X * 0.20, (root_x + sx * BUS_X * 0.10, 0, -BUS_Z * 0.10), mats["copper"], rotate=(0, 0, 90))
        _sphere(stage, f"{root_root}/JointNode", BUS_Y * 0.026, (root_x + sx * BUS_X * 0.11, 0, 0), mats["frame"])

    top_pod_root = f"{bus_root}/TopPallet"
    UsdGeom.Xform.Define(stage, top_pod_root)
    _box(stage, f"{top_pod_root}/Deck", (0, BUS_Y * 0.26, -BUS_Z * 0.06), (BUS_X * 0.34, BUS_Y * 0.028, BUS_Z * 0.26), mats["frame"])
    for idx, sx in enumerate((-1, 1)):
        _cylinder(
            stage,
            f"{top_pod_root}/Tank_{idx}",
            BUS_Y * 0.050,
            BUS_Z * 0.22,
            (sx * BUS_X * 0.10, BUS_Y * 0.34, -BUS_Z * 0.06),
            mats["busEdge"],
            rotate=(90, 0, 0),
        )
    _box(stage, f"{top_pod_root}/Electronics", (0, BUS_Y * 0.31, BUS_Z * 0.08), (BUS_X * 0.22, BUS_Y * 0.10, BUS_Z * 0.12), mats["rack"])
    _cylinder(stage, f"{top_pod_root}/SensorBoom", BUS_Y * 0.010, BUS_Y * 0.44, (0, BUS_Y * 0.50, BUS_Z * 0.16), mats["frame"])
    _sphere(stage, f"{top_pod_root}/SensorHead", BUS_Y * 0.032, (0, BUS_Y * 0.73, BUS_Z * 0.16), mats["glass"])

    face_root = f"{root_path}/ServerFace"
    UsdGeom.Xform.Define(stage, face_root)
    _box(stage, f"{face_root}/TopRail", (0, BUS_Y * 0.22, open_z), (BUS_X * 0.66, rail_t, BUS_Z * 0.020), mats["frame"])
    _box(stage, f"{face_root}/BottomRail", (0, -BUS_Y * 0.22, open_z), (BUS_X * 0.66, rail_t, BUS_Z * 0.020), mats["frame"])
    _box(stage, f"{face_root}/PortRail", (-BUS_X * 0.33, 0, open_z), (rail_t, BUS_Y * 0.52, BUS_Z * 0.020), mats["frame"])
    _box(stage, f"{face_root}/StarboardRail", (BUS_X * 0.33, 0, open_z), (rail_t, BUS_Y * 0.52, BUS_Z * 0.020), mats["frame"])
    _box(stage, f"{face_root}/UpperVisor", (0, BUS_Y * 0.30, BUS_Z * 0.33), (BUS_X * 0.48, BUS_Y * 0.032, BUS_Z * 0.10), mats["accent"], rotate=(-20, 0, 0))
    _box(stage, f"{face_root}/LowerVisor", (0, -BUS_Y * 0.26, BUS_Z * 0.26), (BUS_X * 0.42, BUS_Y * 0.025, BUS_Z * 0.08), mats["accent"], rotate=(18, 0, 0))
    for idx, sx in enumerate((-1, 1)):
        _box(
            stage,
            f"{face_root}/Brace_{idx}",
            (sx * BUS_X * 0.22, 0, BUS_Z * 0.28),
            (BUS_Y * 0.04, BUS_Y * 0.46, BUS_Z * 0.02),
            mats["frame"],
            rotate=(0, 0, -sx * 24),
        )
    for slat_idx in range(8):
        slat_y = -BUS_Y * 0.18 + slat_idx * BUS_Y * 0.055
        _box(
            stage,
            f"{face_root}/GrilleSlat_{slat_idx}",
            (0, slat_y, BUS_Z * 0.48),
            (BUS_X * 0.58, BUS_Y * 0.010, BUS_Z * 0.010),
            mats["grille"],
        )
    for seam_idx in range(6):
        seam_x = -BUS_X * 0.24 + seam_idx * BUS_X * 0.096
        _box(
            stage,
            f"{face_root}/FaceMullion_{seam_idx}",
            (seam_x, 0, BUS_Z * 0.48),
            (BUS_Y * 0.008, BUS_Y * 0.40, BUS_Z * 0.010),
            mats["frame"],
        )

    payload_root = f"{bus_root}/PayloadBay"
    UsdGeom.Xform.Define(stage, payload_root)
    rack_w = BUS_X * 0.14
    rack_h = BUS_Y * 0.12
    rack_d = BUS_Z * 0.14
    x_positions = (-BUS_X * 0.17, BUS_X * 0.17)
    y_positions = (-BUS_Y * 0.27, -BUS_Y * 0.09, BUS_Y * 0.09, BUS_Y * 0.27)

    _box(stage, f"{payload_root}/ServiceTunnel", (0, 0, -BUS_Z * 0.12), (BUS_X * 0.11, BUS_Y * 0.62, BUS_Z * 0.60), mats["frame"])
    _box(stage, f"{payload_root}/CableBridge", (0, BUS_Y * 0.19, BUS_Z * 0.00), (BUS_X * 0.48, BUS_Y * 0.03, BUS_Z * 0.44), mats["frame"])
    for brace_idx, sx in enumerate((-1, 1)):
        _box(
            stage,
            f"{payload_root}/CatwalkBrace_{brace_idx}",
            (sx * BUS_X * 0.18, BUS_Y * 0.14, BUS_Z * 0.06),
            (BUS_X * 0.22, BUS_Y * 0.012, BUS_Y * 0.02),
            mats["frame"],
            rotate=(0, 0, -sx * 26),
        )

    rack_index = 0
    for x_pos in x_positions:
        for y_pos in y_positions:
            rack_root = f"{payload_root}/ServerRack_{rack_index}"
            UsdGeom.Xform.Define(stage, rack_root)
            _box(stage, f"{rack_root}/Cabinet", (x_pos, y_pos, -BUS_Z * 0.02), (rack_w, rack_h, rack_d), mats["rack"])
            _box(stage, f"{rack_root}/FrontFrame", (x_pos, y_pos, rack_d * 0.52), (rack_w * 0.92, rack_h * 0.92, BUS_Z * 0.010), mats["grille"])
            _box(stage, f"{rack_root}/ColdPlate", (x_pos, y_pos, -rack_d * 0.40), (rack_w * 0.88, rack_h * 0.08, rack_d * 0.72), mats["radDark"])
            for blade in range(6):
                blade_y = y_pos - rack_h * 0.34 + blade * rack_h * 0.135
                _box(
                    stage,
                    f"{rack_root}/Blade_{blade}",
                    (x_pos, blade_y, rack_d * 0.36),
                    (rack_w * 0.76, rack_h * 0.05, BUS_Z * 0.010),
                    mats["dark"],
                )
            for handle_idx, handle_x in enumerate((-rack_w * 0.34, rack_w * 0.34)):
                _cylinder(
                    stage,
                    f"{rack_root}/Handle_{handle_idx}",
                    BUS_Y * 0.006,
                    rack_h * 0.76,
                    (x_pos + handle_x, y_pos, rack_d * 0.54),
                    mats["frame"],
                )
            for led_idx in range(4):
                led_y = y_pos - rack_h * 0.24 + led_idx * rack_h * 0.17
                led_mat = mats["led_blue"] if led_idx % 2 == 0 else mats["led_amber"]
                _box(
                    stage,
                    f"{rack_root}/Led_{led_idx}",
                    (x_pos - rack_w * 0.24, led_y, rack_d * 0.56),
                    (rack_w * 0.06, rack_h * 0.04, BUS_Z * 0.008),
                    led_mat,
                )
            _cylinder(
                stage,
                f"{rack_root}/CoolantPipe",
                BUS_Y * 0.010,
                rack_h * 1.16,
                (x_pos + rack_w * 0.30, y_pos, -BUS_Z * 0.02),
                mats["copper"],
                rotate=(0, 0, 90),
            )
            rack_index += 1

    _cylinder(stage, f"{payload_root}/PortManifold", BUS_Y * 0.020, cavity_z * 0.72, (-BUS_X * 0.28, BUS_Y * 0.18, -BUS_Z * 0.04), mats["copper"], rotate=(90, 0, 0))
    _cylinder(stage, f"{payload_root}/StarboardManifold", BUS_Y * 0.020, cavity_z * 0.72, (BUS_X * 0.28, BUS_Y * 0.18, -BUS_Z * 0.04), mats["copper"], rotate=(90, 0, 0))
    _box(stage, f"{payload_root}/ServiceGantry", (0, BUS_Y * 0.29, -BUS_Z * 0.04), (BUS_X * 0.40, BUS_Y * 0.032, BUS_Z * 0.46), mats["frame"])
    _box(stage, f"{payload_root}/ServiceGlass", (0, BUS_Y * 0.22, BUS_Z * 0.18), (BUS_X * 0.16, BUS_Y * 0.05, BUS_Z * 0.06), mats["glass"])
    _sphere(stage, f"{payload_root}/CoreNode", BUS_Y * 0.034, (0, 0, BUS_Z * 0.08), mats["led_green"])


# ── Solar Wings ─────────────────────────────────────────────

def _build_solar_wings(stage, root_path: str, mats: dict, wing_count: int, wing_area: float):
    wings_root = f"{root_path}/SolarWings"
    wings_prim = UsdGeom.Xform.Define(stage, wings_root).GetPrim()
    profile = _long_sail_profile(max(wing_count, 8), max(wing_area, 520.0))
    bus_prim = stage.GetPrimAtPath(f"{root_path}/Bus")
    body_half_x = BUS_X * 0.5
    body_half_y = BUS_Y * 0.5
    if bus_prim and bus_prim.IsValid():
        try:
            body_half_x = float(bus_prim.GetAttribute("spacedc:body_half_x").Get() or body_half_x)
            body_half_y = float(bus_prim.GetAttribute("spacedc:body_half_y").Get() or body_half_y)
        except Exception:
            pass
    for key, value_type in (
        ("segments", Sdf.ValueTypeNames.Int),
        ("segment_len", Sdf.ValueTypeNames.Float),
        ("panel_chord", Sdf.ValueTypeNames.Float),
        ("panel_gap", Sdf.ValueTypeNames.Float),
        ("root_x", Sdf.ValueTypeNames.Float),
        ("panel_thickness", Sdf.ValueTypeNames.Float),
        ("radiator_thickness", Sdf.ValueTypeNames.Float),
    ):
        wings_prim.CreateAttribute(f"spacedc:{key}", value_type).Set(profile[key])

    panel_y = max(BUS_Y * 0.11, body_half_y * 0.18)
    truss_y = BUS_Y * 0.02
    cable_y = BUS_Y * 0.06
    frame_t = BUS_Y * 0.018
    brace_t = BUS_Y * 0.010

    def layout_side(side: int, side_name: str):
        side_root = f"{wings_root}/{side_name}"
        UsdGeom.Xform.Define(stage, side_root)
        wing_root = f"{side_root}/Wing_0"
        UsdGeom.Xform.Define(stage, wing_root)

        hinge_x = side * (body_half_x + BUS_X * 0.05)
        _cylinder(
            stage,
            f"{wing_root}/Hinge",
            BUS_Y * 0.055,
            BUS_Y * 0.44,
            (hinge_x, panel_y, 0),
            mats["frame"],
        )
        _sphere(
            stage,
            f"{wing_root}/RootHub",
            BUS_Y * 0.06,
            (hinge_x, panel_y, 0),
            mats["busEdge"],
        )
        _cylinder(
            stage,
            f"{wing_root}/PrimaryBoom",
            BUS_Y * 0.026,
            profile["boom_len"],
            (side * (BUS_X / 2 + profile["boom_len"] * 0.5), truss_y, 0),
            mats["frame"],
            rotate=(0, 0, 90),
        )
        _cylinder(
            stage,
            f"{wing_root}/UpperBoom",
            BUS_Y * 0.014,
            profile["boom_len"] * 0.92,
            (side * (BUS_X / 2 + profile["boom_len"] * 0.46), truss_y + BUS_Y * 0.07, profile["panel_chord"] * 0.44),
            mats["frame"],
            rotate=(0, 0, 90),
        )
        _cylinder(
            stage,
            f"{wing_root}/LowerBoom",
            BUS_Y * 0.014,
            profile["boom_len"] * 0.92,
            (side * (BUS_X / 2 + profile["boom_len"] * 0.46), truss_y + BUS_Y * 0.07, -profile["panel_chord"] * 0.44),
            mats["frame"],
            rotate=(0, 0, 90),
        )
        _box(
            stage,
            f"{wing_root}/DataTrunk",
            (side * (BUS_X / 2 + profile["boom_len"] * 0.52), cable_y, 0),
            (profile["boom_len"] * 0.96, BUS_Y * 0.018, BUS_Y * 0.024),
            mats["copper"],
        )
        for fork_idx, z_pos in enumerate((-profile["panel_chord"] * 0.24, profile["panel_chord"] * 0.24)):
            _box(
                stage,
                f"{wing_root}/RootFork_{fork_idx}",
                (side * (body_half_x + profile["boom_len"] * 0.14), panel_y, z_pos),
                (profile["boom_len"] * 0.28, BUS_Y * 0.014, BUS_Y * 0.020),
                mats["frame"],
                rotate=(0, 0, side * (10 if fork_idx == 0 else -10)),
            )

        mast_x = side * (profile["root_x"] - profile["segment_len"] * 0.08)
        _cylinder(
            stage,
            f"{wing_root}/UpperMast",
            BUS_Y * 0.018,
            profile["mast_height"],
            (mast_x, panel_y, profile["panel_chord"] * 0.48),
            mats["frame"],
        )
        _cylinder(
            stage,
            f"{wing_root}/LowerMast",
            BUS_Y * 0.018,
            profile["mast_height"],
            (mast_x, panel_y, -profile["panel_chord"] * 0.48),
            mats["frame"],
        )

        brace_len = profile["boom_len"] * 0.82
        brace_center_x = side * (BUS_X / 2 + brace_len * 0.5)
        for brace_idx, z_pos in enumerate(
            (-profile["panel_chord"] * 0.38, -profile["panel_chord"] * 0.12, profile["panel_chord"] * 0.12, profile["panel_chord"] * 0.38)
        ):
            _box(
                stage,
                f"{wing_root}/Brace_{brace_idx}",
                (brace_center_x, panel_y + BUS_Y * 0.03, z_pos),
                (brace_len, brace_t, BUS_Y * 0.03),
                mats["frame"],
            )

        for seg in range(profile["segments"]):
            center_x = side * (
                profile["root_x"]
                + seg * (profile["segment_len"] + profile["panel_gap"])
                + profile["segment_len"] * 0.5
            )
            seg_root = f"{wing_root}/Segment_{seg}"
            UsdGeom.Xform.Define(stage, seg_root)

            _box(
                stage,
                f"{seg_root}/Panel",
                (center_x, panel_y, 0),
                (profile["segment_len"], profile["panel_thickness"], profile["panel_chord"]),
                mats["solar"],
            )
            _box(
                stage,
                f"{seg_root}/Backplane",
                (center_x, panel_y - profile["panel_thickness"] * 0.65, 0),
                (profile["segment_len"] * 0.98, profile["panel_thickness"] * 0.40, profile["panel_chord"] * 0.95),
                mats["dark"],
            )
            _box(
                stage,
                f"{seg_root}/FrameTop",
                (center_x, panel_y + profile["panel_thickness"] * 0.5, profile["panel_chord"] * 0.5 - frame_t * 0.5),
                (profile["segment_len"] + 0.18, frame_t, frame_t),
                mats["frame"],
            )
            _box(
                stage,
                f"{seg_root}/FrameBottom",
                (center_x, panel_y + profile["panel_thickness"] * 0.5, -profile["panel_chord"] * 0.5 + frame_t * 0.5),
                (profile["segment_len"] + 0.18, frame_t, frame_t),
                mats["frame"],
            )
            _box(
                stage,
                f"{seg_root}/FrameInboard",
                (center_x - side * (profile["segment_len"] * 0.5 - frame_t * 0.5), panel_y, 0),
                (frame_t, frame_t, profile["panel_chord"] + 0.18),
                mats["frame"],
            )
            _box(
                stage,
                f"{seg_root}/FrameOutboard",
                (center_x + side * (profile["segment_len"] * 0.5 - frame_t * 0.5), panel_y, 0),
                (frame_t, frame_t, profile["panel_chord"] + 0.18),
                mats["frame"],
            )
            for strip in range(10):
                strip_z = -profile["panel_chord"] * 0.40 + strip * (profile["panel_chord"] * 0.088)
                _box(
                    stage,
                    f"{seg_root}/CellStrip_{strip}",
                    (center_x, panel_y + profile["panel_thickness"] * 0.62, strip_z),
                    (profile["segment_len"] * 0.94, BUS_Y * 0.003, profile["panel_chord"] * 0.042),
                    mats["accent"],
                )
            for batten_idx in range(4):
                batten_x = center_x - side * (profile["segment_len"] * 0.30) + side * batten_idx * (profile["segment_len"] * 0.20)
                _box(
                    stage,
                    f"{seg_root}/Batten_{batten_idx}",
                    (batten_x, panel_y + profile["panel_thickness"] * 0.82, 0),
                    (BUS_Y * 0.007, BUS_Y * 0.007, profile["panel_chord"] * 0.94),
                    mats["frame"],
                )
            for stringer_idx, z_pos in enumerate(
                (
                    -profile["panel_chord"] * 0.46,
                    -profile["panel_chord"] * 0.18,
                    profile["panel_chord"] * 0.18,
                    profile["panel_chord"] * 0.46,
                )
            ):
                _box(
                    stage,
                    f"{seg_root}/Stringer_{stringer_idx}",
                    (center_x, panel_y + profile["panel_thickness"] * 0.30, z_pos),
                    (profile["segment_len"] * 0.95, BUS_Y * 0.004, BUS_Y * 0.012),
                    mats["frame"],
                )
            _box(
                stage,
                f"{seg_root}/Spine",
                (center_x, panel_y + profile["panel_thickness"], 0),
                (profile["segment_len"] * 0.96, BUS_Y * 0.012, BUS_Y * 0.05),
                mats["frame"],
            )
            _cylinder(
                stage,
                f"{seg_root}/ServiceLine",
                BUS_Y * 0.004,
                profile["segment_len"] * 0.90,
                (center_x, panel_y + profile["panel_thickness"] * 1.1, 0),
                mats["copper"],
                rotate=(0, 0, 90),
            )
            _sphere(
                stage,
                f"{seg_root}/Node",
                BUS_Y * 0.024,
                (center_x, panel_y + profile["panel_thickness"] * 1.2, 0),
                mats["led_blue"],
            )
            if seg < profile["segments"] - 1:
                seam_x = side * (
                    profile["root_x"]
                    + seg * (profile["segment_len"] + profile["panel_gap"])
                    + profile["segment_len"]
                    + profile["panel_gap"] * 0.5
                )
                _box(
                    stage,
                    f"{wing_root}/Seam_{seg}",
                    (seam_x, panel_y + profile["panel_thickness"] * 0.5, 0),
                    (profile["panel_gap"] * 0.70, profile["panel_thickness"], profile["panel_chord"] * 0.92),
                    mats["frame"],
                )

        tip_x = side * (profile["root_x"] + profile["total_span"] + BUS_Y * 0.12)
        _cylinder(
            stage,
            f"{wing_root}/TipCanister",
            BUS_Y * 0.030,
            BUS_Y * 0.22,
            (tip_x - side * BUS_Y * 0.10, panel_y, 0),
            mats["frame"],
            rotate=(0, 0, 90),
        )
        _sphere(
            stage,
            f"{wing_root}/TipBeacon",
            BUS_Y * 0.030,
            (tip_x, panel_y + BUS_Y * 0.02, 0),
            mats["led_amber"],
        )

    layout_side(-1, "Left")
    layout_side(1, "Right")


# ── Radiators ───────────────────────────────────────────────

def _build_radiators(stage, root_path: str, mats: dict, rad_count: int, rad_area: float):
    rad_root = f"{root_path}/Radiators"
    UsdGeom.Xform.Define(stage, rad_root)
    solar_root = stage.GetPrimAtPath(f"{root_path}/SolarWings")
    profile = None
    if solar_root and solar_root.IsValid():
        try:
            profile = {
                "segments": int(solar_root.GetAttribute("spacedc:segments").Get() or 0),
                "segment_len": float(solar_root.GetAttribute("spacedc:segment_len").Get() or 0.0),
                "panel_chord": float(solar_root.GetAttribute("spacedc:panel_chord").Get() or 0.0),
                "panel_gap": float(solar_root.GetAttribute("spacedc:panel_gap").Get() or 0.0),
                "root_x": float(solar_root.GetAttribute("spacedc:root_x").Get() or 0.0),
                "panel_thickness": float(solar_root.GetAttribute("spacedc:panel_thickness").Get() or 0.0),
                "radiator_thickness": float(solar_root.GetAttribute("spacedc:radiator_thickness").Get() or 0.0),
            }
        except Exception:
            profile = None

    if not profile or profile["segments"] <= 0:
        profile = _long_sail_profile(max(rad_count, 8), max(rad_area * 3.0, 520.0))

    panel_y = BUS_Y * 0.11
    radiator_y = panel_y - (profile["panel_thickness"] + profile["radiator_thickness"]) * 1.8
    frame_t = BUS_Y * 0.022
    louver_count = max(5, min(8, rad_count + 2))

    def layout_side(side: int, side_name: str):
        side_root = f"{rad_root}/{side_name}"
        UsdGeom.Xform.Define(stage, side_root)

        manifold_len = BUS_X * 0.42
        manifold_x = side * (BUS_X / 2 + manifold_len * 0.54)
        for idx, z_pos in enumerate(
            (-profile["panel_chord"] * 0.42, profile["panel_chord"] * 0.42)
        ):
            _cylinder(
                stage,
                f"{side_root}/RootManifold_{idx}",
                BUS_Y * 0.015,
                manifold_len,
                (manifold_x, radiator_y, z_pos),
                mats["copper"],
                rotate=(0, 0, 90),
            )

        for seg in range(profile["segments"]):
            center_x = side * (
                profile["root_x"]
                + seg * (profile["segment_len"] + profile["panel_gap"])
                + profile["segment_len"] * 0.5
            )
            panel_root = f"{side_root}/Panel_{seg}"
            UsdGeom.Xform.Define(stage, panel_root)

            _box(
                stage,
                f"{panel_root}/Skin",
                (center_x, radiator_y, 0),
                (profile["segment_len"] * 0.98, profile["radiator_thickness"], profile["panel_chord"] * 0.95),
                mats["rad"],
            )
            _box(
                stage,
                f"{panel_root}/FrameTop",
                (center_x, radiator_y + profile["radiator_thickness"] * 0.25, profile["panel_chord"] * 0.5 - frame_t * 0.5),
                (profile["segment_len"] + 0.10, frame_t, frame_t),
                mats["frame"],
            )
            _box(
                stage,
                f"{panel_root}/FrameBottom",
                (center_x, radiator_y + profile["radiator_thickness"] * 0.25, -profile["panel_chord"] * 0.5 + frame_t * 0.5),
                (profile["segment_len"] + 0.10, frame_t, frame_t),
                mats["frame"],
            )
            for pipe_idx, z_pos in enumerate(
                (-profile["panel_chord"] * 0.28, 0.0, profile["panel_chord"] * 0.28)
            ):
                _cylinder(
                    stage,
                    f"{panel_root}/HeatPipe_{pipe_idx}",
                    BUS_Y * 0.013,
                    profile["segment_len"] * 0.92,
                    (center_x, radiator_y + profile["radiator_thickness"] * 0.28, z_pos),
                    mats["copper"],
                    rotate=(0, 0, 90),
                )
            for louver_idx in range(louver_count):
                louver_z = (
                    -profile["panel_chord"] * 0.40
                    + louver_idx * (profile["panel_chord"] * 0.80 / max(louver_count - 1, 1))
                )
                _box(
                    stage,
                    f"{panel_root}/Louver_{louver_idx}",
                    (center_x, radiator_y + profile["radiator_thickness"] * 0.95, louver_z),
                    (profile["segment_len"] * 0.82, BUS_Y * 0.008, BUS_Y * 0.05),
                    mats["radDark"],
                    rotate=(12, 0, 0),
                )
            for stand_idx, stand_x in enumerate(
                (
                    center_x - side * (profile["segment_len"] * 0.34),
                    center_x + side * (profile["segment_len"] * 0.34),
                )
            ):
                _box(
                    stage,
                    f"{panel_root}/StandOff_{stand_idx}",
                    (stand_x, (panel_y + radiator_y) * 0.5, 0),
                    (BUS_Y * 0.030, panel_y - radiator_y, BUS_Y * 0.030),
                    mats["frame"],
                )

    layout_side(-1, "Left")
    layout_side(1, "Right")


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
