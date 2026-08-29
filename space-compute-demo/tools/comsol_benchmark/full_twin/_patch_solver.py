# one-off patch: attach a strict-step solver sequence to study B; run it via sol.runAll
import os, py_compile
D = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(D, "build_comsol.py"); s = open(p, encoding="utf-8").read()
old = "    temp_study('stdB', tlist_B, 'var_stat', 'stdLB', init='stdA').label('B: orbital transient (init from A)')\n"
new = old + """    # Study B solver: STRICT steps equal to the load-sampling interval. The
    # precomputed loads are piecewise-linear in time (kink every dt_out s); a
    # free BDF stepper crawls through those kinks with tiny steps (lite mesh:
    # 0.3 orbit not finished after 5 CPU-hours). Landing every step exactly on
    # a sample removes that penalty. Max BDF order 2.
    solB = j.sol().create('solB'); solB.study('stdB'); solB.createAutoSequence('stdB')
    for f in solB.feature():
        if str(f.getType()) == 'Time':
            f.set('tstepsbdf', 'strict'); f.set('maxstepconstraintbdf', 'const'); f.set('maxstepbdf', str(args.dt_out)); f.set('maxorder', '2')
            f.set('rtol', str(args.rtol))
"""
assert old in s; s = s.replace(old, new); open(p, "w", encoding="utf-8").write(s)
p2 = os.path.join(D, "solve_and_probe.py"); s2 = open(p2, encoding="utf-8").read()
old2 = """    t0 = time.time()
    j.study('stdB').run()
    log['stdB_wall_s'] = round(time.time() - t0, 1)
    print("study B done %.0fs" % log['stdB_wall_s'], flush=True)
    dsB = newest_dataset(j)"""
new2 = """    t0 = time.time()
    j.sol('solB').runAll()
    log['stdB_wall_s'] = round(time.time() - t0, 1)
    print("study B done %.0fs" % log['stdB_wall_s'], flush=True)
    dsB = dataset_for_sol(j, 'solB')"""
assert old2 in s2; s2 = s2.replace(old2, new2)
s2 = s2.replace("def newest_dataset(j):", """def dataset_for_sol(j, soltag):
    for d in j.result().dataset():
        try:
            if str(d.getString('solution')) == soltag:
                return str(d.tag())
        except Exception:
            pass
    return newest_dataset(j)


def newest_dataset(j):""")
open(p2, "w", encoding="utf-8").write(s2)
py_compile.compile(p, doraise=True); py_compile.compile(p2, doraise=True); print("patched & compiles")
