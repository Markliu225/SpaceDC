# -*- coding: utf-8 -*-
"""Read the settings back from a solved model file and compare them with iss_spec.py.

The production models were built before the last parameter changes and updated by the run-time
overrides of iss_run.apply_overrides; this check documents what the solved files actually contain.

    backend/.venv/Scripts/python iss_readback.py <case> [<case> ...]
Writes out/<case>/readback.json (values read back and a list of mismatches).
"""
import glob, json, os, sys
import mph

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import iss_spec as S
import iss_layout as LAY

OUT = os.path.join(os.path.dirname(HERE), 'out')


def solved_file(tag):
    c = [f for f in glob.glob(os.path.join(OUT, 'comsol', f'iss_{tag}_*.mph')) if not f.endswith('_failed.mph') and os.path.getsize(f) > 50e6]
    return max(c, key=os.path.getmtime) if c else None


def close(a, b, rel=1e-6):
    try:
        return abs(float(a) - float(b)) <= rel * max(1.0, abs(float(b)))
    except Exception:
        return str(a).strip() == str(b).strip()


def readback(client, tag, case=None):
    case = case or tag
    f = solved_file(tag)
    model = client.load(f); j = model.java; comp = j.component('comp1')
    lay = LAY.build(case)
    rb = dict(file=os.path.basename(f), params={}, materials={}, optics={}, cold_plates={}, mismatches=[])
    for k, (v, d) in S.PARAMS.items():
        got = str(j.param().get(k))
        rb['params'][k] = got
        if got.replace(' ', '') != v.replace(' ', ''):
            rb['mismatches'].append(f'param {k}: model {got} spec {v}')
    for mname, m in S.MATERIALS.items():
        try:
            pg = comp.material('mat_' + mname).propertyGroup('def')
            got = dict(k=str(pg.getStringArray('thermalconductivity')[0]), rho=str(pg.getString('density')), cp=str(pg.getString('heatcapacity')))
        except Exception as e:
            rb['mismatches'].append(f'material {mname}: not readable {str(e)[:80]}'); continue
        rb['materials'][mname] = got
        for key in ('k', 'rho', 'cp'):
            if not close(got[key], m[key]):
                rb['mismatches'].append(f'material {mname} {key}: model {got[key]} spec {m[key]}')
    for gname, ocs in lay['optics_by_group'].items():
        try: o = comp.physics('otl_' + gname)
        except Exception: continue
        for oc in ocs:
            try: d = o.feature('ds_' + oc['name'])
            except Exception:
                rb['mismatches'].append(f'optics {gname}/{oc["name"]}: feature missing'); continue
            if oc.get('two_sided'):
                got = dict(up=[str(x) for x in d.getStringArray('epsilon_radu_bandSolAmb')], down=[str(x) for x in d.getStringArray('epsilon_radd_bandSolAmb')])
                want = dict(up=oc['up'], down=oc['down'])
            else:
                got = dict(both=[str(x) for x in d.getStringArray('epsilon_rad_bandSolAmb')]); want = dict(both=oc['both'])
            rb['optics'][f'{gname}/{oc["name"]}'] = got
            for key in want:
                if not all(close(a, b) for a, b in zip(got[key], want[key])):
                    rb['mismatches'].append(f'optics {gname}/{oc["name"]} {key}: model {got[key]} spec {want[key]}')
    ht = comp.physics('ht')
    cooled = set(b['name'] for b in lay['blocks'] if b.get('cool'))
    for feat in ht.feature():
        tg = str(feat.tag())
        if tg.startswith('cp_'):
            act = bool(feat.isActive())
            rb['cold_plates'][tg] = act
            if act != (tg[3:] in cooled):
                rb['mismatches'].append(f'cold plate {tg}: active {act}, spec cooled {tg[3:] in cooled}')
    json.dump(rb, open(os.path.join(OUT, tag, 'readback.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print(tag, f, 'mismatches:', len(rb['mismatches']))
    for m in rb['mismatches'][:20]:
        print('  ', m)
    client.remove(model)


if __name__ == '__main__':
    client = mph.start(cores=1)
    for arg in sys.argv[1:]:
        tag, _, case = arg.partition(':')      # tag or tag:case
        readback(client, tag, case or None)
