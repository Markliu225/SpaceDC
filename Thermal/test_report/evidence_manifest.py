"""Bind final case records to the tested source, inputs and bilingual reports.

Execution completion and scientific acceptance are deliberately separate. A fully
executed case may fail its acceptance criterion. Incomplete runs cannot be released.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'tests' / 'results'
CASES = ('DM-001', 'PA-001', 'EN-001', 'EN-002', 'EN-003', 'HT-001', 'HT-002', 'HT-003',
         'EC-001', 'FE-001', 'FE-002', 'FE-003', 'FE-004', 'NI-001', 'NI-002', 'NI-003')


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(paths):
    return {p.relative_to(ROOT).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha256(p)}
            for p in sorted(set(paths)) if p.is_file() and '__pycache__' not in p.parts}


def build():
    code = inventory([p for folder in ('thermal', 'sdtwin_sim', 'tests')
                      for p in (ROOT / folder).rglob('*.py')])
    core = {p: v['sha256'] for p, v in code.items()
            if p.startswith(('thermal/', 'sdtwin_sim/'))}
    case_records = []
    for cid in CASES:
        path = RESULTS / f'{cid}.json'
        data = json.loads(path.read_text(encoding='utf-8'),
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f'{cid}: non-finite {value}')))
        execution = data['execution']
        assert execution['collected_functions'] == execution['finished_functions'] > 0, cid
        assert not execution['unexecuted_functions'], cid
        assert data['summary_cn'] and data['status'] in ('pass', 'fail'), cid
        recorded = execution['source_sha256']
        assert all(recorded.get(p) == digest for p, digest in core.items()), f'{cid}: stale core'
        module = next(p for p in code if p.startswith('tests/test_' + cid.lower().replace('-', '_') + '_'))
        assert recorded[module] == code[module]['sha256'], f'{cid}: stale test'
        assert not any(c['name'].endswith((' setup', ' teardown')) and not c['passed']
                       for c in data['checks']), f'{cid}: test infrastructure error'
        case_records.append({'case_id': cid, 'status': data['status'],
                             'functions': execution['finished_functions'],
                             'checks': len(data['checks']),
                             'failed_checks': sum(not c['passed'] for c in data['checks']),
                             'execution_started_utc': execution['started_utc'],
                             'recorded_utc': execution['recorded_utc'], 'sha256': sha256(path)})
    earth = json.loads((RESULTS / 'EN-003.json').read_text(encoding='utf-8'))['metrics']
    assert earth.get('fe_ladder_missing_cases') == [], 'COMSOL refinement is incomplete'
    assert set(earth['fe_refined_comparison']['cases']) == {'cold0', 'nom0', 'hot75'}
    logs = [RESULTS / name for name in ('pytest_verified_run.txt', 'pytest_en003_final.txt')]
    assert all(p.exists() for p in logs), 'Missing final execution log'
    reports = [ROOT / f'SDTwin_Thermal_Test_Report_{lang}.{ext}'
               for lang in ('CN', 'EN') for ext in ('docx', 'pdf')]
    assert all(p.exists() for p in reports), 'Missing report'
    data_paths = [p for p in (ROOT / 'tests' / 'data').rglob('*')
                  if p.is_file() and p.suffix.lower() not in ('.pyc', '.log')]
    result_paths = [p for p in RESULTS.rglob('*') if p.is_file()
                    and p.name != 'verification_manifest.json']
    manifest = {
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Thermal software tests with illustrative Power stand-in; no hardware calibration claim',
        'execution_complete': True,
        'all_acceptance_criteria_pass': all(c['status'] == 'pass' for c in case_records),
        'case_status_counts': dict(Counter(c['status'] for c in case_records)),
        'test_functions': sum(c['functions'] for c in case_records),
        'checks': sum(c['checks'] for c in case_records),
        'cases': case_records,
        'source_files': code, 'input_files': inventory(data_paths),
        'report_sources': inventory(list((ROOT / 'test_report').glob('*.py')) +
                                    list((ROOT / 'test_report' / 'out').glob('fig_*.png')) +
                                    [ROOT / 'test_report' / 'out' / 'reviewed_results.json',
                                     ROOT / 'test_report' / 'finalize.ps1', ROOT / 'IMPLEMENTATION.md']),
        'comsol_model_files': inventory([ROOT / 'iss_fem' / 'out' / 'comsol' / name for name in
                                        ('iss_nom0_29756.mph', 'iss_cold0_34584.mph', 'iss_hot75_2404.mph')]),
        'evidence_files': inventory(result_paths), 'reports': inventory(reports),
        'quality_assurance': inventory([ROOT / 'test_report' / 'qa' / name for name in
                                       ('report_content_audit.json', 'visual_inspection.json',
                                        'adaptive_reference_validation.json', 'ladder_baseline_reproduction.json',
                                        'ladder_sampling_validation.json')]),
        'comsol_refinement': {
            'cases': ['cold0', 'nom0', 'hot75'], 'levels': ['2x6', '4x12', '8x24'],
            'requested_tlist': 'range(10920,360,16560)', 'sample_count_per_case': 16,
            'sample_time_s': [10920 + i * 360 for i in range(16)],
            'event_samples': 'COMSOL may export extra paired eclipse-boundary samples; retained raw, excluded from the common arithmetic means',
            'scope': 'orbital thermal loads only; no thermal-solver convergence claim',
            'baseline': 'hot75 2x6 rerun; cold0 and nom0 2x6 from production export at matching instants',
        },
    }
    path = RESULTS / 'verification_manifest.json'
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: manifest[k] for k in ('execution_complete', 'all_acceptance_criteria_pass',
                                             'case_status_counts', 'test_functions', 'checks')}, indent=2))
    print(path)


if __name__ == '__main__':
    build()
