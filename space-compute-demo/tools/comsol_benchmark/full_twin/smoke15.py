import mph, os, sys, time
D = os.path.dirname(os.path.abspath(__file__))
client = mph.start(cores=3)
model = client.load(os.path.join(D, "out", "comsol", "caseA_lite_copy.mph")); j = model.java
comp = j.component('comp1'); otl = comp.physics('otl')
def ev(typ, expr, named, ds):
    try: j.result().numerical().remove('gev')
    except Exception: pass
    n = j.result().numerical().create('gev', typ); n.selection().named(named); n.set('expr', expr); n.set('data', ds); n.set('innerinput', 'all')
    try: return [float(x) for x in n.getReal()[0]]
    finally: j.result().numerical().remove('gev')
def short(tag):
    st = j.study().create(tag)
    for typ, ftag in (('OrbitThermalLoads', 'otl'), ('OrbitalTemperature', 'ot')):
        s = st.create(ftag, typ); s.set('timestepspec', 'timesteps'); s.set('tlist', 'range(0,100,300)'); s.set('useadvanceddisable', True); s.set('disabledvariables', ['var_trans'])
        if typ == 'OrbitalTemperature': s.set('rtol', '0.005')
    t0 = time.time()
    try: st.run()
    except Exception as e: print(tag, "ERR", str(e).replace(chr(10), ' ')[:300], flush=True); return
    print(tag, "solved %.0fs" % (time.time() - t0), flush=True)
    tags = [str(d.tag()) for d in j.result().dataset()]
    best = None; bestr = -1
    for tg in tags[-2:]:
        v = ev('AvVolume', 'T', 'geom1_csel_bus_dom', tg); r = max(v) - min(v)
        if r > bestr: best, bestr = tg, r
    w = ev('AvVolume', 'T', 'geom1_csel_wings_dom', best); b = ev('AvVolume', 'T', 'geom1_csel_bus_dom', best)
    print(f"{tag}: wing T {w[0]-273.15:.2f} -> {w[-1]-273.15:.2f} C ; bus {b[0]-273.15:.2f} -> {b[-1]-273.15:.2f} C", flush=True)
ds_c, ds_b = otl.feature('ds_cell'), otl.feature('ds_back')
print("radDirectionTypeSolAmb now:", [str(x) for x in ds_c.getStringArray('radDirectionTypeSolAmb')], flush=True)
for cand in ('positiveNormal', 'negativeNormal', 'bothSides', 'PositiveNormal', 'NegativeNormal', 'Both', 'upside', 'downside'):
    try:
        ds_c.set('radDirectionTypeSolAmb', [cand, cand]); print("accepted:", cand, flush=True)
    except Exception as e:
        print("rejected:", cand, str(e).replace(chr(10), ' ')[:160], flush=True)
        continue
    ds_b.set('radDirectionTypeSolAmb', [cand, cand])
    short('V_' + cand)
print("done", flush=True)
