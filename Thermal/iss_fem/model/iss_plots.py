# -*- coding: utf-8 -*-
"""Time-history figures from out/<tag>/series.csv (matplotlib, Chinese labels).

    python iss_plots.py <tag> [<tag2> ...]
Writes out/figures/<tag>_*.png
"""
import csv, json, os, sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'out')
FIG = os.path.join(OUT, 'figures'); os.makedirs(FIG, exist_ok=True)
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
C = ['#1f77b4', '#d62728', '#2ca02c', '#ff7f0e', '#9467bd', '#8c564b', '#17becf', '#7f7f7f']


def load(tag):
    rows = list(csv.DictReader(open(os.path.join(OUT, tag, 'series.csv'), encoding='utf-8')))
    d = {k: np.array([float(r[k]) for r in rows]) for k in rows[0]}
    summ = json.load(open(os.path.join(OUT, tag, 'summary.json'), encoding='utf-8'))
    return d, summ


def shade_eclipse(ax, d, summ):
    per = summ['orbit']['period'] if 'period' in summ['orbit'] else None
    ecl = summ['orbit'].get('eclipse_deg', 0.0)
    if not ecl or per is None: return
    t = d['t_s']; n = int(np.ceil(t[-1] / per)) + 1
    for k in range(n):
        a = (k + 0.5) * per - ecl / 360 * per / 2; b = (k + 0.5) * per + ecl / 360 * per / 2
        a, b = max(a, t[0]), min(b, t[-1])
        if b > a: ax.axvspan(a / per, b / per, color='0.88', lw=0)
    ax.set_xlim(t[0] / per, t[-1] / per)


def fig_loops(tag, d, summ):
    loops = [k[2:] for k in d if k.startswith('f_')]
    fig, axs = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    x = d['orbit']
    for ax in axs: shade_eclipse(ax, d, summ)
    for i, L in enumerate(l for l in loops if not l.startswith('PV')):
        axs[0].plot(x, d[f'Q_{L}'] / 1e3, color=C[i], label=f'回路 {L} 收集热量')
        axs[0].plot(x, d[f'Qrad_{L}'] / 1e3, '--', color=C[i], label=f'回路 {L} 散热器排热')
        axs[1].plot(x, d[f'f_{L}'], color=C[i], label=f'回路 {L}')
        axs[2].plot(x, d[f'Tret_{L}_C'], color=C[i], label=f'回路 {L} 散热器入口')
        axs[2].plot(x, d[f'Tout_{L}_C'], '--', color=C[i], label=f'回路 {L} 散热器出口')
    axs[0].set_ylabel('热量 kW'); axs[1].set_ylabel('散热器分流比'); axs[2].set_ylabel('氨温度 °C')
    axs[2].axhline(2.8, color='k', lw=0.8, ls=':'); axs[2].axhline(-40, color='k', lw=0.8, ls='-.')
    axs[2].set_xlabel('轨道圈数')
    for ax in axs: ax.grid(alpha=0.3); ax.legend(fontsize=8, ncol=2)
    fig.suptitle(f'{tag} EATCS 回路时程，灰色为地影区')
    fig.tight_layout(); p = os.path.join(FIG, f'{tag}_loops.png'); fig.savefig(p, dpi=150); plt.close(fig); print('wrote', p)


def fig_pv(tag, d, summ):
    loops = [k[2:] for k in d if k.startswith('f_PV')]
    if not loops: return
    fig, axs = plt.subplots(2, 1, figsize=(10, 6.5), sharex=True)
    x = d['orbit']
    for ax in axs: shade_eclipse(ax, d, summ)
    for i, L in enumerate(loops):
        axs[0].plot(x, d[f'f_{L}'], color=C[i], label=L)
        axs[1].plot(x, d[f'Tout_{L}_C'], color=C[i], label=f'{L} PVR 出口')
    axs[0].set_ylabel('PVR 分流比'); axs[1].set_ylabel('氨温度 °C'); axs[1].set_xlabel('轨道圈数')
    for ax in axs: ax.grid(alpha=0.3); ax.legend(fontsize=8, ncol=4)
    fig.suptitle(f'{tag} 光伏热控回路时程')
    fig.tight_layout(); p = os.path.join(FIG, f'{tag}_pvtcs.png'); fig.savefig(p, dpi=150); plt.close(fig); print('wrote', p)


LABELS = {'skin_usos': '美国段舱体蒙皮', 'skin_rus': '俄罗斯段舱体蒙皮', 'truss': '桁架', 'box': '舱外设备', 'payload': '舱外载荷',
          'rack': '舱内机柜', 'hrs': 'EATCS 散热器', 'pvr': 'PVR', 'saw': '美国太阳翼', 'rsa': '俄罗斯太阳翼'}


def fig_classes(tag, d, summ):
    classes = [k[:-len('_Tmean_C')] for k in d if k.endswith('_Tmean_C') and k[:-len('_Tmean_C')] in LABELS]
    n = len(classes); cols = 2; rows = (n + 1) // 2
    fig, axs = plt.subplots(rows, cols, figsize=(12, 2.6 * rows), sharex=True)
    axs = np.atleast_1d(axs).ravel(); x = d['orbit']
    for ax, c in zip(axs, classes):
        shade_eclipse(ax, d, summ)
        ax.fill_between(x, d[f'{c}_Tmin_C'], d[f'{c}_Tmax_C'], color=C[0], alpha=0.2, lw=0)
        ax.plot(x, d[f'{c}_Tmean_C'], color=C[0]); ax.set_title(LABELS[c] + ' 平均与极值 °C', fontsize=10); ax.grid(alpha=0.3)
    for ax in axs[n:]: ax.axis('off')
    for ax in axs[-cols:]: ax.set_xlabel('轨道圈数')
    fig.suptitle(f'{tag} 各类部件温度时程')
    fig.tight_layout(); p = os.path.join(FIG, f'{tag}_classes.png'); fig.savefig(p, dpi=150); plt.close(fig); print('wrote', p)


def fig_orus(tag, d, summ):
    keys = [k for k in d if k.endswith('_Tmean_C') and ('_S1-' in k or '_P1-' in k)]
    if not keys: return
    fig, ax = plt.subplots(figsize=(10, 4.5)); x = d['orbit']; shade_eclipse(ax, d, summ)
    for i, k in enumerate(sorted(keys)):
        ax.plot(x, d[k], color=C[i % len(C)], label=k.split('_')[1])
    ax.set_ylabel('散热器 ORU 面板平均温度 °C'); ax.set_xlabel('轨道圈数'); ax.grid(alpha=0.3); ax.legend(ncol=3, fontsize=8)
    fig.suptitle(f'{tag} 六个 EATCS 散热器 ORU 的平均温度')
    fig.tight_layout(); p = os.path.join(FIG, f'{tag}_orus.png'); fig.savefig(p, dpi=150); plt.close(fig); print('wrote', p)


if __name__ == '__main__':
    for tag in sys.argv[1:]:
        d, summ = load(tag)
        fig_loops(tag, d, summ); fig_pv(tag, d, summ); fig_classes(tag, d, summ); fig_orus(tag, d, summ)
