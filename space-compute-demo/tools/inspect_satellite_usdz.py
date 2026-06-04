"""Inspect satellite_compute.usdz and emit JSON findings."""
import json, os, sys
from pxr import Usd, UsdGeom, UsdShade, Tf, Gf, Sdf

PATH = r"C:/Users/markl/Downloads/satellite_compute.usdz"

issues = []

class Delegate(Tf.Diagnostics.Delegate if hasattr(Tf, "Diagnostics") else object):
    pass

# Use Tf.Notice / Diagnostic handler
diagnostics = []

def collect_diag():
    pass

# Simpler: just capture stderr-ish via Tf
def _diag_handler(notice, sender):
    try:
        diagnostics.append(str(notice.GetCommentary()))
    except Exception:
        diagnostics.append(repr(notice))

result = {
    "exists": False,
    "file_size_mb": 0.0,
    "default_prim": "",
    "up_axis": "",
    "meters_per_unit": 0.0,
    "bbox_min": [],
    "bbox_max": [],
    "bbox_size_meters": [],
    "prim_tree": [],
    "solar_panel_candidates": [],
    "body_shell_prims": [],
    "all_materials": [],
    "mirror_axis_suggestion": "",
    "mirror_axis_explanation": "",
    "issues": [],
    "notes": "",
}

if not os.path.exists(PATH):
    result["exists"] = False
    print(json.dumps(result))
    sys.exit(0)

result["exists"] = True
result["file_size_mb"] = round(os.path.getsize(PATH) / (1024 * 1024), 4)

stage = Usd.Stage.Open(PATH)
if stage is None:
    result["issues"].append("Stage.Open returned None")
    print(json.dumps(result))
    sys.exit(0)

dp = stage.GetDefaultPrim()
result["default_prim"] = dp.GetPath().pathString if dp else ""
result["up_axis"] = UsdGeom.GetStageUpAxis(stage)
result["meters_per_unit"] = UsdGeom.GetStageMetersPerUnit(stage)

bc = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])

def get_world_bbox(prim):
    try:
        b = bc.ComputeWorldBound(prim)
        rng = b.ComputeAlignedRange()
        if rng.IsEmpty():
            return None, None
        mn = rng.GetMin()
        mx = rng.GetMax()
        return (mn[0], mn[1], mn[2]), (mx[0], mx[1], mx[2])
    except Exception as e:
        issues.append(f"bbox error {prim.GetPath()}: {e}")
        return None, None

# Default prim bbox
root_prim = dp if dp else stage.GetPseudoRoot()
mn, mx = get_world_bbox(root_prim)
if mn and mx:
    result["bbox_min"] = list(mn)
    result["bbox_max"] = list(mx)
    mpu = result["meters_per_unit"] or 1.0
    result["bbox_size_meters"] = [(mx[i] - mn[i]) * mpu for i in range(3)]

# Walk prims
mesh_prims = []
xform_prims = []
material_prims = []
all_prims = []

for prim in stage.Traverse():
    tn = prim.GetTypeName()
    p = prim.GetPath().pathString
    if tn == "Mesh":
        mesh_prims.append(prim)
        all_prims.append(p)
    elif tn == "Xform":
        xform_prims.append(prim)
        all_prims.append(p)
    elif tn == "Material":
        material_prims.append(prim)
        all_prims.append(p)

result["prim_tree"] = all_prims

# Helper: read UsdPreviewSurface inputs from a Material
def read_material(mat_prim):
    mat = UsdShade.Material(mat_prim)
    info = {
        "path": mat_prim.GetPath().pathString,
        "shader_id": "",
        "summary": "",
    }
    surface_out = mat.GetSurfaceOutput()
    shader_prim = None
    shader = None
    if surface_out:
        src = surface_out.GetConnectedSource()
        if src:
            shader_prim = src[0].GetPrim()
            shader = UsdShade.Shader(shader_prim)
    if shader is None:
        # fallback: find any Shader child
        for c in mat_prim.GetChildren():
            if c.GetTypeName() == "Shader":
                shader = UsdShade.Shader(c)
                shader_prim = c
                break
    if shader:
        sid = shader.GetShaderId()
        info["shader_id"] = sid or ""
        def grab(name):
            inp = shader.GetInput(name)
            if inp:
                v = inp.Get()
                if v is None:
                    src = inp.GetConnectedSource()
                    return f"<connected:{src[0].GetPrim().GetPath()}>" if src else None
                return v
            return None
        diffuse = grab("diffuseColor")
        metallic = grab("metallic")
        roughness = grab("roughness")
        emissive = grab("emissiveColor")
        if diffuse is not None:
            try:
                info["diffuse"] = [float(diffuse[0]), float(diffuse[1]), float(diffuse[2])]
            except Exception:
                info["diffuse_raw"] = str(diffuse)
        if metallic is not None:
            try:
                info["metallic"] = float(metallic)
            except Exception:
                pass
        if roughness is not None:
            try:
                info["roughness"] = float(roughness)
            except Exception:
                pass
        if emissive is not None:
            try:
                info["emissive"] = [float(emissive[0]), float(emissive[1]), float(emissive[2])]
            except Exception:
                pass
        # Build summary
        parts = [f"id={info['shader_id']}"]
        if "diffuse" in info:
            parts.append(f"diffuse={tuple(round(x,3) for x in info['diffuse'])}")
        if "metallic" in info:
            parts.append(f"metallic={round(info['metallic'],3)}")
        if "roughness" in info:
            parts.append(f"roughness={round(info['roughness'],3)}")
        if "emissive" in info:
            parts.append(f"emissive={tuple(round(x,3) for x in info['emissive'])}")
        info["summary"] = ", ".join(parts)
    else:
        info["summary"] = "no shader found"
    return info

