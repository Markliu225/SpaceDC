"""extract_bbox.py - list every node/mesh/part of the public NASA ISS 3D models with its
world-space axis-aligned bounding box (after applying all node/item transforms).

Models handled (all downloaded into this folder, see README section in the report):
  C   : NASA JSC Visual Communications Lab "ISS complete_2011" LightWave 9 scene
        (NASA-3D-Resources "International Space Station (ISS) (C) (High Res)", Feb 2011)
        -> C_HighRes/Scenes/ISS complete_2011.lws + Objects/**/*.lwo   (units: inch)
  VTAD: NASA VTAD "ISS_stationary.glb" (science.nasa.gov, published 2019-04-22)  (units: m)
  IGOAL: NASA JSC IGOAL "International Space Station (ISS).glb" (NASA-3D-Resources (D), 2026)
        root node "SSREF_IGOAL" (units: inch inside the root; root carries a viewer scale)

For each model the native frame is:
  C     : object space of the scene null "ISS PIVOT" (all station items are its children),
          i.e. the LightWave modelling frame of the assembled station (left-handed LW axes).
  VTAD  : glTF world space (right-handed, +Y up).
  IGOAL : child space of the root node "SSREF_IGOAL" (root viewer scale -0.00258 removed).

The mapping native -> ISS analysis frame (X fwd, Y stbd, Z nadir, metres) is given in
MAPPINGS below; it was determined from known placements (see report), and every row of the
CSV carries both the native box and the mapped box.

Output: parts_bbox.csv  (one row per node/item 'mesh' box, per node 'subtree' box, and for
model C per-surface and per-connected-component boxes of selected surfaces).

usage:  venv/Scripts/python.exe extract_bbox.py
"""
import csv
import json
import math
import os
import struct
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lwo2 import read_lwo2, layer_groups  # noqa: E402

# ----------------------------------------------------------------------------------------
# native -> ISS analysis frame mappings:   p_iss[m] = scale * (R @ p_native) + t
# R rows = ISS X, Y, Z expressed in native axes.  The axis maps were identified from physical
# placements that fix every axis independently (S-truss & Columbus & Airlock = starboard,
# Node 2 fwd of Lab & Russian segment aft = forward, Cupola/PMM below Node 3/Node 1 and Z1
# above Node 1 = nadir).  Origins: C and IGOAL native origins already sit at the S0 centre on
# the truss centre line (S0 spans +-6.7 m symmetric, truss segments centred on the origin);
# VTAD scale/translation come from a least-squares similarity fit to IGOAL on 19 truss/module
# box centres (analyze_layout.py; rms residual 0.43 m).
# ----------------------------------------------------------------------------------------
MAPPINGS = {
    # LightWave scene, ISS PIVOT object space: +X fwd, +Y stbd, +Z zenith (left-handed LW),
    # 1 unit = 1 inch.  -> X_iss = X, Y_iss = Y, Z_iss = -Z
    "C": dict(scale=0.0254, R=np.array([[1, 0, 0], [0, 1, 0], [0, 0, -1]], float), t=np.zeros(3)),
    # glTF world: +Z fwd, -X stbd, +Y zenith, metres  -> X_iss = z, Y_iss = -x, Z_iss = -y,
    # then similarity fit to IGOAL: scale 0.9580, t = (-4.550, 0.006, 4.887) m (19 centres, rms 0.43 m)
    "VTAD": dict(scale=0.9580, R=np.array([[0, 0, 1], [-1, 0, 0], [0, -1, 0]], float),
                 t=np.array([-4.550, 0.006, 4.887])),
    # IGOAL child-of-root (SSREF_IGOAL) space: a = X, b = Z (nadir), c = -Y ; inches.
    "IGOAL": dict(scale=0.0254, R=np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float), t=np.zeros(3)),
}


def mapped_box(model, bmin, bmax):
    """Map a native AABB to the ISS frame (exact for axis permutations/sign flips)."""
    m = MAPPINGS[model]
    corners = np.array([[x, y, z] for x in (bmin[0], bmax[0]) for y in (bmin[1], bmax[1])
                        for z in (bmin[2], bmax[2])])
    c = corners @ m["R"].T * m["scale"] + m["t"]
    return c.min(0), c.max(0)


# ----------------------------------------------------------------------------------------
# glTF / GLB
# ----------------------------------------------------------------------------------------
COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def load_glb(path):
    with open(path, "rb") as f:
        data = f.read()
    magic, ver, length = struct.unpack("<4sII", data[:12])
    assert magic == b"glTF", path
    off = 12
    js, bin_ = None, b""
    while off < length:
        clen, ctype = struct.unpack("<I4s", data[off:off + 8])
        chunk = data[off + 8:off + 8 + clen]
        if ctype == b"JSON":
            js = json.loads(chunk)
        elif ctype.startswith(b"BIN"):
            bin_ = chunk
        off += 8 + clen
    return js, bin_


