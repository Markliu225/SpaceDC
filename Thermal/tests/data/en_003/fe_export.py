# -*- coding: utf-8 -*-
"""EN-003 finite-element export, run OUTSIDE pytest with the MPh interpreter (COMSOL 6.3):

    C:\\Workspace\\SpaceDC\\space-compute-demo\\backend\\.venv\\Scripts\\python.exe fe_export.py

Reads the solved ISS models of the three environment cases and exports the Orbital Thermal Loads external
irradiation (W/m^2) of the US solar array blankets (interface otl_saw, variable scope otl4) and of the EATCS radiator
panels (interface otl_hrs, scope otl2), per side and per band:
  Gextu1 / Gextu2  up side,   solar band / infrared band
  Gextd1 / Gextd2  down side, solar band / infrared band
Up side: blanket +Z (anti-Sun, back face), radiator panel +Y (checked with nx, ny, nz below). Gext holds the
external sources only (direct Sun, Earth albedo, Earth infrared); radiation from other surfaces is Gm and the
2.7 K ambient is separate. On the blanket back face and on the radiator faces (edge to the Sun) the solar band is
therefore pure Earth albedo and the infrared band pure Earth infrared.

Writes fe_loads.json next to this script (values as evaluated, face averages over each selection, all output times
of the orbital transient study). The model files are only read; nothing is saved.
"""
import datetime as dt
import json
import os
import sys
import time

import mph
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
COMSOL_DIR = r"C:\Workspace\SpaceDC\Thermal\iss_fem\out\comsol"
FILES = {"nom0": "iss_nom0_29756.mph", "cold0": "iss_cold0_34584.mph", "hot75": "iss_hot75_2404.mph"}
VARS = ("Gextu1", "Gextu2", "Gextd1", "Gextd2")
SAW_WINGS = ("2A", "4A", "2B", "4B", "1A", "3A", "1B", "3B")
HRS_ORUS = ("S1_1", "S1_2", "S1_3", "P1_1", "P1_2", "P1_3")


def log(*args):
    print(time.strftime("%H:%M:%S"), *args, flush=True)


def evaluate(j, typ, expr, sel, data):
    tag = "ev_en003"
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


def string_of(feature, name):
    """Property value: a list for array properties (getStringArray), else a string."""

    try:
        values = [str(x) for x in feature.getStringArray(name)]
        return values if len(values) != 1 else values[0]
    except Exception:
        try:
            return str(feature.getString(name))
        except Exception as exc:  # noqa: BLE001
            return f"(not readable: {str(exc)[:80]})"


