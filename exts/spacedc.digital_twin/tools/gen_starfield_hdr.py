#!/usr/bin/env python3
"""
Generate a procedural starfield equirectangular HDR image.
Pure Python — no numpy or Pillow required.
Outputs Radiance RGBE (.hdr) format.
"""

import math
import os
import random
import struct

WIDTH = 2048
HEIGHT = 1024

# ── RGBE encoding ────────────────────────────────────────────

def _float_to_rgbe(r: float, g: float, b: float) -> bytes:
    """Convert float RGB to Radiance RGBE (4 bytes)."""
    v = max(r, g, b)
    if v < 1e-32:
        return b'\x00\x00\x00\x00'
    # frexp: v = mantissa * 2^exp, 0.5 <= mantissa < 1
    mantissa, exp = math.frexp(v)
    scale = mantissa * 256.0 / v
    ri = max(0, min(255, int(r * scale)))
    gi = max(0, min(255, int(g * scale)))
    bi = max(0, min(255, int(b * scale)))
    ei = max(0, min(255, exp + 128))
    return bytes([ri, gi, bi, ei])


def _write_hdr(path: str, width: int, height: int, pixels: list):
    """
    Write a Radiance HDR file.
    pixels: list of (r, g, b) float tuples, row-major, top-to-bottom.
    Uses uncompressed scanline format for simplicity.
    """
    with open(path, 'wb') as f:
        # Header
        f.write(b"#?RADIANCE\n")
        f.write(b"FORMAT=32-bit_rle_rgbe\n")
        f.write(b"\n")
        # Resolution string: -Y height +X width
        res = f"-Y {height} +X {width}\n"
        f.write(res.encode('ascii'))
        # Pixel data — uncompressed: just 4 bytes per pixel
        for i in range(len(pixels)):
            r, g, b = pixels[i]
            f.write(_float_to_rgbe(r, g, b))


# ── Star generation ──────────────────────────────────────────

def main():
    random.seed(42)

    # Prepare blank (dark space) background
    pixels = [(0.0, 0.0, 0.0)] * (WIDTH * HEIGHT)

    # Very faint background glow (deep space noise)
    for i in range(len(pixels)):
        noise = random.random() * 0.002
        pixels[i] = (noise * 0.5, noise * 0.5, noise * 0.7)

    # Generate stars
    num_stars = 12000
    for _ in range(num_stars):
        # Random position on sphere → equirectangular UV
        theta = random.random() * 2.0 * math.pi       # longitude [0, 2π]
        phi = math.acos(2.0 * random.random() - 1.0)   # latitude [0, π]

        u = theta / (2.0 * math.pi)   # [0, 1]
        v = phi / math.pi              # [0, 1]

        px = int(u * WIDTH) % WIDTH
        py = int(v * HEIGHT) % HEIGHT

        # Star brightness — power law distribution (many dim, few bright)
        brightness = 0.3 + random.random() ** 3 * 8.0

        # Star color temperature variation
        temp_rand = random.random()
        if temp_rand < 0.15:
            # Blue-white hot star
            cr, cg, cb = 0.8, 0.85, 1.0
        elif temp_rand < 0.40:
            # Pure white
            cr, cg, cb = 1.0, 1.0, 1.0
        elif temp_rand < 0.70:
            # Yellow-white (sun-like)
            cr, cg, cb = 1.0, 0.95, 0.85
        elif temp_rand < 0.85:
            # Orange
            cr, cg, cb = 1.0, 0.8, 0.5
        else:
            # Red dwarf
            cr, cg, cb = 1.0, 0.6, 0.4

        r = brightness * cr
        g = brightness * cg
        b = brightness * cb

        # Set the star pixel
        idx = py * WIDTH + px
        pixels[idx] = (r, g, b)

        # Optionally create a soft glow (1-pixel radius) for brighter stars
        if brightness > 2.0:
            glow = brightness * 0.15
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    if dx == 0 and dy == 0:
                        continue
                    gx = (px + dx) % WIDTH
                    gy = max(0, min(HEIGHT - 1, py + dy))
                    gidx = gy * WIDTH + gx
                    er, eg, eb = pixels[gidx]
                    pixels[gidx] = (
                        er + glow * cr,
                        eg + glow * cg,
                        eb + glow * cb,
                    )

    # Add a subtle Milky Way band (horizontal gaussian strip)
    for y in range(HEIGHT):
        v = y / HEIGHT
        lat = (v - 0.5) * math.pi  # [-π/2, π/2]
        # Milky Way roughly along the equator in galactic coords
        # We tilt it ~60° from equator for visual interest
        for x in range(WIDTH):
            u = x / WIDTH
            lon = u * 2.0 * math.pi
            # Simple gaussian band
            band_center = 0.3 * math.sin(lon * 0.5 + 0.8)
            dist = abs(lat - band_center)
            glow = 0.008 * math.exp(-dist * dist / 0.12)
            if glow > 0.0005:
                idx = y * WIDTH + x
                er, eg, eb = pixels[idx]
                pixels[idx] = (er + glow * 0.9, eg + glow * 0.85, eb + glow * 1.0)

    # Write HDR
    out_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "data", "textures"
    )
    out_dir = os.path.normpath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "starfield.hdr")

    print(f"Writing starfield HDR ({WIDTH}x{HEIGHT}) to: {out_path}")
    _write_hdr(out_path, WIDTH, HEIGHT, pixels)
    size_kb = os.path.getsize(out_path) / 1024
    print(f"Done! File size: {size_kb:.0f} KB")


if __name__ == "__main__":
    main()
