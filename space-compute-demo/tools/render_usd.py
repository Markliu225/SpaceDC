"""Minimal flat-shaded software renderer for USD/USDZ — no GL needed.

Reads every UsdGeom.Mesh on a stage, transforms to world space, projects
orthographically from a chosen view, z-sorts triangles (painter's algorithm),
and flat-shades them with a single key light. Each top-level part gets a
distinct hue so structure (and slots) are easy to read.

Usage:
    python tools/render_usd.py <stage.usd[z]> [out.png] [--view iso|front|side|top|back]
                               [--size 1100] [--by-part] [--label]

--by-part colors each /root/ParentNode/<part> a distinct hue (default).
--label   prints a legend mapping color -> part path to stdout.
"""
from __future__ import annotations

import sys
import colorsys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from pxr import Usd, UsdGeom, UsdLux, Gf

# Keep in sync with ov_app/.../extension.py SUN_DRIVEN_LIGHTS (lo, hi). The
# --sun f flag previews the runtime intensity lo+f*(hi-lo) for these lights.
_DRIVEN_RANGES = {
    "Key":         (400.0, 4000.0),
    "Rim":         (300.0, 1300.0),
    "EarthBounce": (1000.0, 1600.0),
}
_LIT_EXPOSURE = 1.0 / 1600.0   # tonemap scale for the lit preview


def gather_lights(stage, sun=None):
    """Scene lights for the lit preview: returns (ambient rgb, [(L_unit, rgb)]).
    DistantLight emits along local -Z; L = -emit is the to-light direction.
    DomeLight contributes uniform ambient. `sun` (0..1), if given, applies the
    extension's lo+f*(hi-lo) ramp to the SUN_DRIVEN lights."""
    tc = Usd.TimeCode.Default()
    ambient = np.zeros(3)
    dirs = []
    for prim in stage.Traverse():
        if prim.IsA(UsdLux.DistantLight):
            lt = UsdLux.DistantLight(prim)
            inten = float(lt.GetIntensityAttr().Get() or 0.0)
            nm = prim.GetName()
            if sun is not None and nm in _DRIVEN_RANGES:
                lo, hi = _DRIVEN_RANGES[nm]
                inten = lo + max(0.0, min(1.0, sun)) * (hi - lo)
            col = lt.GetColorAttr().Get() or Gf.Vec3f(1, 1, 1)
            xf = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(tc)
            emit = np.array(xf.TransformDir(Gf.Vec3d(0, 0, -1)))
            n = np.linalg.norm(emit) or 1.0
            L = -emit / n
            dirs.append((L, np.array([col[0], col[1], col[2]]) * inten))
        elif prim.IsA(UsdLux.DomeLight):
            lt = UsdLux.DomeLight(prim)
            inten = float(lt.GetIntensityAttr().Get() or 0.0)
            col = lt.GetColorAttr().Get() or Gf.Vec3f(1, 1, 1)
            ambient = ambient + np.array([col[0], col[1], col[2]]) * inten
    return ambient, dirs


def _triangulate(counts, indices):
    tris = []
    i = 0
    for c in counts:
        if c < 3:
            i += c
            continue
        v0 = indices[i]
        for k in range(1, c - 1):
            tris.append((v0, indices[i + k], indices[i + k + 1]))
        i += c
    return tris


def _part_key(path: str) -> str:
    # /root/ParentNode/tripo_part_3/Mesh_5 -> tripo_part_3
    # /World/Satellite/Servers/Server_UpY_0/Chassis -> Server_UpY_0
    segs = path.strip("/").split("/")
    for s in reversed(segs):  # deepest-first: Server_UpY_0 beats the Servers scope
        if s.startswith("Server_") or "part" in s or "node" in s or "Panel" in s or "Slot" in s:
            return s
    return segs[-2] if len(segs) >= 2 else path


def gather(stage):
    """Return list of (part_key, Nx3 world points, list-of-tri-index)."""
    xfc = UsdGeom.XformCache(Usd.TimeCode.Default())
    meshes = []
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        m = UsdGeom.Mesh(prim)
        pts = m.GetPointsAttr().Get()
        if not pts:
            continue
        counts = m.GetFaceVertexCountsAttr().Get() or []
        idx = m.GetFaceVertexIndicesAttr().Get() or []
        tris = _triangulate(counts, idx)
        if not tris:
            continue
        M = xfc.GetLocalToWorldTransform(prim)
        Mn = np.array(M, dtype=np.float64).reshape(4, 4)  # row-vector convention
        P = np.array([[p[0], p[1], p[2], 1.0] for p in pts], dtype=np.float64)
        W = P @ Mn  # (N,4)
        W = W[:, :3] / W[:, 3:4]
        meshes.append((_part_key(prim.GetPath().pathString), W, np.array(tris, dtype=np.int64)))
    return meshes


