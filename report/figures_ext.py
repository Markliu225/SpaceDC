"""Re-plots the STK position-error and COMSOL overlay charts from the benchmark
data with report-consistent labels.   Run: python figures_ext.py [zh|en]"""
from __future__ import annotations

import csv
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(os.path.dirname(HERE), "space-compute-demo")
GREEN = "#2F8F6B"
BLUE = "#2E6FB5"
ORANGE = "#D9782D"

LABELS = {
    "zh": dict(
        font=["Microsoft YaHei", "SimHei", "sans-serif"], out="figures",
        cases=[("leo_iss", "低轨，国际空间站类"), ("sso_landsat", "太阳同步轨道，705 km"), ("geo_goes", "地球静止轨道")],
        stk_title="本平台与 STK 11.6 的 SGP4 位置差，24 h，步长 60 s", tmax="最大", xlabel="时间 h", ylabel="位置差 |Δr| μm",
        panels=[("comsol_rad_mean_C", "散热板面积加权均温"), ("comsol_baseplate_mean_C", "GPU 基板均温"), ("comsol_bus_mean_C", "机身体积均温")],
        ours="本平台单节点模型", comsol="COMSOL 有限元",
        cx="自热点时刻起算的时间 h，第 2 至 3 圈，阴影为地影", ctitle="V100 工况，12 卡，白漆散热板"),
    "en": dict(
        font=["Segoe UI", "Arial", "DejaVu Sans", "sans-serif"], out="figures_en",
        cases=[("leo_iss", "LEO, ISS class"), ("sso_landsat", "SSO, 705 km"), ("geo_goes", "GEO")],
        stk_title="SGP4 position difference between the platform and STK 11.6, 24 h, 60 s step",
        tmax="max", xlabel="time h", ylabel="|Δr| μm",
        panels=[("comsol_rad_mean_C", "Radiator area-weighted mean"), ("comsol_baseplate_mean_C", "GPU baseplate mean"),
                ("comsol_bus_mean_C", "Bus volume mean")],
        ours="platform single-node model", comsol="COMSOL finite element",
        cx="time since the hot instant h, orbits 2 to 3, shaded spans are eclipse",
        ctitle="V100 case, 12 cards, white-paint radiator"),
}


def stk_position(L, out):
    base = os.path.join(DEMO, "tools", "stk_benchmark", "out")
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.4), sharey=True)
    for ax, (cid, label) in zip(axes, L["cases"]):
        ours = {float(r["t"]): r for r in csv.DictReader(open(os.path.join(base, "ours", f"ephem_{cid}.csv"), encoding="utf-8"))}
        stk = {float(r["t"]): r for r in csv.DictReader(open(os.path.join(base, "stk", f"ephem_{cid}.csv"), encoding="utf-8"))}
        t, um = [], []
        for tk in sorted(set(ours) & set(stk)):
            a, b = ours[tk], stk[tk]
            dr = ((float(a["x_km"]) - float(b["x_km"])) ** 2 + (float(a["y_km"]) - float(b["y_km"])) ** 2
                  + (float(a["z_km"]) - float(b["z_km"])) ** 2) ** 0.5
            t.append(tk / 3600.0)
            um.append(dr * 1e9)
        ax.plot(t, um, color=GREEN, lw=0.9)
        ax.set_title(f"{label}, {L['tmax']} {max(um):.2f} μm", fontsize=10, loc="left")
        ax.set_xlabel(L["xlabel"])
        ax.set_xlim(0, 24)
        ax.grid(alpha=0.3)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    axes[0].set_ylabel(L["ylabel"])
    fig.suptitle(L["stk_title"], fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_stk_position.png"), dpi=200, facecolor="white")
    plt.close(fig)


def comsol_overlay(L, out):
    path = os.path.join(DEMO, "tools", "comsol_benchmark", "full_twin", "out", "compare", "caseA_aligned.csv")
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    P = 5574.2
    win = [r for r in rows if P <= float(r["tau_s"]) <= 3 * P]
    t = [float(r["tau_s"]) / 3600.0 for r in win]
    illum = [float(r["orbitwiz_illum"]) for r in win]
    ours = [float(r["orbitwiz_T_struct_C"]) for r in win]
    fig, axes = plt.subplots(3, 1, figsize=(9, 8.2), sharex=True)
    for ax, (col, title) in zip(axes, L["panels"]):
        com = [float(r[col]) for r in win]
        start = None
        for i, il in enumerate(illum + [1.0]):
            if il == 0.0 and start is None:
                start = t[i]
            elif il != 0.0 and start is not None:
                ax.axvspan(start, t[min(i, len(t) - 1)], color="#000000", alpha=0.06, lw=0)
                start = None
        ax.plot(t, ours, color=ORANGE, lw=2.0, label=L["ours"])
        ax.plot(t, com, color=BLUE, lw=2.0, label=L["comsol"])
        ax.set_title(title, fontsize=10, loc="left")
        ax.set_ylabel("°C")
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=9, frameon=False)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    axes[-1].set_xlabel(L["cx"])
    fig.suptitle(L["ctitle"], fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_comsol_overlay.png"), dpi=200, facecolor="white")
    plt.close(fig)


def main(lang="zh"):
    L = LABELS[lang]
    plt.rcParams["font.family"] = L["font"]
    plt.rcParams["axes.unicode_minus"] = False
    out = os.path.join(HERE, L["out"])
    os.makedirs(out, exist_ok=True)
    stk_position(L, out)
    comsol_overlay(L, out)
    print("ok", lang)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "zh")