def export_case(client, case, filename):
    path = os.path.join(COMSOL_DIR, filename)
    t0 = time.time()
    model = client.load(path)
    log(case, "loaded", round(time.time() - t0, 1), "s")
    j = model.java
    comp = j.component("comp1")
    data = None
    for ds in j.result().dataset():
        try:
            if str(j.sol(str(ds.getString("solution"))).study()) == "stdO" and str(ds.getString("solution")) == "sol4":
                data = str(ds.tag())
        except Exception:
            pass
    if data is None:
        raise RuntimeError("orbital transient dataset of sol4 not found")
    # radiator unions per ORU and per wing (in memory only)
    tags = set(str(x) for x in comp.selection().tags())
    selections = {}
    for wing in SAW_WINGS:
        for side in ("a", "b"):
            selections[f"saw_{wing}_{side}"] = (f"sp_saw_{wing}_{side}", "otl4")
    selections["saw_all"] = ("sel_grp_saw", "otl4")
    for oru in HRS_ORUS:
        members = [f"sp_hrs_{oru}_{k}" for k in range(1, 9)]
        missing = [m for m in members if m not in tags]
        if missing:
            raise RuntimeError(f"missing radiator panel selections {missing}")
        u = comp.selection().create(f"en003_{oru}", "Union")
        u.set("entitydim", "2")
        u.set("input", members)
        selections[f"hrs_{oru}"] = (f"en003_{oru}", "otl2")
    for wing in ("S1", "P1"):
        u = comp.selection().create(f"en003_{wing}", "Union")
        u.set("entitydim", "2")
        u.set("input", [f"en003_{wing}_{k}" for k in (1, 2, 3)])
        selections[f"hrs_{wing}"] = (f"en003_{wing}", "otl2")
    t = evaluate(j, "AvSurface", "t", "sel_grp_saw", data)
    out = {"file": filename, "file_bytes": os.path.getsize(path),
           "file_mtime_utc": dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc).isoformat(),
           "dataset": data, "t_s": t, "series": {}, "area_m2": {}, "normal_up": {}}
    for key, (sel, scope) in selections.items():
        entry = {}
        for var in VARS:
            entry[var] = evaluate(j, "AvSurface", f"{scope}.{var}", sel, data)
        out["series"][key] = entry
        out["area_m2"][key] = evaluate(j, "IntSurface", "1", sel, data)[0]
        out["normal_up"][key] = [evaluate(j, "AvSurface", c, sel, data)[0] for c in ("nx", "ny", "nz")]
        log(case, key, "area", round(out["area_m2"][key], 2), "normal", np.round(out["normal_up"][key], 3).tolist())
    params = {}
    for name in ("S_sun", "albedo", "q_olr", "T_space"):
        try:
            params[name] = str(j.param().get(name))
        except Exception as exc:  # noqa: BLE001
            params[name] = f"(not readable: {exc})"
    out["params"] = params
    otl = {}
    for tag, scope in (("otl_saw", "otl4"), ("otl_hrs", "otl2")):
        ph = comp.physics(tag)
        info = {"scope": scope}
        rs = ph.prop("RadiationSettings")
        for name in ("radiationMethod", "radiationResolution", "viewFactorsUpdateTolerance",
                     "wavelengthDependenceOfSurfaceProperties"):
            info[name] = string_of(rs, name)
        plp = ph.feature("plp1")
        for name in ("nRings", "nPointsRing", "planetAlbedoEachBandSolAmb", "planetRadiativeFluxEachBandSolAmb"):
            info[name] = string_of(plp, name)
        try:
            info["planet_feature_all"] = {str(p): string_of(plp, str(p)) for p in plp.properties()}
        except Exception as exc:  # noqa: BLE001
            info["planet_feature_all"] = f"(not readable: {str(exc)[:80]})"
        try:
            info["orbit_feature_all"] = {str(p): string_of(ph.feature("op1"), str(p)) for p in ph.feature("op1").properties()}
        except Exception as exc:  # noqa: BLE001
            info["orbit_feature_all"] = f"(not readable: {str(exc)[:80]})"
        sup = ph.feature("sup1")
        for name in ("SV_ECS", "q0s_bandSolAmb"):
            info[name] = string_of(sup, name)
        for feat in ("sa1", "so1", "sa2", "so2"):
            try:
                f = ph.feature(feat)
            except Exception:
                continue
            for name in ("primaryAxis", "secondaryAxis", "primaryOrientation", "secondaryOrientation"):
                value = string_of(f, name)
                if not str(value).startswith("(not readable"):
                    info[f"{feat}.{name}"] = value
        op = ph.feature("op1")
        info["orbit_functions"] = [string_of(op, f"userDefinedFunction_{ax}_ECS") for ax in "XYZ"]
        otl[tag] = info
    out["otl"] = otl
    funcs = {}
    for name in ("rx", "ry", "rz"):
        try:
            funcs[name] = string_of(j.func(name), "expr")
        except Exception as exc:  # noqa: BLE001
            funcs[name] = f"(not readable: {exc})"
    out["orbit_functions"] = funcs
    log(case, "params", params, "planet", otl["otl_saw"]["nRings"], otl["otl_saw"]["nPointsRing"],
        "total", round(time.time() - t0, 1), "s")
    client.remove(model)
    return out


def main():
    started = time.time()
    client = mph.start(cores=4)
    result = {"tool": "fe_export.py", "mph": mph.__version__, "comsol": str(client.version),
              "exported_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "variables": {
                  "Gextu1": "up side, solar band external irradiation W/m^2",
                  "Gextu2": "up side, infrared band external irradiation W/m^2",
                  "Gextd1": "down side, solar band external irradiation W/m^2",
                  "Gextd2": "down side, infrared band external irradiation W/m^2"},
              "cases": {}}
    cases = sys.argv[1:] or list(FILES)
    for case in cases:
        result["cases"][case] = export_case(client, case, FILES[case])
        with open(os.path.join(HERE, "fe_loads.json"), "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=1)
    log("written fe_loads.json in", round(time.time() - started, 1), "s")


if __name__ == "__main__":
    main()
