# -*- coding: utf-8 -*-
"""EN-003 reference refinement, run OUTSIDE pytest with the MPh interpreter (COMSOL 6.3):

    C:\\Workspace\\SpaceDC\\space-compute-demo\\backend\\.venv\\Scripts\\python.exe fe_refine_ladder.py CASE TLIST LEVEL [LEVEL ...]

    CASE   cold0, nom0 or hot75
    TLIST  COMSOL time list of the loads-only study, for example "range(0,720,5553.6243)" for every sixth instant of
           the 120 s grid of fe_export.py, or "0" for a single instant
    LEVEL  planet discretisation as RINGSxPOINTS, for example 2x6 4x12 8x24

The production ISS loads use a planet discretised into 2 rings of 6 points (iss_build.py --planet-rings 2
--planet-points 6, docs/REPORT.md). For each level this script loads the solved model of the case, sets the planet
discretisation of the solar array (otl_saw) and radiator (otl_hrs) interfaces, switches the body and SARJ interfaces
off in the loads-only study stdL, solves stdL on TLIST and exports the same irradiation variables as fe_export.py
(otl4.Gextu1/2 and Gextd1/2 on the solar array, otl2 on the radiator panels of wings S1 and P1). The model file is
never saved. Each level is written as soon as it finishes to fe_loads_ladder_<CASE>.json next to this script, so the
EN-003 test can compare the module with each available level and assess changes under planet refinement.
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


def log(*args):
    print(time.strftime("%H:%M:%S"), *args, flush=True)


def evaluate(j, typ, expr, sel, data):
    tag = "ev_en003l"
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


def run_level(client, case, tlist, rings, points):
    t0 = time.time()
    model = client.load(os.path.join(COMSOL_DIR, FILES[case]))
    j = model.java
    comp = j.component("comp1")
    log(case, f"{rings}x{points}", "loaded", round(time.time() - t0, 1), "s")
    for tag in ("otl_saw", "otl_hrs"):
        plp = comp.physics(tag).feature("plp1")
        plp.set("nRings", str(rings))
        plp.set("nPointsRing", str(points))
    step = j.study("stdL").feature("otl")
    new = [str(x) for x in step.getStringArray("activate")]
    for k in range(0, len(new) - 1, 2):
        if new[k] in ("otl_body", "otl_sarj") or new[k].startswith(("rad_body", "rad_sarj")):
            new[k + 1] = "off"
    step.set("activate", new)
    step.set("tlist", tlist)
    log(case, f"{rings}x{points}", "activate", [str(x) for x in step.getStringArray("activate")], "tlist", tlist)
    t1 = time.time()
    j.study("stdL").run()
    solve_s = time.time() - t1
    log(case, f"{rings}x{points}", "stdL solved in", round(solve_s, 1), "s")
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
        u = comp.selection().create(f"en003l_{wing}", "Union")
        u.set("entitydim", "2")
        u.set("input", members)
        selections[f"hrs_{wing}"] = (f"en003l_{wing}", "otl2")
    out = {"file": FILES[case], "dataset": data, "planet_nRings": rings, "planet_nPointsRing": points,
           "tlist": tlist, "solve_wall_s": solve_s,
           "activate": [str(x) for x in step.getStringArray("activate")],
           "t_s": evaluate(j, "AvSurface", "t", "sel_grp_saw", data), "series": {}}
    for key, (sel, scope) in selections.items():
        out["series"][key] = {var: evaluate(j, "AvSurface", f"{scope}.{var}", sel, data) for var in VARS}
    client.remove(model)
    log(case, f"{rings}x{points}", "exported, total", round(time.time() - t0, 1), "s")
    return out


def main():
    case, tlist, levels = sys.argv[1], sys.argv[2], sys.argv[3:]
    client = mph.start(cores=10)
    path = os.path.join(HERE, f"fe_loads_ladder_{case}.json")
    result = {"tool": "fe_refine_ladder.py", "comsol": str(client.version), "mph": mph.__version__,
              "note": "loads-only re-solve of the solved model at several planet discretisations",
              "case": case, "levels": {}}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            old = json.load(fh)
        if old.get("case") == case:
            result["levels"] = old.get("levels", {})
    for level in levels:
        rings, points = (int(v) for v in level.lower().split("x"))
        key = f"{rings}x{points}@{tlist}"
        try:
            result["levels"][key] = run_level(client, case, tlist, rings, points)
        except Exception as exc:  # noqa: BLE001
            log(case, level, "FAILED", str(exc).replace("\n", " ")[:2000])
            result["levels"][key] = {"error": str(exc)[:2000], "planet_nRings": rings, "planet_nPointsRing": points,
                                     "tlist": tlist}
        result["exported_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=1)
        log("written", path, key)


if __name__ == "__main__":
    main()
