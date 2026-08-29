# -*- coding: utf-8 -*-
"""Thermal-model figures that do not need a COMSOL solution: an annotated 3D
view of the COMSOL geometry (bus, blades, GPU packages, heat-pipe network,
radiators, solar wings, body axes, Sun/nadir/ram directions) and a top/side
orthographic pair. Output: out/figures/model_geometry_3d.png, _ortho.png"""
import os, math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import geometry_spec as G

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(HERE, "out", "figures"); os.makedirs(FIG, exist_ok=True)
C = dict(bus="#52514e", blade="#2a78d6", pkg="#e34948", rad="#f0efec", boom="#9a9890", wing="#1c5cab", hp="#eb6834")
EDGE = "#0b0b0b"


def box_faces(mn, sz):
    x0, y0, z0 = mn; x1, y1, z1 = mn[0] + sz[0], mn[1] + sz[1], mn[2] + sz[2]
    p = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]])
    idx = [[0, 1, 2, 3], [4, 5, 6, 7], [0, 1, 5, 4], [2, 3, 7, 6], [1, 2, 6, 5], [0, 3, 7, 4]]
    return [p[i] for i in idx]


def add_box(ax, b, color, alpha=1.0, lw=0.3):
    pc = Poly3DCollection(box_faces(b['min'], b['size']), facecolors=color, edgecolors=EDGE, linewidths=lw, alpha=alpha)
    ax.add_collection3d(pc)


def draw(ax, wings=True):
    for b in G.BUS: add_box(ax, b, C['bus'])
    for b, p in G.blades():
        add_box(ax, b, C['blade']); add_box(ax, p, C['pkg'])
    for r in G.radiators(): add_box(ax, r, C['boom'] if r.get('boom') else C['rad'], lw=0.5)
    hp, n_tr = G.heat_pipe_blocks(400 * 0.95)
    for h in hp: add_box(ax, h, C['hp'], lw=0.2)
    if wings:
        for w in G.wings(): add_box(ax, w, C['wing'], alpha=0.85)
    return n_tr


def fig3d():
    fig = plt.figure(figsize=(11, 8), facecolor="#fcfcfb")
    ax = fig.add_subplot(111, projection='3d'); ax.set_facecolor("#fcfcfb")
    n_tr = draw(ax, wings=True)
    # body axes and directions (arrows from origin)
    L = 2.0
    ax.quiver(0, 0, 0, L, 0, 0, color="#0b0b0b", arrow_length_ratio=0.08); ax.text(L * 1.05, 0, 0, "+X orbit normal\n(cell normal)", fontsize=8)
    ax.quiver(0, 0, 0, 0, L, 0, color="#0b0b0b", arrow_length_ratio=0.08); ax.text(0, L * 1.05, 0, "+Y ram", fontsize=8)
    ax.quiver(0, 0, 0, 0, 0, L, color="#0b0b0b", arrow_length_ratio=0.08); ax.text(0, 0, L * 1.1, "+Z nadir (spine)", fontsize=8)
    # sun direction at the hot instant (body frame, from the OrbitWiz trace): (-0.509, -0.856, -0.085)
    s = np.array([-0.509, -0.856, -0.085]); o = -s * 4.5
    ax.quiver(o[0], o[1], o[2], s[0] * 2.5, s[1] * 2.5, s[2] * 2.5, color="#eda100", arrow_length_ratio=0.12, linewidth=2)
    ax.text(o[0], o[1] - 0.5, o[2] + 0.4, "Sun rays at t0\n(beta = -31 deg)", fontsize=8, color="#7a5300")
    ax.set_xlim(-6, 6); ax.set_ylim(-6, 6); ax.set_zlim(-4, 4)
    ax.set_box_aspect((12, 12, 8)); ax.view_init(elev=22, azim=-50)
    ax.set_xlabel('X [m]'); ax.set_ylabel('Y [m]'); ax.set_zlabel('Z [m]')
    ax.set_title("COMSOL twin geometry — full satellite (stage metres)", fontsize=10, loc='left')
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=C['bus'], label='bus: spine, thrusters, tanks (Al)'), Patch(color=C['blade'], label='blade chassis (Al)'), Patch(color=C['pkg'], label='GPU package + TIM (heat source)'),
                       Patch(color=C['hp'], label='heat pipes (k_eff 1.6e5 W/mK)'), Patch(facecolor=C['rad'], edgecolor=EDGE, label='radiator panels (WhitePaint, 1.63 mm eq.)'), Patch(color=C['wing'], label='solar wings (decoupled, 0.93 mm eq.)')],
              loc='lower left', fontsize=7, frameon=False)
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "model_geometry_3d.png"), dpi=160); plt.close(fig)


