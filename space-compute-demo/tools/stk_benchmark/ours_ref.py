# -*- coding: utf-8 -*-
"""Export OUR engine's orbit/power/thermal outputs on the benchmark timeline.

Run with the backend venv interpreter:
    space-compute-demo\\backend\\.venv\\Scripts\\python.exe ours_ref.py

Calls the real backend modules (services.orbit_catalog / constellations /
geodyn) and mirrors state_engine.py's short inline formulas verbatim, driven
at scaled-time = real seconds since the DEMO epoch (the engine multiplies
sim time by TIME_SCALE=60; we feed sim_t = t/60 so both sides share one
absolute timeline).
"""

import csv
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(HERE, "..", "..", "backend"))
sys.path.insert(0, HERE)
sys.path.insert(0, BACKEND)

import cases  # noqa: E402
from sgp4.api import Satrec  # noqa: E402
from services import orbit_catalog as oc  # noqa: E402
from services import constellations as cs  # noqa: E402
from services import geodyn  # noqa: E402

SIGMA = 5.67e-8


def sgp4_rv(satrec, t_s):
    """TEME position/velocity at DEMO epoch + t_s (mirrors oc._propagate_eci)."""
    e, r, v = satrec.sgp4(oc.DEMO_JD0, oc.DEMO_FR0 + t_s / 86400.0)
    if e:
        return None, None
    return r, v


def sun_state(t_s):
    """Real sun at the absolute epoch: (vector km, unit, S_eff W/m²)."""
    jd = oc.DEMO_JD0 + oc.DEMO_FR0 + t_s / 86400.0
    sun_km, r_au = geodyn.sun_teme(jd)
    n = math.sqrt(sum(c * c for c in sun_km)) or 1.0
    unit = (sun_km[0] / n, sun_km[1] / n, sun_km[2] / n)
    return sun_km, unit, geodyn.SOLAR_CONSTANT_W_M2 / (r_au * r_au)


def thermal_env_w(r_km, s_eff, illum, cos_zen):
    """Mirror of state_engine._thermal_env_in_w for the benchmark sphere."""
    area = cases.THERM_RADIATING_AREA_M2
    f = geodyn.earth_view_factor(max(r_km, geodyn.R_EARTH_THERMAL_KM))
    q_sun = cases.THERM_ABSORPTIVITY * s_eff * illum * (area / 4.0)
    q_alb = (cases.THERM_ABSORPTIVITY * geodyn.EARTH_ALBEDO * s_eff * area
             * f * max(0.0, cos_zen))
    q_ir = cases.THERM_EMISSIVITY * geodyn.EARTH_IR_W_M2 * area * f
    return q_sun + q_alb + q_ir