mat_info_by_path = {}
for mp in material_prims:
    mi = read_material(mp)
    mat_info_by_path[mi["path"]] = mi
    result["all_materials"].append(mi)

# Color name from diffuse rgb
def color_name(rgb):
    if rgb is None:
        return "unknown"
    r, g, b = rgb
    # Normalize 0..1
    mx = max(r, g, b)
    mn = min(r, g, b)
    if mx < 0.05:
        return "black"
    if mn > 0.85:
        return "white"
    if abs(r - g) < 0.05 and abs(g - b) < 0.05:
        if mx < 0.3:
            return f"dark grey ({round(r,2)},{round(g,2)},{round(b,2)})"
        if mx < 0.6:
            return f"neutral grey ({round(r,2)},{round(g,2)},{round(b,2)})"
        return f"light grey ({round(r,2)},{round(g,2)},{round(b,2)})"
    if b > r and b > g and b > 0.2:
        if g > 0.3 and r < 0.3:
            return f"cyan/teal ({round(r,2)},{round(g,2)},{round(b,2)})"
        return f"blue ({round(r,2)},{round(g,2)},{round(b,2)})"
    if r > 0.5 and g > 0.4 and b < 0.3:
        return f"gold/yellow ({round(r,2)},{round(g,2)},{round(b,2)})"
    if r > g and r > b:
        return f"red/warm ({round(r,2)},{round(g,2)},{round(b,2)})"
    if g > r and g > b:
        return f"green ({round(r,2)},{round(g,2)},{round(b,2)})"
    return f"rgb ({round(r,2)},{round(g,2)},{round(b,2)})"

# For each mesh, compute world bbox + material binding
mesh_records = []
for m in mesh_prims:
    mn, mx = get_world_bbox(m)
    if mn is None:
        continue
    size = [mx[i] - mn[i] for i in range(3)]
    centroid = [(mn[i] + mx[i]) / 2.0 for i in range(3)]
    # Material binding
    bapi = UsdShade.MaterialBindingAPI(m)
    bound_mat, _ = bapi.ComputeBoundMaterial()
    mat_path = bound_mat.GetPath().pathString if bound_mat else ""
    # Local xformOps
    xops = []
    try:
        xformable = UsdGeom.Xformable(m)
        ops = xformable.GetOrderedXformOps()
        for op in ops:
            try:
                xops.append(f"{op.GetOpName()}={op.Get()}")
            except Exception:
                xops.append(op.GetOpName())
    except Exception:
        pass
    mesh_records.append({
        "prim": m,
        "path": m.GetPath().pathString,
        "type_name": str(m.GetTypeName()),
        "bbox_min": list(mn),
        "bbox_max": list(mx),
        "bbox_size": size,
        "centroid": centroid,
        "material_binding": mat_path,
        "xformOps": xops,
    })

# Body centroid: use the default prim's bbox centroid
body_centroid = None
if result["bbox_min"] and result["bbox_max"]:
    body_centroid = [(result["bbox_min"][i] + result["bbox_max"][i]) / 2.0 for i in range(3)]

# Heuristic: classify panels vs body
# Panel: large flat aspect (one dim << other two), and centroid offset from body centroid on one axis
solar_candidates = []
body_shells = []

# Sort by overall volume desc
def vol(s):
    return s[0] * s[1] * s[2]

# Compute body extents per-axis
overall_size = [result["bbox_size_meters"][i] / (result["meters_per_unit"] or 1.0) if result["bbox_size_meters"] else 0 for i in range(3)]

