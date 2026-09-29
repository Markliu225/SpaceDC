"""Minimal LightWave LWO2 reader: layers -> points, polygons, surface/part tags.

Only what is needed for bounding boxes: PNTS, LAYR, TAGS, POLS(FACE/PTCH/SUBD),
PTAG(SURF/PART).  Everything else (VMAP, SURF, CLIP, ENVL ...) is skipped.
"""
import struct
import numpy as np


def _read_s0(buf, off):
    end = buf.index(b"\0", off)
    s = buf[off:end].decode("latin-1")
    n = end - off + 1
    if n % 2:
        n += 1
    return s, off + n


def _read_vx(buf, off):
    if buf[off] == 0xFF:
        return struct.unpack(">I", buf[off:off + 4])[0] & 0x00FFFFFF, off + 4
    return struct.unpack(">H", buf[off:off + 2])[0], off + 2


class Layer:
    def __init__(self, number, name, pivot, parent):
        self.number = number
        self.name = name
        self.pivot = np.asarray(pivot, float)
        self.parent = parent
        self.points = np.zeros((0, 3))
        self.polys = []          # list of index arrays
        self.poly_type = None
        self.surf_of_poly = {}   # poly idx -> tag idx
        self.part_of_poly = {}


def read_lwo2(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"FORM" or data[8:12] not in (b"LWO2", b"LWO3"):
        raise ValueError(f"{path}: not an LWO2 file (header {data[:12]!r})")
    size = struct.unpack(">I", data[4:8])[0]
    end = min(8 + size, len(data))
    off = 12
    tags = []
    layers = []
    cur = None
    while off + 8 <= end:
        cid = data[off:off + 4]
        csz = struct.unpack(">I", data[off + 4:off + 8])[0]
        body = data[off + 8:off + 8 + csz]
        off = off + 8 + csz + (csz & 1)
        if cid == b"TAGS":
            p = 0
            while p < len(body):
                s, p = _read_s0(body, p)
                tags.append(s)
        elif cid == b"LAYR":
            num, flags = struct.unpack(">HH", body[:4])
            pivot = struct.unpack(">3f", body[4:16])
            name, p = _read_s0(body, 16)
            parent = struct.unpack(">h", body[p:p + 2])[0] if p + 2 <= len(body) else -1
            cur = Layer(num, name, pivot, parent)
            layers.append(cur)
        elif cid == b"PNTS":
            if cur is None:           # file without LAYR chunk
                cur = Layer(0, "", (0, 0, 0), -1)
                layers.append(cur)
            pts = np.frombuffer(body, dtype=">f4").astype(float).reshape(-1, 3)
            cur.points = pts
        elif cid == b"POLS":
            ptype = body[:4].decode("latin-1")
            p = 4
            polys = []
            n = len(body)
            while p < n:
                nv = struct.unpack(">H", body[p:p + 2])[0] & 0x03FF
                p += 2
                idx = []
                for _ in range(nv):
                    v, p = _read_vx(body, p)
                    idx.append(v)
                polys.append(idx)
            # several POLS chunks may exist in one layer (e.g. FACE + PTCH); keep offsets
            base = len(cur.polys)
            cur.polys.extend(polys)
            cur.poly_type = ptype if cur.poly_type is None else cur.poly_type + "+" + ptype
            cur._last_pols_base = base
        elif cid == b"PTAG":
            ttype = body[:4]
            p = 4
            base = getattr(cur, "_last_pols_base", 0)
            target = cur.surf_of_poly if ttype == b"SURF" else (cur.part_of_poly if ttype == b"PART" else None)
            while p < len(body):
                pi, p = _read_vx(body, p)
                tg = struct.unpack(">H", body[p:p + 2])[0]
                p += 2
                if target is not None:
                    target[base + pi] = tg
    return tags, layers


def layer_groups(tags, layer, kind="SURF"):
    """Return {tag_name: point-index array} for polygons grouped by SURF or PART tag."""
    m = layer.surf_of_poly if kind == "SURF" else layer.part_of_poly
    groups = {}
    for pi, tg in m.items():
        if pi >= len(layer.polys):
            continue
        name = tags[tg] if tg < len(tags) else f"tag{tg}"
        groups.setdefault(name, []).extend(layer.polys[pi])
    return {k: np.unique(np.asarray(v, dtype=np.int64)) for k, v in groups.items()}
