"""Second pass: enumerate every mesh w/ size/centroid/color so we can fill body_shell_prims."""
import json, os
from pxr import Usd, UsdGeom, UsdShade, Gf

PATH = r"C:/Users/markl/Downloads/satellite_compute.usdz"
stage = Usd.Stage.Open(PATH)
bc = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])

dp = stage.GetDefaultPrim()
root_bb = bc.ComputeWorldBound(dp).ComputeAlignedRange()
body_centroid = [
    (root_bb.GetMin()[0] + root_bb.GetMax()[0]) / 2.0,
    (root_bb.GetMin()[1] + root_bb.GetMax()[1]) / 2.0,
    (root_bb.GetMin()[2] + root_bb.GetMax()[2]) / 2.0,
]
overall = [root_bb.GetMax()[i] - root_bb.GetMin()[i] for i in range(3)]

def mat_diffuse(mat_prim):
    mat = UsdShade.Material(mat_prim)
    so = mat.GetSurfaceOutput()
    shader = None
    if so:
        src = so.GetConnectedSource()
        if src:
            shader = UsdShade.Shader(src[0].GetPrim())
    if shader is None:
        for c in mat_prim.GetChildren():
            if c.GetTypeName() == "Shader":
                shader = UsdShade.Shader(c); break
    if shader is None:
        return None, None
    inp = shader.GetInput("diffuseColor")
    if not inp: return None, None
    v = inp.Get()
    if v is not None:
        try: return [float(v[0]), float(v[1]), float(v[2])], None
        except: return None, None
    # connected to texture
    src = inp.GetConnectedSource()
    if src:
        return None, src[0].GetPrim().GetPath().pathString
    return None, None

def color_name(rgb):
    if rgb is None: return "texture-driven (no constant diffuse)"
    r,g,b = rgb
    mx = max(r,g,b); mn = min(r,g,b)
    if mx < 0.05: return "black"
    if mn > 0.85: return "white"
    if abs(r-g) < 0.05 and abs(g-b) < 0.05:
        if mx < 0.3: return f"dark grey ({round(r,2)},{round(g,2)},{round(b,2)})"
        if mx < 0.6: return f"neutral grey ({round(r,2)},{round(g,2)},{round(b,2)})"
        return f"light grey ({round(r,2)},{round(g,2)},{round(b,2)})"
    if b > r and b > g and b > 0.2:
        return f"blue ({round(r,2)},{round(g,2)},{round(b,2)})"
    if r > 0.5 and g > 0.4 and b < 0.3:
        return f"gold/yellow ({round(r,2)},{round(g,2)},{round(b,2)})"
    return f"rgb ({round(r,2)},{round(g,2)},{round(b,2)})"

records = []
for prim in stage.Traverse():
    if prim.GetTypeName() != "Mesh": continue
    bb = bc.ComputeWorldBound(prim).ComputeAlignedRange()
    if bb.IsEmpty(): continue
    mn = [bb.GetMin()[i] for i in range(3)]
    mx = [bb.GetMax()[i] for i in range(3)]
    sz = [mx[i]-mn[i] for i in range(3)]
    ct = [(mn[i]+mx[i])/2 for i in range(3)]
    off = [ct[i]-body_centroid[i] for i in range(3)]
    bapi = UsdShade.MaterialBindingAPI(prim)
    bound_mat, _ = bapi.ComputeBoundMaterial()
    mat_path = bound_mat.GetPath().pathString if bound_mat else ""
    diffuse, tex = (None, None)
    if bound_mat:
        diffuse, tex = mat_diffuse(bound_mat.GetPrim())
    # xformOps on the mesh + its parent
    xops = []
    for p in [prim, prim.GetParent()]:
        try:
            xf = UsdGeom.Xformable(p)
            for op in xf.GetOrderedXformOps():
                try:
                    v = op.Get()
                except Exception:
                    v = None
                xops.append(f"{p.GetPath().name}:{op.GetOpName()}={v}")
        except Exception:
            pass
    flatness = min(sz)/max(sz) if max(sz)>0 else 1.0
    max_off_axis = max(range(3), key=lambda i: abs(off[i]))
    records.append({
        "path": prim.GetPath().pathString,
        "type_name": str(prim.GetTypeName()),
        "bbox_min": mn,
        "bbox_max": mx,
        "bbox_size": sz,
        "centroid": ct,
        "offset": off,
        "flatness": flatness,
        "max_off_axis": ["X","Y","Z"][max_off_axis],
        "max_off": abs(off[max_off_axis]),
        "material_binding": mat_path,
        "diffuse": diffuse,
        "diffuse_texture": tex,
        "color_name": color_name(diffuse),
        "xformOps": xops,
        "vol": sz[0]*sz[1]*sz[2],
    })

# Rank by volume desc
records.sort(key=lambda r: r["vol"], reverse=True)
print(json.dumps({"body_centroid": body_centroid, "overall": overall, "records": records}, default=str, indent=2))
