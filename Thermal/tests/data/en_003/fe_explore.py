# -*- coding: utf-8 -*-
"""EN-003 helper, run OUTSIDE pytest with the MPh interpreter:

    C:\\Workspace\\SpaceDC\\space-compute-demo\\backend\\.venv\\Scripts\\python.exe fe_explore.py [mph file]

Explores a solved ISS model: physics interface tags and variable scopes, datasets, and which Orbital Thermal Loads
irradiation variables evaluate on one US solar array blanket and one EATCS radiator panel. Writes
fe_explore.log next to this script. Read-only: the model file is never saved.
"""
import os
import sys
import time

import mph
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = r"C:\Workspace\SpaceDC\Thermal\iss_fem\out\comsol\iss_nom0_29756.mph"
LOG = open(os.path.join(HERE, "fe_explore.log"), "w", encoding="utf-8")


def log(*args):
    text = time.strftime("%H:%M:%S ") + " ".join(str(a) for a in args)
    print(text, flush=True)
    LOG.write(text + "\n")
    LOG.flush()


def ev(j, expr, sel, data, typ="AvSurface"):
    tag = "ev_explore"
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
        vals = n.getReal()
        return np.array(vals[0], dtype=float)
    finally:
        try:
            j.result().numerical().remove(tag)
        except Exception:
            pass


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    t0 = time.time()
    client = mph.start(cores=4)
    log("client started", round(time.time() - t0, 1), "s")
    model = client.load(path)
    log("loaded", path, round(time.time() - t0, 1), "s")
    j = model.java
    comp = j.component("comp1")
    for tag in [str(x) for x in comp.physics().tags()]:
        ph = comp.physics(tag)
        try:
            name = str(ph.name())
        except Exception as exc:  # noqa: BLE001
            name = f"(name n/a: {str(exc)[:60]})"
        log("physics", tag, "name", name, "label", str(ph.label()))
    for ds in j.result().dataset():
        try:
            sol = str(ds.getString("solution"))
            study = str(j.sol(sol).study())
        except Exception:
            sol, study = "?", "?"
        log("dataset", str(ds.tag()), "solution", sol, "study", study, "label", str(ds.label()))
    log("mph datasets", model.datasets())
    sel_tags = [str(x) for x in comp.selection().tags()]
    log("selections", len(sel_tags), [s for s in sel_tags if s.startswith(("sp_saw", "sel_grp", "sp_hrs_S1_1_1", "sp_hrs_P1_1_1"))])
    candidates = []
    for scope in ("otl", "otl2", "otl3", "otl4"):
        for base in ("Gext", "G", "Gm", "J", "q", "Gextu", "Gextd", "Gu", "Gd", "Gmu", "Gmd", "Ju", "Jd",
                     "Gext_u", "Gext_d", "G_u", "G_d"):
            for band in ("1", "2", "_1", "_2", ""):
                candidates.append(f"{scope}.{base}{band}")
    datasets = []
    for ds in j.result().dataset():
        try:
            if str(j.sol(str(ds.getString("solution"))).study()) == "stdO":
                datasets.append(str(ds.tag()))
        except Exception:
            pass
    log("orbital transient datasets", datasets)
    for sel in ("sp_saw_2A_a", "sp_hrs_S1_1_1"):
        for data in datasets:
            try:
                t = ev(j, "t", sel, data)
            except Exception as exc:  # noqa: BLE001
                log("t on", sel, data, "ERR", str(exc).replace("\n", " ")[:160])
                continue
            log("time on", sel, data, "n", t.size, "first", t[:3].round(1).tolist(), "last", t[-2:].round(1).tolist())
            for expr in candidates:
                try:
                    v = ev(j, expr, sel, data)
                    log("OK", sel, data, expr, "n", v.size, "min", round(float(v.min()), 3), "max", round(float(v.max()), 3),
                        "first", np.round(v[:8], 2).tolist())
                except Exception as exc:  # noqa: BLE001
                    msg = str(exc).replace("\n", " ")
                    if "未定义变量" in msg or "Undefined variable" in msg:
                        continue
                    log("ERR", sel, data, expr, msg[:160])
    for sel in ("sp_saw_2A_a", "sp_hrs_S1_1_1"):
        for expr in ("nx", "ny", "nz", "x", "y", "z"):
            try:
                v = ev(j, expr, sel, datasets[0])
                log("geometry", sel, expr, np.round(v[:3], 4).tolist())
            except Exception as exc:  # noqa: BLE001
                log("geometry ERR", sel, expr, str(exc).replace("\n", " ")[:120])
    log("total", round(time.time() - t0, 1), "s")
    client.remove(model)


if __name__ == "__main__":
    main()
