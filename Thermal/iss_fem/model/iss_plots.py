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
plt.rcParams['axes.unicode_minus'] = True
C = ['#1f77b4', '#d62728', '#2ca02c', '#ff7f0e', '#9467bd', '#8c564b', '#17becf', '#7f7f7f']
CASE_CN = {'cold0': '设计冷工况', 'hot75': '设计热工况', 'nom0': '平均环境工况'}


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
        axs[1].plot(x, d[f'feff_{L}'] if f'feff_{L}' in d else d[f'f_{L}'], color=C[i], label=f'回路 {L}')
        axs[2].plot(x, d[f'Tret_{L}_C'], color=C[i], label=f'回路 {L} 散热器入口')
        axs[2].plot(x, d[f'Tout_{L}_C'], '--', color=C[i], label=f'回路 {L} 散热器出口')
    axs[0].set_ylabel('热量 kW'); axs[1].set_ylabel('散热器分流比'); axs[2].set_ylabel('氨温度 °C')
    axs[2].axhline(2.8, color='k', lw=0.8, ls=':', label='供液设定点 2.8 °C'); axs[2].axhline(-40, color='k', lw=0.8, ls='-.', label='出口温度目标 −40 °C')
    axs[2].set_xlabel('轨道圈数')
    for ax in axs: ax.grid(alpha=0.3); ax.legend(fontsize=8, ncol=2)
    fig.suptitle(f'{CASE_CN.get(tag, tag)} EATCS 回路时程，灰色区域为地影')
    fig.tight_layout(); p = os.path.join(FIG, f'{tag}_loops.png'); fig.savefig(p, dpi=150); plt.close(fig); print('wrote', p)


def fig_pv(tag, d, summ):
    loops = [k[2:] for k in d if k.startswith('f_PV')]
    if not loops: return
    fig, axs = plt.subplots(2, 1, figsize=(10, 6.5), sharex=True)
    x = d['orbit']
    for ax in axs: shade_eclipse(ax, d, summ)
    for i, L in enumerate(loops):
        axs[0].plot(x, d[f'feff_{L}'] if f'feff_{L}' in d else d[f'f_{L}'], color=C[i], label=L[2:])
        axs[1].plot(x, d[f'Tout_{L}_C'], color=C[i], label=f'{L[2:]} PVR 出口')
    axs[0].set_ylabel('PVR 分流比'); axs[1].set_ylabel('氨温度 °C'); axs[1].set_xlabel('轨道圈数')
    for ax in axs: ax.grid(alpha=0.3); ax.legend(fontsize=8, ncol=4)
    fig.suptitle(f'{CASE_CN.get(tag, tag)} PVTCS 回路时程')
    fig.tight_layout(); p = os.path.join(FIG, f'{tag}_pvtcs.png'); fig.savefig(p, dpi=150); plt.close(fig); print('wrote', p)


LABELS = {'skin_usos': '美国段舱体防护屏', 'skin_rus': '俄罗斯段舱体外表面', 'truss': '桁架包络', 'box': '舱外设备与 IEA', 'payload': '舱外载荷',
          'rack': '舱内机柜', 'hrs': 'EATCS 散热器面板', 'pvr': 'PVR 面板', 'saw': '美国太阳翼', 'rsa': '服务舱太阳翼'}


def fig_classes(tag, d, summ):
    classes = [k[:-len('_Tmean_C')] for k in d if k.endswith('_Tmean_C') and k[:-len('_Tmean_C')] in LABELS]
    n = len(classes); cols = 2; rows = (n + 1) // 2
    fig, axs = plt.subplots(rows, cols, figsize=(12, 2.6 * rows), sharex=True)
    axs = np.atleast_1d(axs).ravel(); x = d['orbit']
    for ax, c in zip(axs, classes):
        shade_eclipse(ax, d, summ)
        ax.fill_between(x, d[f'{c}_Tmin_C'], d[f'{c}_Tmax_C'], color=C[0], alpha=0.2, lw=0)
        ax.plot(x, d[f'{c}_Tmean_C'], color=C[0]); ax.set_title(LABELS[c], fontsize=10); ax.set_ylabel('温度 °C', fontsize=9); ax.grid(alpha=0.3)
    for ax in axs[n:]: ax.axis('off')
    for ax in axs[-cols:]: ax.set_xlabel('轨道圈数')
    fig.suptitle(f'{CASE_CN.get(tag, tag)}各类部件温度时程，实线为平均值，色带为最低值至最高值，灰色区域为地影')
    fig.tight_layout(); p = os.path.join(FIG, f'{tag}_classes.png'); fig.savefig(p, dpi=150); plt.close(fig); print('wrote', p)


def fig_orus(tag, d, summ):
    keys = [k for k in d if k.endswith('_Tmean_C') and ('_S1-' in k or '_P1-' in k)]
    if not keys: return
    fig, ax = plt.subplots(figsize=(10, 4.5)); x = d['orbit']; shade_eclipse(ax, d, summ)
    for i, k in enumerate(sorted(keys)):
        ax.plot(x, d[k], color=C[i % len(C)], label=k.split('_')[1])
    ax.set_ylabel('散热器 ORU 面板平均温度 °C'); ax.set_xlabel('轨道圈数'); ax.grid(alpha=0.3); ax.legend(ncol=3, fontsize=8)
    fig.suptitle(f'{CASE_CN.get(tag, tag)}六个 EATCS 散热器 ORU 面板平均温度时程')
    fig.tight_layout(); p = os.path.join(FIG, f'{tag}_orus.png'); fig.savefig(p, dpi=150); plt.close(fig); print('wrote', p)


