"""Audit saved campaign artifacts without adding formal test projects."""
from pathlib import Path
import json,hashlib,platform,sys
import numpy as np
import scipy
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return np.genfromtxt(p,delimiter=',',names=True)
con=json.loads((HERE/'contract.json').read_text());s=json.loads((HERE/'results/summary.json').read_text())
assert sha(HERE/'fixtures/accepted_test_plan.md')==con['plan_sha256']
assert sha(HERE.parent/'SDTwin_Power_Design_Report_CN_v19.1.docx')==con['design_sha256']
assert sha(HERE.parent/'battery_rebuild/data/BAK_25C.csv')==con['raw_data_sha256']
assert sha(HERE.parent/'battery_rebuild/results/parameters.json')==con['calibration_record_sha256']
assert len(s['projects'])==10 and len(con['cases'])==26
assert s['passed']==sum(p['pass_']for p in s['projects'].values())
records=[]
for cid in con['cases']:
    cfg=json.loads((HERE/f'fixtures/{cid}.json').read_text())
    assert sha(HERE/f'fixtures/{cid}.csv')==cfg['input_sha256']
    suffix='_aligned' if cid=='BT06' else ''
    a=read(HERE/f'results/{cid}_python{suffix}.csv');b=read(HERE/f'results/{cid}_simulink{suffix}.csv')
    delta=read(HERE/f'results/{cid}_difference.csv')
    for k in a.dtype.names:assert np.array_equal(a[k]-b[k],delta[k]),(cid,k,'difference is not exact subtraction')
    assert len(a)==round(cfg['stop_s']/cfg['dt_s'])+1
    assert abs(a['time_s'][0])<1e-10 and abs(a['time_s'][-1]-cfg['stop_s'])<1e-7
    assert np.all(np.diff(a['time_s'])>0) and max(np.diff(a['time_s']))<=cfg['dt_s']+1e-7
    records.append(dict(id=cid,rows=len(a),stop_s=cfg['stop_s'],dt_s=cfg['dt_s'],exact_saved_subtraction=True))
audit=json.loads((HERE/'results/BT06_alignment_audit.json').read_text())
raw=read(HERE/'results/BT06_simulink.csv');aligned=read(HERE/'results/BT06_simulink_aligned.csv')
changed=np.flatnonzero(np.any(np.stack([raw[k]!=aligned[k] for k in raw.dtype.names]),axis=0))
assert changed.tolist()==[audit['replaced_sample_index']]
assert abs(audit['time_error_s'])<=audit['time_tolerance_s']
models=json.loads((HERE/'results/model_load_audit.json').read_text())
assert len(models)==11 and all(m['continuous_integrators']==5 for m in models)
run=json.loads((HERE/'results/simulink_execution.json').read_text())
assert {r['id'] for r in run['cases']}==set(con['cases'])
assert sum(r['rows']for r in run['cases'])==s['compared_samples']==sum(r['rows'] for r in records)
fields=dict(date='2026-10-08',project_count=10,run_count=26,compared_samples=s['compared_samples'],passed=s['passed'],
            design_unchanged=True,accepted_plan_unchanged=True,inputs_hash_verified=True,
            exact_csv_subtraction=True,only_event_sample_aligned=changed.tolist(),
            native_model_count=11,representative_models=10,
            numerical_runtime=dict(python=sys.version,platform=platform.platform(),numpy=np.__version__,scipy=scipy.__version__),runs=records)
(HERE/'results/evidence_audit.json').write_text(json.dumps(fields,indent=2,ensure_ascii=False),encoding='utf8')
files=[p for p in HERE.rglob('*') if p.is_file() and not any(part in ('qa','jobs','cache','__pycache__')for part in p.relative_to(HERE).parts) and p.name!='evidence_manifest.json']
files += [HERE.parent/'battery.py',HERE.parent/'SDTwin_Power_Design_Report_CN_v19.1.docx',HERE.parent/'SDTwin_Power_Model_Test_Report_CN_v19.1.docx',HERE.parent/'SDTwin_Power_Model_Test_Report_CN_v19.1.pdf']
manifest=dict(summary=fields,files={p.relative_to(ROOT).as_posix():dict(bytes=p.stat().st_size,sha256=sha(p))for p in sorted(files)})
(HERE/'evidence_manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf8')
print(json.dumps({k:v for k,v in fields.items() if k not in ('runs','numerical_runtime')},ensure_ascii=False))