def read_accessor(js, bin_, ai):
    acc = js["accessors"][ai]
    n = acc["count"]
    nc = NCOMP[acc["type"]]
    dt = np.dtype(COMP[acc["componentType"]]).newbyteorder("<")
    if "bufferView" not in acc:
        return np.zeros((n, nc))
    bv = js["bufferViews"][acc["bufferView"]]
    base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride", 0) or dt.itemsize * nc
    raw = np.frombuffer(bin_, dtype=np.uint8, count=stride * (n - 1) + dt.itemsize * nc, offset=base)
    arr = np.lib.stride_tricks.as_strided(raw, shape=(n, dt.itemsize * nc), strides=(stride, 1))
    return np.ascontiguousarray(arr).view(dt).reshape(n, nc).astype(float)


def mesh_positions(js, bin_, mi, cache):
    if mi in cache:
        return cache[mi]
    pts = []
    for prim in js["meshes"][mi]["primitives"]:
        ext = prim.get("extensions", {}).get("KHR_draco_mesh_compression")
        if ext is not None:
            import DracoPy
            bv = js["bufferViews"][ext["bufferView"]]
            o = bv.get("byteOffset", 0)
            dm = DracoPy.decode(bin_[o:o + bv["byteLength"]])
            p = np.asarray(dm.points, float).reshape(-1, 3)
        else:
            p = read_accessor(js, bin_, prim["attributes"]["POSITION"])
        pts.append(p)
    P = np.vstack(pts) if pts else np.zeros((0, 3))
    cache[mi] = P
    return P


def quat_to_mat(q):
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def node_local(n):
    if "matrix" in n:
        return np.array(n["matrix"], float).reshape(4, 4).T
    M = np.eye(4)
    S = np.diag(n.get("scale", [1, 1, 1]))
    R = quat_to_mat(n.get("rotation", [0, 0, 0, 1]))
    M[:3, :3] = R @ S
    M[:3, 3] = n.get("translation", [0, 0, 0])
    return M


def glb_rows(model, path, skip_root_transform=False):
    js, bin_ = load_glb(path)
    nodes = js["nodes"]
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent[c] = i
    roots = js["scenes"][js.get("scene", 0)]["nodes"]
    world = {}
    pathname = {}

    def walk(i, M, pth):
        n = nodes[i]
        L = node_local(n)
        if skip_root_transform and i in roots and n.get("name", "").startswith("SSREF"):
            L = np.eye(4)
        W = M @ L
        world[i] = W
        pathname[i] = pth + "/" + n.get("name", f"node{i}")
        for c in n.get("children", []):
            walk(c, W, pathname[i])

    for r in roots:
        walk(r, np.eye(4), "")
    cache = {}
    own = {}
    for i, n in enumerate(nodes):
        if "mesh" in n and i in world:
            P = mesh_positions(js, bin_, n["mesh"], cache)
            if len(P):
                W = world[i]
                Pw = P @ W[:3, :3].T + W[:3, 3]
                own[i] = (Pw.min(0), Pw.max(0), len(P))
    # subtree boxes
    sub = {}

    def subtree(i):
        boxes = []
        if i in own:
            boxes.append(own[i])
        for c in nodes[i].get("children", []):
            s = subtree(c)
            if s is not None:
                boxes.append(s)
        if not boxes:
            sub[i] = None
            return None
        mn = np.min([b[0] for b in boxes], 0)
        mx = np.max([b[1] for b in boxes], 0)
        nv = sum(b[2] for b in boxes)
        sub[i] = (mn, mx, nv)
        return sub[i]

    for r in roots:
        subtree(r)
    rows = []
    for i, n in enumerate(nodes):
        if i not in world:
            continue
        pname = nodes[parent[i]].get("name", "") if i in parent else ""
        if i in own:
            rows.append(dict(model=model, file=os.path.basename(path), node_index=i, name=n.get("name", ""),
                             parent=pname, path=pathname[i], scope="mesh", box=own[i]))
        if n.get("children") and sub.get(i) is not None:
            rows.append(dict(model=model, file=os.path.basename(path), node_index=i, name=n.get("name", ""),
                             parent=pname, path=pathname[i], scope="subtree", box=sub[i]))
    return rows


# ----------------------------------------------------------------------------------------
# LightWave scene (.lws, LWSC v5) + LWO2 objects
# ----------------------------------------------------------------------------------------
def lw_rot(h, p, b):
    """LightWave HPB rotation matrix (applied to column vectors): R = Ry(h) Rx(p) Rz(b)."""
    ch, sh, cp, sp, cb, sb = math.cos(h), math.sin(h), math.cos(p), math.sin(p), math.cos(b), math.sin(b)
    return np.array([
        [ch * cb + sh * sp * sb, -ch * sb + sh * sp * cb, sh * cp],
        [cp * sb, cp * cb, -sp],
        [-sh * cb + ch * sp * sb, sh * sb + ch * sp * cb, ch * cp]])