for rec in mesh_records:
    sz = rec["bbox_size"]
    sorted_dims = sorted(sz)
    smallest = sorted_dims[0]
    mid = sorted_dims[1]
    largest = sorted_dims[2]
    flatness = (smallest / largest) if largest > 0 else 1.0
    # Aspect: flat if smallest is much less than mid AND largest
    # Offset
    offset = [0, 0, 0]
    if body_centroid:
        offset = [rec["centroid"][i] - body_centroid[i] for i in range(3)]
    max_off_axis = max(range(3), key=lambda i: abs(offset[i]))
    max_off = abs(offset[max_off_axis])
    # Material color
    mat_info = mat_info_by_path.get(rec["material_binding"], {})
    diffuse = mat_info.get("diffuse")
    cname = color_name(diffuse) if diffuse else "no-diffuse"

    is_flat = flatness < 0.2 and smallest < (largest * 0.2)
    is_offset = max_off > (max(overall_size) * 0.1) if overall_size else False
    is_blueish = False
    if diffuse:
        r, g, b = diffuse
        if b > 0.15 and b >= r and b >= g and (r + g) < 1.5:
            is_blueish = True
        if r < 0.2 and g < 0.2 and b < 0.3:  # very dark = solar cells
            is_blueish = True

    reasons = []
    if is_flat:
        reasons.append(f"flat aspect smallest/largest={round(flatness,3)} (dims={[round(x,3) for x in sz]})")
    if is_offset:
        reasons.append(f"centroid offset {round(max_off,3)} along axis {['X','Y','Z'][max_off_axis]} (offset={[round(o,3) for o in offset]})")
    if is_blueish:
        reasons.append(f"material '{cname}' looks like solar-cell blue/dark")

    if (is_flat and (is_offset or is_blueish)) or (is_offset and is_blueish):
        solar_candidates.append({
            "path": rec["path"],
            "type_name": rec["type_name"],
            "bbox_min": rec["bbox_min"],
            "bbox_max": rec["bbox_max"],
            "bbox_size": rec["bbox_size"],
            "centroid": rec["centroid"],
            "material_binding": rec["material_binding"],
            "xform_translate": [],
            "xform_rotate": [],
            "xform_scale": [],
            "reason": "; ".join(reasons) if reasons else "heuristic match",
        })
    else:
        # Treat as potential body shell if it's large and not flat
        is_chunky = flatness > 0.3
        is_central = max_off < (max(overall_size) * 0.15) if overall_size else True
        if is_chunky and is_central:
            body_shells.append({
                "path": rec["path"],
                "type_name": rec["type_name"],
                "material_binding": rec["material_binding"],
                "color_summary": cname,
            })

# If nothing matched as solar, fall back to flattest mesh
if not solar_candidates and mesh_records:
    flat_sorted = sorted(mesh_records, key=lambda r: (min(r["bbox_size"]) / max(r["bbox_size"])) if max(r["bbox_size"]) else 1.0)
    for rec in flat_sorted[:2]:
        mat_info = mat_info_by_path.get(rec["material_binding"], {})
        diffuse = mat_info.get("diffuse")
        cname = color_name(diffuse) if diffuse else "no-diffuse"
        sz = rec["bbox_size"]
        flatness = min(sz) / max(sz) if max(sz) else 1.0
        offset = [rec["centroid"][i] - body_centroid[i] for i in range(3)] if body_centroid else [0,0,0]
        solar_candidates.append({
            "path": rec["path"],
            "type_name": rec["type_name"],
            "bbox_min": rec["bbox_min"],
            "bbox_max": rec["bbox_max"],
            "bbox_size": sz,
            "centroid": rec["centroid"],
            "material_binding": rec["material_binding"],
            "xform_translate": [],
            "xform_rotate": [],
            "xform_scale": [],
            "reason": f"fallback: flattest mesh (smallest/largest={round(flatness,3)}), offset={[round(o,3) for o in offset]}, color={cname}",
        })

result["solar_panel_candidates"] = solar_candidates
result["body_shell_prims"] = body_shells

# Mirror axis: pick by largest offset of FIRST candidate's centroid vs body centroid
if solar_candidates and body_centroid:
    c = solar_candidates[0]["centroid"]
    off = [c[i] - body_centroid[i] for i in range(3)]
    ax_i = max(range(3), key=lambda i: abs(off[i]))
    ax = ["X", "Y", "Z"][ax_i]
    sign = "+" if off[ax_i] > 0 else "-"
    result["mirror_axis_suggestion"] = ax
    result["mirror_axis_explanation"] = (
        f"Panel centroid {[round(x,3) for x in c]} vs body centroid {[round(x,3) for x in body_centroid]}; "
        f"largest absolute offset is along {ax} ({round(off[ax_i],3)} stage units, sign {sign}). "
        f"Mirror the duplicate panel by negating that axis."
    )
else:
    result["mirror_axis_suggestion"] = "X"
    result["mirror_axis_explanation"] = "Could not determine — no candidate or body centroid; defaulting to X."

# Notes
notes = []
mpu = result["meters_per_unit"] or 1.0
notes.append(f"Stage metersPerUnit={mpu}. If gen_twin_satellite.py host stage is centimeters (mpu=0.01), reference will need a scale of {mpu/0.01:.3f} to land in cm.")
if not solar_candidates:
    notes.append("No clear solar panel candidate detected from heuristics — manual selection may be needed.")
if any("variantSet" for _ in []):
    pass
notes.append("USDZ assets are typically flattened; variantSet override hooks declared on a stand-in prim will NOT bind to mesh paths inside this referenced asset unless authored to the actual paths above.")
notes.append("Material overrides to recolor the bus should be authored as override prims targeting the exact Material paths above (or via MaterialBindingAPI rebind on the mesh prims).")
result["notes"] = " ".join(notes)
result["issues"] = issues + diagnostics

print(json.dumps(result, default=str, indent=2))
