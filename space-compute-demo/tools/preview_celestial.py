"""Faithful offline preview of the twin's celestial bodies (Earth + clouds +
atmosphere + Sun + starfield) — a small analytic ray-tracer that replicates Kit's
UsdPreviewSurface semantics (diffuse texture + emissive + uniform opacity blend),
so the cloud / atmosphere / day-night look can be verified WITHOUT the live RTX
viewport. Imports the exact scene constants from gen_twin_satellite so it never
drifts from what Kit renders.

    python tools/preview_celestial.py [out.png] [--eye x,y,z] [--target x,y,z]
                                      [--focal F] [--size N]
"""
from __future__ import annotations
import sys
import numpy as np
from PIL import Image

import gen_twin_satellite as G

HAP, VAP = 20.955, 15.2908            # film aperture (matches render_usd / USD camera)


def load(rel):
    return np.asarray(Image.open(G.ROOT / "usd" / rel.lstrip("./")).convert("RGB"), float) / 255.0


def sample(tex, u, v):
    """Nearest-sample an equirectangular texture; u,v in [0,1] arrays."""
    Hd, Wd = tex.shape[:2]
    ui = np.clip((u * (Wd - 1)).astype(int), 0, Wd - 1)
    vi = np.clip((v * (Hd - 1)).astype(int), 0, Hd - 1)
    return tex[vi, ui]


def equirect_uv(n):
    """Unit normals (...,3) → equirect (u,v), matching uv_sphere's lon→u, lat→v."""
    lon = np.arctan2(n[..., 1], n[..., 0])
    lat = np.arcsin(np.clip(n[..., 2], -1, 1))
    u = lon / (2 * np.pi) + 0.5
    v = 1.0 - (0.5 + lat / np.pi)          # image row 0 = north pole
    return u, v


def intersect(O, D, C, R):
    """Ray O + tD vs sphere(C,R). Returns (hit mask, t near, point, normal)."""
    oc = O - C
    b = 2.0 * (D @ oc)
    c = oc @ oc - R * R
    disc = b * b - 4.0 * c
    ok = disc >= 0
    sq = np.sqrt(np.where(ok, disc, 0.0))
    t = (-b - sq) / 2.0
    hit = ok & (t > 0)
    P = O + t[..., None] * D
    N = (P - C) / R
    return hit, t, P, N


def main():
    args = sys.argv[1:]
    out = next((a for a in args if not a.startswith("--")), "tools/_renders/celestial.png")
    def opt(k, d):
        return args[args.index(k) + 1] if k in args else d
    eye = np.array([float(x) for x in opt("--eye", "1234,-1480,1036").split(",")])
    target = np.array([float(x) for x in opt("--target", "0,0,0").split(",")])
    focal = float(opt("--focal", "22"))
    size = int(opt("--size", "900"))

    # camera basis
    f = target - eye; f /= np.linalg.norm(f)
    r = np.cross(np.array([0, 0, 1.0]), f); r /= np.linalg.norm(r)
    u = np.cross(f, r)
    tan_h, tan_v = (HAP / 2) / focal, (VAP / 2) / focal
    W = size; H = int(round(size * VAP / HAP))
    xs = (np.arange(W) + 0.5) / W * 2 - 1
    ys = 1 - (np.arange(H) + 0.5) / H * 2
    NX, NY = np.meshgrid(xs, ys)
    D = (f[None, None] + (NX * tan_h)[..., None] * r + (NY * tan_v)[..., None] * u)
    D /= np.linalg.norm(D, axis=2, keepdims=True)

    # textures + constants
    day = load(G.EARTH_TEX)
    night = load(G.EARTH_NIGHT_TEX) if hasattr(G, "EARTH_NIGHT_TEX") else None
    cloud = load(G.CLOUD_TEX) if hasattr(G, "CLOUD_TEX") else None
    stars = load("./textures/starfield.png"); suntex = load(G.SUN_TEX)
    C = np.array(G.EARTH_CENTER); Re = G.EARTH_RADIUS_CM
    sun_dir = np.array(G.SUN_DIR); sun_dir = sun_dir / np.linalg.norm(sun_dir)
    sun_c = sun_dir * G.SUN_DIST_CM
    AMB = 0.13

    # background starfield
    lon = np.arctan2(D[..., 1], D[..., 0]); lat = np.arcsin(np.clip(D[..., 2], -1, 1))
    bg = sample(stars, lon / (2 * np.pi) + 0.5, 0.5 - lat / np.pi)
    img = 1.0 - np.exp(-bg * 2.4)

    O = eye.astype(float)
    # --- Earth (opaque): day diffuse * (amb + N·sun) + dimmed day self-emissive ---
    eh, et, eP, eN = intersect(O, D, C, Re)
    eu, ev = equirect_uv(eN)
    ndl = np.clip(np.sum(eN * sun_dir, axis=2), 0, 1)[..., None]
    dayrgb = sample(day, eu, ev)
    earth = dayrgb * (AMB + ndl)
    if night is not None:
        # City-light emissive (matches the Kit material: adds everywhere,
        # visually only survives on the dark side).
        earth = earth + sample(night, eu, ev) * np.array(G.EARTH_NIGHT_EMIT)
    else:
        earth = earth + dayrgb * np.array(getattr(G, "EARTH_EMIT", (0.0,) * 3))
    img = np.where(eh[..., None], earth, img)

    # --- Clouds (optional): white * (amb + N·sun), opacity = cloud-map red ---
    if cloud is not None:
        ch, ct, cP, cN = intersect(O, D, C, Re * G.CLOUD_SCALE)
        cu, cv = equirect_uv(cN)
        cndl = np.clip(np.sum(cN * sun_dir, axis=2), 0, 1)[..., None]
        ca = (sample(cloud, cu, cv)[..., 0:1] * ch[..., None]
              * float(getattr(G, "CLOUD_OPACITY", 1.0)))
        img = img * (1 - ca) + (np.array([1.0, 1.0, 1.0]) * (AMB + cndl)) * ca

    # --- Sun (emissive disk) ---
    sh, st_, sP, sN = intersect(O, D, sun_c, G.SUN_RADIUS_CM)
    su, sv = equirect_uv(sN)
    sun_col = sample(suntex, su, sv) * np.array(G.SUN_EMIT)
    img = np.where(sh[..., None], sun_col, img)

    img = np.clip(img, 0, 1)
    Image.fromarray((img * 255).astype("uint8")).save(out)
    print(f"[celestial] {out}  {W}x{H}  focal={focal}  clouds={cloud is not None}")


if __name__ == "__main__":
    main()
