# -*- coding: utf-8 -*-
"""Export STK 11 truth data for the orbit/power/thermal benchmark.

Run with the system Python (needs pywin32 + a one-time
`python -m win32com.client.makepy "AGI STK Objects 11"`).

Outputs CSVs under out/stk/ — schema documented in PLAN.md §3.
"""

import csv
import json
import os
import sys
import traceback

from win32com.client import CastTo, gencache

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cases  # noqa: E402


def cast(obj, name):
    for candidate in (name, "_" + name):
        try:
            return CastTo(obj, candidate)
        except Exception:
            continue
    raise RuntimeError("cannot cast to %s" % name)


def exec_timevar(dp_raw, t0, t1, step):
    """Run a time-var provider, return {element_name: [values...]} merged over
    result intervals (some providers section their output per interval)."""
    dp = cast(dp_raw, "IAgDataPrvTimeVar")
    res = dp.Exec(t0, t1, step)
    merged = {}
    blocks = []
    try:
        n = res.Intervals.Count
    except Exception:
        n = 0
    if n:
        for i in range(n):
            blocks.append(res.Intervals.Item(i).DataSets)
    else:
        blocks.append(res.DataSets)
    for ds in blocks:
        names = list(ds.ElementNames)
        for j in range(ds.Count):
            name = names[j] if j < len(names) else str(j)
            merged.setdefault(name, []).extend(list(ds.Item(j).GetValues()))
    return merged


def exec_interval(dp_raw, t0, t1):
    dp = cast(dp_raw, "IAgDataPrvInterval")
    res = dp.Exec(t0, t1)
    ds = res.DataSets
    names = list(ds.ElementNames)
    out = {}
    for j in range(ds.Count):
        name = names[j] if j < len(names) else str(j)
        out.setdefault(name, []).extend(list(ds.Item(j).GetValues()))
    return out


def grouped(obj, provider, group):
    dp = cast(obj.DataProviders.Item(provider), "IAgDataProviderGroup")
    return dp.Group.Item(group)


def write_csv(path, header, columns):
    """columns: list of lists, one per header entry, equal length."""
    n = min(len(c) for c in columns) if columns else 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for i in range(n):
            w.writerow([c[i] for c in columns])


