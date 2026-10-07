"""Check plotted FE values against the original CSV and all differences against test evidence."""
from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import json
import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def main():
    plot_path = ROOT / 'test_report/out/fe001_plot_data.json'
    plotted = json.loads(plot_path.read_text(encoding='utf-8'))
    metrics = json.loads((ROOT / 'tests/results/FE-001.json').read_text(encoding='utf-8'))['metrics']
    records = {}
    for case, p in plotted.items():
        source = ROOT / 'iss_fem/out' / case / 'series.csv'
        with source.open(encoding='utf-8-sig', newline='') as stream:
            csv_rows = list(csv.DictReader(stream))
        tx, fe, module, delta = [np.asarray(p[k], dtype=float) for k in
                                 ('time_s', 'fe_C', 'module_C', 'module_minus_fe_K')]
        reference = metrics[case + '_comparison']
        np.testing.assert_array_equal(tx, reference['fe_time_s'])
        for moment, value in zip(tx, fe):
            matching = [float(r['saw_Tmean_C']) for r in csv_rows if abs(float(r['t_s']) - moment) < 1e-9]
            assert matching and all(abs(v - value) < 1e-10 for v in matching), (case, moment)
        np.testing.assert_allclose(module - fe, delta, rtol=0, atol=1e-12)
        np.testing.assert_allclose(delta, reference['module_minus_fe_pointwise_K'], rtol=0, atol=1e-12)
        # Identical piecewise-linear knots also preserve subtraction between samples.
        dense = np.linspace(tx[0], tx[-1], 5001)
        line_error = np.interp(dense, tx, module) - np.interp(dense, tx, fe) - np.interp(dense, tx, delta)
        assert np.max(abs(line_error)) < 1e-12
        i = int(np.argmax(abs(delta)))
        records[case] = {'samples':len(tx), 'worst_time_s':float(tx[i]),
                         'worst_time_last_orbit_min':p['time_in_last_orbit_min'][i],
                         'fe_C':float(fe[i]), 'module_C':float(module[i]), 'difference_K':float(delta[i]),
                         'old_plot_max_error_vs_test_K':p['old_plot_max_abs_difference_from_test_K'],
                         'new_plot_max_error_vs_test_K':float(np.max(abs(delta - reference['module_minus_fe_pointwise_K']))),
                         'between_sample_subtraction_max_error_K':float(np.max(abs(line_error))),
                         'original_fe_source':str(source.relative_to(ROOT)),
                         'original_fe_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    output = {'checked_utc':datetime.now(timezone.utc).isoformat(), 'cases':records,
              'plot_data_sha256':hashlib.sha256(plot_path.read_bytes()).hexdigest(),
              'method':'Both temperature curves and residual use the same acceptance samples; no 10 s export re-interpolation.',
              'figures':{lang:hashlib.sha256((ROOT / f'test_report/out/fig_fe001_solar_{lang}.png').read_bytes()).hexdigest()
                         for lang in ('cn','en')}}
    Path(__file__).with_name('fe001_plot_audit.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps(records,indent=2))


if __name__ == '__main__':
    main()
