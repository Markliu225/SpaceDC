"""Generate the NVIDIA-style compute-blade front textures for the twin servers:
  usd/textures/nv_blade_front.png       — diffuse (gunmetal + gold chevron grille
                                          + NVIDIA-green brand rail), wide 4:1
  usd/textures/nv_blade_front_emit.png  — emissive mask (green status dot + brand
                                          tile + faint gold rim)
Run: python tools/gen_blade_texture.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "usd" / "textures"
W, H = 1024, 256

GUNMETAL = (21, 24, 30); ALU = (156, 163, 176)
GOLD = (201, 150, 43); GOLD_HI = (232, 198, 106); GOLD_LO = (90, 63, 14)
RAIL = (12, 14, 18); GREEN = (118, 185, 0); WORD = (200, 204, 212)


def _font(size):
    for name in ("arialbd.ttf", "Arialbd.ttf", "arial.ttf", "segoeuib.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def diffuse():
    img = Image.new("RGB", (W, H), GUNMETAL)
    d = ImageDraw.Draw(img, "RGBA")
    # brushed vertical gradient on the body (subtle sheen)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(GUNMETAL[i] + (6 - 12 * t)) for i in range(3)))
    # 1) top brushed-aluminium heat-spreader lip
    d.rectangle([0, 0, W, 28], fill=ALU)
    # 2) gold grille band (hero) with coarse, mip-safe chevron voids
    d.rectangle([0, 64, W, 176], fill=GOLD)
    GY0, GY1, yc, APEX = 72, 168, 120, 26
    for i in range(8):
        cx = 64 + i * 120
        d.line([(cx, GY0), (cx + APEX, yc)], fill=GOLD_LO, width=22)
        d.line([(cx + APEX, yc), (cx, GY1)], fill=GOLD_LO, width=22)
    d.rectangle([0, 64, W, 70], fill=GOLD_HI)      # machined top highlight
    d.rectangle([0, 170, W, 176], fill=GOLD_LO)    # machined bottom shadow
    # 3) bottom brand rail
    d.rectangle([0, 196, W, H], fill=RAIL)
    d.rounded_rectangle([40, 202, 120, 250], radius=14, fill=GREEN)   # NVIDIA green tile
    f = _font(34)
    d.text((150, 210), "NVIDIA", font=f, fill=WORD)                  # wordmark
    d.ellipse([942, 206, 978, 242], fill=GREEN)                      # status dot
    img.save(OUT / "nv_blade_front.png")
    return img


def emissive():
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([942, 206, 978, 242], fill=GREEN)                      # live status dot (blooms)
    d.rounded_rectangle([40, 202, 120, 250], radius=14, fill=(59, 93, 0))   # green tile ~50%
    d.rectangle([0, 64, W, 70], fill=(42, 36, 16))                   # faint gold rim glow
    img.save(OUT / "nv_blade_front_emit.png")
    return img


if __name__ == "__main__":
    diffuse(); emissive()
    print("wrote", OUT / "nv_blade_front.png", "+", OUT / "nv_blade_front_emit.png")
