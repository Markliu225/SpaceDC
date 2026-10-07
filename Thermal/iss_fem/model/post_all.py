# -*- coding: utf-8 -*-
"""Post-process solved cases: probes (with loop globals), time-history plots, COMSOL temperature
renders at named orbit instants of orbit 3, then the report.

    python post_all.py cold0 hot75 nom0 [--cores 2] [--skip-probe] [--skip-render] [--no-report]
"""
import argparse, glob, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = r'C:\Workspace\SpaceDC\space-compute-demo\backend\.venv\Scripts\python.exe'
sys.path.insert(0, HERE)
import iss_layout as LAY


def run(cmd, log):
    print('>>', ' '.join(cmd), flush=True)
    with open(log, 'w', encoding='utf-8') as fh:
        r = subprocess.run(cmd, cwd=HERE, stdout=fh, stderr=subprocess.STDOUT, env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    print('   exit', r.returncode, '->', log, flush=True)
    return r.returncode


def solved_file(tag):
    c = [f for f in glob.glob(os.path.join(ROOT, 'out', 'comsol', f'iss_{tag}_*.mph')) if not f.endswith('_failed.mph') and os.path.getsize(f) > 50e6]
    return max(c, key=os.path.getmtime) if c else None


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('cases', nargs='+'); ap.add_argument('--cores', type=int, default=2)
    ap.add_argument('--skip-probe', action='store_true'); ap.add_argument('--skip-render', action='store_true'); ap.add_argument('--no-report', action='store_true')
    a = ap.parse_args()
    for case in a.cases:
        lay = LAY.build(case); per = lay['period']; ecl = lay['orbit_info']['eclipse_deg']
        logd = os.path.join(ROOT, 'out', case); os.makedirs(logd, exist_ok=True)
        if not a.skip_probe:
            run([PY, '-u', 'iss_run.py', case, '--tag', case, '--probe-only', '--cores', str(a.cores)], os.path.join(logd, 'post_probe.log'))
        run([sys.executable, 'iss_plots.py', case], os.path.join(logd, 'post_plots.log'))
        if not a.skip_render:
            f = solved_file(case)
            if f:
                times = [('noon', 2.0 * per)] + ([('ecl', 2.5 * per)] if ecl else [('q90', 2.25 * per)]) + [('q270', 2.75 * per)]
                tl = ','.join(f'{n}:{t:.1f}' for n, t in times)
                run([PY, '-u', 'iss_render.py', f, '--what', 'temp', '--times', tl, '--prefix', case, '--period', f'{per:.2f}',
                     '--cores', str(a.cores)], os.path.join(logd, 'post_render.log'))
                pngs = [p for p in glob.glob(os.path.join(ROOT, 'out', 'figures', f'{case}_T_*.png')) if not p.endswith('_cb.png')]
                run([sys.executable, 'iss_plots.py', '--colorbar'] + pngs, os.path.join(logd, 'post_colorbar.log'))
            else:
                print('no solved model file for', case)
    if not a.no_report:
        rep = os.path.join(ROOT, 'report')
        run([sys.executable, os.path.join(rep, 'build_iss_report.py'), '--cases', ','.join(a.cases)], os.path.join(ROOT, 'out', 'post_report.log'))


if __name__ == '__main__':
    main()