def intervals_from_flags(ts, flags):
    out, start = [], None
    for t, f in zip(ts, flags):
        if f and start is None:
            start = t
        elif not f and start is not None:
            out.append((start, t))
            start = None
    if start is not None:
        out.append((start, ts[-1]))
    return out


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main():
    os.makedirs(cases.OURS_OUT, exist_ok=True)
    n_coarse = int(cases.DURATION_S / cases.STEP_S) + 1
    coarse_ts = [i * cases.STEP_S for i in range(n_coarse)]

    manifest = {
        "epoch_iso": cases.EPOCH_ISO,
        "time_scale_note": "driven at scaled seconds (engine sim_t x 60)",
        "physics": "geodyn v2 (real sun, conical eclipse, WGS84, env thermal)",
        "cases": list(cases.TLE_CASES),
    }

    for cname, cfg in cases.TLE_CASES.items():
        print("[case %s] exporting..." % cname)
        satrec = Satrec.twoline2rv(cfg["line1"], cfg["line2"])

        ephem_rows, sun_rows, inten_rows, power_rows, therm_rows = [], [], [], [], []
        for t in coarse_ts:
            r, v = sgp4_rv(satrec, t)
            if r is None:
                continue
            x, y, z = r
            lat, lon, alt = oc.eci_to_lat_lon_alt(x, y, z, t / oc.TIME_SCALE)
            ephem_rows.append([t, x, y, z, v[0], v[1], v[2], lat, lon, alt])

            sun_km, su, s_eff = sun_state(t)
            nx = y * v[2] - z * v[1]
            ny = z * v[0] - x * v[2]
            nz = x * v[1] - y * v[0]
            nn = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            beta = math.degrees(math.asin(max(-1.0, min(1.0,
                (nx * su[0] + ny * su[1] + nz * su[2]) / nn))))
            sun_rows.append([t, su[0], su[1], su[2], beta])

            # state_engine._set_tracked_kinematics: conical illum + bool
            illum = geodyn.sun_visible_fraction(r, sun_km)
            rn = math.sqrt(x * x + y * y + z * z) or 1.0
            cos_a = (x * su[0] + y * su[1] + z * su[2]) / rn
            sunlit = illum >= 0.5
            inten_rows.append([t, 1 if sunlit else 0, illum])

            # state_engine solar input: η·A·S_eff·incidence·illum (frac=1)
            base = cases.SOLAR_EFFICIENCY * cases.SOLAR_AREA_M2 * s_eff
            inc_sun = 1.0 if sunlit else 0.0
            inc_nadir = max(0.0, cos_a) if sunlit else 0.0
            power_rows.append([t, base * inc_sun * illum,
                               base * inc_nadir * illum, inc_nadir])

            # thermal equilibrium of the benchmark sphere (engine formulas)
            q_in = cases.THERM_DISSIPATION_W + thermal_env_w(
                rn, s_eff, illum, cos_a)
            t_eq = (q_in / (cases.THERM_EMISSIVITY * SIGMA
                            * cases.THERM_RADIATING_AREA_M2)) ** 0.25
            therm_rows.append([t, t_eq])

        out = cases.OURS_OUT
        write_csv(os.path.join(out, "ephem_%s.csv" % cname),
                  ["t", "x_km", "y_km", "z_km", "vx_kms", "vy_kms", "vz_kms",
                   "lat_deg", "lon_deg", "alt_km"], ephem_rows)
        write_csv(os.path.join(out, "sun_%s.csv" % cname),
                  ["t", "sun_ux", "sun_uy", "sun_uz", "beta_deg"], sun_rows)
        write_csv(os.path.join(out, "intensity_%s.csv" % cname),
                  ["t", "sunlit", "illum"], inten_rows)
        write_csv(os.path.join(out, "power_%s.csv" % cname),
                  ["t", "p_sun_w", "p_nadir_w", "incidence_nadir"], power_rows)
        write_csv(os.path.join(out, "thermal_%s.csv" % cname),
                  ["t", "temp_k"], therm_rows)

        # fine 1 s pass: eclipse intervals + access windows (event edges)
        n_fine = int(cases.DURATION_S / cases.EVENT_STEP_S) + 1
        fine_ts, dark_flags = [], []
        elev_series = []
        vis_flags = {m: [] for m in cases.ELEVATION_MASKS_DEG}
        for i in range(n_fine):
            t = i * cases.EVENT_STEP_S
            r, _v = sgp4_rv(satrec, t)
            if r is None:
                continue
            x, y, z = r
            fine_ts.append(t)
            sun_km, _su, _s = sun_state(t)
            dark_flags.append(geodyn.sun_visible_fraction(r, sun_km) < 0.5)
            if cfg["access"]:
                lat, lon, alt = oc.eci_to_lat_lon_alt(x, y, z, t / oc.TIME_SCALE)
                el = cs.elevation_deg(lat, lon, alt,
                                      cases.GS_LAT_DEG, cases.GS_LON_DEG)
                if t % cases.STEP_S == 0:
                    elev_series.append([t, el])
                for m in cases.ELEVATION_MASKS_DEG:
                    vis_flags[m].append(el >= m)

        write_csv(os.path.join(out, "lighting_%s.csv" % cname),
                  ["kind", "start", "stop"],
                  [("dark", s, e) for s, e in
                   intervals_from_flags(fine_ts, dark_flags)])
        if cfg["access"]:
            write_csv(os.path.join(out, "elev_%s.csv" % cname),
                      ["t", "el_deg"], elev_series)
            for m in cases.ELEVATION_MASKS_DEG:
                write_csv(os.path.join(out, "access_%s_m%02d.csv" % (cname, int(m))),
                          ["start", "stop"],
                          intervals_from_flags(fine_ts, vis_flags[m]))

    with open(os.path.join(cases.OURS_OUT, "manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print("OURS export DONE ->", cases.OURS_OUT)


if __name__ == "__main__":
    main()
