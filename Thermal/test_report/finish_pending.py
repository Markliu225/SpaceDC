"""Finish this experiment batch once all three COMSOL refinement exports exist.

This is a one-shot local coordinator, not a scheduled service. It leaves numerical
acceptance failures visible, and stops on incomplete execution or export errors.
Final page-image inspection is performed separately after rendering.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'test_report'
QA = HERE / 'qa'
SCIENCE = ROOT / '.venv' / 'Scripts' / 'python.exe'
DOCUMENT = Path(r'C:\Users\markl\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe')
CASES = ('hot75', 'nom0', 'cold0')
TLIST = 'range(10920,360,16560)'
LOG = QA / 'finish_pending.log'


def log(message):
    line = f'{dt.datetime.now().astimezone().isoformat(timespec="seconds")} {message}'
    print(line, flush=True)
    with LOG.open('a', encoding='utf-8') as stream:
        stream.write(line + '\n')


def readiness():
    complete = []
    for case in CASES:
        path = ROOT / 'tests' / 'data' / 'en_003' / f'fe_loads_ladder_{case}.json'
        if not path.exists():
            continue
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:  # the exporter may still be writing
            continue
        for level in ('4x12', '8x24'):
            item = record.get('levels', {}).get(f'{level}@{TLIST}', {})
            if 'error' in item:
                raise RuntimeError(f'{case} {level}: {item["error"]}')
            if 'series' not in item:
                continue
            expected = [10920 + 360 * i for i in range(16)]
            assert all(sum(abs(a - b) < 1e-6 for a in item['t_s']) == 1 for b in expected), (case, level, 'time grid')
            assert len(item['series']) == 3, (case, level, 'surface groups')
            for series in item['series'].values():
                assert len(series) == 4, (case, level, 'irradiation variables')
                for values in series.values():
                    assert len(values) == len(item['t_s']) and all(math.isfinite(x) for x in values), (case, level, 'finite data')
            complete.append(f'{case}/{level}')
    return complete


def run(args, **kwargs):
    log('Running ' + ' '.join(map(str, args)))
    subprocess.run(list(map(str, args)), cwd=ROOT, check=True, **kwargs)


def main():
    os.environ['PYTHONUTF8'] = '1'
    last = None
    while True:
        ready = readiness()
        if ready != last:
            log(f'Completed refinement levels: {ready}')
            last = ready
        if len(ready) == 6:
            break
        time.sleep(30)
    log('All refinement data are available; starting the final EN-003 rerun.')
    result_log = ROOT / 'tests' / 'results' / 'pytest_en003_final.txt'
    with result_log.open('w', encoding='utf-8') as stream:
        result = subprocess.run([str(SCIENCE), '-m', 'pytest', 'tests/test_en_003_earth_flux.py', '-q'],
                                cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    assert result.returncode in (0, 1), f'pytest infrastructure exit {result.returncode}'
    record = json.loads((ROOT / 'tests' / 'results' / 'EN-003.json').read_text(encoding='utf-8'))
    execution = record['execution']
    assert execution['finished_functions'] == execution['collected_functions'] == 7
    assert not execution['unexecuted_functions']
    assert not record['metrics']['fe_ladder_missing_cases']
    assert not any(not c['passed'] and c['name'].endswith((' setup', ' teardown')) for c in record['checks'])
    log(f'EN-003 execution complete; acceptance status: {record["status"]}.')
    run([DOCUMENT, HERE / 'reviewed_results.py'])
    run([DOCUMENT, HERE / 'figures_results.py'])
    for lang in ('cn', 'en'):
        run([DOCUMENT, HERE / 'build_test_report.py', lang])
        run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', HERE / 'finalize.ps1',
             '-Name', f'SDTwin_Thermal_Test_Report_{lang.upper()}'])
    run([DOCUMENT, QA / 'audit_reports.py'])
    run([SCIENCE, HERE / 'evidence_manifest.py'])
    run([DOCUMENT, QA / 'render_review.py', ROOT / 'SDTwin_Thermal_Test_Report_CN.pdf',
         ROOT / 'SDTwin_Thermal_Test_Report_EN.pdf'])
    log('Final reports and evidence manifest generated. Final page-image inspection remains required.')


if __name__ == '__main__':
    main()
