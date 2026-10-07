# -*- coding: utf-8 -*-
"""EN-003 step 3 reference verification: FE thermal loads at successively finer planet discretisations.

fe_refine_ladder.py re-solves only the orbital thermal loads of the solved ISS models with the planet discretised
into 2 x 6, 4 x 12 and 8 x 24 points (rings x points per ring) at 16 common instants from 10920 to 16320 s and writes
fe_loads_ladder_<case>.json. This helper turns the irradiation of each level into the absorbed thermal loads of the
test (area x absorptivity or emissivity x irradiation, summed over the two faces), takes the module loads from
earth_flux at the same instants, checks that the 2 x 6 level reproduces the production export, and estimates the
conditional Richardson estimates of the arithmetic sample mean and sample peak. These samples do not cover
the exact last-orbit window. Three levels alone do not establish convergence or temperature-solver accuracy.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

LADDER_TLIST = "range(10920,360,16560)"
LEVELS = ("2x6", "4x12", "8x24")
SAMPLE_TIMES = np.arange(10920.0, 16320.0 + 1.0, 360.0)
LOADS = (("太阳翼", "solar_array", (("saw_cells", "SAW_cells"), ("saw_back", "SAW_back"))),
         ("散热器", "radiator", (("radiator_up", "HRS_up"), ("radiator_down", "HRS_down"))))
BANDS = (("反照", "albedo"), ("红外", "infrared"))
LABEL_EN = {"太阳翼反照": "Solar array albedo", "太阳翼红外": "Solar array infrared",
            "散热器反照": "Radiator albedo", "散热器红外": "Radiator infrared"}


def richardson(m2: float, m4: float, m8: float) -> dict:
    """Conditional estimate from three levels refined by two in rings and in points per ring.

    With monotone convergence (successive changes of one sign and shrinking) the estimate is
    m8 + d2 * r / (1 - r) with r = d2 / d1; otherwise the finest level is used and the case is flagged.
    """
    d1, d2 = m4 - m2, m8 - m4
    if d1 != 0.0 and d2 * d1 > 0.0 and abs(d2) < abs(d1):
        r = d2 / d1
        return {"value": m8 + d2 * r / (1.0 - r), "ratio": r, "order": math.log2(1.0 / r), "monotone": True}
    return {"value": m8, "ratio": (d2 / d1) if d1 else None, "order": None, "monotone": False}


def select_common_samples(entry: dict) -> dict:
    """Select requested output instants; preserve raw eclipse-event samples in the export.

    COMSOL inserts paired pre/post-eclipse instants in beta-zero cases. Including
    those extra points would give different arithmetic weights between cases.
    Match actual output times rather than interpolate across the discontinuity.
    """
    raw_t = np.asarray(entry['t_s'], dtype=float)
    if raw_t.ndim != 1 or not np.all(np.isfinite(raw_t)):
        raise ValueError('Invalid COMSOL output times')
    indices = []
    for target in SAMPLE_TIMES:
        match = np.flatnonzero(np.isclose(raw_t, target, atol=1e-6, rtol=0.0))
        if len(match) != 1:
            raise ValueError(f'Expected one output at {target:g} s, found {len(match)}')
        indices.append(int(match[0]))
    chosen = set(indices)
    sampled = dict(entry)
    sampled['raw_sample_count'] = len(raw_t)
    sampled['excluded_event_times_s'] = [float(t) for i, t in enumerate(raw_t) if i not in chosen]
    sampled['t_s'] = raw_t[indices].tolist()
    sampled['series'] = {}
    for group, variables in entry['series'].items():
        sampled['series'][group] = {}
        for variable, values in variables.items():
            if len(values) != len(raw_t) or not np.all(np.isfinite(values)):
                raise ValueError(f'Invalid {group}/{variable} output series')
            sampled['series'][group][variable] = [values[i] for i in indices]
    return sampled


def load_ladder(data_dir: Path, case: str) -> dict | None:
    path = data_dir / f"fe_loads_ladder_{case}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for level in LEVELS:
        entry = data.get("levels", {}).get(f"{level}@{LADDER_TLIST}")
        if entry and "series" in entry:
            out[level] = select_common_samples(entry)
    # 4 x 12 and 8 x 24 must come from the ladder; 2 x 6 may be taken from the production export at the same instants
    return out if all(level in out for level in LEVELS[1:]) else None


def compare_case(case: str, env: dict, run: dict, fe_case: dict, ladder: dict, face_series, faces_from_series) -> dict:
    """Loads of the module, the production export and the three ladder levels at the ladder instants."""
    t = np.array(ladder[LEVELS[-1]]["t_s"], dtype=float)
    for level in ladder:
        if not np.allclose(np.array(ladder[level]["t_s"], dtype=float), t, atol=1e-6, rtol=0.0):
            raise ValueError(f"{case}: ladder levels use different instants")
    S = env["S"]
    production = face_series(fe_case, t, S)
    levels = {lv: faces_from_series(ladder[lv]["series"], S) for lv in LEVELS if lv in ladder}
    source_2x6 = "ladder" if "2x6" in ladder else "production export"
    if "2x6" not in levels:
        levels["2x6"] = production
    surf = {s.surface_id: s for s in run["params"].surfaces}
    ids = [s.surface_id for s in run["params"].surfaces]
    providers = {"太阳翼": run["runs"]["saw"]["provider"], "散热器": run["runs"]["hrs"]["provider"]}
    out = {"time_s": t.tolist(), "level_2x6_source": source_2x6,
           "sampling": {level: {'raw_sample_count': entry['raw_sample_count'],
                                'excluded_event_times_s': entry['excluded_event_times_s']}
                        for level, entry in ladder.items()}, "loads": {}}
    for comp, tag, faces in LOADS:
        samples = [providers[comp].sample(float(x)) for x in t]
        for band, key in BANDS:
            name = f"{comp}{band}"
            mod = np.zeros(t.size)
            prod = np.zeros(t.size)
            lv = {level: np.zeros(t.size) for level in LEVELS}
            for face, sid in faces:
                coef = surf[sid].absorptivity if key == "albedo" else surf[sid].emissivity
                area = surf[sid].area_m2
                idx = ids.index(sid)
                mod += area * coef * np.array([float(smp.earth_flux[f"{key}_W_m2"][idx]) for smp in samples])
                prod += area * coef * production[f"{face}_{key}"]
                for level in LEVELS:
                    lv[level] += area * coef * levels[level][f"{face}_{key}"]
            means = {level: float(np.mean(lv[level])) for level in LEVELS}
            peaks = {level: float(np.max(lv[level])) for level in LEVELS}
            conv_mean = richardson(*(means[level] for level in LEVELS))
            conv_peak = richardson(*(peaks[level] for level in LEVELS))
            m_mod, p_mod = float(np.mean(mod)), float(np.max(mod))
            big = lv[LEVELS[-1]] >= 0.1 * peaks[LEVELS[-1]]
            inst = (float(np.max(np.abs(mod[big] - lv[LEVELS[-1]][big]) / lv[LEVELS[-1]][big]))
                    if big.any() else float("nan"))
            out["loads"][name] = {
                "label_en": LABEL_EN[name],
                "module_mean_W": m_mod, "module_peak_W": p_mod,
                "production_mean_W": float(np.mean(prod)), "production_peak_W": float(np.max(prod)),
                "ladder_2x6_vs_production_max_rel": float(np.max(np.abs(lv["2x6"] - prod) / np.maximum(np.abs(prod), 1.0))),
                "fe_mean_W": means, "fe_peak_W": peaks,
                "fe_converged_mean_W": conv_mean, "fe_converged_peak_W": conv_peak,
                "finest_vs_converged_mean_rel": (means[LEVELS[-1]] - conv_mean["value"]) / conv_mean["value"],
                "finest_vs_converged_peak_rel": (peaks[LEVELS[-1]] - conv_peak["value"]) / conv_peak["value"],
                "production_vs_converged_mean_rel": (float(np.mean(prod)) - conv_mean["value"]) / conv_mean["value"],
                "module_vs_converged_mean_rel": (m_mod - conv_mean["value"]) / conv_mean["value"],
                "module_vs_converged_peak_rel": (p_mod - conv_peak["value"]) / conv_peak["value"],
                "module_vs_finest_mean_rel": (m_mod - means[LEVELS[-1]]) / means[LEVELS[-1]],
                "module_vs_finest_peak_rel": (p_mod - peaks[LEVELS[-1]]) / peaks[LEVELS[-1]],
                "module_vs_production_mean_rel": (m_mod - float(np.mean(prod))) / float(np.mean(prod)),
                "module_vs_finest_pointwise_max_rel_above_10pct_peak": inst,
                "series_W": {"module": mod.tolist(), "production": prod.tolist(),
                             **{level: lv[level].tolist() for level in LEVELS}},
            }
    return out
