"""FE-004 support code: whole-satellite COMSOL data, T5 derivation of J, C and R, FE orbit environment, statistics.

Nothing in this file imports the module under test (``thermal``) or ``sdtwin_sim``. Every value comes from the FE
model files of ``space-compute-demo/tools/comsol_benchmark/full_twin`` or from independent calculations:

* ``fe_constants`` reads the hot instant ``T0_HOT_S`` and the orbital period ``PERIOD_S`` from ``build_comsol.py``;
  ``load_geometry_spec`` imports ``geometry_spec.py`` (geometry, material, TIM and heat-pipe data of the FE model).
* ``mass_table`` sums masses of the FE solids by component from exact union volumes of the FE blocks (T5 first line).
* ``blade_conduction`` solves steady three-dimensional conduction in one blade with its GPU package on a structured
  finite-volume grid: heat enters through the package (or through the spine contact for the bus heat) and leaves at the
  heat-pipe bundle contact. It gives the conduction part of R_JC (T5 second line with an effective cross-section).
* ``heat_pipe_network`` evaluates the FE heat-pipe network (bundle, connector, header, spreaders) with T5 segment
  resistances l/(k_eff A) from the vendor resistance behind k_eff, plus the conduction in the radiator panel between
  the spreaders (a one-dimensional fin), and gives R_CR.
* ``FEOrbitEnvironment`` rebuilds the FE orbit, Sun and attitude from the OrbitWiz 1 s trace that COMSOL read:
  TEME vectors are rotated to GCRS with ``ntu_space_dynamics.transform_ephemeris`` (a rotation, not a relabelling),
  the body frame is +X along r x v, +Z nadir and +Y along the velocity like the FE (``sa1``/``so1``), and the eclipse is
  the shadow of the FE: parallel solar rays and an Earth sphere of the FE planet radius.
* ``earth_plate_factors`` integrates the Earth view factor and albedo factor of a plate over the visible spherical cap
  with an Earth-centred parametrisation, independent of ``sdtwin_sim.earth_flux`` which integrates over the satellite
  sky.
* ``window_mean`` gives the time-weighted mean of a sampled series over an orbit window.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from scipy.interpolate import CubicHermiteSpline
from scipy.spatial.transform import Rotation

AU_M = 1.495978707e11
SIGMA_W_M2_K4 = 5.670374419e-8
MINUS = "−"
JD_UNIX_EPOCH = 2440587.5


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_geometry_spec(path: Path) -> Any:
    """Import the FE geometry and material specification geometry_spec.py (pure data and geometry helpers)."""

    spec = importlib.util.spec_from_file_location("fe004_geometry_spec", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fe_constants(build_comsol_path: Path) -> dict[str, float]:
    """Hot instant and orbital period exactly as written in the FE build script."""

    text = Path(build_comsol_path).read_text(encoding="utf-8")
    t0 = re.search(r"^T0_HOT_S\s*=\s*([0-9.eE+-]+)", text, re.M)
    period = re.search(r"^PERIOD_S\s*=\s*([0-9.eE+-]+)", text, re.M)
    if not (t0 and period):
        raise ValueError(f"T0_HOT_S or PERIOD_S not found in {build_comsol_path}")
    return {"T0_HOT_S": float(t0.group(1)), "PERIOD_S": float(period.group(1))}


def read_csv_columns(path: Path, columns: list[str] | None = None) -> dict[str, np.ndarray]:
    with open(path, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    keys = columns or list(rows[0].keys())
    out: dict[str, np.ndarray] = {}
    for key in keys:
        values = []
        for row in rows:
            text = row[key]
            values.append(float(text) if text not in ("", None) else math.nan)
        out[key] = np.array(values, dtype=float)
    return out


TRACE_COLUMNS = [
    "t_s", "jd_utc", "heat_per_gpu_w", "heat_platform_w", "solar_flux_w_m2", "illum", "T_struct_c",
    "r_eci_x_km", "r_eci_y_km", "r_eci_z_km", "v_eci_x", "v_eci_y", "v_eci_z",
    "sun_eci_x", "sun_eci_y", "sun_eci_z", "sun_body_x", "sun_body_y", "sun_body_z", "gpu_count",
]


def read_trace(path: Path) -> dict[str, np.ndarray]:
    return read_csv_columns(path, TRACE_COLUMNS)


def jd_to_datetime(jd: float) -> datetime:
    """UTC datetime of a Julian date, rounded to the microsecond."""

    seconds = (float(jd) - JD_UNIX_EPOCH) * 86400.0
    whole = math.floor(seconds)
    micro = int(round((seconds - whole) * 1e6))
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=whole, microseconds=micro)


# ------------------------------------------------------------------------------------------------ FE geometry, T5 masses


def box_union_volume(boxes: list[tuple[list[float], list[float]]]) -> float:
    """Exact volume of a union of axis-aligned boxes (min corner, size) by coordinate compression."""

    if not boxes:
        return 0.0
    axes = []
    for k in range(3):
        cuts = sorted({b[0][k] for b in boxes} | {b[0][k] + b[1][k] for b in boxes})
        axes.append(np.array(cuts))
    centres = [0.5 * (a[1:] + a[:-1]) for a in axes]
    widths = [np.diff(a) for a in axes]
    X, Y, Z = np.meshgrid(*centres, indexing="ij")
    covered = np.zeros(X.shape, dtype=bool)
    for mn, size in boxes:
        covered |= ((X > mn[0]) & (X < mn[0] + size[0]) & (Y > mn[1]) & (Y < mn[1] + size[1])
                    & (Z > mn[2]) & (Z < mn[2] + size[2]))
    WX, WY, WZ = np.meshgrid(*widths, indexing="ij")
    return float(np.sum((WX * WY * WZ)[covered]))


def _box(item: dict) -> tuple[list[float], list[float]]:
    return [float(v) for v in item["min"]], [float(v) for v in item["size"]]


def hp_blocks(G: Any) -> tuple[list[dict], int]:
    """Heat-pipe blocks of the FE build: geometry_spec.heat_pipe_blocks(400 x 0.95), as called by build_comsol.py."""

    return G.heat_pipe_blocks(400 * 0.95)


def mass_table(G: Any) -> dict[str, Any]:
    """Masses of the FE solids grouped into the design components J, C and R (T5 first line inputs).

    Aluminium solids use the FE library density; radiator panels use the FE equivalent shell, whose mass equals the
    OrbitWiz areal density times the panel area; heat-pipe blocks use solid aluminium capacity like the FE.
    Overlapping FE blocks of one group are merged (COMSOL Form Union), so every volume is counted once.
    """

    rho, cp = G.AL["rho"], G.AL["cp"]
    blades = G.blades()
    pkg_boxes = [_box(p) for _, p in blades]
    blade_boxes = [_box(b) for b, _ in blades]
    bus_boxes = [_box(b) for b in G.BUS]
    blocks, n_tr = hp_blocks(G)
    transport = [_box(b) for b in blocks if b["name"].startswith(("HPtr", "HPcn"))]
    condenser = [_box(b) for b in blocks if b["name"].startswith(("HPhd", "HPsp"))]
    panels = [r for r in G.radiators() if not r.get("boom")]
    v_pkg = box_union_volume(pkg_boxes)
    v_blade = box_union_volume(blade_boxes)
    v_bus = box_union_volume(bus_boxes)
    v_cond = box_union_volume(condenser)
    v_all_hp = box_union_volume(transport + condenser)
    v_transport = v_all_hp - v_cond  # transport and connector part not already in the condenser group
    panel_area = [r["size"][0] * r["size"][2] for r in panels]
    m_panels = sum(a * G.RAD_AREAL_KG_M2 for a in panel_area)
    # The FE panel material is the equivalent shell: rho_eq x volume of the 20 mm model block.
    m_panels_shell = sum(G.RAD_SHELL["rho"] * r["size"][0] * r["size"][1] * r["size"][2] for r in panels)
    sum_bus_boxes = sum(s[0] * s[1] * s[2] for _, s in bus_boxes)
    return {
        "rho_kg_m3": rho, "cp_J_kgK": cp, "n_tr": n_tr,
        "packages": {"volume_m3": v_pkg, "mass_kg": v_pkg * rho, "count": len(pkg_boxes)},
        "blades": {"volume_m3": v_blade, "mass_kg": v_blade * rho, "count": len(blade_boxes)},
        "bus": {"volume_m3": v_bus, "mass_kg": v_bus * rho, "box_sum_volume_m3": sum_bus_boxes,
                "parts": [b["name"] for b in G.BUS]},
        "hp_transport": {"volume_m3": v_transport, "mass_kg": v_transport * rho, "blocks": len(transport)},
        "hp_condenser": {"volume_m3": v_cond, "mass_kg": v_cond * rho, "blocks": len(condenser)},
        "radiator_panels": {"mass_kg": m_panels, "mass_shell_kg": m_panels_shell, "areas_m2": panel_area,
                            "areal_kg_m2": G.RAD_AREAL_KG_M2},
    }


# ------------------------------------------------------------------------------------------------ blade conduction


def _axis(breaks: list[float], h: float) -> np.ndarray:
    edges = [breaks[0]]
    for a, b in zip(breaks[:-1], breaks[1:]):
        n = max(1, int(math.ceil((b - a) / h - 1e-9)))
        edges.extend(list(np.linspace(a, b, n + 1)[1:]))
    return np.array(edges)


def blade_conduction(G: Any, h: float, q_gpu: float, q_bus: float) -> dict[str, float]:
    """Steady conduction in one +Y blade with its package (finite volumes, cell size about ``h``).

    Geometry from geometry_spec: blade box extended to the spine face, package box on the blade top face, TIM sheet
    resistance between them, heat-pipe bundle contact on the +X face over the bundle width (temperature 0), bus heat
    entering through the part of the spine face that touches the blade. ``q_gpu`` W is generated uniformly in the
    package volume and ``q_bus`` W enters uniformly over the spine contact; all other faces are adiabatic. Returns the
    area-mean temperature of the blade side of the TIM face (the FE "GPU baseplate"), the package and blade volume
    means, all relative to the contact, the cell count and the contact heat flow.
    """

    k = float(G.AL["k"])
    b, p = G.blades()[0]
    x0, y0, z0 = b["min"]
    sx, sy, sz = b["size"]
    px0, py0, pz0 = p["min"]
    psx, psy, psz = p["size"]
    spine = G.BUS[0]
    spx0, spx1 = spine["min"][0], spine["min"][0] + spine["size"][0]
    w_tr = math.ceil(3 * 400 * 0.95 / G.HP_Q_MAX_W) * G.HP_SIDE
    cy0, cy1 = G.SLOT_Y - w_tr / 2, G.SLOT_Y + w_tr / 2
    xe = _axis(sorted({x0, px0, max(x0, spx0), px0 + psx, min(x0 + sx, spx1), x0 + sx}), h)
    ye = _axis(sorted({y0, py0, cy0, cy1, py0 + psy, y0 + sy}), h)
    ze = _axis([z0, pz0, pz0 + psz], h)
    xc, yc, zc = 0.5 * (xe[1:] + xe[:-1]), 0.5 * (ye[1:] + ye[:-1]), 0.5 * (ze[1:] + ze[:-1])
    dx, dy, dz = np.diff(xe), np.diff(ye), np.diff(ze)
    X, Y, Z = np.meshgrid(xc, yc, zc, indexing="ij")
    DX, DY, DZ = np.meshgrid(dx, dy, dz, indexing="ij")
    in_blade = Z < pz0
    in_pkg = (Z > pz0) & (X > px0) & (X < px0 + psx) & (Y > py0) & (Y < py0 + psy)
    solid = in_blade | in_pkg
    idx = -np.ones(X.shape, dtype=np.int64)
    n = int(solid.sum())
    idx[solid] = np.arange(n)
    rows, cols, vals = [], [], []
    for axis_id in range(3):
        lo = [slice(None)] * 3
        hi = [slice(None)] * 3
        lo[axis_id] = slice(None, -1)
        hi[axis_id] = slice(1, None)
        lo, hi = tuple(lo), tuple(hi)
        both = solid[lo] & solid[hi]
        i1, i2 = idx[lo][both], idx[hi][both]
        width = (DX, DY, DZ)[axis_id]
        area = (DY * DZ, DX * DZ, DX * DY)[axis_id][lo][both]
        resistance = 0.5 * width[lo][both] / k + 0.5 * width[hi][both] / k
        if axis_id == 2:
            tim = in_blade[lo][both] & in_pkg[hi][both]
            resistance = resistance + np.where(tim, G.TIM_R_M2K_W, 0.0)
        g = area / resistance
        rows += [i1, i2, i1, i2]
        cols += [i2, i1, i1, i2]
        vals += [-g, -g, g, g]
    contact = solid[-1] & (Y[-1] > cy0) & (Y[-1] < cy1) & in_blade[-1]
    ic = idx[-1][contact]
    gc = (DY * DZ)[-1][contact] / (0.5 * DX[-1][contact] / k)
    rows.append(ic)
    cols.append(ic)
    vals.append(gc)
    A = sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n))
    rhs = np.zeros(n)
    vol = DX * DY * DZ
    if q_gpu:
        rhs[idx[in_pkg]] += q_gpu * vol[in_pkg] / vol[in_pkg].sum()
    if q_bus:
        face = solid[:, 0, :] & (X[:, 0, :] > spx0) & (X[:, 0, :] < spx1) & in_blade[:, 0, :]
        area = (DX * DZ)[:, 0, :][face]
        rhs[idx[:, 0, :][face]] += q_bus * area / area.sum()
    M = sp.diags(1.0 / A.diagonal())
    T, info = spla.cg(A, rhs, M=M, rtol=1e-12, atol=0.0, maxiter=50000)
    if info != 0:
        raise RuntimeError(f"blade conduction CG did not converge (info={info})")
    grid = np.full(X.shape, np.nan)
    grid[solid] = T
    kz = int(np.searchsorted(zc, pz0) - 1)
    under = in_pkg[:, :, kz + 1]
    Tb, Tp = grid[:, :, kz][under], grid[:, :, kz + 1][under]
    a_face = (DX * DY)[:, :, kz][under]
    g_int = a_face / (0.5 * DZ[:, :, kz][under] / k + 0.5 * DZ[:, :, kz + 1][under] / k + G.TIM_R_M2K_W)
    flux = g_int * (Tp - Tb)
    face_blade = Tb + flux * 0.5 * DZ[:, :, kz][under] / (k * a_face)
    contact_flow = float(np.sum(gc * T[ic]))
    spine_face = solid[:, 0, :] & (X[:, 0, :] > spx0) & (X[:, 0, :] < spx1) & in_blade[:, 0, :]
    spine_area = (DX * DZ)[:, 0, :][spine_face]
    return {
        "h_m": h,
        "cells": n,
        "baseplate_K": float(np.sum(face_blade * a_face) / a_face.sum()),
        "package_K": float(np.sum(grid[in_pkg] * vol[in_pkg]) / vol[in_pkg].sum()),
        "blade_K": float(np.sum(grid[in_blade] * vol[in_blade]) / vol[in_blade].sum()),
        "spine_contact_K": float(np.sum(grid[:, 0, :][spine_face] * spine_area) / spine_area.sum()),
        "contact_flow_W": contact_flow,
        "conduction_length_m": float(x0 + sx - (px0 + psx / 2)),
        "contact_width_m": float(w_tr),
        "footprint_width_m": float(psy),
        "blade_thickness_m": float(sz),
    }


# ------------------------------------------------------------------------------------------------ heat-pipe network


def heat_pipe_network(G: Any) -> dict[str, Any]:
    """Equivalent resistance of the FE heat-pipe network from the blade contacts to the radiator panel mean.

    For each of the four networks (one per radiator face) the three blade contacts of one rack feed the transport
    bundle; the bundle leads to the connector, the connector to the header and the header to eight spreaders lying
    on the panel face. Every segment uses T5 l/(k_eff A) with the FE k_eff (vendor resistance per length) and the FE
    block cross-section. Distributed inputs and outputs use the exact mean of a linearly accumulating flow (length/3).
    The spreader to panel-mean step is the panel fin: in-plane conduction k t of the FE equivalent shell, uniform
    rejection from both faces, strip widths set by the spreader pitch and the panel edges. Each blade carries the same
    heat, so the mean contact temperature over the twelve blades is the mean of the four network responses to Q/4.
    """

    k = float(G.HP_K_EFF)
    blocks, n_tr = hp_blocks(G)
    by_name = {b["name"]: b for b in blocks}
    kt = float(G.RAD_SHELL["k"] * G.RAD_SHELL["t_model"])
    nets: dict[str, Any] = {}
    for rad, sgn in (("Top", +1), ("Bot", -1)):
        panel = next(r for r in G.radiators() if r["name"] == f"Radiator{rad}")
        px0, px1 = panel["min"][0], panel["min"][0] + panel["size"][0]
        zs = G.SLOT_Z["upper"] if sgn > 0 else G.SLOT_Z["lower"]
        for side_tag in ("p", "n"):
            net = f"{rad}_{side_tag}"
            tr, cn, hd = by_name[f"HPtr_{net}"], by_name[f"HPcn_{net}"], by_name[f"HPhd_{net}"]
            sps = [by_name[f"HPsp_{net}_{i + 1}"] for i in range(8)]
            a_tr = tr["size"][0] * tr["size"][1]
            z_end = tr["min"][2] + tr["size"][2] if sgn > 0 else tr["min"][2]
            dist = sorted(abs(z_end - z) for z in zs)  # nearest contact first
            q = 1.0 / 3.0  # per contact, per watt of network heat
            # temperature of each contact above the bundle end, flow accumulates towards the end
            seg_lengths = [dist[0]] + [dist[i] - dist[i - 1] for i in range(1, 3)]
            flows = [3 * q, 2 * q, 1 * q]
            rise, contact_rise = 0.0, []
            for length, flow in zip(seg_lengths, flows):
                rise += flow * length / (k * a_tr)
                contact_rise.append(rise)
            bundle_mean = float(np.mean(contact_rise))  # K per W of network heat
            # connector: input over the bundle end face (bundle width), flow along y to the header centre line
            yb0, yb1 = tr["min"][1], tr["min"][1] + tr["size"][1]
            yh = hd["min"][1] + hd["size"][1] / 2
            near = yb0 if abs(yb0 - yh) < abs(yb1 - yh) else yb1
            l_cn = abs(near - yh) + (yb1 - yb0) / 3.0
            a_cn = cn["size"][0] * cn["size"][2]
            r_cn = l_cn / (k * a_cn)
            # header + spreaders + fins: small resistor network, panel mean is the reference node
            a_hd = hd["size"][1] * hd["size"][2]
            x_c = cn["min"][0] + cn["size"][0] / 2
            xs = [s["min"][0] + s["size"][0] / 2 for s in sps]
            width = sps[0]["size"][0]
            l_sp = sps[0]["size"][2]
            a_sp = sps[0]["size"][0] * sps[0]["size"][1]
            r_sp = l_sp / (3.0 * k * a_sp)
            fins = []
            for i, x in enumerate(xs):
                # half the gap to the neighbouring spreader, or the whole overhang to the adiabatic panel edge
                if i == 0:
                    left = (x - width / 2) - px0
                else:
                    left = 0.5 * ((x - width / 2) - (xs[i - 1] + width / 2))
                if i == len(xs) - 1:
                    right = px1 - (x + width / 2)
                else:
                    right = 0.5 * ((xs[i + 1] - width / 2) - (x + width / 2))
                strip = left + width + right
                r_fin = 2.0 * (left**3 + right**3) / (3.0 * kt * strip**2 * l_sp)
                fins.append({"x_m": x, "left_m": left, "right_m": right, "strip_m": strip, "R_fin_K_W": r_fin})
            nodes = sorted(set(xs + [x_c]))
            index = {x: i for i, x in enumerate(nodes)}
            n = len(nodes)
            Gm = np.zeros((n, n))
            for a, b in zip(nodes[:-1], nodes[1:]):
                g = k * a_hd / (b - a)
                ia, ib = index[a], index[b]
                Gm[ia, ia] += g
                Gm[ib, ib] += g
                Gm[ia, ib] -= g
                Gm[ib, ia] -= g
            for x, fin in zip(xs, fins):
                Gm[index[x], index[x]] += 1.0 / (r_sp + fin["R_fin_K_W"])
            rhs = np.zeros(n)
            rhs[index[x_c]] = 1.0
            T = np.linalg.solve(Gm, rhs)
            r_header_spreaders = float(T[index[x_c]])  # K per W from the header junction to the panel mean
            split = [float(T[index[x]] / (r_sp + f["R_fin_K_W"])) for x, f in zip(xs, fins)]
            total = bundle_mean + r_cn + r_header_spreaders
            nets[net] = {
                "R_net_K_W": total,
                "bundle_mean_rise_K_W": bundle_mean,
                "bundle_area_m2": a_tr,
                "contact_distances_m": dist,
                "R_connector_K_W": r_cn,
                "connector_length_m": l_cn,
                "connector_area_m2": a_cn,
                "R_header_spreaders_fins_K_W": r_header_spreaders,
                "R_spreader_K_W": r_sp,
                "spreader_length_m": l_sp,
                "spreader_area_m2": a_sp,
                "fins": fins,
                "spreader_heat_split": split,
            }
    r_cr = float(np.mean([v["R_net_K_W"] for v in nets.values()]) / 4.0)
    return {"R_CR_K_W": r_cr, "k_eff_W_mK": k, "n_tr": n_tr, "panel_kt_W_K": kt, "networks": nets}


def radiator_face_coverage(G: Any) -> dict[str, float]:
    """Area of one radiator face covered by the surface-mounted header and spreaders (union of their footprints).

    The covered strips are interior boundaries of the FE geometry; their emission is in the FE probe emitted_rad_W
    (evaluated from T over the whole face selection), while the FE absorbed-flux probes evaluate the radiation
    variables, which exist on exterior boundaries only.
    """

    blocks, _ = hp_blocks(G)
    foot = []
    for b in blocks:
        if b["name"].startswith(("HPhd_Top_p", "HPsp_Top_p")):
            mn, size = _box(b)
            foot.append(([mn[0], 0.0, mn[2]], [size[0], 1.0, size[2]]))
    panel = next(r for r in G.radiators() if r["name"] == "RadiatorTop")
    face = panel["size"][0] * panel["size"][2]
    covered = box_union_volume(foot)
    return {"face_area_m2": face, "covered_m2": covered, "exposed_fraction": 1.0 - covered / face}


# ------------------------------------------------------------------------------------------------ FE energy budget


def fe_energy_budget(probes: dict[str, np.ndarray], lo: float, hi: float, exposed_fraction: float,
                     capacities_J_K: dict[str, float]) -> dict[str, float]:
    """Window-mean energy budget of the FE radiator faces and of the rest of the FE satellite (diagnostic only).

    Heat delivered by the heat pipes to the radiator = emitted by the four faces - absorbed environment on the four
    faces + storage of the radiator assembly. The FE absorbed-flux probes cover the exposed part of the faces, so they
    are divided by the exposed fraction for the whole face area. The rest of the source heat leaves through other FE
    surfaces (bus, blades, packages, heat-pipe block faces) or is stored in the bus, blades, packages and transport
    pipes (storage from the probe temperatures at the window ends; transport pipes take the mean of blades and
    radiator).
    """

    t = probes["t_s"]

    def at(key: str, moment: float) -> float:
        return float(np.interp(moment, t, probes[key]))

    span = hi - lo
    p_src = window_mean(t, probes["P_sources_W"], lo, hi)
    emitted = window_mean(t, probes["emitted_rad_W"], lo, hi)
    absorbed_probe = window_mean(t, probes["abs_solar_rad_faces_W"] + probes["abs_IR_rad_faces_W"], lo, hi)
    absorbed_full = absorbed_probe / exposed_fraction
    d_rad = at("rad_mean_K", hi) - at("rad_mean_K", lo)
    store_r = capacities_J_K["radiator"] * d_rad / span
    q_pipes = emitted - absorbed_full + store_r
    d_pipe = 0.5 * (at("blades_mean_K", hi) + at("rad_mean_K", hi)) - 0.5 * (at("blades_mean_K", lo) + at("rad_mean_K", lo))
    store_jc = (capacities_J_K["bus"] * (at("bus_mean_K", hi) - at("bus_mean_K", lo))
                + capacities_J_K["blades"] * (at("blades_mean_K", hi) - at("blades_mean_K", lo))
                + capacities_J_K["packages"] * (at("pkg_mean_K", hi) - at("pkg_mean_K", lo))
                + capacities_J_K["transport"] * d_pipe) / span
    q_other = p_src - q_pipes - store_jc
    base = window_mean(t, probes["baseplate_mean_K"], lo, hi)
    rad = window_mean(t, probes["rad_mean_K"], lo, hi)
    return {
        "P_sources_W": p_src, "emitted_faces_W": emitted, "absorbed_probe_W": absorbed_probe,
        "absorbed_faces_W": absorbed_full, "storage_radiator_W": store_r, "heat_to_radiator_W": q_pipes,
        "storage_bus_blades_pipes_W": store_jc, "heat_other_surfaces_W": q_other,
        "baseplate_minus_radiator_K": base - rad, "chain_resistance_K_W": (base - rad) / q_pipes,
    }


# ------------------------------------------------------------------------------------------------ FE orbit environment


class FEOrbitEnvironment:
    """Orbit, Sun, attitude and eclipse of the FE run, from the OrbitWiz 1 s trace that COMSOL read.

    ``tau`` is the FE time: trace time minus the hot instant ``t0``. TEME positions, velocities and Sun directions
    are rotated to GCRS with Orbit's ``transform_ephemeris``; positions use cubic Hermite interpolation with the
    velocities; the Sun direction is interpolated linearly and renormalised; the Earth-to-Sun vector has the length
    implied by the trace irradiance S = 1361 / d^2 at the mean of the run window.
    """

    def __init__(self, trace: dict[str, np.ndarray], t0_s: float, tau_lo: float, tau_hi: float,
                 earth_radius_m: float, solar_irradiance_W_m2: float, au_m: float = AU_M) -> None:
        from ntu_space_dynamics import Ephemeris, transform_ephemeris

        tau_all = trace["t_s"] - t0_s
        keep = (tau_all >= tau_lo - 5.0) & (tau_all <= tau_hi + 5.0)
        self.tau = tau_all[keep]
        jd = trace["jd_utc"][keep]
        self.epoch = jd_to_datetime(float(np.interp(0.0, tau_all, trace["jd_utc"])))
        times = tuple(jd_to_datetime(v) for v in jd)
        r_teme = np.column_stack([trace[f"r_eci_{c}_km"][keep] for c in "xyz"]) * 1e3
        v_teme = np.column_stack([trace[f"v_eci_{c}"][keep] for c in "xyz"]) * 1e3
        s_teme = np.column_stack([trace[f"sun_eci_{c}"][keep] for c in "xyz"])
        n = len(times)
        basis = []
        for e in np.eye(3):
            eph = Ephemeris(times, np.tile(e * 1e7, (n, 1)), np.zeros((n, 3)), "TEME")
            basis.append(transform_ephemeris(eph, "GCRS").positions_m / 1e7)
        rot = np.stack(basis, axis=2)  # rot[i] columns = GCRS images of the TEME basis vectors
        self.rotation_teme_to_gcrs = rot
        self.r = np.einsum("nij,nj->ni", rot, r_teme)
        self.v = np.einsum("nij,nj->ni", rot, v_teme)
        sun = np.einsum("nij,nj->ni", rot, s_teme)
        self.sun_hat = sun / np.linalg.norm(sun, axis=1, keepdims=True)
        self.sun_body_trace = np.column_stack([trace[f"sun_body_{c}"][keep] for c in "xyz"])
        self.r_teme, self.v_teme, self.s_teme = r_teme, v_teme, s_teme
        self.spline = CubicHermiteSpline(self.tau, self.r, self.v, axis=0)
        self.dspline = self.spline.derivative()
        self.earth_radius_m = float(earth_radius_m)
        self.S = float(solar_irradiance_W_m2)
        self.sun_distance_m = au_m * math.sqrt(1361.0 / self.S)
        self.tau_range = (float(self.tau[0]), float(self.tau[-1]))

    def position(self, tau: float) -> np.ndarray:
        return np.asarray(self.spline(tau), dtype=float)

    def velocity(self, tau: float) -> np.ndarray:
        return np.asarray(self.dspline(tau), dtype=float)

    def sun_unit(self, tau: float) -> np.ndarray:
        s = np.array([np.interp(tau, self.tau, self.sun_hat[:, c]) for c in range(3)])
        return s / np.linalg.norm(s)

    def sun_position(self, tau: float) -> np.ndarray:
        return self.sun_distance_m * self.sun_unit(tau)

    def body_axes(self, tau: float) -> np.ndarray:
        """Columns: body +X (r x v), +Y (velocity side, z x x) and +Z (nadir) in GCRS."""

        r, v = self.position(tau), self.velocity(tau)
        x = np.cross(r, v)
        x /= np.linalg.norm(x)
        z = -r / np.linalg.norm(r)
        y = np.cross(z, x)
        return np.column_stack([x, y, z])

    def quaternion(self, tau: float) -> np.ndarray:
        q = Rotation.from_matrix(self.body_axes(tau)).as_quat()
        return q / np.linalg.norm(q)

    def in_shadow(self, tau: float) -> bool:
        """FE eclipse: parallel solar rays, Earth sphere of the FE planet radius."""

        r = self.position(tau)
        s = self.sun_unit(tau)
        along = float(r @ s)
        if along >= 0.0:
            return False
        return float(np.linalg.norm(r - along * s)) < self.earth_radius_m

    def illumination(self, tau: float) -> float:
        return 0.0 if self.in_shadow(tau) else 1.0

    def irradiance(self, tau: float) -> float:
        return self.S * self.illumination(tau)

    def shadow_boundaries(self, step_s: float = 10.0) -> list[tuple[float, str]]:
        """Eclipse entries and exits on the trace range by scanning and bisection to 1e-6 s."""

        grid = np.arange(self.tau_range[0] + 1.0, self.tau_range[1] - 1.0, step_s)
        states = [self.in_shadow(t) for t in grid]
        out = []
        for i in range(1, len(grid)):
            if states[i] != states[i - 1]:
                a, b = grid[i - 1], grid[i]
                while b - a > 1e-6:
                    m = 0.5 * (a + b)
                    if self.in_shadow(m) == states[i - 1]:
                        a = m
                    else:
                        b = m
                out.append((0.5 * (a + b), "entry" if states[i] else "exit"))
        return out


# ------------------------------------------------------------------------------------------------ Earth flux reference


def earth_plate_factors(position_m: np.ndarray, normal: np.ndarray, sun_hat: np.ndarray, earth_radius_m: float,
                        n_psi: int = 400, n_phi: int = 720) -> tuple[float, float]:
    """Earth view factor and albedo factor of a plate, integrated over the visible cap from the Earth centre.

    Earth element at central angle psi from the sub-satellite point and azimuth phi; dA = R^2 sin(psi) dpsi dphi;
    F = sum cos(theta_plate) cos(theta_earth) dA / (pi d^2) with both cosines clipped at zero; the albedo factor adds
    max(0, cos solar zenith) of the element. Gauss-Legendre in psi, midpoint rule in phi.
    """

    r = np.asarray(position_m, dtype=float)
    rn = float(np.linalg.norm(r))
    up = r / rn
    helper = np.array([1.0, 0.0, 0.0]) if abs(up[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = np.cross(up, helper)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(up, e1)
    psi_max = math.acos(earth_radius_m / rn)
    xg, wg = np.polynomial.legendre.leggauss(n_psi)
    psi = 0.5 * psi_max * (xg + 1.0)
    wpsi = 0.5 * psi_max * wg
    phi = (np.arange(n_phi) + 0.5) * 2.0 * math.pi / n_phi
    dphi = 2.0 * math.pi / n_phi
    P, PH = np.meshgrid(psi, phi, indexing="ij")
    W = np.outer(wpsi, np.full(n_phi, dphi))
    nrm = (np.cos(P)[..., None] * up + (np.sin(P) * np.cos(PH))[..., None] * e1
           + (np.sin(P) * np.sin(PH))[..., None] * e2)
    point = earth_radius_m * nrm
    d = r - point
    dist = np.linalg.norm(d, axis=-1)
    u = d / dist[..., None]
    cos_e = np.clip(np.einsum("ijk,ijk->ij", nrm, u), 0.0, None)
    cos_p = np.clip(-(u @ np.asarray(normal, dtype=float)), 0.0, None)
    dA = earth_radius_m**2 * np.sin(P) * W
    kernel = cos_p * cos_e * dA / (math.pi * dist**2)
    zen = np.clip(nrm @ np.asarray(sun_hat, dtype=float), 0.0, None)
    return float(kernel.sum()), float((kernel * zen).sum())


# ------------------------------------------------------------------------------------------------ statistics


def window_mean(t: np.ndarray, x: np.ndarray, lo: float, hi: float) -> float:
    """Time-weighted mean of samples (t, x) over [lo, hi]; the window edges are linearly interpolated."""

    t = np.asarray(t, dtype=float)
    x = np.asarray(x, dtype=float)
    inside = (t > lo) & (t < hi)
    tt = np.concatenate([[lo], t[inside], [hi]])
    xx = np.concatenate([[np.interp(lo, t, x)], x[inside], [np.interp(hi, t, x)]])
    order = np.argsort(tt, kind="stable")
    tt, xx = tt[order], xx[order]
    return float(np.trapezoid(xx, tt) / (hi - lo))


def sample_mean(t: np.ndarray, x: np.ndarray, lo: float, hi: float) -> float:
    """Plain mean of the samples with lo <= t <= hi (the statistic of the FE report)."""

    w = (np.asarray(t) >= lo) & (np.asarray(t) <= hi)
    return float(np.nanmean(np.asarray(x)[w]))


def cn_number(value: float, digits: int = 1) -> str:
    """Number for the Chinese summary, with the U+2212 minus sign."""

    text = f"{value:.{digits}f}"
    if text.startswith("-"):
        text = MINUS + text[1:]
    if text in (MINUS + "0." + "0" * digits, MINUS + "0"):
        text = text[1:]
    return text