def fig3d_bus():
    """Bus detail without the wings: blades, GPU packages, heat-pipe network, radiators."""
    fig = plt.figure(figsize=(9, 10), facecolor="#fcfcfb")
    ax = fig.add_subplot(111, projection='3d'); ax.set_facecolor("#fcfcfb")
    n_tr = draw(ax, wings=False)
    s = np.array([-0.509, -0.856, -0.085]); o = -s * 1.6
    ax.quiver(o[0], o[1], o[2], s[0] * 0.9, s[1] * 0.9, s[2] * 0.9, color="#eda100", arrow_length_ratio=0.2, linewidth=2)
    ax.text(o[0] + 0.05, o[1] + 0.1, o[2] + 0.15, "Sun rays at t0", fontsize=8, color="#7a5300")
    ax.quiver(0, 0, 0, 0.8, 0, 0, color="#0b0b0b", arrow_length_ratio=0.15); ax.text(0.85, 0, 0, "+X", fontsize=8)
    ax.quiver(0, 0, 0, 0, 0.8, 0, color="#0b0b0b", arrow_length_ratio=0.15); ax.text(0, 0.85, 0, "+Y ram", fontsize=8)
    ax.quiver(0, 0, 0, 0, 0, 0.8, color="#0b0b0b", arrow_length_ratio=0.15); ax.text(0, 0, 0.9, "+Z nadir", fontsize=8)
    ax.set_xlim(-1.2, 1.2); ax.set_ylim(-1.2, 1.2); ax.set_zlim(-3.4, 3.4); ax.set_box_aspect((2.4, 2.4, 6.8)); ax.view_init(elev=18, azim=-40)
    ax.set_xlabel('X [m]'); ax.set_ylabel('Y [m]'); ax.set_zlabel('Z [m]')
    ax.set_title("Bus detail (wings hidden): 12 blades + GPU packages, %d-pipe transport bundles," % n_tr + chr(10) + "header + 8 spreaders per radiator face, radiators at +/-Z", fontsize=9, loc="left")
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "model_geometry_bus.png"), dpi=160); plt.close(fig)


def fig_ortho():
    fig, axes = plt.subplots(1, 2, figsize=(12, 6), facecolor="#fcfcfb")
    # side view (Y-Z plane), wings excluded for scale; and detail of bus+radiators (X-Z)
    ax = axes[0]; ax.set_facecolor("#fcfcfb")
    def rect(ax, mn, sz, i, j, color, lw=0.4, alpha=1.0):
        ax.add_patch(plt.Rectangle((mn[i], mn[j]), sz[i], sz[j], facecolor=color, edgecolor=EDGE, linewidth=lw, alpha=alpha))
    for b in G.BUS: rect(ax, b['min'], b['size'], 1, 2, C['bus'])
    for b, p in G.blades(): rect(ax, b['min'], b['size'], 1, 2, C['blade']); rect(ax, p['min'], p['size'], 1, 2, C['pkg'])
    for r in G.radiators(): rect(ax, r['min'], r['size'], 1, 2, C['boom'] if r.get('boom') else C['rad'])
    hp, _ = G.heat_pipe_blocks(400 * 0.95)
    for h in hp: rect(ax, h['min'], h['size'], 1, 2, C['hp'], lw=0.2)
    for w in G.wings(): rect(ax, w['min'], w['size'], 1, 2, C['wing'], alpha=0.5)
    ax.set_xlim(-2.5, 2.5); ax.set_ylim(-3.6, 3.6); ax.set_aspect('equal'); ax.set_xlabel('Y ram [m]'); ax.set_ylabel('Z nadir [m]')
    ax.set_title('side view (along -X): radiators at +/-Z, blades on +/-Y racks, wings edge-on', fontsize=9, loc='left')
    ax.annotate('radiator faces look along +/-Y\n(ram / wake)', xy=(0.05, 2.2), xytext=(0.9, 3.0), fontsize=8, arrowprops=dict(arrowstyle='->', color='#52514e'))
    ax = axes[1]; ax.set_facecolor("#fcfcfb")
    for b in G.BUS: rect(ax, b['min'], b['size'], 0, 2, C['bus'])
    for b, p in G.blades(): rect(ax, b['min'], b['size'], 0, 2, C['blade'], alpha=0.6); rect(ax, p['min'], p['size'], 0, 2, C['pkg'], alpha=0.8)
    for r in G.radiators(): rect(ax, r['min'], r['size'], 0, 2, C['boom'] if r.get('boom') else C['rad'])
    for h in hp: rect(ax, h['min'], h['size'], 0, 2, C['hp'], lw=0.2, alpha=0.9)
    ax.set_xlim(-0.6, 0.6); ax.set_ylim(-3.6, 3.6); ax.set_aspect('equal'); ax.set_xlabel('X orbit normal [m]'); ax.set_ylabel('Z nadir [m]')
    ax.set_title('front view (along +Y): 8 spreaders/face at 0.1016 m pitch', fontsize=9, loc='left')
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "model_geometry_ortho.png"), dpi=160); plt.close(fig)


if __name__ == '__main__':
    fig3d(); fig3d_bus(); fig_ortho(); print("wrote", FIG)
