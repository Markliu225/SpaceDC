"""plot_layout.py - plan view (X-Y) and front view (Y-Z) of the component boxes in the ISS
analysis frame; IGOAL boxes filled by group, model C boxes as dashed grey outlines."""
import csv
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
rows = list(csv.DictReader(open(os.path.join(HERE, "components_iss_frame.csv"), encoding="utf-8")))

# categorical slots in fixed order (reference palette, light mode)
GROUPS = [("truss", "#2a78d6", "Truss segment"),
          ("module", "#eb6834", "Pressurized module"),
          ("solar array wing", "#1baf7a", "Solar array wing"),
          ("HRS radiator ORU", "#eda100", "HRS radiator ORU"),
          ("PVR", "#e87ba4", "PVR panels"),
          ("carrier", "#008300", "External carrier")]
COL = {g: c for g, c, _ in GROUPS}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
SKIP = {"HRS radiator wing (3 ORUs + beam)"}


def boxes(model, i, j):
    out = []
    for r in rows:
        if r["group"] not in COL or not r[f"{model}_cx"]:
            continue
        if any(s in r["component"] for s in SKIP):
            continue
        ax = "xyz"
        c = [float(r[f"{model}_c{a}"]) for a in ax]
        s = [float(r[f"{model}_s{a}"]) for a in ax]
        out.append((r["group"], r["component"], c[i] - s[i] / 2, c[j] - s[j] / 2, s[i], s[j]))
    return out


fig, axes = plt.subplots(1, 2, figsize=(15, 7.2), gridspec_kw=dict(width_ratios=[1.25, 1]))
fig.patch.set_facecolor("#fcfcfb")
views = [(axes[0], 1, 0, "Plan view from zenith: Y starboard (m) vs X forward (m)", "Y (m, starboard +)", "X (m, forward +)"),
         (axes[1], 1, 2, "View from aft looking forward: Y starboard (m) vs Z nadir (m)", "Y (m, starboard +)", "Z (m, nadir +)")]
for ax, i, j, title, xl, yl in views:
    ax.set_facecolor("#fcfcfb")
    # z-order: arrays and radiators under modules so modules stay readable
    order = {"solar array wing": 1, "HRS radiator ORU": 2, "PVR": 3, "truss": 4, "carrier": 5, "module": 6}
    for g, comp, x0, y0, w, h in sorted(boxes("IGOAL", i, j), key=lambda b: order[b[0]]):
        ax.add_patch(Rectangle((x0, y0), w, h, facecolor=COL[g], alpha=0.28, edgecolor=COL[g], lw=1.0,
                               zorder=order[g]))
    for g, comp, x0, y0, w, h in boxes("C", i, j):
        ax.add_patch(Rectangle((x0, y0), w, h, fill=False, edgecolor=INK2, lw=0.7, ls=(0, (3, 2)), zorder=10))
    ax.set_title(title, color=INK, fontsize=11, loc="left")
    ax.set_xlabel(xl, color=INK2)
    ax.set_ylabel(yl, color=INK2)
    ax.grid(color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for sp in ax.spines.values():
        sp.set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.set_aspect("equal")
axes[0].set_xlim(-57, 57)
axes[0].set_ylim(-40, 40)
axes[1].set_xlim(-57, 57)
axes[1].set_ylim(17, -9)  # nadir down on the page
# direct labels for truss segments (plan view)
for r in rows:
    if r["group"] == "truss" and r["IGOAL_cx"]:
        nm = r["component"].split()[0]
        y, x = float(r["IGOAL_cy"]), float(r["IGOAL_cx"])
        axes[0].text(y, 3.2 + (2.6 if nm in ("S5", "P5", "S3", "P3") else 0), nm, ha="center", va="bottom",
                     fontsize=7.5, color=INK, zorder=20)
for r in rows:
    if r["component"] in ("Destiny US Lab", "Harmony Node 2", "Unity Node 1", "Zvezda SM body", "Zarya FGB body",
                          "Kibo JEM PM", "Columbus", "Tranquility Node 3") and r["IGOAL_cx"]:
        axes[0].text(float(r["IGOAL_cy"]) + (2.8 if r["component"] in ("Columbus",) else 0),
                     float(r["IGOAL_cx"]), r["component"].replace(" US Lab", "").replace(" body", ""),
                     fontsize=6.5, color=INK, ha="left" if r["component"] == "Columbus" else "center",
                     va="center", zorder=20)
handles = [Rectangle((0, 0), 1, 1, facecolor=c, alpha=0.4, edgecolor=c) for _, c, _ in GROUPS]
labels = [l for _, _, l in GROUPS]
handles.append(Rectangle((0, 0), 1, 1, fill=False, edgecolor=INK2, ls=(0, (3, 2))))
labels.append("Model C 2011 box, same component")
fig.legend(handles, labels, loc="lower center", ncol=7, frameon=False, fontsize=8.5, labelcolor=INK)
fig.suptitle("ISS component boxes in the ISS analysis frame, origin at S0 centre. Filled: IGOAL model. "
             "Dashed: 2011 JSC model C. Arrays and radiators shown in each model's stored pose.",
             color=INK, fontsize=10.5, x=0.01, ha="left")
fig.tight_layout(rect=(0, 0.05, 1, 0.95))
out = os.path.join(HERE, "iss_layout_boxes.png")
fig.savefig(out, dpi=130)
print("wrote", out)
