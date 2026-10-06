# -*- coding: utf-8 -*-
"""Figures of the executed FE comparison cases, drawn from the test evidence in tests/results.

    python figures_results.py          -> Chinese and English versions in test_report/out

FE-001 solar array node, FE-002 common radiator node and FE-004 whole-satellite chain: module curves against the
finite element curves of the same quantity.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / 'out'
RESULTS = HERE.parent / 'tests' / 'results'

INK, INK2, GRID, BAND, WINDOW = '#0b0b0b', '#52514e', '#e6e5e1', '#f0efec', '#f6f1e7'
FEM_C, MOD_C = '#2a78d6', '#eb6834'
HOT_C, COLD_C = '#2a78d6', '#1f9e74'
CASE_ORDER = ('cold0', 'nom0', 'hot75')
TEXT = {
    'cn': {
        'cases': {'cold0': '设计冷工况', 'nom0': '平均环境工况', 'hot75': '设计热工况'},
        'eclipse': '日食', 'fe': '有限元', 'module': '热模块', 'temp': '温度/°C',
        'last_orbit': '最后一圈内的时间/min', 'third_orbit': '第三圈内的时间/min',
        'loop': '回路 {}\n面板平均温度/°C', 'orbits': '时间/轨道周期', 'window': '对比窗口',
        'chain_cases': {'caseA': '12 块 V100', 'caseB': '12 块 A100'},
        'chain_labels': ('GPU 基板，有限元', '计算节点，热模块', '散热板，有限元', '散热板，热模块'),
        'font': ['Times New Roman', 'SimSun'],
    },
    'en': {
        'cases': {'cold0': 'Design cold case', 'nom0': 'Mean environment case', 'hot75': 'Design hot case'},
        'eclipse': 'Eclipse', 'fe': 'FE', 'module': 'Thermal module', 'temp': 'Temperature (°C)',
        'last_orbit': 'Time in the last orbit (min)', 'third_orbit': 'Time in the third orbit (min)',
        'loop': 'Loop {}\npanel mean (°C)', 'orbits': 'Time (orbit periods)', 'window': 'Comparison window',
        'chain_cases': {'caseA': '12 V100', 'caseB': '12 A100'},
        'chain_labels': ('GPU baseplate, FE', 'Computing node, thermal module', 'Radiator, FE',
                         'Radiator, thermal module'),
        'font': ['Times New Roman'],
    },
}


def setup(lang):
    plt.rcParams.update({
        'font.family': TEXT[lang]['font'],
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


def style_axes(ax):
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    ax.set_axisbelow(True)


def load(name):
    return json.loads((RESULTS / name).read_text(encoding='utf-8'))


def shade(ax, windows, origin, label=None):
    for a, b in windows:
        ax.axvspan((a - origin) / 60, (b - origin) / 60, color=BAND, lw=0, zorder=0)
        if label:
            ax.text(((a + b) / 2 - origin) / 60, 0.96, label, transform=ax.get_xaxis_transform(), ha='center',
                    va='top', color=INK2, fontsize=7.5)


def fig_fe001(lang):
    t = TEXT[lang]
    s = load('FE-001_series.json')
    fig, axes = plt.subplots(2, 3, figsize=(5.9, 3.6), sharex=True,
                             gridspec_kw={'height_ratios': [1.6, 1]})
    for col, case in enumerate(CASE_ORDER):
        ax = axes[0, col]
        c = s['cases'][case]
        t0 = c['last_orbit_start_s']
        shade(ax, c['eclipse_windows_s'], t0, t['eclipse'])
        ax.plot([(x - t0) / 60 for x in c['fe_time_s']], c['fe_T_saw_mean_C'], color=FEM_C, lw=1.5, label=t['fe'])
        ax.plot([(x - t0) / 60 for x in c['module_time_s']], c['module_T_S_C'], color=MOD_C, lw=1.5,
                ls=(0, (4, 2.5)), label=t['module'])
        ax.set_title(t['cases'][case], fontsize=8.5, color=INK, pad=4)
        ax.set_xlim(0, (c['last_orbit_end_s'] - t0) / 60)
        ax.set_xticks([0, 30, 60, 90])
        style_axes(ax)
        tx = np.asarray(c['fe_time_s'])
        delta = np.interp(tx, c['module_time_s'], c['module_T_S_C']) - np.asarray(c['fe_T_saw_mean_C'])
        keep = (tx >= t0) & (tx <= c['last_orbit_end_s'])
        assert abs(float(np.max(np.abs(delta[keep]))) - c['pointwise']['max_K']) < 1e-8
        lower = axes[1, col]
        lower.axhspan(-3, 3, color='#eef4ec', zorder=0)
        lower.axhline(3, color='#658358', lw=0.7, ls='--')
        lower.axhline(-3, color='#658358', lw=0.7, ls='--')
        lower.plot((tx[keep] - t0) / 60, delta[keep], color='#754694', lw=1,
                   marker='o', markersize=1.6)
        lower.set_ylim(-14, 14)
        lower.set_yticks([-12, -6, 0, 6, 12])
        lower.text(0.5, 0.97, f'max |ΔT| = {c["pointwise"]["max_K"]:.2f} K',
                   ha='center', va='top', transform=lower.transAxes, fontsize=7)
        style_axes(lower)
    axes[0, 0].set_ylabel(t['temp'])
    axes[1, 0].set_ylabel('模块减有限元/K' if lang == 'cn' else 'Module − FE (K)')
    axes[1, 1].set_xlabel(t['last_orbit'])
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', ncol=2, bbox_to_anchor=(0.5, 1.02), fontsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.95), w_pad=1.2, h_pad=0.6)
    fig.savefig(OUT / f'fig_fe001_solar_{lang}.png')
    plt.close(fig)


def fig_fe002(lang):
    t = TEXT[lang]
    s = load('FE-002_series.json')
    t0 = s['third_orbit_start_s']
    t1 = s['t_end_s']
    fig, axes = plt.subplots(2, 3, figsize=(5.9, 3.7), sharex=True)
    for col, case in enumerate(CASE_ORDER):
        c = s['cases'][case]
        windows = [w for w in c['eclipse_windows_s'] if w[1] > t0]
        for row, loop in enumerate(('A', 'B')):
            ax = axes[row, col]
            lp = c['loops'][loop]
            shade(ax, windows, t0)
            fe_t = [x for x in c['fe_time_s']]
            fe = [(x - t0) / 60 for x in fe_t]
            keep = [k for k, x in enumerate(fe_t) if x >= t0 - 1e-6]
            ax.plot([fe[k] for k in keep], [lp['T_R_fe_mean_C'][k] for k in keep], color=FEM_C, lw=1.5, label=t['fe'])
            mt = lp['time_s']
            keep = [k for k, x in enumerate(mt) if x >= t0 - 1e-6]
            ax.plot([(mt[k] - t0) / 60 for k in keep], [lp['T_R_module_C'][k] for k in keep], color=MOD_C, lw=1.5,
                    ls=(0, (4, 2.5)), label=t['module'])
            ax.set_xlim(0, (t1 - t0) / 60)
            ax.set_xticks([0, 30, 60, 90])
            style_axes(ax)
            if row == 0:
                ax.set_title(t['cases'][case], fontsize=8.5, color=INK, pad=4)
            if col == 0:
                ax.set_ylabel(t['loop'].format(loop))
    axes[1, 1].set_xlabel(t['third_orbit'])
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', ncol=2, bbox_to_anchor=(0.5, 1.01), fontsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.95), w_pad=1.0, h_pad=0.8)
    fig.savefig(OUT / f'fig_fe002_radiator_{lang}.png')
    plt.close(fig)


def fig_fe004(lang):
    t = TEXT[lang]
    s = load('FE-004_series.json')
    period = s['period_s']
    fig, axes = plt.subplots(2, 1, figsize=(5.9, 4.0), sharex=True)
    for ax, case in zip(axes, ('caseA', 'caseB')):
        c = s['cases'][case]
        ax.axvspan(3.0, 5.0, color=WINDOW, lw=0, zorder=0)
        ax.text(4.0, 0.04, t['window'], transform=ax.get_xaxis_transform(), ha='center', va='bottom', color=INK2,
                fontsize=7.5)
        fe_t = [x / period for x in c['fe']['t_s']]
        mo = c['module_output']
        mo_t = [x / period for x in mo['time_s']]
        T = mo['temperature_K']
        ax.plot(fe_t, [v - 273.15 for v in c['fe']['baseplate_mean_K']], color=HOT_C, lw=1.5,
                label=t['chain_labels'][0])
        ax.plot(mo_t, [row[1] - 273.15 for row in T], color=HOT_C, lw=1.5, ls=(0, (4, 2.5)),
                label=t['chain_labels'][1])
        ax.plot(fe_t, [v - 273.15 for v in c['fe']['rad_mean_K']], color=COLD_C, lw=1.5, label=t['chain_labels'][2])
        ax.plot(mo_t, [row[5] - 273.15 for row in T], color=COLD_C, lw=1.5, ls=(0, (4, 2.5)),
                label=t['chain_labels'][3])
        ax.set_title(t['chain_cases'][case], fontsize=8.5, color=INK, pad=4)
        ax.set_ylabel(t['temp'])
        ax.set_xlim(0, 5)
        style_axes(ax)
    axes[1].set_xlabel(t['orbits'])
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', ncol=2, bbox_to_anchor=(0.5, 1.01), fontsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.91), h_pad=1.0)
    fig.savefig(OUT / f'fig_fe004_chain_{lang}.png')
    plt.close(fig)


def main():
    OUT.mkdir(exist_ok=True)
    for lang in ('cn', 'en'):
        setup(lang)
        fig_fe001(lang)
        fig_fe002(lang)
        fig_fe004(lang)
    print('figures written to', OUT)


if __name__ == '__main__':
    main()
