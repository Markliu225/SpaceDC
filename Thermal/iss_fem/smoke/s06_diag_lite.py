# Diagnose the consistent-initialisation failure of the lite ISS model by bisection
import mph, sys, time
c = mph.start(cores=5)
path = r'C:\Workspace\SpaceDC\Thermal\iss_fem\out\comsol\iss_beta0_lite_try_failed.mph'
def attempt(label, mutate):
    m = c.load(path); j = m.java; comp = j.component('comp1')
    for s in ('otl', 'ot'):
        j.study('stdO').feature(s).set('tlist', 'range(0,60,240)')
    try:
        mutate(j, comp)
    except Exception as e:
        print(label, 'mutate ERR', str(e).replace(chr(10), ' ')[:300]); c.remove(m); return
    t0 = time.time()
    try:
        j.study('stdO').run(); print(label, 'OK %.0fs' % (time.time() - t0), flush=True)
    except Exception as e:
        msg = str(e).replace(chr(10), ' ')
        k = msg.find('Variable'); print(label, 'FAIL %.0fs' % (time.time() - t0), msg[:220], '...', msg[k:k+200] if k > 0 else '', flush=True)
    c.remove(m)

def no_ge(j, comp):
    for s in ('otl', 'ot'):
        st = j.study('stdO').feature(s); a = [str(x) for x in st.getStringArray('activate')]
        i = a.index('ge'); a[i + 1] = 'off'; st.set('activate', a)
    # heat sources that reference ge variables must go too
    sh = comp.physics('htlsh')
    for f in sh.feature():
        if str(f.tag()).startswith('fx_'): f.active(False)
def no_fx(j, comp):
    sh = comp.physics('htlsh')
    for f in sh.feature():
        if str(f.tag()).startswith('fx_'): f.active(False)
def no_events(j, comp):
    for p in comp.physics():
        if str(p.getType()) == 'OrbitalThermalLoadsEvents':
            try: p.feature('et1').set('eventType', [])
            except Exception as e: print('events off ERR', str(e)[:120])
def no_ht_ic(j, comp):
    pass
which = sys.argv[1:] or ['asis', 'no_ge', 'no_fx']
for w in which:
    attempt(w, {'asis': lambda j, c_: None, 'no_ge': no_ge, 'no_fx': no_fx, 'no_events': no_events}[w])