VIEWS = {
    # eye direction (from camera toward target), up
    "iso":   (np.array([1.0, -1.0, 0.6]),  np.array([0.0, 0.0, 1.0])),
    "iso2":  (np.array([-1.0, -1.0, 0.6]), np.array([0.0, 0.0, 1.0])),
    "front": (np.array([0.0, -1.0, 0.0]),  np.array([0.0, 0.0, 1.0])),
    "back":  (np.array([0.0, 1.0, 0.0]),   np.array([0.0, 0.0, 1.0])),
    "side":  (np.array([1.0, 0.0, 0.0]),   np.array([0.0, 0.0, 1.0])),
    "top":   (np.array([0.0, 0.0, 1.0]),   np.array([0.0, 1.0, 0.0])),
}


def basis(view, eye=None, target=None):
    if eye is not None and target is not None:
        eye_dir = np.array(target, float) - np.array(eye, float)
        up = np.array([0.0, 0.0, 1.0])
    else:
        eye_dir, up = VIEWS[view]
    f = eye_dir / np.linalg.norm(eye_dir)        # forward (toward scene, +depth)
    r = np.cross(up, f); r /= np.linalg.norm(r)  # right -> screen +x
    u = np.cross(f, r)                            # up    -> screen +y
    return r, u, f


def render_persp(meshes, out, eye, target, focal=35.0, hap=20.955, vap=15.2908,
                 size=1100, by_part=True, lit=None):
    """Perspective render matching USD Camera semantics (focalLength + film
    aperture). If `lit` = (ambient, dirs) the triangles are shaded by the scene
    lights (Lambertian + ambient, normals flipped toward the camera so the dark
    side reads correctly) instead of the structural hue light — a brightness
    preview for the Kit RTX viewport."""
    eye = np.array(eye, float)
    r, u, f = basis("iso", eye, target)
    tan_h = (hap / 2.0) / focal
    tan_v = (vap / 2.0) / focal
    W = size
    H = int(round(size * vap / hap))
    # In a lit render the DomeLight IS the background (Kit renders the dome as
    # the sky). Tonemap its ambient as the bg so "black space vs white bg" is
    # verifiable; non-lit keeps the neutral dark slate.
    if lit is not None:
        amb = lit[0] * _LIT_EXPOSURE
        bg = tuple(int(255 * (1.0 - np.exp(-max(0.0, v)))) for v in amb)
    else:
        bg = (8, 10, 16)
    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)
    parts = sorted({k for k, _, _ in meshes})
    hues = {p: (i / max(1, len(parts))) for i, p in enumerate(parts)}
    light = np.array([0.4, -0.5, 0.75]); light /= np.linalg.norm(light)
    faces = []
    for key, Wpts, tris in meshes:
        rel = Wpts - eye
        depth = rel @ f
        sx = rel @ r; sy = rel @ u
        safe = np.where(depth <= 1e-6, 1e-6, depth)
        ndc_x = (sx / safe) / tan_h
        ndc_y = (sy / safe) / tan_v
        px = (ndc_x * 0.5 + 0.5) * W
        py = (1.0 - (ndc_y * 0.5 + 0.5)) * H
        h = hues[key] if by_part else 0.58
        tv = Wpts[tris]
        nrm = np.cross(tv[:, 1] - tv[:, 0], tv[:, 2] - tv[:, 0])
        nl = np.linalg.norm(nrm, axis=1, keepdims=True); nl[nl == 0] = 1
        unit = nrm / nl
        cen = tv.mean(axis=1)
        to_cam = eye - cen
        flip = np.sum(unit * to_cam, axis=1) < 0
        unit[flip] = -unit[flip]            # orient toward the camera
        zc = depth[tris].mean(axis=1)
        if lit is not None:
            ambient, dirs = lit
            base = np.array(colorsys.hsv_to_rgb(h, 0.30, 1.0)) if by_part else np.array([0.7, 0.72, 0.78])
            for t in range(tris.shape[0]):
                a, b, c = tris[t]
                if depth[a] <= 0 and depth[b] <= 0 and depth[c] <= 0:
                    continue
                acc = ambient.copy()
                n = unit[t]
                for L, rgb in dirs:
                    d = n @ L
                    if d > 0:
                        acc = acc + rgb * d
                val = base * acc * _LIT_EXPOSURE
                col = tuple(int(255 * (1.0 - np.exp(-max(0.0, v)))) for v in val)
                faces.append((zc[t], [(px[a], py[a]), (px[b], py[b]), (px[c], py[c])], col))
        else:
            lam = np.abs(unit @ light)
            for t in range(tris.shape[0]):
                a, b, c = tris[t]
                if depth[a] <= 0 and depth[b] <= 0 and depth[c] <= 0:
                    continue
                poly = [(px[a], py[a]), (px[b], py[b]), (px[c], py[c])]
                shade = 0.22 + 0.78 * float(lam[t])
                rr, gg, bb = colorsys.hsv_to_rgb(h, 0.55, shade)
                faces.append((zc[t], poly, (int(rr*255), int(gg*255), int(bb*255))))
    faces.sort(key=lambda e: -e[0])
    for _, poly, col in faces:
        draw.polygon(poly, fill=col, outline=None)
    img.save(out)
    print(f"[persp] {out}  {W}x{H}  focal={focal}  tris={len(faces)}  lit={lit is not None}")