def main():
    os.makedirs(cases.STK_OUT, exist_ok=True)
    gencache.EnsureDispatch("STKX11.Application")
    root = gencache.EnsureDispatch("AgStkObjects11.AgStkObjectRoot")
    try:
        root.CloseScenario()
    except Exception:
        pass
    root.NewScenario("Benchmark")
    sc = root.CurrentScenario
    sc2 = cast(sc, "IAgScenario")
    sc2.SetTimePeriod(cases.EPOCH_UTCG, cases.STOP_UTCG)
    root.Rewind()

    manifest = {
        "epoch_utcg": cases.EPOCH_UTCG,
        "duration_s": cases.DURATION_S,
        "step_s": cases.STEP_S,
        "stk_version": "11.6.0",
        "seet": {},
        "cases": {},
    }

    # facilities: one per elevation mask
    fac_by_mask = {}
    for mask in cases.ELEVATION_MASKS_DEG:
        name = "SG%02d" % int(mask)
        fac = sc.Children.New(8, name)  # eFacility
        root.ExecuteCommand(
            "SetPosition */Facility/%s Geodetic %.6f %.6f %.1f"
            % (name, cases.GS_LAT_DEG, cases.GS_LON_DEG, cases.GS_ALT_M))
        root.ExecuteCommand(
            "SetConstraint */Facility/%s ElevationAngle Min %.1f" % (name, mask))
        fac_by_mask[mask] = fac

    sats = {}
    for cname, cfg in cases.TLE_CASES.items():
        sat_name = "S_" + cname
        sat = sc.Children.New(18, sat_name)  # eSatellite
        l1 = cases.fix_checksum(cfg["line1"])
        l2 = cases.fix_checksum(cfg["line2"])
        root.ExecuteCommand(
            'SetState */Satellite/%s TLE "%s" "%s" TimePeriod "%s" "%s"'
            % (sat_name, l1, l2, cases.EPOCH_UTCG, cases.STOP_UTCG))
        # SEET isothermal-sphere thermal model, parameters mirrored in ours_ref
        seet_cmd = (
            "SEET */Satellite/%s VehTemperature EarthAlbedo %.2f "
            "MaterialEmissivity %.2f MaterialAbsorptivity %.2f "
            "Dissipation %.1f CrossSectionalArea %.1f ShapeModel %s"
            % (sat_name, cases.THERM_EARTH_ALBEDO, cases.THERM_EMISSIVITY,
               cases.THERM_ABSORPTIVITY, cases.THERM_DISSIPATION_W,
               cases.THERM_CROSS_SECTION_M2, cases.THERM_SHAPE))
        try:
            root.ExecuteCommand(seet_cmd)
            manifest["seet"][cname] = "configured"
        except Exception as exc:
            manifest["seet"][cname] = "config FAILED: %s" % exc
        sats[cname] = sat

    # units for extraction
    up = root.UnitPreferences
    up.SetCurrentUnit("DateFormat", "EpSec")
    up.SetCurrentUnit("Distance", "km")
    up.SetCurrentUnit("Time", "sec")
    up.SetCurrentUnit("Angle", "deg")
    up.SetCurrentUnit("Temperature", "K")

    t0, t1, step = 0.0, cases.DURATION_S, cases.STEP_S

    for cname, cfg in cases.TLE_CASES.items():
        sat = sats[cname]
        print("[case %s] exporting..." % cname)
        case_info = {}

        pos = exec_timevar(grouped(sat, "Cartesian Position", "TEMEOfDate"),
                           t0, t1, step)
        vel = exec_timevar(grouped(sat, "Cartesian Velocity", "TEMEOfDate"),
                           t0, t1, step)
        lla = exec_timevar(grouped(sat, "LLA State", "Fixed"), t0, t1, step)
        write_csv(
            os.path.join(cases.STK_OUT, "ephem_%s.csv" % cname),
            ["t", "x_km", "y_km", "z_km", "vx_kms", "vy_kms", "vz_kms",
             "lat_deg", "lon_deg", "alt_km", "lat_centric_deg"],
            [pos["Time"], pos["x"], pos["y"], pos["z"],
             vel["x"], vel["y"], vel["z"],
             lla["Lat"], lla["Lon"], lla["Alt"], lla["Centric Lat"]])

        sun = exec_timevar(grouped(sat, "Sun Vector", "TEMEOfDate"), t0, t1, step)
        beta = exec_timevar(sat.DataProviders.Item("Beta Angle"), t0, t1, step)
        write_csv(
            os.path.join(cases.STK_OUT, "sun_%s.csv" % cname),
            ["t", "sun_x_km", "sun_y_km", "sun_z_km", "beta_deg"],
            [sun["Time"], sun["x"], sun["y"], sun["z"], beta["Beta Angle"]])

        light_rows = []
        light_dp = cast(sat.DataProviders.Item("Lighting Times"),
                        "IAgDataProviderGroup")
        for kind in ("Sunlight", "Penumbra", "Umbra"):
            try:
                data = exec_interval(light_dp.Group.Item(kind), t0, t1)
            except Exception:
                continue
            for s, e in zip(data.get("Start Time", []), data.get("Stop Time", [])):
                light_rows.append((kind, s, e))
        with open(os.path.join(cases.STK_OUT, "lighting_%s.csv" % cname),
                  "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["kind", "start", "stop"])
            w.writerows(light_rows)

        inten = exec_timevar(sat.DataProviders.Item("Solar Intensity"),
                             t0, t1, step)
        write_csv(
            os.path.join(cases.STK_OUT, "intensity_%s.csv" % cname),
            ["t", "intensity_pct", "percent_shadow"],
            [inten["Time"], inten["Intensity"], inten["Percent Shadow"]])

        try:
            seet = exec_timevar(sat.DataProviders.Item("SEET Vehicle Temperature"),
                                t0, t1, step)
            write_csv(
                os.path.join(cases.STK_OUT, "seet_%s.csv" % cname),
                ["t", "temp_k", "solar_flux_w_m2", "seet_intensity"],
                [seet["Time"], seet["Temperature"], seet["Solar Flux"],
                 seet["Solar Intensity"]])
            case_info["seet"] = "ok"
        except Exception:
            case_info["seet"] = "export FAILED"
            traceback.print_exc()

        if cfg["access"]:
            for mask in cases.ELEVATION_MASKS_DEG:
                fac = fac_by_mask[mask]
                access = sat.GetAccessToObject(fac)
                access.ComputeAccess()
                acc = exec_interval(access.DataProviders.Item("Access Data"),
                                    t0, t1)
                write_csv(
                    os.path.join(cases.STK_OUT,
                                 "access_%s_m%02d.csv" % (cname, int(mask))),
                    ["start", "stop"],
                    [acc.get("Start Time", []), acc.get("Stop Time", [])])
                if mask == 0.0:
                    # AER during horizon-visible passes only (sectioned result)
                    try:
                        aer = exec_timevar(
                            grouped(access, "AER Data", "Default"), t0, t1, step)
                    except Exception:
                        aer = exec_timevar(access.DataProviders.Item("AER Data"),
                                           t0, t1, step)
                    write_csv(
                        os.path.join(cases.STK_OUT, "aer_%s.csv" % cname),
                        ["t", "az_deg", "el_deg", "range_km"],
                        [aer["Time"], aer["Azimuth"], aer["Elevation"],
                         aer["Range"]])
        manifest["cases"][cname] = case_info

    with open(os.path.join(cases.STK_OUT, "manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    root.CloseScenario()
    print("STK export DONE ->", cases.STK_OUT)


if __name__ == "__main__":
    main()