CLASS_COLORS = {   # same palette as iss_render.CLASS_COLORS
    'skin_usos': (0.80, 0.80, 0.78), 'skin_rus': (0.62, 0.70, 0.62), 'truss': (0.55, 0.55, 0.60),
    'box': (0.85, 0.62, 0.30), 'payload': (0.85, 0.35, 0.25),
    'hrs': (0.95, 0.95, 0.97), 'pvr': (0.88, 0.92, 0.98), 'saw': (0.25, 0.35, 0.65), 'rsa': (0.30, 0.45, 0.60),
}
CLASS_CN = {'skin_usos': '美国段舱体', 'skin_rus': '俄罗斯段舱体', 'truss': '桁架', 'box': '舱外设备与 IEA', 'payload': '舱外载荷',
            'hrs': 'EATCS 散热器', 'pvr': 'PVR', 'saw': '美国太阳翼', 'rsa': '服务舱太阳翼'}


def add_class_legend(path):
    """Append the thermal-class colour key below a COMSOL geometry render; writes <stem>_legend.png."""
    from matplotlib.patches import Patch
    img = plt.imread(path); h, w = img.shape[:2]
    fig = plt.figure(figsize=(w / 150, h / 150 + 0.55), dpi=150)
    ax = fig.add_axes([0, 0.55 / (h / 150 + 0.55), 1, 1 - 0.55 / (h / 150 + 0.55)]); ax.imshow(img); ax.axis('off')
    handles = [Patch(facecolor=CLASS_COLORS[c], edgecolor='0.3', label=CLASS_CN[c]) for c in CLASS_COLORS]
    fig.legend(handles=handles, loc='lower center', ncol=len(handles), fontsize=8, frameon=False, handlelength=1.4, columnspacing=1.0)
    out = path.replace('.png', '_legend.png'); fig.savefig(out, dpi=150); plt.close(fig); print('wrote', out)


def add_colorbar(path, vmin=-80.0, vmax=80.0, cmap='plasma', label='表面温度 °C'):
    """Append a horizontal colour bar (true minus signs) below a COMSOL temperature render exported
    without its own legend; writes <stem>_cb.png. COMSOL's 'Plasma' table equals matplotlib's 'plasma'."""
    import matplotlib as mpl
    img = plt.imread(path); h, w = img.shape[:2]
    extra = 0.8
    fig = plt.figure(figsize=(w / 150, h / 150 + extra), dpi=150)
    top = extra / (h / 150 + extra)
    ax = fig.add_axes([0, top, 1, 1 - top]); ax.imshow(img); ax.axis('off')
    cax = fig.add_axes([0.25, top * 0.55, 0.5, top * 0.22])
    cb = fig.colorbar(mpl.cm.ScalarMappable(norm=mpl.colors.Normalize(vmin, vmax), cmap=cmap), cax=cax, orientation='horizontal')
    cb.set_ticks(np.arange(vmin, vmax + 1, 20)); cb.ax.tick_params(labelsize=8); cb.set_label(label, fontsize=9)
    out = path.replace('.png', '_cb.png'); fig.savefig(out, dpi=150); plt.close(fig); print('wrote', out)


def fig_capacity(cases=('hot75', 'nom0', 'cold0')):
    """Radiator outlet temperature against loop heat, all flow through the radiators (out/capacity)."""
    fig, ax = plt.subplots(figsize=(9, 5.2)); k = 0
    for c in cases:
        p = os.path.join(OUT, 'capacity', f'capacity_{c}.csv')
        if not os.path.exists(p): continue
        rows = list(csv.DictReader(open(p, encoding='utf-8')))
        for L, ls in (('A', '-'), ('B', '--')):
            rr = sorted([r for r in rows if r['loop'] == L], key=lambda r: float(r['Qd_kW']))
            if not rr: continue
            q = np.array([float(r['Qd_kW']) for r in rr]); m = np.array([float(r['Tout_mean_C']) for r in rr])
            lo = np.array([float(r['Tout_min_C']) for r in rr]); hi = np.array([float(r['Tout_max_C']) for r in rr])
            ax.plot(q, m, ls, marker='o', color=C[k], label=f'{CASE_CN.get(c, c)}回路 {L} 一圈平均值')
            ax.fill_between(q, lo, hi, color=C[k], alpha=0.12, lw=0)
        k += 1
    ax.axhline(2.8, color='k', lw=0.9, ls=':'); ax.text(ax.get_xlim()[0], 3.4, ' 供液设定点 2.8 °C', fontsize=9)
    ax.axvline(35, color='0.4', lw=0.9, ls='-.'); ax.text(35.5, ax.get_ylim()[0] + 2, '单回路设计排热能力 35 kW', fontsize=9, color='0.3')
    ax.set_xlabel('单回路排热量 kW'); ax.set_ylabel('散热器出口氨温度 °C'); ax.grid(alpha=0.3); ax.legend(fontsize=8, ncol=2)
    fig.suptitle('散热器全流量时出口温度与排热量的关系，色带为一圈内最低值至最高值')
    fig.tight_layout(); p = os.path.join(FIG, 'capacity_outlet.png'); fig.savefig(p, dpi=150); plt.close(fig); print('wrote', p)


if __name__ == '__main__':
    if sys.argv[1:] == ['--capacity']:
        fig_capacity(); sys.exit(0)
    if sys.argv[1:2] == ['--colorbar']:
        for p in sys.argv[2:]:
            add_colorbar(p)
        sys.exit(0)
    if sys.argv[1:2] == ['--legend']:
        for p in sys.argv[2:]:
            add_class_legend(p)
        sys.exit(0)
    for tag in sys.argv[1:]:
        d, summ = load(tag)
        fig_loops(tag, d, summ); fig_pv(tag, d, summ); fig_classes(tag, d, summ); fig_orus(tag, d, summ)