def render(path, out, view="iso", size=1100, by_part=True, label=False, only=None,
           eye=None, target=None, persp=False, focal=35.0, lit=False, sun=None):
    stage = Usd.Stage.Open(str(path))
    meshes = gather(stage)
    if only:
        keys = [k.strip() for k in only.split(",")]
        meshes = [m for m in meshes if any(k in m[0] for k in keys)]
    if not meshes:
        print("no meshes"); return
    lit_lights = gather_lights(stage, sun) if lit else None
    if persp and eye is not None and target is not None:
        render_persp(meshes, out, eye, target, focal=focal, size=size,
                     by_part=by_part, lit=lit_lights)
        return
    r, u, f = basis(view, eye, target)

    allpts = np.vstack([W for _, W, _ in meshes])
    sx = allpts @ r; sy = allpts @ u; sz = allpts @ f
    minx, maxx = sx.min(), sx.max()
    miny, maxy = sy.min(), sy.max()
    pad = 0.06
    spanx = (maxx - minx) or 1.0
    spany = (maxy - miny) or 1.0
    span = max(spanx, spany) * (1 + pad)
    cx = (minx + maxx) / 2; cy = (miny + maxy) / 2
    scale = size / span

    def to_px(P):
        x = P @ r; y = P @ u
        px = (x - cx) * scale + size / 2
        py = size / 2 - (y - cy) * scale
        return px, py

    img = Image.new("RGB", (size, size), (8, 10, 16))
    draw = ImageDraw.Draw(img)

    parts = sorted({k for k, _, _ in meshes})
    hues = {p: (i / max(1, len(parts))) for i, p in enumerate(parts)}
    light = np.array([0.4, -0.5, 0.75]); light /= np.linalg.norm(light)

    faces = []  # (depth, poly_px, shade_color)
    for key, W, tris in meshes:
        px, py = to_px(W)
        depth = W @ f
        h = hues[key] if by_part else 0.58
        tv = W[tris]  # (T,3,3)
        e1 = tv[:, 1] - tv[:, 0]; e2 = tv[:, 2] - tv[:, 0]
        nrm = np.cross(e1, e2)
        nl = np.linalg.norm(nrm, axis=1, keepdims=True); nl[nl == 0] = 1
        nrm = nrm / nl
        lam = np.abs(nrm @ light)
        zc = depth[tris].mean(axis=1)
        for t in range(tris.shape[0]):
            a, b, c = tris[t]
            poly = [(px[a], py[a]), (px[b], py[b]), (px[c], py[c])]
            shade = 0.22 + 0.78 * float(lam[t])
            rr, gg, bb = colorsys.hsv_to_rgb(h, 0.55, shade)
            faces.append((zc[t], poly, (int(rr*255), int(gg*255), int(bb*255))))

    faces.sort(key=lambda e: -e[0])  # far first
    for _, poly, col in faces:
        draw.polygon(poly, fill=col, outline=None)

    img.save(out)
    print(f"[render] {out}  view={view}  parts={len(parts)}  tris={len(faces)}")
    if label:
        for p in parts:
            rr, gg, bb = colorsys.hsv_to_rgb(hues[p], 0.55, 0.9)
            print(f"  {p:24s} hsv-hue={hues[p]:.2f}  rgb=({int(rr*255)},{int(gg*255)},{int(bb*255)})")


if __name__ == "__main__":
    args = sys.argv[1:]
    src = args[0]
    out = "render.png"
    view = "iso"
    size = 1100
    label = "--label" in args
    rest = [a for a in args[1:] if not a.startswith("--")]
    if rest:
        out = rest[0]
    if "--view" in args:
        view = args[args.index("--view") + 1]
    if "--size" in args:
        size = int(args[args.index("--size") + 1])
    only = args[args.index("--only") + 1] if "--only" in args else None
    eye = target = None
    if "--eye" in args:
        eye = [float(x) for x in args[args.index("--eye") + 1].split(",")]
    if "--target" in args:
        target = [float(x) for x in args[args.index("--target") + 1].split(",")]
    persp = "--persp" in args
    focal = float(args[args.index("--focal") + 1]) if "--focal" in args else 35.0
    lit = "--lit" in args
    sun = float(args[args.index("--sun") + 1]) if "--sun" in args else None
    render(src, out, view=view, size=size, label=label, only=only, eye=eye,
           target=target, persp=persp, focal=focal, lit=lit, sun=sun)