def parse_lws(path):
    items = []
    cur = None
    with open(path, "r", encoding="latin-1") as f:
        lines = [ln.rstrip("\n") for ln in f]
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        tok = ln.split()
        if not tok:
            i += 1
            continue
        if tok[0] == "LoadObjectLayer":
            cur = dict(kind="object", layer=int(tok[1]), id=tok[2], path=" ".join(tok[3:]),
                       name=os.path.basename(" ".join(tok[3:])) + f"#L{tok[1]}")
            items.append(cur)
        elif tok[0] == "AddNullObject":
            cur = dict(kind="null", id=tok[1], name=" ".join(tok[2:]), path="")
            items.append(cur)
        elif tok[0] in ("AddLight", "AddCamera"):
            cur = None
        elif cur is not None and tok[0] == "NumChannels":
            nch = int(tok[1])
            vals = [0.0] * nch
            i += 1
            while i < len(lines) and lines[i].strip().split()[:1] == ["Channel"]:
                ch = int(lines[i].split()[1])
                # envelope block
                i += 1  # '{ Envelope'
                i += 1
                nkeys = int(lines[i].strip())
                keys = []
                for k in range(nkeys):
                    i += 1
                    kt = lines[i].split()
                    keys.append((float(kt[2]), float(kt[1])))  # (time, value)
                i += 1  # Behaviors
                i += 1  # '}'
                keys.sort()
                v = keys[0][1]
                for t, val in keys:  # value at frame/time 0
                    if t <= 0:
                        v = val
                vals[ch] = v
                i += 1
            cur["channels"] = vals
            continue
        elif cur is not None and tok[0] == "PivotPosition":
            cur["pivot"] = np.array([float(t) for t in tok[1:4]])
        elif cur is not None and tok[0] == "ParentItem":
            cur["parent"] = tok[1]
        elif cur is not None and tok[0] == "ObjectDissolve":
            try:
                cur["dissolve"] = float(tok[1])
            except ValueError:
                cur["dissolve"] = tok[1]
        i += 1
    return items


def lw_local(it):
    ch = it.get("channels", [0, 0, 0, 0, 0, 0, 1, 1, 1])
    pos = np.array(ch[0:3])
    h, p, b = ch[3:6]
    s = np.array(ch[6:9]) if len(ch) >= 9 else np.ones(3)
    piv = it.get("pivot", np.zeros(3))
    M = np.eye(4)
    M[:3, :3] = lw_rot(h, p, b) @ np.diag(s)
    M[:3, 3] = pos - M[:3, :3] @ piv
    return M


def connected_components(polys, idx_subset):
    """Union-find over polygon vertex sharing, restricted to polygons given (lists of indices)."""
    parent = {}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for poly in polys:
        for v in poly:
            parent.setdefault(v, v)
        r0 = find(poly[0])
        for v in poly[1:]:
            rv = find(v)
            if rv != r0:
                parent[rv] = r0
    comps = defaultdict(list)
    for v in parent:
        comps[find(v)].append(v)
    return [np.array(sorted(c)) for c in comps.values()]


# surfaces of model C for which per-surface and per-component boxes are written
C_SURF_REPORT = {"iearad", "tcsrad", "pan-cels", "pan-celback", "truss", "truss cover"}
C_COMPONENT_SURF = {"iearad", "tcsrad", "pan-cels"}


