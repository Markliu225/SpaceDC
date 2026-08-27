# -*- coding: utf-8 -*-
"""Local PNG plots: TEME position, ours vs STK, per benchmark case.

Reads out/stk/ephem_<case>.csv and out/ours/ephem_<case>.csv only (no
backend deps), writes out/plots/position_<case>.png and a combined
position_error_all.png.  Run with any Python that has matplotlib.
"""
import csv, math, os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
PLOTS = os.path.join(OUT, "plots")
os.makedirs(PLOTS, exist_ok=True)
rcParams["font.family"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
rcParams["axes.unicode_minus"] = False

C_STK, C_OURS = "#2a78d6", "#1baf7a"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e1e0d9"
NAMES = {"leo_iss": "LEO · ISS 类 (51.6°, 420 km)",
         "sso_landsat": "SSO · 705 km", "geo_goes": "GEO"}

def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    hdr = rows[0]
    return {h: [float(r[i]) for r in rows[1:]] for i, h in enumerate(hdr)}

def style(ax):
    ax.grid(True, color=GRID, linewidth=0.8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#c3c2b7")
    ax.tick_params(colors=INK2, labelsize=9)
    ax.xaxis.label.set_color(INK2); ax.yaxis.label.set_color(INK2)

errs = {}
for case, title in NAMES.items():
    s = load(os.path.join(OUT, "stk", "ephem_%s.csv" % case))
    o = load(os.path.join(OUT, "ours", "ephem_%s.csv" % case))
    io_ = {round(t): i for i, t in enumerate(o["t"])}
    t_h, sx, sy, sz, ox, oy, oz, d_um = [], [], [], [], [], [], [], []
    for i, t in enumerate(s["t"]):
        j = io_.get(round(t))
        if j is None:
            continue
        t_h.append(t / 3600.0)
        sx.append(s["x_km"][i]); sy.append(s["y_km"][i]); sz.append(s["z_km"][i])
        ox.append(o["x_km"][j]); oy.append(o["y_km"][j]); oz.append(o["z_km"][j])
        d_um.append(math.dist((sx[-1], sy[-1], sz[-1]), (ox[-1], oy[-1], oz[-1])) * 1e9)  # km -> um
    errs[case] = (t_h, d_um)

    fig, axes = plt.subplots(2, 2, figsize=(12, 7.2), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    for ax, (lab, a, b) in zip(axes.flat[:3], [("X", sx, ox), ("Y", sy, oy), ("Z", sz, oz)]):
        ax.plot(t_h, a, color=C_STK, linewidth=2.4, label="STK 11.6")
        ax.plot(t_h, b, color=C_OURS, linewidth=1.4, linestyle=(0, (5, 3)), label="SpaceDC")
        ax.set_ylabel("%s (km, TEME)" % lab); ax.set_xlabel("时间 (h)")
        ax.set_xlim(0, 24); style(ax)
    ax = axes.flat[3]
    ax.plot(t_h, d_um, color=C_OURS, linewidth=1.2)
    ax.set_ylabel("|Δr| (µm)"); ax.set_xlabel("时间 (h)"); ax.set_xlim(0, 24); ax.set_ylim(bottom=0)
    ax.set_title("位置差 SpaceDC − STK，最大 %.2f µm" % max(d_um), fontsize=10, color=INK2, loc="left")
    style(ax)
    axes.flat[0].legend(loc="upper right", frameon=False, fontsize=9)
    fig.suptitle("TEME 位置对比 · %s · 2024-08-22 12:00 UTC 起 24 h" % title,
                 fontsize=13, color=INK, x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    p = os.path.join(PLOTS, "position_%s.png" % case)
    fig.savefig(p, facecolor=fig.get_facecolor()); plt.close(fig)
    print("wrote", p)

# combined error figure, small multiples
fig, axes = plt.subplots(1, 3, figsize=(13, 3.6), dpi=150, sharey=True)
fig.patch.set_facecolor("#fcfcfb")
for ax, (case, (t_h, d)) in zip(axes, errs.items()):
    ax.plot(t_h, d, color=C_OURS, linewidth=1.1)
    ax.set_title("%s · max %.2f µm" % (NAMES[case].split(" (")[0], max(d)), fontsize=10, color=INK2, loc="left")
    ax.set_xlabel("时间 (h)"); ax.set_xlim(0, 24); style(ax)
axes[0].set_ylabel("|Δr| (µm)"); axes[0].set_ylim(bottom=0)
fig.suptitle("SGP4 位置差 SpaceDC − STK · 三用例 24 h", fontsize=13, color=INK, x=0.02, ha="left")
fig.tight_layout(rect=(0, 0, 1, 0.92))
p = os.path.join(PLOTS, "position_error_all.png")
fig.savefig(p, facecolor=fig.get_facecolor()); plt.close(fig)
print("wrote", p)
