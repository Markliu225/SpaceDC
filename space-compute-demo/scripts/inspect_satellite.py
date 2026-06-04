"""Inspect satellite_body.usdz - structural analysis for gen_twin_satellite wiring."""
import os
import sys
import json
from pxr import Usd, UsdGeom, UsdShade, Tf, Gf

PATH = r'C:/Users/markl/Downloads/satellite_body.usdz'

result = {
    "exists": False,
    "file_size_mb": 0.0,
    "default_prim": "",
    "up_axis": "",
    "meters_per_unit": 0.0,
    "bbox_size_m": [0.0, 0.0, 0.0],
    "prim_tree_lines": [],
    "components_raw": [],
    "materials": [],
    "issues": [],
    "notes": "",
}

result["exists"] = os.path.exists(PATH)
if result["exists"]:
    result["file_size_mb"] = round(os.path.getsize(PATH) / 1024.0 / 1024.0, 3)

try:
    stage = Usd.Stage.Open(PATH)
except Exception as e:
    result["issues"].append(f"Stage.Open failed: {e}")
    print(json.dumps(result, indent=2))
    sys.exit(1)

if not stage:
    result["issues"].append("Stage.Open returned None")
    print(json.dumps(result, indent=2))
    sys.exit(1)

dp = stage.GetDefaultPrim()
if dp:
    result["default_prim"] = str(dp.GetPath())
else:
    result["issues"].append("No default prim set on stage")

up = UsdGeom.GetStageUpAxis(stage)
result["up_axis"] = str(up)
result["meters_per_unit"] = UsdGeom.GetStageMetersPerUnit(stage)

# bbox of default prim
bc = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ['default', 'render'])
try:
    bbox = bc.ComputeWorldBound(dp)
    rng = bbox.ComputeAlignedRange()
    size = rng.GetSize()
    mpu = result["meters_per_unit"] or 1.0
    result["bbox_size_m"] = [size[0] * mpu, size[1] * mpu, size[2] * mpu]
    result["_bbox_size_units"] = [size[0], size[1], size[2]]
    result["_bbox_min"] = [rng.GetMin()[0], rng.GetMin()[1], rng.GetMin()[2]]
    result["_bbox_max"] = [rng.GetMax()[0], rng.GetMax()[1], rng.GetMax()[2]]
except Exception as e:
    result["issues"].append(f"BBoxCache default prim failed: {e}")

# Walk prim tree, collecting Mesh / Xform / Material
mesh_info = []  # (path, bbox_min, bbox_max, size, center)
xform_info = []
material_paths = []

def walk(prim, depth=0):
    if not prim:
        return
    name = prim.GetName()
    type_name = prim.GetTypeName()
    path = str(prim.GetPath())
    indent = "  " * depth
    line = f"{indent}{type_name} {path}"
    if type_name in ("Mesh", "Xform", "Material", "Scope"):
        result["prim_tree_lines"].append(line)
    if type_name == "Mesh":
        try:
            b = bc.ComputeWorldBound(prim)
            r = b.ComputeAlignedRange()
            mn = r.GetMin()
            mx = r.GetMax()
            sz = r.GetSize()
            ctr = (mn + mx) * 0.5
            mesh_info.append({
                "path": path,
                "size_u": [sz[0], sz[1], sz[2]],
                "center_u": [ctr[0], ctr[1], ctr[2]],
                "min_u": [mn[0], mn[1], mn[2]],
                "max_u": [mx[0], mx[1], mx[2]],
            })
        except Exception as e:
            result["issues"].append(f"BBox mesh {path}: {e}")
    elif type_name == "Xform":
        xform_info.append(path)
    elif type_name == "Material":
        material_paths.append(path)
    for child in prim.GetChildren():
        walk(child, depth + 1)

walk(dp)
result["materials"] = material_paths

# Convert mesh sizes/centers to meters
mpu = result["meters_per_unit"] or 1.0
for m in mesh_info:
    m["size_m"] = [v * mpu for v in m["size_u"]]
    m["center_m"] = [v * mpu for v in m["center_u"]]
    m["volume_m"] = m["size_m"][0] * m["size_m"][1] * m["size_m"][2]
    # distance from origin
    cx, cy, cz = m["center_m"]
    m["dist_origin_m"] = (cx * cx + cy * cy + cz * cz) ** 0.5
    # max dim
    m["maxdim_m"] = max(m["size_m"])

# Sort by volume desc for inspection
mesh_info.sort(key=lambda x: x["volume_m"], reverse=True)

result["mesh_count"] = len(mesh_info)
result["meshes"] = mesh_info

# Save report
with open(r'C:/Workspace/SpaceDC/space-compute-demo/scripts/inspect_satellite_report.json', 'w') as f:
    json.dump(result, f, indent=2, default=str)

# Print summary
print(f"file_size_mb = {result['file_size_mb']}")
print(f"default_prim = {result['default_prim']}")
print(f"up_axis = {result['up_axis']}")
print(f"meters_per_unit = {result['meters_per_unit']}")
print(f"bbox_size_m = {result['bbox_size_m']}")
print(f"materials count = {len(material_paths)}")
print(f"mesh count = {len(mesh_info)}")
print()
print("=== Prim tree (first 80 lines) ===")
for ln in result["prim_tree_lines"][:80]:
    print(ln)
print(f"... total {len(result['prim_tree_lines'])} lines")
print()
print("=== Meshes by volume (top) ===")
for i, m in enumerate(mesh_info[:30]):
    print(f"[{i:02d}] vol={m['volume_m']:.4g} m^3, size_m={[round(v,4) for v in m['size_m']]}, ctr_m={[round(v,4) for v in m['center_m']]}, dist={m['dist_origin_m']:.4f} -> {m['path']}")
print()
print(f"Materials: {material_paths}")
print(f"Issues: {result['issues']}")
