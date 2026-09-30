# -*- coding: utf-8 -*-
"""Explanatory figures for the plain-language ISS thermal summary (out/figures/easy_*.png).

Two schematics (heat path, orbit day and night) and three simple data charts built from the
production results through iss_results. Light print palette from the dataviz reference instance.

    python figures_easy.py
"""
import os, sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle, Wedge, Polygon

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'model'))
import iss_results as R
import iss_results_ext as X

FIG = os.path.join(os.path.dirname(HERE), 'out', 'figures')
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = True
plt.rcParams['font.size'] = 12

INK, INK2, GRID = '#0b0b0b', '#52514e', '#d9d8d4'
BLUE, ORANGE, AQUA, YELLOW = '#2a78d6', '#eb6834', '#1baf7a', '#eda100'
CASES = [('cold0', '设计冷工况'), ('hot75', '设计热工况'), ('nom0', '平均环境工况')]


def save(fig, name):
    p = os.path.join(FIG, name); fig.savefig(p, dpi=170, bbox_inches='tight', facecolor='white'); plt.close(fig); print('wrote', p)


def style(ax):
    for s in ('top', 'right'): ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'): ax.spines[s].set_color(INK2)
    ax.tick_params(colors=INK2)
    ax.grid(axis='x', color=GRID, lw=0.8); ax.set_axisbelow(True)


# ------------------------------------------------------------------ 1 heat path
def heat_path():
    fig, ax = plt.subplots(figsize=(12, 4.6)); ax.set_xlim(0, 12); ax.set_ylim(0, 4.6); ax.axis('off')
    boxes = [
        (0.2, '舱内设备\n机柜 44.8 kW', '#e8f0fb'),
        (2.6, '舱内水回路\n低温 4 °C\n中温 17 °C', '#e8f0fb'),
        (5.0, '换热器\n把热交给氨', '#fdeee7'),
        (7.4, '舱外氨回路\n送回设备 2.8 °C', '#fdeee7'),
        (9.8, '散热器面板\n向太空辐射', '#e6f6f0'),
    ]
    for x, txt, fc in boxes:
        ax.add_patch(FancyBboxPatch((x, 2.3), 2.0, 1.4, boxstyle='round,pad=0.05,rounding_size=0.15', fc=fc, ec=INK2, lw=1.2))
        ax.text(x + 1.0, 3.0, txt, ha='center', va='center', fontsize=13, color=INK)
    for x in (2.2, 4.6, 7.0, 9.4):
        ax.annotate('', xy=(x + 0.4, 3.0), xytext=(x, 3.0), arrowprops=dict(arrowstyle='-|>', color=INK, lw=2))
    ax.annotate('', xy=(11.95, 4.3), xytext=(11.3, 3.75), arrowprops=dict(arrowstyle='-|>', color=ORANGE, lw=2.5))
    ax.text(11.2, 4.45, '热量离开空间站', ha='right', va='center', fontsize=11, color=ORANGE)
    # other heat paths
    ax.add_patch(FancyBboxPatch((0.2, 0.3), 3.6, 1.2, boxstyle='round,pad=0.05,rounding_size=0.15', fc='#fff6e0', ec=INK2, lw=1.2))
    ax.text(2.0, 0.9, '舱外电子设备 IEA 24 kW\n由太阳能系统的四个小冷却回路散热', ha='center', va='center', fontsize=11.5, color=INK)
    ax.add_patch(FancyBboxPatch((4.4, 0.3), 3.6, 1.2, boxstyle='round,pad=0.05,rounding_size=0.15', fc='#fff6e0', ec=INK2, lw=1.2))
    ax.text(6.2, 0.9, '舱外载荷 9.5 kW\n不接回路，自己向太空辐射', ha='center', va='center', fontsize=11.5, color=INK)
    ax.add_patch(FancyBboxPatch((8.6, 0.3), 3.2, 1.2, boxstyle='round,pad=0.05,rounding_size=0.15', fc='#fff6e0', ec=INK2, lw=1.2))
    ax.text(10.2, 0.9, '太阳、地球红外、地球反光\n从外面加热空间站', ha='center', va='center', fontsize=11.5, color=INK)
    ax.text(6.0, 4.35, '舱内设备的热量一步步传到散热器，最后辐射到太空', ha='center', fontsize=13, color=INK, weight='bold')
    save(fig, 'easy_heat_path.png')


