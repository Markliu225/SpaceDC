"""Single-page English flow diagram: satellite assembly -> command path ->
coupled physics loop -> hot reload and live results.

Run: python fig_pipeline_en.py   ->  report/figures_en/fig_pipeline_en.png
"""
from __future__ import annotations

import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from figures import _box, _arrow, INK, LINE

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "figures_en")
os.makedirs(OUT, exist_ok=True)
plt.rcParams["font.family"] = ["Segoe UI", "Arial", "DejaVu Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

C_USER, C_CMD, C_PHYS, C_OUT = "#2E5A88", "#B85C1E", "#2F6B3A", "#7A3E7A"
F_USER, F_CMD, F_PHYS, F_OUT = "#EEF4FB", "#FDF3EA", "#EEF7EE", "#F7EEF7"
NL = chr(10)

TITLE_FS = 11.5
BODY_FS = 9.2
EDGE_FS = 8.6


def node(ax, x, y, w, h, title, body="", fill="#FFFFFF", edge=LINE, lw=1.1):
    _box(ax, x, y, w, h, "", fill=fill, edge=edge, lw=lw)
    if body:
        ax.text(x + w / 2, y + h - 0.34, title, ha="center", va="center", fontsize=TITLE_FS,
                fontweight="bold", color=INK)
        ax.text(x + w / 2, y + h - 0.66, body, ha="center", va="top", fontsize=BODY_FS,
                color=INK, linespacing=1.45)
    else:
        ax.text(x + w / 2, y + h / 2, title, ha="center", va="center", fontsize=TITLE_FS,
                fontweight="bold", color=INK)


def header(ax, x, w, y, text, color):
    _box(ax, x, y, w, 0.7, "", fill=color, edge=color)
    ax.text(x + w / 2, y + 0.35, text, ha="center", va="center", fontsize=12.5,
            fontweight="bold", color="white")


def label(ax, x, y, text, ha="center", rot=0, color=LINE):
    ax.text(x, y, text, ha=ha, va="center", fontsize=EDGE_FS, color=color, rotation=rot)


def poly_arrow(ax, pts, lw=1.4, color=LINE, ls="-"):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    if len(pts) > 2:
        ax.plot(xs[:-1], ys[:-1], color=color, lw=lw, ls=ls, zorder=2, solid_capstyle="round")
    _arrow(ax, xs[-2], ys[-2], xs[-1], ys[-1], lw=lw, color=color)


def main():
    W, H = 24.4, 14.3
    fig, ax = plt.subplots(figsize=(W * 0.8, H * 0.8))
    ax.text(0.4, 13.85, "SDCTwin data path: satellite assembly, coupled physics, hot reload, live results",
            fontsize=15, fontweight="bold", color=INK, va="center")
    HY = 12.6

    # ------------------------------------------------------------ column 1
    ax0, aw = 0.4, 5.2
    header(ax, ax0, aw, HY, "1   Assemble the satellite", C_USER)
    _box(ax, ax0 - 0.2, 3.5, aw + 0.4, 8.75, "", fill=F_USER, edge="#C9CFD6", rounded=False)
    steps = ["Step 1   Platform", "Step 2   Structure", "Step 3   Payload", "Step 4   Workload profile"]
    ys = [11.15, 10.05, 8.95, 7.85]
    for t, y in zip(steps, ys):
        node(ax, ax0, y, aw, 0.9, t)
        if y != ys[-1]:
            _arrow(ax, ax0 + aw / 2, y, ax0 + aw / 2, y - 0.18)
    node(ax, ax0, 5.85, aw, 1.4, "Preview on every edit",
         "a detached engine assembles the draft" + NL + "and returns margins and fit verdicts")
    _arrow(ax, ax0 + aw / 2, 7.85, ax0 + aw / 2, 7.27)
    poly_arrow(ax, [(ax0, 6.55), (ax0 - 0.08, 6.55), (ax0 - 0.08, 9.4), (ax0, 9.4)], ls="--", lw=1.1)
    label(ax, ax0 + 0.15, 7.55, "revise", ha="left")
    node(ax, ax0, 3.85, aw, 1.4, "Run",
         "one atomic commit of platform," + NL + "configuration, GPU slots, workload, attitude")
    _arrow(ax, ax0 + aw / 2, 5.85, ax0 + aw / 2, 5.27)

    # ------------------------------------------------------------ column 2
    bx0, bw = 6.6, 5.0
    header(ax, bx0, bw, HY, "2   Command path", C_CMD)
    _box(ax, bx0 - 0.2, 2.3, bw + 0.4, 9.95, "", fill=F_CMD, edge="#C9CFD6", rounded=False)
    node(ax, bx0, 10.5, bw, 1.4, "Command response",
         "FastAPI, synchronous mutators" + NL + "on the engine event loop")
    node(ax, bx0 + 0.6, 8.05, bw - 0.6, 1.5, "Engine state",
         "configuration, GPU groups, workload, attitude" + NL + "hot-applied at the next 1 Hz step, no restart")
    node(ax, bx0, 5.5, bw, 1.4, "Geometry store",
         "twin_params.json" + NL + "written under a lock")
    _arrow(ax, bx0 + 0.6 + (bw - 0.6) / 2, 10.5, bx0 + 0.6 + (bw - 0.6) / 2, 9.57)
    poly_arrow(ax, [(bx0 + 0.3, 10.5), (bx0 + 0.3, 6.92)])
    label(ax, bx0 + 0.48, 7.5, "geometry", rot=90)
    _arrow(ax, bx0 + bw / 2, 5.5, bx0 + bw / 2, 1.97)
    label(ax, bx0 + bw / 2 + 0.18, 3.7, "regenerate", ha="left")
    # Run -> command response
    poly_arrow(ax, [(ax0 + aw, 4.55), (6.15, 4.55), (6.15, 11.2), (bx0, 11.2)])
    label(ax, 6.15, 3.95, "REST")

    # ------------------------------------------------------------ asset pipeline band
    node(ax, 6.6, 0.6, 11.8, 1.35, "3D asset pipeline",
         "USD generator in a subprocess  →  twin_satellite.usda  →  version + 1  →  renderer hot-reloads the model layer",
         fill="#F7EEF7", edge=C_OUT)

    # ------------------------------------------------------------ column 3
    cx0, cw = 12.4, 6.0
    header(ax, cx0, cw, HY, "3   Coupled physics, every 1 Hz step", C_PHYS)
    _box(ax, cx0, 5.05, cw, 6.95, "", fill=F_PHYS, edge=C_PHYS, lw=1.4, rounded=False)
    ax.text(cx0 + cw / 2, 11.7, "fixed call order, one step per second", ha="center", va="center",
            fontsize=EDGE_FS, color=C_PHYS)
    L, R, nw, nh = 12.6, 15.7, 2.5, 1.3
    yt, ym, yb = 10.05, 7.95, 5.8
    node(ax, L, yt, nw, nh, "Orbit", "SGP4, ground track")
    node(ax, R, yt, nw, nh, "Lighting", "Sun vector, eclipse")
    node(ax, R, ym, nw, nh, "Solar array", "η·A·S·k_inc·f_illum·η_T")
    node(ax, L, ym, nw, nh, "Battery", "state of charge")
    node(ax, L, yb, nw, nh, "GPU payload", "DVFS budget, tok/s")
    node(ax, R, yb, nw, nh, "Thermal node", "Q_out = ε·σ·A·T⁴")
    # forward edges
    _arrow(ax, L + nw, yt + nh / 2, R, yt + nh / 2)
    _arrow(ax, R + nw / 2, yt, R + nw / 2, ym + nh)
    _arrow(ax, R, ym + nh / 2, L + nw, ym + nh / 2)
    _arrow(ax, L + nw / 2, ym, L + nw / 2, yb + nh)
    label(ax, L + nw / 2 - 0.15, (ym + yb + nh) / 2, "power", ha="right")
    _arrow(ax, L + nw, yb + nh - 0.3, R, yb + nh - 0.3)
    label(ax, (L + nw + R) / 2, (yb + nh + ym) / 2, "heat")
    # feedback edges
    _arrow(ax, R, yb + 0.3, L + nw, yb + 0.3, color=C_PHYS, lw=1.8)
    label(ax, (L + R + nw) / 2, yb - 0.38, "structure temperature caps the GPU power budget", color=C_PHYS)
    _arrow(ax, R + nw - 0.3, yb + nh, R + nw - 0.3, ym, color=C_PHYS, lw=1.8)
    label(ax, R + nw - 0.48, (yb + nh + ym) / 2, "η_T(T) derating", ha="right", color=C_PHYS)
    # engine state -> loop
    _arrow(ax, bx0 + bw, 8.8, cx0, 8.8)
    # margins and snapshot
    node(ax, 12.85, 4.05, 5.3, 0.75, "Design margins and alarms")
    _arrow(ax, cx0 + cw / 2, 5.05, cx0 + cw / 2, 4.82)
    node(ax, 12.85, 2.5, 5.3, 1.35, "State snapshot",
         "StatePacket, comparison variants in lockstep")
    _arrow(ax, cx0 + cw / 2, 4.05, cx0 + cw / 2, 3.87)

    # ------------------------------------------------------------ column 4
    dx0, dw = 18.9, 5.0
    header(ax, dx0, dw, HY, "4   Hot reload and live results", C_OUT)
    _box(ax, dx0 - 0.2, 2.3, dw + 0.4, 9.95, "", fill=F_OUT, edge="#C9CFD6", rounded=False)
    node(ax, dx0, 8.6, dw, 3.4, "Browser",
         "state_update over WebSocket at 1 Hz" + NL + "telemetry strip, margins, alarms" + NL
         + "comparison variants overlaid" + NL + "viewport shows the WebRTC stream")
    node(ax, dx0, 3.9, dw, 3.4, "Omniverse Kit renderer",
         "polls /state at 5 Hz" + NL + "hot reload: version changed, swap the model layer" + NL
         + "per-frame drive of Earth, Sun, attitude" + NL + "RTX render to WebRTC stream")
    _arrow(ax, dx0 + dw / 2, 7.3, dx0 + dw / 2, 8.6, color=C_OUT, lw=1.8)
    label(ax, dx0 + dw / 2 + 0.2, 7.95, "WebRTC video", ha="left", color=C_OUT)
    # version -> kit, the hot reload edge
    poly_arrow(ax, [(18.4, 1.28), (dx0 + dw / 2, 1.28), (dx0 + dw / 2, 3.9)], color=C_OUT, lw=1.8)
    label(ax, dx0 + dw / 2 - 0.2, 1.62, "hot reload of the 3D model", ha="right", color=C_OUT)
    # snapshot -> kit and -> browser
    poly_arrow(ax, [(18.15, 3.4), (18.45, 3.4), (18.45, 4.5), (dx0, 4.5)])
    poly_arrow(ax, [(18.15, 3.7), (18.62, 3.7), (18.62, 10.3), (dx0, 10.3)])

    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.set_aspect("equal")
    ax.axis("off")
    path = os.path.join(OUT, "fig_pipeline_en.png")
    fig.savefig(path, dpi=220, bbox_inches="tight", pad_inches=0.1, facecolor="white")
    plt.close(fig)
    print("written", path)


if __name__ == "__main__":
    main()