def lws_rows(model, scene_path, content_dir, frame_item="ISS PIVOT"):
    items = parse_lws(scene_path)
    by_id = {it["id"]: it for it in items}
    frame = next(it for it in items if it["name"] == frame_item)
    world = {}

    def W(it):
        if it["id"] in world:
            return world[it["id"]]
        if it is frame:
            M = np.eye(4)  # report in the frame item's object space
        else:
            par = by_id.get(it.get("parent"))
            P = W(par) if par is not None else np.eye(4)
            M = P @ lw_local(it)
        world[it["id"]] = M
        return M

    def under_frame(it):
        while it is not None:
            if it is frame:
                return True
            it = by_id.get(it.get("parent"))
        return False

    lwo_cache = {}
    rows = []
    own = {}
    for it in items:
        if not under_frame(it) or it is frame:
            continue
        M = W(it)
        pname = by_id[it["parent"]]["name"] if it.get("parent") in by_id else ""
        if it["kind"] != "object":
            continue
        fp = os.path.join(content_dir, it["path"].replace("/", os.sep))
        if fp not in lwo_cache:
            lwo_cache[fp] = read_lwo2(fp)
        tags, layers = lwo_cache[fp]
        lay = [L for L in layers if L.number == it["layer"] - 1] or \
              ([layers[it["layer"] - 1]] if len(layers) >= it["layer"] else [])
        if not lay or not len(lay[0].points):
            continue
        L = lay[0]
        Pw = L.points @ M[:3, :3].T + M[:3, 3]
        hidden = it.get("dissolve", 0) == 1
        base = dict(model=model, file=it["path"], node_index=it["id"], name=it["name"] + (" [dissolved]" if hidden else ""),
                    parent=pname, path=f"{pname}/{it['name']}")
        box = (Pw.min(0), Pw.max(0), len(Pw))
        own[it["id"]] = box
        rows.append(dict(base, scope="mesh", box=box))
        groups = layer_groups(tags, L, "SURF")
        for sname, idx in sorted(groups.items()):
            if sname not in C_SURF_REPORT:
                continue
            P = Pw[idx]
            rows.append(dict(base, scope=f"surface:{sname}", box=(P.min(0), P.max(0), len(P))))
            if sname in C_COMPONENT_SURF:
                polys = [L.polys[pi] for pi, tg in L.surf_of_poly.items()
                         if (tags[tg] if tg < len(tags) else "") == sname and pi < len(L.polys)]
                comps = connected_components(polys, idx)
                comps.sort(key=lambda c: (round(float(Pw[c][:, 0].mean()), 1), round(float(Pw[c][:, 2].mean()), 1)))
                for k, c in enumerate(comps):
                    P = Pw[c]
                    rows.append(dict(base, scope=f"component:{sname}#{k}", box=(P.min(0), P.max(0), len(P))))
    # subtree boxes for nulls (e.g. LAB, NODE1, AIRLOCK, FGB, SM, JEM, MLM, SSRMS ...)
    children = defaultdict(list)
    for it in items:
        if it.get("parent"):
            children[it["parent"]].append(it)

    def sub(it):
        boxes = [own[it["id"]]] if it["id"] in own else []
        for c in children[it["id"]]:
            s = sub(c)
            if s is not None:
                boxes.append(s)
        if not boxes:
            return None
        return (np.min([b[0] for b in boxes], 0), np.max([b[1] for b in boxes], 0), sum(b[2] for b in boxes))

    for it in items:
        if under_frame(it) and it is not frame and children[it["id"]]:
            s = sub(it)
            if s is not None:
                pname = by_id[it["parent"]]["name"] if it.get("parent") in by_id else ""
                rows.append(dict(model=model, file=it["path"], node_index=it["id"], name=it["name"], parent=pname,
                                 path=f"{pname}/{it['name']}", scope="subtree", box=s))
    return rows


# ----------------------------------------------------------------------------------------
def write_csv(rows, out):
    cols = ["model", "file", "node_index", "name", "parent", "scope", "n_vertices",
            "min_x", "min_y", "min_z", "max_x", "max_y", "max_z", "center_x", "center_y", "center_z",
            "size_x", "size_y", "size_z",
            "iss_cx_m", "iss_cy_m", "iss_cz_m", "iss_sx_m", "iss_sy_m", "iss_sz_m", "path"]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            mn, mx, nv = r["box"]
            c = (mn + mx) / 2
            s = mx - mn
            mb = mapped_box(r["model"], mn, mx)
            ic = [f"{v:.3f}" for v in (mb[0] + mb[1]) / 2]
            isz = [f"{v:.3f}" for v in (mb[1] - mb[0])]
            w.writerow([r["model"], r["file"], r["node_index"], r["name"], r["parent"], r["scope"], nv,
                        *[f"{v:.4f}" for v in mn], *[f"{v:.4f}" for v in mx], *[f"{v:.4f}" for v in c],
                        *[f"{v:.4f}" for v in s], *ic, *isz, r["path"]])


def main():
    rows = []
    c_scene = os.path.join(HERE, "C_HighRes", "Scenes", "ISS complete_2011.lws")
    if os.path.exists(c_scene):
        rows += lws_rows("C", c_scene, os.path.join(HERE, "C_HighRes"))
    for model, fn, skip in (("VTAD", "ISS_stationary_VTAD.glb", False), ("IGOAL", "ISS_D_IGOAL.glb", True)):
        p = os.path.join(HERE, fn)
        if os.path.exists(p):
            rows += glb_rows(model, p, skip_root_transform=skip)
    out = os.path.join(HERE, "parts_bbox.csv")
    write_csv(rows, out)
    print(f"wrote {len(rows)} rows -> {out}")
    for k, m in MAPPINGS.items():
        print(k, "scale", m["scale"], "t", m["t"], "R rows", m["R"].tolist())


if __name__ == "__main__":
    main()