# ------------------------------------------------------------------ 2 orbit day and night
def orbit():
    fig, axs = plt.subplots(1, 2, figsize=(12, 5.4), gridspec_kw=dict(width_ratios=[1.15, 1]))
    ax = axs[0]; ax.set_aspect('equal'); ax.set_xlim(-2.6, 2.9); ax.set_ylim(-2.2, 2.2); ax.axis('off')
    ax.add_patch(Polygon([[0, 1.0], [-2.6, 1.0], [-2.6, -1.0], [0, -1.0]], closed=True, fc='#e2e1dc', ec='none'))
    ax.add_patch(Circle((0, 0), 1.0, fc='#cfe0f5', ec=BLUE, lw=1.5))
    ax.add_patch(Wedge((0, 0), 1.0, 90, 270, fc='#9fb6d3', ec='none'))
    ax.add_patch(Circle((0, 0), 1.45, fc='none', ec=INK, lw=1.5, ls='-'))
    for y in (-1.6, -0.8, 0.0, 0.8, 1.6):
        ax.annotate('', xy=(1.55, y), xytext=(2.75, y), arrowprops=dict(arrowstyle='-|>', color=YELLOW, lw=2))
    ax.text(2.75, 1.95, '阳光', ha='right', fontsize=12, color='#9a6a00')
    ax.text(0, 0, '地球', ha='center', va='center', fontsize=13, color=INK)
    ax.text(-2.05, 0.55, '地球的影子\n即地影', ha='center', va='center', fontsize=12, color=INK)
    ax.plot([1.45], [0], 'o', ms=10, color=ORANGE); ax.text(1.55, -0.28, '正午', fontsize=11, color=INK)
    ax.plot([-1.45], [0], 'o', ms=10, color=INK2); ax.text(-1.4, -0.35, '午夜', fontsize=11, color=INK)
    per = R.load_case('nom0')['per']
    ax.text(0, 1.62, f'空间站轨道，约 {per / 60:.0f} 分钟一圈', ha='center', fontsize=12, color=INK)
    ax.set_title('β 为 0：每圈约 36 分钟在地影里', fontsize=13, color=INK)
    ax = axs[1]; ax.set_aspect('equal'); ax.set_xlim(-2.0, 2.4); ax.set_ylim(-2.0, 2.2); ax.axis('off')
    ax.add_patch(Circle((0, 0), 1.0, fc='#cfe0f5', ec=BLUE, lw=1.5))
    ax.plot([-1.7, 1.7], [0, 0], color=INK, lw=1.5)
    ax.text(-1.75, 0.12, '轨道面', fontsize=11, color=INK, ha='left')
    ang = np.radians(75)
    ax.annotate('', xy=(0, 0), xytext=(2.0 * np.cos(ang), 2.0 * np.sin(ang)), arrowprops=dict(arrowstyle='-|>', color=YELLOW, lw=2.5))
    th = np.linspace(0, ang, 40); ax.plot(0.55 * np.cos(th), 0.55 * np.sin(th), color=ORANGE, lw=2)
    ax.text(0.75, 0.12, 'β = 75°', fontsize=13, color=ORANGE)
    ax.text(2.0 * np.cos(ang) + 0.05, 2.0 * np.sin(ang), '阳光', fontsize=12, color='#9a6a00')
    ax.set_title('β 为 75°：阳光和轨道面接近垂直，整圈都在阳光下', fontsize=13, color=INK)
    save(fig, 'easy_orbit.png')


# ------------------------------------------------------------------ 3 heat budget
def heat_budget():
    items = [('舱内机柜', 44.8, BLUE), ('舱外电子设备 IEA', 24.0, AQUA), ('舱外载荷', 9.5, ORANGE),
             ('舱外配电设备', 6.1, BLUE), ('航天员身体散热', 0.8, BLUE)]
    fig, ax = plt.subplots(figsize=(10, 3.9))
    y = np.arange(len(items))[::-1]
    for yi, (lab, v, c) in zip(y, items):
        ax.barh(yi, v, height=0.62, color=c, edgecolor='white', lw=2)
        ax.text(v + 0.6, yi, f'{v:.1f} kW', va='center', fontsize=12, color=INK)
    ax.set_yticks(y); ax.set_yticklabels([i[0] for i in items], fontsize=12, color=INK)
    ax.set_xlabel('发热功率，单位 kW，1 kW 约等于一台小电暖器', color=INK2); style(ax); ax.set_xlim(0, 52)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=BLUE, label='由两条主冷却回路带走'), Patch(color=AQUA, label='由太阳能系统的四个小冷却回路带走'),
                       Patch(color=ORANGE, label='不接回路，自己辐射到太空')], loc='lower right', fontsize=11, frameon=False)
    ax.set_title('空间站上的主要热源，合计约 85 kW', fontsize=13, color=INK, loc='left')
    save(fig, 'easy_heat_budget.png')


