# -*- coding: utf-8 -*-
"""EN-003 diagnostic, run OUTSIDE pytest with the MPh interpreter (COMSOL 6.3):

    C:\\Workspace\\SpaceDC\\space-compute-demo\\backend\\.venv\\Scripts\\python.exe fe_refine.py hot75 [nom0 ...]

The production ISS loads use a planet discretised into 2 rings of 6 points (iss_build.py --planet-rings 2
--planet-points 6, docs/REPORT.md). This script loads the solved model of a case, raises the planet discretisation of
the solar array (otl_saw) and radiator (otl_hrs) interfaces to N_RINGS x N_POINTS, switches the body and SARJ
interfaces off in the loads-only study stdL, solves stdL over one orbit on the 120 s grid and exports the same
irradiation variables as fe_export.py. Only the loads change; the model file is never saved.
Writes fe_loads_refined.json next to this script (one entry per case, appended as cases finish).
Diagnostic only; the EN-003 test uses the result when the file exists. A hot75 run on 6 cores was stopped after
26 min of solving without a result (fe_refine.log, 2026-10-05), so expect a long solve.
"""
import datetime as dt
import json
import os
import sys
import time

import mph

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
COMSOL_DIR = r"C:\Workspace\SpaceDC\Thermal\iss_fem\out\comsol"
FILES = {"nom0": "iss_nom0_29756.mph", "cold0": "iss_cold0_34584.mph", "hot75": "iss_hot75_2404.mph"}
VARS = ("Gextu1", "Gextu2", "Gextd1", "Gextd2")
N_RINGS, N_POINTS = 10, 36
PERIOD_S = 5553.6243


def log(*args):
    print(time.strftime("%H:%M:%S"), *args, flush=True)


def evaluate(j, typ, expr, sel, data):
    tag = "ev_en003r"
    try:
        j.result().numerical().remove(tag)
    except Exception:
        pass
    n = j.result().numerical().create(tag, typ)
    try:
        n.selection().named(sel)
        n.set("data", data)
        n.set("expr", [expr])
        try:
            n.set("innerinput", "all")
        except Exception:
            pass
        return [float(v) for v in n.getReal()[0]]
    finally:
        try:
            j.result().numerical().remove(tag)
        except Exception:
            pass


def refine_case(client, case):
    t0 = time.time()
    model = client.load(os.path.join(COMSOL_DIR, FILES[case]))
    j = model.java
    comp = j.component("comp1")
    log(case, "loaded", round(time.time() - t0, 1), "s")
    for tag in ("otl_saw", "otl_hrs"):
        plp = comp.physics(tag).feature("plp1")
        plp.set("nRings", str(N_RINGS))
        plp.set("nPointsRing", str(N_POINTS))
        log(case, tag, "planet", str(plp.getString("nRings")), str(plp.getString("nPointsRing")))
    step = j.study("stdL").feature("otl")
    act = [str(x) for x in step.getStringArray("activate")]
    log(case, "stdL activate before", act)
    new = list(act)
    for k in range(0, len(new) - 1, 2):
        name = new[k]
        if name in ("otl_body", "otl_sarj") or name.startswith(("rad_body", "rad_sarj")):
            new[k + 1] = "off"
    step.set("activate", new)
    log(case, "stdL activate after", [str(x) for x in step.getStringArray("activate")])
    step.set("tlist", f"range(0,120,{PERIOD_S:.4f})")
    log(case, "stdL tlist", str(step.getString("tlist")))
    t1 = time.time()
    j.study("stdL").run()
    solve_s = time.time() - t1
    log(case, "stdL solved in", round(solve_s, 1), "s")
    data = None
    for ds in j.result().dataset():
        try:
            if str(j.sol(str(ds.getString("solution"))).study()) == "stdL":
                data = str(ds.tag())
                break
        except Exception:
            pass
    tags = set(str(x) for x in comp.selection().tags())
    selections = {"saw_all": ("sel_grp_saw", "otl4")}
    for wing in ("S1", "P1"):
        members = [f"sp_hrs_{wing}_{o}_{k}" for o in (1, 2, 3) for k in range(1, 9)]
        missing = [m for m in members if m not in tags]
        if missing:
            raise RuntimeError(f"missing radiator panel selections {missing[:3]}")
        u = comp.selection().create(f"en003r_{wing}", "Union")
        u.set("entitydim", "2")
        u.set("input", members)
        selections[f"hrs_{wing}"] = (f"en003r_{wing}", "otl2")
    out = {"file": FILES[case], "dataset": data, "planet_nRings": N_RINGS, "planet_nPointsRing": N_POINTS,
           "solve_wall_s": solve_s, "activate": [str(x) for x in step.getStringArray("activate")],
           "t_s": evaluate(j, "AvSurface", "t", "sel_grp_saw", data), "series": {}}
    for key, (sel, scope) in selections.items():
        out["series"][key] = {var: evaluate(j, "AvSurface", f"{scope}.{var}", sel, data) for var in VARS}
        log(case, key, "exported")
    client.remove(model)
    log(case, "total", round(time.time() - t0, 1), "s")
    return out


def main():
    client = mph.start(cores=6)
    path = os.path.join(HERE, "fe_loads_refined.json")
    result = {"tool": "fe_refine.py", "comsol": str(client.version), "mph": mph.__version__,
              "note": "loads-only re-solve of the solved model with a finer planet discretisation; diagnostic only",
              "exported_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "cases": {}}
    for case in sys.argv[1:] or ["hot75"]:
        try:
            result["cases"][case] = refine_case(client, case)
        except Exception as exc:  # noqa: BLE001
            log(case, "FAILED", str(exc).replace("\n", " ")[:2000])
            result["cases"][case] = {"error": str(exc)[:2000]}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=1)
    log("written", path)


if __name__ == "__main__":
    main()
