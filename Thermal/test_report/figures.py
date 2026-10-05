# -*- coding: utf-8 -*-
"""Figures for the thermal test report: FE versus lumped temperature histories over the last orbit."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / 'out'

INK, INK2, GRID, BAND = '#0b0b0b', '#52514e', '#e6e5e1', '#f0efec'
FEM_C, LUMP_C = '#2a78d6', '#eb6834'
CASE_ORDER = ('cold0', 'nom0', 'hot75')
CASE_NAME = {'cold0': '设计冷工况', 'nom0': '平均环境工况', 'hot75': '设计热工况'}

plt.rcParams.update({
    'font.family': ['Times New Roman', 'SimSun'],
    'font.size': 8.5,
    'axes.unicode_minus': True,
    'axes.edgecolor': '#b9b8b3',
    'axes.linewidth': 0.6,
    'axes.labelcolor': INK,
    'xtick.color': INK2,
    'ytick.color': INK2,
    'xtick.major.size': 0,
    'ytick.major.size': 0,
    'axes.grid': True,
    'grid.color': GRID,
    'grid.linewidth': 0.5,
    'grid.linestyle': '-',
    'legend.frameon': False,
    'savefig.dpi': 220,
})


def eclipse_minutes(case):
    ecl = case.get('eclipse_s')
    return None if not ecl else (ecl[0] / 60, ecl[1] / 60)


def style_axes(ax):
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    ax.set_axisbelow(True)


def fig_solar(res):
    period = res['orbit_period_s']
    fig, axes = plt.subplots(1, 3, figsize=(5.9, 2.25), sharex=True)
    for ax, case in zip(axes, CASE_ORDER):
        c = res['cases'][case]
        ecl = eclipse_minutes(c)
        if ecl:
            ax.axvspan(*ecl, color=BAND, lw=0, zorder=0)
            ax.text(sum(ecl) / 2, 0.04, '日食', transform=ax.get_xaxis_transform(), ha='center', va='bottom', color=INK2, fontsize=7.5)
        ft, fv = c['S']['curve_fem']
        lt, lv = c['S']['curve_lumped']
        ax.plot([x / 60 for x in ft], fv, color=FEM_C, lw=1.5, solid_capstyle='round', label='有限元')
        ax.plot([x / 60 for x in lt], lv, color=LUMP_C, lw=1.5, ls=(0, (4, 2.5)), label='集总模型')
        ax.set_title(CASE_NAME[case], fontsize=8.5, color=INK, pad=4)
        ax.set_xlim(0, period / 60)
        ax.set_xticks([0, 30, 60, 90])
        style_axes(ax)
    axes[0].set_ylabel('温度/°C')
    axes[1].set_xlabel('轨道正午后的时间/min')
    axes[2].set_ylim(48, 60)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', ncol=2, bbox_to_anchor=(0.5, 1.02), fontsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.92), w_pad=1.2)
    fig.savefig(OUT / 'fig_solar_node.png')
    plt.close(fig)


def fig_radiator(res):
    period = res['orbit_period_s']
    fig, axes = plt.subplots(2, 3, figsize=(5.9, 3.7), sharex=True)
    for col, case in enumerate(CASE_ORDER):
        c = res['cases'][case]
        ecl = eclipse_minutes(c)
        for row, loop in enumerate(('A', 'B')):
            ax = axes[row, col]
            r = c['R'][loop]
            ft, fv = r['curve_fem']
            lt, lv = r['curve_lumped']
            if ecl:
                # radiator curves start at the beginning of the last orbit, shift the eclipse window to that origin
                t0_phase = c['last_orbit_start_s'] % period
                e0 = (ecl[0] * 60 - t0_phase) % period / 60
                e1 = (ecl[1] * 60 - t0_phase) % period / 60
                if e0 < e1:
                    ax.axvspan(e0, e1, color=BAND, lw=0, zorder=0)
                else:
                    ax.axvspan(e0, period / 60, color=BAND, lw=0, zorder=0)
                    ax.axvspan(0, e1, color=BAND, lw=0, zorder=0)
            ax.plot([x / 60 for x in ft], fv, color=FEM_C, lw=1.5, label='有限元')
            ax.plot([x / 60 for x in lt], lv, color=LUMP_C, lw=1.5, ls=(0, (4, 2.5)), label='集总模型')
            ax.set_xlim(0, period / 60)
            ax.set_xticks([0, 30, 60, 90])
            style_axes(ax)
            if row == 0:
                ax.set_title(CASE_NAME[case], fontsize=8.5, color=INK, pad=4)
            if col == 0:
                ax.set_ylabel(f'回路 {loop}\n面板平均温度/°C')
    axes[1, 1].set_xlabel('第三圈内的时间/min')
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', ncol=2, bbox_to_anchor=(0.5, 1.01), fontsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.95), w_pad=1.0, h_pad=0.8)
    fig.savefig(OUT / 'fig_radiator_node.png')
    plt.close(fig)


def main():
    res = json.loads((OUT / 'fe_compare.json').read_text(encoding='utf-8'))
    fig_solar(res)
    fig_radiator(res)
    print('figures written to', OUT)


if __name__ == '__main__':
    main()