# ------------------------------------------------------------------ 4 load vs capacity
def load_vs_capacity():
    C = {c: R.load_case(c) for c, _ in CASES}
    LT = {c: R.loop_table(C[c]) for c in C}
    fig, ax = plt.subplots(figsize=(10, 4.6))
    x = np.arange(len(CASES)); w = 0.34
    for k, (L, col) in enumerate((('A', BLUE), ('B', AQUA))):
        v = [LT[c][L]['Q']['mean'] / 1e3 for c, _ in CASES]
        bars = ax.bar(x + (k - 0.5) * w, v, width=w - 0.04, color=col, label=f'回路 {L} 实际要排的热')
        for b, vv in zip(bars, v):
            ax.text(b.get_x() + b.get_width() / 2, vv + 0.6, f'{vv:.1f}', ha='center', fontsize=12, color=INK)
    ax.axhline(35, color=ORANGE, lw=2, ls='--'); ax.text(2.45, 35.6, '每条回路的设计排热能力 35 kW', ha='right', fontsize=12, color=INK)
    ax.set_xticks(x); ax.set_xticklabels([n for _, n in CASES], fontsize=12, color=INK)
    ax.set_ylabel('热量，单位 kW', color=INK2); ax.set_ylim(0, 42)
    for s in ('top', 'right'): ax.spines[s].set_visible(False)
    ax.grid(axis='y', color=GRID, lw=0.8); ax.set_axisbelow(True)
    ax.legend(loc='upper left', fontsize=11, frameon=False, ncol=2)
    ax.set_title('冷却回路的负担：实际要排的热都明显低于设计能力', fontsize=13, color=INK, loc='left')
    save(fig, 'easy_load_capacity.png')


# ------------------------------------------------------------------ 5 component temperature ranges
def temp_ranges():
    c = R.load_case('nom0'); CT = R.class_table(c)
    rows = [('rack', '舱内机柜'), ('box', '舱外电子设备'), ('skin_usos', '美国、欧洲、日本舱段外壳'), ('skin_rus', '俄罗斯舱段外壳'),
            ('payload', '舱外载荷'), ('hrs', '散热器面板'), ('saw', '美国太阳翼')]
    rows = [(k, n) for k, n in rows if k in CT]
    fig, ax = plt.subplots(figsize=(10, 4.8))
    y = np.arange(len(rows))[::-1]
    for yi, (k, n) in zip(y, rows):
        v = CT[k]
        ax.plot([v['min'], v['max']], [yi, yi], color=BLUE, lw=6, solid_capstyle='round', alpha=0.35)
        ax.plot([v['mean']], [yi], 'o', ms=10, color=BLUE, mec='white', mew=2)
        ax.text(v['max'] + 2, yi, f"{X.num(v['min'], 0)} 至 {X.num(v['max'], 0)} °C", va='center', fontsize=11, color=INK2)
    ax.axvline(0, color=INK2, lw=1, ls=':'); ax.text(1.0, -0.75, '0 °C', fontsize=10, color=INK2)
    ax.set_yticks(y); ax.set_yticklabels([n for _, n in rows], fontsize=12, color=INK)
    ax.set_xlabel('温度，单位 °C', color=INK2); style(ax); ax.set_xlim(-95, 110); ax.set_ylim(-0.9, len(rows) - 0.5)
    ax.set_title('平均环境下一圈之内各部件的温度范围，圆点为平均温度', fontsize=13, color=INK, loc='left')
    save(fig, 'easy_temp_ranges.png')


if __name__ == '__main__':
    heat_path(); orbit(); heat_budget(); load_vs_capacity(); temp_ranges()
