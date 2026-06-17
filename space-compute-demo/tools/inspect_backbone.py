"""Inspect assets_raw/SpaceDcBackbone.usdz — full structural survey.

Dumps stage metadata, the prim tree, and per-prim world bounding boxes so we
can locate the server-mounting slots and wire gen_twin_satellite.py to them.

Run:
    python tools/inspect_backbone.py
"""
import json
import sys
from pathlib import Path

from pxr import Usd, UsdGeom, Gf

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "assets_raw" / "SpaceDcBackbone.usdz"

stage = Usd.Stage.Open(str(PATH))
if stage is None:
    print("FAILED to open", PATH)
    sys.exit(1)

print("=== STAGE METADATA ===")
print("defaultPrim   :", stage.GetDefaultPrim().GetPath() if stage.GetDefaultPrim() else None)
print("upAxis        :", UsdGeom.GetStageUpAxis(stage))
print("metersPerUnit :", UsdGeom.GetStageMetersPerUnit(stage))
print("timeCodes     :", stage.GetStartTimeCode(), "->", stage.GetEndTimeCode())

bc = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"], useExtentsHint=True)

def bbox(prim):
    try:
        r = bc.ComputeWorldBound(prim).ComputeAlignedRange()
        if r.IsEmpty():
            return None
        mn, mx = r.GetMin(), r.GetMax()
        size = [mx[i] - mn[i] for i in range(3)]
        cen  = [(mn[i] + mx[i]) / 2.0 for i in range(3)]
        return {
            "min":  [round(mn[i], 4) for i in range(3)],
            "max":  [round(mx[i], 4) for i in range(3)],
            "size": [round(size[i], 4) for i in range(3)],
            "cen":  [round(cen[i], 4) for i in range(3)],
        }
    except Exception as e:
        return {"err": str(e)}

print("\n=== ROOT WORLD BBOX ===")
dp = stage.GetDefaultPrim()
print(json.dumps(bbox(dp), indent=2) if dp else "no default prim")

print("\n=== PRIM TREE (type | path | bbox size | centroid) ===")
rows = []
for prim in stage.Traverse():
    path = prim.GetPath().pathString
    depth = path.count("/") - 1
    tname = prim.GetTypeName()
    bb = bbox(prim) if prim.IsA(UsdGeom.Imageable) else None
    indent = "  " * depth
    name = prim.GetName()
    szc = ""
    if bb and "size" in bb:
        szc = f"  size={bb['size']}  cen={bb['cen']}"
    print(f"{indent}[{tname or 'Xform?'}] {name}{szc}")
    rows.append({
        "path": path, "type": str(tname), "name": name,
        "bbox": bb,
    })

# Heuristic: surface any prim whose name hints at a mount slot.
print("\n=== SLOT-LIKE PRIMS (name matches slot/server/rack/bay/node/mount/socket/blade) ===")
KEYS = ("slot", "server", "rack", "bay", "node", "mount", "socket", "blade",
        "card", "module", "gpu", "tray", "shelf", "compute", "pcb", "board")
for r in rows:
    nm = r["name"].lower()
    if any(k in nm for k in KEYS):
        print(f"  {r['path']}  [{r['type']}]  {r['bbox']['size'] if r['bbox'] and 'size' in r['bbox'] else None}")

# Dump full rows to JSON for downstream tooling.
out = ROOT / "tools" / "inspect_backbone_report.json"
out.write_text(json.dumps({
    "defaultPrim": str(dp.GetPath()) if dp else None,
    "upAxis": str(UsdGeom.GetStageUpAxis(stage)),
    "metersPerUnit": UsdGeom.GetStageMetersPerUnit(stage),
    "rootBBox": bbox(dp) if dp else None,
    "prims": rows,
}, indent=2), encoding="utf-8")
print(f"\n[wrote] {out}  ({len(rows)} prims)")
