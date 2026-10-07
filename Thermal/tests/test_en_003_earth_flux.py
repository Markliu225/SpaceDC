"""EN-003 地球反照与红外输入: the earth_flux environment input of design 4.4 table 5, 5.3 and 9.4.

Steps of the test report case (CASES['EN-003'] of test_report/build_test_report_cn.py):
1. nadir plate view factor of the module against the analytic value (R/r)^2 at 400 km;
2. albedo and infrared irradiance of the other orientations (and the nadir albedo) against a numerical integration over
   the visible Earth surface, beta 0 and 75 deg, the three ISS environment value sets;
3. the albedo and infrared thermal loads of the ISS US solar array and EATCS radiator exported from the solved COMSOL
   models (tests/data/en_003/fe_export.py, run outside pytest) against earth_flux, through the coupled runner;
4. a deleted albedo or infrared record must be reported as an unconfigured field and never be taken as zero.

References are independent of the module: tests/data/en_003/earth_reference.py (analytic plate-to-sphere view factor,
geocentric surface quadrature, Monte Carlo) and the finite-element results.
"""
from __future__ import annotations

import importlib.util
import json
import math
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from sdtwin_sim import coupled as cp
from sdtwin_sim import earth_flux as ef
from thermal import (
    ThermalInputError,
    ThermalState,
    assemble_thermal_parameters,
    calculate_surface_heat,
    prepare_surface_environment,
)

pytestmark = pytest.mark.case("EN-003")

TESTS = Path(__file__).resolve().parent
DATA = TESTS / "data" / "en_003"
RESULTS = TESTS / "results"
ISS = TESTS.parent / "iss_fem"

_spec = importlib.util.spec_from_file_location("en003_earth_reference", DATA / "earth_reference.py")
ref = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ref)
_spec2 = importlib.util.spec_from_file_location("en003_iss_spec", ISS / "model" / "iss_spec.py")
iss_spec = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(iss_spec)

MINUS = "−"
R_E = 6378137.0                    # WGS84 equatorial radius, the module default and iss_spec ORBIT R_earth_m
ALT = 400e3
R_ORB = R_E + ALT                  # 6778137 m, equal to the FE orbit radius
H = R_ORB / R_E
INC = 0.90128803                   # 51.64 deg, FE orbit inclination (summary.json)
AU = 1.495978707e11
EPOCH = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)
# ISS design environment values of the case input (cold, mean, hot); the solar constant belongs to the same case
ENV = {
    "cold0": dict(name="冷工况", S=1321.0, albedo=0.20, olr=206.0, beta=0.0),
    "nom0": dict(name="平均工况", S=1371.0, albedo=0.31, olr=241.0, beta=0.0),
    "hot75": dict(name="热工况", S=1423.0, albedo=0.40, olr=286.0, beta=75.0),
}
BETAS = (0.0, 75.0)
N_POS = 96                          # orbit positions per beta, 3.75 deg apart
ORBIT_PERIOD_S = 2.0 * math.pi * math.sqrt(R_ORB**3 / 3.986004418e14)
SERIES: dict = {
    "case_id": "EN-003",
    "description": "orientation: module earth_flux and the independent geocentric quadrature along the 400 km orbits "
                   "for the mean environment values, time from orbit noon; fe: module earth_flux and FE Orbital "
                   "Thermal Loads external irradiation per face and absorbed albedo and infrared loads of the solar "
                   "array and radiator on the regular 120 s FE grid of the last-period window",
}
STEP2_REL = 0.01                    # 1 % acceptance of step 2
STEP2_FLOOR_W_M2 = 1e-10            # only numerical zero: 1 % of this scale is 1e-12 W/m2
FE_REL = 0.03                       # 3 % acceptance of step 3
FE_PERIOD_S = 5553.6243             # period inside the FE orbit functions rx, ry, rz
PV_FRACTION = 0.073                 # FE-001 input: P_pv = 0.073 x direct power on the cell side


def signed(value: float, digits: int = 1, unit: str = "") -> str:
    text = f"{abs(value):.{digits}f}"
    if round(value, digits) < 0:
        text = MINUS + text
    return text + unit


def pct(value: float, digits: int = 1) -> str:
    return signed(100.0 * value, digits, "%")


def clean_cn(text: str) -> str:
    """Report-rule guard for the Chinese summary and anomalies: no brackets of any kind."""

    for ch in "()[]{}（）【】〔〕《》<>":
        text = text.replace(ch, "")
    return text


def pct_small(value: float) -> str:
    """Small non-negative fraction as a plain percentage without exponent notation."""

    text = f"{100.0 * value:.6f}".rstrip("0").rstrip(".")
    return (text if text else "0") + "%"


@dataclass(frozen=True)
class Surf:
    surface_id: str
    normal_body: np.ndarray


# ----------------------------------------------------------------------------------------------------------- geometry
def orbit_state(u: float, beta_deg: float):
    """Position (m), velocity direction and Earth-to-Sun unit vector of the FE-style circular orbit at angle u."""

    r = R_ORB * np.array([math.cos(u), math.sin(u) * math.cos(INC), math.sin(u) * math.sin(INC)])
    v = np.array([-math.sin(u), math.cos(u) * math.cos(INC), math.cos(u) * math.sin(INC)])
    b = math.radians(beta_deg)
    s = np.array([math.cos(b), -math.sin(b) * math.sin(INC), math.sin(b) * math.cos(INC)])
    return r, v, s


def quat_from_axes(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Active body-to-GCRS quaternion (xyzw) of the body axes x, y, z given in GCRS."""

    return Rotation.from_matrix(np.column_stack([x, y, z])).as_quat()


def lvlh_axes(r: np.ndarray, v: np.ndarray):
    x = v / np.linalg.norm(v)
    z = -r / np.linalg.norm(r)
    y = np.cross(z, x)
    return x, y, z


def sun_axes(r: np.ndarray, v: np.ndarray, s: np.ndarray):
    """Sun-tracking body axes: +Z toward the Sun as seen from the satellite, +X along the orbit normal projection."""

    z = s * AU - r
    z /= np.linalg.norm(z)
    h = np.cross(r, v)
    h /= np.linalg.norm(h)
    x = h - (h @ z) * z
    if np.linalg.norm(x) < 1e-6:
        x = v - (v @ z) * z
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return x, y, z


LVLH_SURFACES = (
    Surf("nadir", np.array([0.0, 0.0, 1.0])),
    Surf("zenith", np.array([0.0, 0.0, -1.0])),
    Surf("along_pos", np.array([1.0, 0.0, 0.0])),
    Surf("along_neg", np.array([-1.0, 0.0, 0.0])),
    Surf("cross_pos", np.array([0.0, 1.0, 0.0])),
    Surf("cross_neg", np.array([0.0, -1.0, 0.0])),
)
SUN_SURFACES = (Surf("sun", np.array([0.0, 0.0, 1.0])), Surf("antisun", np.array([0.0, 0.0, -1.0])))
GROUPS = {
    "对地": ("nadir",),
    "背地": ("zenith",),
    "垂直于当地竖直方向": ("along_pos", "along_neg", "cross_pos", "cross_neg"),
    "跟踪太阳": ("sun",),
    "跟踪太阳背面": ("antisun",),
}


def last_period(t: np.ndarray, v: np.ndarray, t_end: float, period: float):
    """Time-weighted mean, maximum and minimum over the exact last period [t_end - period, t_end]."""

    t0 = t_end - period
    keep = (t > t0) & (t <= t_end + 1e-9)
    tt = np.concatenate([[t0], t[keep]])
    vv = np.interp(tt, t, v)
    mean = float(np.trapezoid(vv, tt) / (tt[-1] - tt[0]))
    return mean, float(vv.max()), float(vv.min())


# ----------------------------------------------------------------------------------------------- shared step-2 sweep
@pytest.fixture(scope="module")
def sweep():
    """Module records and independent references along both orbits for every orientation and environment case."""

    fine = ref.CapQuadrature(R_ORB, R_E, 600, 1200)
    coarse = ref.CapQuadrature(R_ORB, R_E, 300, 600)
    out = {}
    for beta in BETAS:
        rows = []
        for k in range(N_POS):
            u = 2.0 * math.pi * k / N_POS
            r, v, s = orbit_state(u, beta)
            xl, yl, zl = lvlh_axes(r, v)
            xs, ys, zs = sun_axes(r, v, s)
            normals = {
                "nadir": zl, "zenith": -zl, "along_pos": xl, "along_neg": -xl, "cross_pos": yl, "cross_neg": -yl,
                "sun": zs, "antisun": -zs,
            }
            names = list(normals)
            n_arr = np.array([normals[nm] for nm in names])
            F, F_alb = fine.factors(r, n_arr, s)
            Fc, F_albc = coarse.factors(r, n_arr, s)
            for index, normal in enumerate(n_arr):
                # A uniform geocentric mesh cannot establish a relative reference
                # tolerance for very small grazing/terminator intersections.
                if (0 < F[index] < 0.005) or (0 < F_alb[index] < 0.005):
                    precise = ref.adaptive_cap_factors(r, normal, s, R_E, rtol=1e-8)
                    relaxed = ref.adaptive_cap_factors(r, normal, s, R_E, rtol=1e-6)
                    F[index], F_alb[index] = precise[:2]
                    Fc[index], F_albc[index] = relaxed[:2]
            lam = np.arccos(np.clip(n_arr @ (-r / np.linalg.norm(r)), -1.0, 1.0))
            F_an = ref.plate_sphere_view_factor(H, lam)
            module = {}
            for case, env in ENV.items():
                recs = {}
                for label, surfaces, axes in (("lvlh", LVLH_SURFACES, (xl, yl, zl)), ("sun", SUN_SURFACES, (xs, ys, zs))):
                    rec = ef.earth_flux_record(
                        f"en003-{case}", u / (2.0 * math.pi) * ORBIT_PERIOD_S, r, s * AU, quat_from_axes(*axes), surfaces,
                        albedo=env["albedo"], olr_W_m2=env["olr"], solar_constant_W_m2=env["S"],
                    )
                    for idx, sid in enumerate(rec["surface_ids"]):
                        recs[sid] = (float(rec["albedo_W_m2"][idx]), float(rec["infrared_W_m2"][idx]))
                module[case] = recs
            rows.append(dict(u=u, r=r, s=s, normals=normals, names=names, F=dict(zip(names, F)),
                             F_alb=dict(zip(names, F_alb)), Fc=dict(zip(names, Fc)), F_albc=dict(zip(names, F_albc)),
                             F_an=dict(zip(names, F_an)), lam=dict(zip(names, lam)), module=module))
        out[beta] = rows
    return out


# ------------------------------------------------------------------------------------------------------------ step 1
def test_step1_nadir_view_factor(case_record, sweep):
    F_exact = (R_E / R_ORB) ** 2
    case_record.metric("nadir_view_factor_analytic", F_exact)
    ok_round = round(F_exact, 4) == 0.8855
    case_record.check(
        "步骤1 解析值 400 km 对地平板视角系数",
        "(R/r)^2 = (6378137/6778137)^2 = 0.8855",
        f"{F_exact:.6f}", ok_round,
    )
    helper = []
    record = []
    for beta in BETAS:
        for row in sweep[beta]:
            nadir = -row["r"] / np.linalg.norm(row["r"])
            helper.append(ef.earth_view_factor(row["r"], nadir))
            for case, env in ENV.items():
                record.append(row["module"][case]["nadir"][1] / env["olr"])
    helper = np.array(helper)
    record = np.array(record)
    err_helper = float(np.max(np.abs(helper - F_exact)) / F_exact)
    err_record = float(np.max(np.abs(record - F_exact)) / F_exact)
    case_record.metric("nadir_view_factor_module", float(np.mean(record)))
    case_record.metric("nadir_view_factor_max_rel_error", max(err_helper, err_record))
    ok = max(err_helper, err_record) <= 1e-3 and round(float(np.mean(record)), 4) == 0.8855
    case_record.check(
        "步骤1 earth_flux 对地平板视角系数与解析值",
        "两条轨道全部位置的视角系数 0.8855，相对误差不超过 0.1%",
        f"earth_view_factor {helper.min():.6f} 至 {helper.max():.6f}，earth_flux_record 红外除以地球红外 "
        f"{record.min():.6f} 至 {record.max():.6f}，最大相对误差 {max(err_helper, err_record):.2e}，"
        f"样本 {helper.size} 与 {record.size} 个",
        ok,
    )
    assert ok_round and ok


# ------------------------------------------------------------------------------------------------------------ step 2
def test_step2_reference_validity(case_record, sweep):
    """The independent references agree with each other far inside the 1 % acceptance."""

    lams = np.radians(np.arange(0.0, 180.5, 1.0))
    quad = ref.CapQuadrature(R_ORB, R_E, 600, 1200)
    r = np.array([R_ORB, 0.0, 0.0])
    normals = np.stack([-np.cos(lams), np.sin(lams), np.zeros_like(lams)], axis=1)
    F_q, _ = quad.factors(r, normals, np.array([1.0, 0.0, 0.0]))
    F_a = ref.plate_sphere_view_factor(H, lams)
    d_an = float(np.max(np.abs(F_q - F_a)))
    case_record.metric("reference_quadrature_vs_analytic_max_abs", d_an)
    ok1 = d_an <= 2e-5
    case_record.check(
        "步骤2 参照校核 地心面元积分与解析倾斜平板视角系数",
        "0° 至 180° 每 1° 绝对差不超过 2e-5",
        f"最大绝对差 {d_an:.2e}", ok1,
    )
    diff = []
    for beta in BETAS:
        for row in sweep[beta]:
            for nm in row["names"]:
                for env in ENV.values():
                    for fine_v, coarse_v, scale in ((row["F_alb"][nm], row["F_albc"][nm], env["albedo"] * env["S"]),
                                                    (row["F"][nm], row["Fc"][nm], env["olr"])):
                        diff.append(abs(fine_v - coarse_v) * scale / max(fine_v * scale, STEP2_FLOOR_W_M2))
    d_conv = float(max(diff))
    case_record.metric("reference_grid_convergence_max", d_conv)
    ok2 = d_conv <= 1e-3
    case_record.check(
        "步骤2 参照校核 面元积分网格加密收敛",
        "600×1200 与 300×600 网格的反照与红外辐照按步骤2 判据折算相差不超过 0.1%，即参照误差不超过门限的十分之一",
        f"全部 {len(diff)} 个样本最大 {d_conv:.2e}", ok2,
    )
    mc_rows = []
    worst = 0.0
    # nadir at noon; Sun-tracking plate near the terminator; cross-track and anti-Sun plates at beta 75
    picks = [(0.0, 0, "nadir"), (0.0, 26, "sun"), (75.0, 10, "cross_pos"), (75.0, 50, "antisun")]
    for beta, k, nm in picks:
        row = sweep[beta][k]
        normal = row["normals"][nm]
        sums = np.zeros(4)
        batches = 4
        for seed in range(batches):
            sums += np.array(ref.monte_carlo_cap(row["r"], normal, row["s"], R_E, 1_000_000, 100 + seed))
        mF, sF, mA, sA = sums / batches
        sF /= math.sqrt(batches)
        sA /= math.sqrt(batches)
        zF = abs(mF - row["F"][nm]) / max(sF, 1e-12)
        zA = abs(mA - row["F_alb"][nm]) / max(sA, 1e-12)
        worst = max(worst, zF, zA)
        mc_rows.append(f"β {beta:.0f}° {nm} F {mF:.4f}±{sF:.4f} 对 {row['F'][nm]:.4f}，F_alb {mA:.4f}±{sA:.4f} 对 {row['F_alb'][nm]:.4f}")
    case_record.metric("reference_monte_carlo_max_sigma", worst)
    ok3 = worst <= 4.0
    case_record.check(
        "步骤2 参照校核 蒙特卡罗积分",
        "四个构型各 4×10^6 个随机面元，与面元积分之差不超过 4 倍标准误差",
        "；".join(mc_rows) + f"；最大 {worst:.2f} 倍标准误差", ok3,
    )
    assert ok1 and ok2 and ok3


def _compare(module: np.ndarray, reference: np.ndarray):
    scale = np.maximum(reference, STEP2_FLOOR_W_M2)
    rel = np.abs(module - reference) / scale
    big = reference >= STEP2_FLOOR_W_M2
    small = ~big
    max_rel_big = float(np.max(np.abs(module[big] - reference[big]) / reference[big])) if big.any() else 0.0
    max_abs_small = float(np.max(np.abs(module[small] - reference[small]))) if small.any() else 0.0
    return float(rel.max()), max_rel_big, max_abs_small, int(big.sum()), int(small.sum())


def test_step2_orientations_vs_numerical_integration(case_record, sweep):
    all_ok = True
    worst_overall = 0.0
    for group, members in GROUPS.items():
        for quantity in ("反照", "红外"):
            m_vals, r_vals, a_vals = [], [], []
            for beta in BETAS:
                for row in sweep[beta]:
                    for case, env in ENV.items():
                        for nm in members:
                            alb, ir = row["module"][case][nm]
                            if quantity == "反照":
                                m_vals.append(alb)
                                r_vals.append(env["albedo"] * env["S"] * row["F_alb"][nm])
                            else:
                                m_vals.append(ir)
                                r_vals.append(env["olr"] * row["F"][nm])
                                a_vals.append(env["olr"] * row["F_an"][nm])
            m_vals, r_vals = np.array(m_vals), np.array(r_vals)
            crit, rel_big, abs_small, n_big, n_small = _compare(m_vals, r_vals)
            ok = crit <= STEP2_REL
            extra = ""
            if quantity == "红外":
                a_vals = np.array(a_vals)
                crit_a, rel_a, abs_a, _, _ = _compare(m_vals, a_vals)
                ok = ok and crit_a <= STEP2_REL
                extra = f"；与解析倾斜平板视角系数相比最大相对差 {rel_a:.2e}，小值样本最大绝对差 {abs_a:.2e} W/m²"
                crit = max(crit, crit_a)
            if group == "背地":
                exact_zero = bool(np.all(m_vals == 0.0) and np.all(r_vals == 0.0))
                ok = ok and exact_zero
                extra += f"；模块与参照全部为 0：{exact_zero}"
            worst_overall = max(worst_overall, crit)
            all_ok &= ok
            case_record.metric(f"step2_{group}_{quantity}_max_rel", rel_big)
            case_record.check(
                f"步骤2 {group}平板{quantity}辐照与可见地球面元积分",
                "逐点相对差不超过 1%，仅参照接近数值零时使用 1e-12 W/m² 的绝对容限",
                f"β 0° 与 75°、三组环境值、{len(members)} 个法向、每圈 {N_POS} 个位置，共 {m_vals.size} 个样本；"
                f"参照值不低于 1e-10 W/m² 的 {n_big} 个样本最大相对差 {rel_big:.2e}，其余 {n_small} 个样本最大绝对差 "
                f"{abs_small:.2e} W/m²；按判据折算最大 {crit:.2e}；最大值 模块 {m_vals.max():.2f} 参照 {r_vals.max():.2f} W/m²"
                + extra,
                ok,
            )
    case_record.metric("step2_worst_criterion", worst_overall)
    env = ENV["nom0"]
    orientation = {}
    for beta in BETAS:
        rows = sweep[beta]
        entry = {"time_s": [row["u"] / (2.0 * math.pi) * ORBIT_PERIOD_S for row in rows],
                 "orbit_angle_deg": [math.degrees(row["u"]) for row in rows],
                 "environment": {"albedo": env["albedo"], "olr_W_m2": env["olr"], "solar_constant_W_m2": env["S"]}}
        for nm in ("nadir", "zenith", "along_pos", "cross_pos", "sun", "antisun"):
            entry[f"{nm}_albedo_module_W_m2"] = [row["module"]["nom0"][nm][0] for row in rows]
            entry[f"{nm}_albedo_reference_W_m2"] = [env["albedo"] * env["S"] * row["F_alb"][nm] for row in rows]
            entry[f"{nm}_infrared_module_W_m2"] = [row["module"]["nom0"][nm][1] for row in rows]
            entry[f"{nm}_infrared_reference_W_m2"] = [env["olr"] * row["F"][nm] for row in rows]
            entry[f"{nm}_infrared_analytic_W_m2"] = [env["olr"] * row["F_an"][nm] for row in rows]
            entry[f"{nm}_tilt_from_nadir_deg"] = [math.degrees(row["lam"][nm]) for row in rows]
        orientation[f"beta_{beta:.0f}"] = entry
    SERIES["orientation"] = orientation
    assert all_ok


# ------------------------------------------------------------------------------------------------------------ step 3
def _fe_parameters(case: str, area_saw: float, area_hrs: float):
    z93 = dict(iss_spec.OPTICS["z93"])
    z93.update(iss_spec.OPTICS_BY_CASE.get(case, {}).get("z93", {}))
    cells = iss_spec.OPTICS["saw_cells"]
    back = iss_spec.OPTICS["saw_back"]
    blk = iss_spec.MATERIALS["saw_blk"]
    pan = iss_spec.MATERIALS["hrs_pan"]
    src = "Thermal/iss_fem/model/iss_spec.py"
    rng = [100.0, 450.0]

    def dummy(instance, node, ports):
        return dict(instance_id=instance, node_id=node, asset_id=f"en003_{instance.lower()}", asset_version="test-1",
                    materials=[dict(material_id=f"{instance.lower()}_mass", mass_kg=10.0, cp_J_kgK=900.0,
                                    source="EN-003 test value, not compared")],
                    temperature_range_K=rng, ports=ports)

    components = [
        dict(instance_id="SolarArray01", node_id="S", asset_id="iss_us_saw_blankets", asset_version="iss_spec",
             materials=[dict(material_id="saw_blanket", mass_kg=blk["rho"] * blk["t"] * area_saw, cp_J_kgK=blk["cp"],
                             source=f"{src} MATERIALS saw_blk")],
             surfaces=[
                 dict(surface_id="SAW_cells", area_m2=area_saw, normal_body=[0.0, 0.0, -1.0],
                      absorptivity=round(cells["alpha"] + PV_FRACTION, 6), emissivity=cells["eps"],
                      source=f"{src} OPTICS saw_cells plus the 0.073 electrical share, FE-001 input"),
                 dict(surface_id="SAW_back", area_m2=area_saw, normal_body=[0.0, 0.0, 1.0],
                      absorptivity=back["alpha"], emissivity=back["eps"], source=f"{src} OPTICS saw_back"),
             ],
             temperature_range_K=rng, ports=["P_pv_W"]),
        dummy("Compute01", "J", ["P_load_W"]),
        dummy("ColdPlate01", "C", []),
        dummy("Battery01", "B", ["Q_B_W"]),
        dummy("Controller01", "D", []),
        dummy("PDU01", "D", ["Q_D_W"]),
        dict(instance_id="Radiator01", node_id="R", asset_id="iss_eatcs_radiator_wing", asset_version="iss_spec",
             materials=[dict(material_id="hrs_panels", mass_kg=pan["rho"] * pan["t"] * area_hrs, cp_J_kgK=pan["cp"],
                             source=f"{src} MATERIALS hrs_pan")],
             surfaces=[
                 dict(surface_id="HRS_up", area_m2=area_hrs, normal_body=[0.0, 1.0, 0.0],
                      absorptivity=z93["alpha"], emissivity=z93["eps"], source=f"{src} OPTICS z93 for {case}"),
                 dict(surface_id="HRS_down", area_m2=area_hrs, normal_body=[0.0, -1.0, 0.0],
                      absorptivity=z93["alpha"], emissivity=z93["eps"], source=f"{src} OPTICS z93 for {case}"),
             ],
             temperature_range_K=rng, ports=[]),
    ]
    connections = [
        dict(path="SR", equivalent_total_resistance_K_W=1.0e6, includes_contact=True,
             source="FE has no array to radiator conduction, very large resistance, FE-001 configuration"),
        dict(path="JC", equivalent_total_resistance_K_W=0.1, includes_contact=True, source="EN-003 test value"),
        dict(path="CR", equivalent_total_resistance_K_W=0.05, includes_contact=True, source="EN-003 test value"),
        dict(path="BR", equivalent_total_resistance_K_W=0.5, includes_contact=True, source="EN-003 test value"),
        dict(path="DR", equivalent_total_resistance_K_W=0.5, includes_contact=True, source="EN-003 test value"),
    ]
    return assemble_thermal_parameters(components, connections, None)


class FEGeometry:
    """Orbit, Sun, eclipse and the two FE attitude laws, rebuilt from summary.json and the exported OTL settings."""

    def __init__(self, case: str, fe_case: dict, summary: dict):
        self.case = case
        self.S = ENV[case]["S"]
        self.radius = float(summary["orbit"]["R"])
        self.period = FE_PERIOD_S
        s = np.array(summary["orbit"]["sun_ecs"], dtype=float)
        self.s = s / np.linalg.norm(s)
        self.law = iss_spec.CASES[case]["hrs_law"]
        self.inc = INC

    def position(self, t: float) -> np.ndarray:
        w = 2.0 * math.pi * t / self.period
        return self.radius * np.array([math.cos(w), math.sin(w) * math.cos(self.inc), math.sin(w) * math.sin(self.inc)])

    def velocity_dir(self, t: float) -> np.ndarray:
        w = 2.0 * math.pi * t / self.period
        return np.array([-math.sin(w), math.cos(w) * math.cos(self.inc), math.cos(w) * math.sin(self.inc)])

    def sun_position(self, t: float) -> np.ndarray:
        return self.s * AU

    def lit(self, t: float) -> float:
        r = self.position(t)
        along = float(r @ self.s)
        return 1.0 if along >= 0.0 or float(np.linalg.norm(r - along * self.s)) >= R_E else 0.0

    def G(self, t: float) -> float:
        return self.S * self.lit(t)

    def q_saw(self, t: float) -> np.ndarray:
        """otl_saw: primary +Z antisun, secondary +Y antinormal."""

        r = self.position(t)
        v = self.velocity_dir(t)
        normal = np.cross(r, v)
        normal /= np.linalg.norm(normal)
        z = -self.s
        y = -normal - (-normal @ z) * z
        y /= np.linalg.norm(y)
        return quat_from_axes(np.cross(y, z), y, z)

    def q_hrs(self, t: float) -> np.ndarray:
        """otl_hrs: daylight +X velocity, +Z nadir (zero law) or antisun (track law); eclipse +X velocity, +Y nadir."""

        r = self.position(t)
        x = self.velocity_dir(t)
        nadir = -r / np.linalg.norm(r)
        if self.lit(t) < 0.5:
            y = nadir - (nadir @ x) * x
            y /= np.linalg.norm(y)
            return quat_from_axes(x, y, np.cross(x, y))
        target = nadir if self.law == "zero" else -self.s
        z = target - (target @ x) * x
        z /= np.linalg.norm(z)
        return quat_from_axes(x, np.cross(z, x), z)


@pytest.fixture(scope="module")
def fe_data():
    path = DATA / "fe_loads.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fe_runs(fe_data):
    """Coupled thermal-only runs over the FE last period for each case and FE attitude law."""

    if fe_data is None:
        return None
    runs = {}
    settings = cp.SolverSettings(method="RK45", rtol=1e-6, atol_T_K=1e-4, max_step_s=60.0, output_step_s=120.0,
                                 environment_step_s=10.0, event_time_tol_s=1e-3)
    for case in ENV:
        fe_case = fe_data["cases"][case]
        summary = json.loads((ISS / "out" / case / "summary.json").read_text(encoding="utf-8"))
        geo = FEGeometry(case, fe_case, summary)
        t_fe = np.array(fe_case["t_s"], dtype=float)
        t_end = float(t_fe[-1])
        t_start = 120.0 * math.floor((t_end - geo.period) / 120.0)
        area_saw = float(fe_case["area_m2"]["saw_all"])
        area_hrs = float(fe_case["area_m2"]["hrs_S1"])
        params = _fe_parameters(case, area_saw, area_hrs)
        model = cp.EarthFluxModel(albedo=ENV[case]["albedo"], olr_W_m2=ENV[case]["olr"],
                                  solar_constant_W_m2=ENV[case]["S"], earth_radius_m=R_E)
        case_runs = {}
        for law, quaternion in (("saw", geo.q_saw), ("hrs", geo.q_hrs)):
            run_id = f"en003-{case}-{law}"
            provider = cp.EnvironmentProvider.from_callables(
                run_id=run_id, epoch=EPOCH, parameters=params, position=geo.position, sun_position=geo.sun_position,
                quaternion=quaternion, G=geo.G, earth_flux=model, eclipse_fraction=geo.lit,
            )
            cells_area = area_saw

            def ports(t, law=law, geo=geo, cells_area=cells_area):
                p_pv = PV_FRACTION * cells_area * geo.G(t) if law == "saw" else 0.0
                return {"P_pv_W": p_pv, "P_load_W": 100.0, "Q_B_W": 0.0, "Q_D_W": 10.0}

            state = ThermalState(run_id, t_start, np.array([290.0, 293.15, 293.15, 293.15, 293.15, 260.0]))
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                archive = cp.run_coupled(params, state, provider, t_end, settings=settings, prescribed_ports=ports)
            samples = [provider.sample(float(t)) for t in archive.time_s]
            case_runs[law] = dict(archive=archive, provider=provider, samples=samples)
        runs[case] = dict(geo=geo, params=params, t_end=t_end, t_start=t_start, area_saw=area_saw,
                          area_hrs=area_hrs, runs=case_runs, summary=summary)
    return runs


def _fe_face_series(fe_case: dict, times: np.ndarray, S: float):
    """FE irradiation per face at the given times (regular 120 s grid rows only), W/m2."""

    t_fe = np.array(fe_case["t_s"], dtype=float)
    regular = np.isclose(np.mod(t_fe, 120.0), 0.0, atol=1e-6) | np.isclose(np.mod(t_fe, 120.0), 120.0, atol=1e-6)
    index = {}
    for i in np.flatnonzero(regular):
        index.setdefault(round(float(t_fe[i]), 6), int(i))
    rows = [index[round(float(t), 6)] for t in times]
    saw = {k: np.array(v, dtype=float)[rows] for k, v in fe_case["series"]["saw_all"].items()}
    s1 = {k: np.array(v, dtype=float)[rows] for k, v in fe_case["series"]["hrs_S1"].items()}
    p1 = {k: np.array(v, dtype=float)[rows] for k, v in fe_case["series"]["hrs_P1"].items()}
    lit_cells = saw["Gextd1"] > 0.5 * S
    return {
        "saw_back_albedo": saw["Gextu1"],
        "saw_back_infrared": saw["Gextu2"],
        "saw_cells_albedo": np.where(lit_cells, np.maximum(saw["Gextd1"] - S, 0.0), saw["Gextd1"]),
        "saw_cells_infrared": saw["Gextd2"],
        # outer faces of the two wings: S1 +Y and P1 -Y never face the other wing
        "radiator_up_albedo": s1["Gextu1"],
        "radiator_up_infrared": s1["Gextu2"],
        "radiator_down_albedo": p1["Gextd1"],
        "radiator_down_infrared": p1["Gextd2"],
        # inner faces, shadowed by the other wing in some attitudes (design 4.4 neglects mutual obstruction)
        "radiator_inner_S1_down_infrared": s1["Gextd2"],
        "radiator_inner_P1_up_infrared": p1["Gextu2"],
        "radiator_inner_S1_down_albedo": s1["Gextd1"],
        "radiator_inner_P1_up_albedo": p1["Gextu1"],
        "fe_direct_cells": np.where(lit_cells, S, 0.0),
    }


def test_step3_fe_thermal_loads(case_record, fe_data, fe_runs):
    if fe_data is None:
        case_record.check("步骤3 有限元热载荷导出", "tests/data/en_003/fe_loads.json 由 fe_export.py 导出",
                          "文件不存在，有限元对比未执行", False)
        pytest.fail("FE export missing")
    SERIES["fe"] = {}
    all_ok = True
    quad = ref.CapQuadrature(R_ORB, R_E, 600, 1200)
    planet = {c: (fe_data["cases"][c]["otl"]["otl_saw"]["nRings"], fe_data["cases"][c]["otl"]["otl_saw"]["nPointsRing"])
              for c in ENV}
    case_record.metric("fe_planet_discretisation", {c: list(v) for c, v in planet.items()})
    case_record.metric("fe_export_provenance", {
        "tool": "tests/data/en_003/fe_export.py", "comsol": fe_data.get("comsol"), "mph": fe_data.get("mph"),
        "exported_utc": fe_data.get("exported_utc"),
        "files": {c: {k: fe_data["cases"][c][k] for k in ("file", "file_bytes", "file_mtime_utc", "dataset")} for c in ENV},
        "variables": fe_data.get("variables")})
    for case, env in ENV.items():
        fe_case = fe_data["cases"][case]
        summary = fe_runs[case]["summary"]
        funcs = fe_case["orbit_functions"]
        raw = fe_case["otl"]["otl_saw"]["SV_ECS"]
        rays = [float(x) for x in (raw if isinstance(raw, list) else [raw])]
        sun = np.array(summary["orbit"]["sun_ecs"], dtype=float)
        geo_ok = (
            all("6778137.0" in funcs[k] and "5553.6243" in funcs[k] for k in ("rx", "ry", "rz"))
            and "cos(0.90128803)" in funcs["ry"] and "sin(0.90128803)" in funcs["rz"]
            and float(np.max(np.abs(np.array(rays) + sun[: len(rays)]))) < 1e-7
            and len(rays) == 3
            and abs(float(summary["orbit"]["R"]) - R_ORB) < 1e-6
        )
        all_ok &= geo_ok
        t_fe = np.array(fe_case["t_s"], dtype=float)
        on_grid = np.isclose(np.mod(t_fe, 120.0), 0.0, atol=1e-6) | np.isclose(np.mod(t_fe, 120.0), 120.0, atol=1e-6)
        events = sorted(set(np.round(t_fe[~on_grid], 3).tolist()))
        boundaries = [b.time_s for b in fe_runs[case]["runs"]["saw"]["archive"].eclipse_boundaries]
        offsets = [min(abs(b - e) for e in events) for b in boundaries] if events and boundaries else []
        case_record.metric(f"fe_{case}_eclipse_event_offsets_s", offsets)
        planet_all = fe_case["otl"]["otl_saw"].get("planet_feature_all", {})
        r_planet = str(planet_all.get("R_planet", "?")) if isinstance(planet_all, dict) else "?"
        try:
            r_planet_m = float(r_planet.split("[")[0]) * 1e3 if "[km]" in r_planet else float("nan")
        except ValueError:
            r_planet_m = float("nan")
        f_fe_radius = (r_planet_m / R_ORB) ** 2
        case_record.metric(f"fe_{case}_planet_radius", {"R_planet": r_planet,
                                                       "nadir_view_factor_change_rel": f_fe_radius / (R_E / R_ORB) ** 2 - 1})
        case_record.check(
            f"步骤3 {env['name']} 有限元轨道、太阳方向与日食",
            "模型轨道函数半径 6778137 m、周期 5553.6243 s、倾角 0.90128803 rad，太阳光线方向与 summary.json 太阳方向相反",
            f"rx {funcs['rx']}；光线 {rays}；太阳方向 {sun.tolist()}；有限元日食事件 {events[:4]} s，"
            f"柱形地影边界与之相差 {[round(x, 2) for x in offsets]} s；有限元行星半径 {r_planet}，"
            f"使对地视角系数变化 {pct(f_fe_radius / (R_E / R_ORB) ** 2 - 1, 4)}",
            geo_ok,
        )
        params_ok = (
            abs(float(fe_case["params"]["S_sun"].split("[")[0]) - env["S"]) < 1e-9
            and abs(float(fe_case["params"]["albedo"]) - env["albedo"]) < 1e-12
            and abs(float(fe_case["params"]["q_olr"].split("[")[0]) - env["olr"]) < 1e-9
            and iss_spec.CASES[case]["beta_deg"] == env["beta"]
        )
        all_ok &= params_ok
        case_record.check(
            f"步骤3 {env['name']} 有限元模型环境参数",
            f"太阳常数 {env['S']:.0f} W/m²，反照率 {env['albedo']:.2f}，地球红外 {env['olr']:.0f} W/m²，β {env['beta']:.0f}°",
            f"模型读出 {fe_case['params']}，文件 {fe_case['file']}，行星离散 {planet[case][0]} 圈每圈 {planet[case][1]} 点",
            params_ok,
        )
        run = fe_runs[case]
        geo = run["geo"]
        out_case = {}
        for law in ("saw", "hrs"):
            archive = run["runs"][law]["archive"]
            completed = archive.status == "completed" and bool(np.all(archive.sample_valid))
            all_ok &= completed
            case_record.check(
                f"步骤3 {env['name']} 耦合运行 {'太阳翼指向' if law == 'saw' else '散热器指向'}",
                "run_coupled 经 thermal_derivative 与 earth_flux 完成最后一个周期，全部输出样本有效",
                f"状态 {archive.status}，{archive.time_s[0]:.0f} 至 {archive.time_s[-1]:.0f} s，样本 {archive.time_s.size} 个，"
                f"日食边界 {len(archive.eclipse_boundaries)} 个，已接受步 {len(archive.steps['t_new_s'])} 个",
                completed,
            )
        saw_run = run["runs"]["saw"]
        hrs_run = run["runs"]["hrs"]
        times = np.array(saw_run["archive"].time_s, dtype=float)
        assert np.array_equal(times, np.array(hrs_run["archive"].time_s, dtype=float))
        fe = _fe_face_series(fe_case, times, env["S"])
        ids = [s.surface_id for s in run["params"].surfaces]
        surf = {s.surface_id: s for s in run["params"].surfaces}

        def module_faces(samples):
            alb = np.array([[float(x) for x in smp.earth_flux["albedo_W_m2"]] for smp in samples])
            ir = np.array([[float(x) for x in smp.earth_flux["infrared_W_m2"]] for smp in samples])
            cos = np.array([[float(x) for x in smp.surface_environment["cos_incidence"]] for smp in samples])
            G = np.array([smp.G_W_m2 for smp in samples])
            return alb, ir, cos, G

        alb_s, ir_s, cos_s, G_s = module_faces(saw_run["samples"])
        alb_r, ir_r, cos_r, G_r = module_faces(hrs_run["samples"])
        ic, ib, iu, idn = ids.index("SAW_cells"), ids.index("SAW_back"), ids.index("HRS_up"), ids.index("HRS_down")
        mod = {
            "saw_back_albedo": alb_s[:, ib], "saw_back_infrared": ir_s[:, ib],
            "saw_cells_albedo": alb_s[:, ic], "saw_cells_infrared": ir_s[:, ic],
            "radiator_up_albedo": alb_r[:, iu], "radiator_up_infrared": ir_r[:, iu],
            "radiator_down_albedo": alb_r[:, idn], "radiator_down_infrared": ir_r[:, idn],
        }
        # T4 consistency inside the coupled run: Q_env from thermal_derivative against the earth_flux records
        A = np.array([surf[i].area_m2 for i in ids])
        a = np.array([surf[i].absorptivity for i in ids])
        e = np.array([surf[i].emissivity for i in ids])
        node = np.array([surf[i].node_id for i in ids])
        worst_t4 = 0.0
        for law, (alb, ir, cos, G), col in (("saw", (alb_s, ir_s, cos_s, G_s), 0), ("hrs", (alb_r, ir_r, cos_r, G_r), 1)):
            archive = run["runs"][law]["archive"]
            sel = node == ("S" if col == 0 else "R")
            hand = (A[sel] * (a[sel] * (G[:, None] * np.maximum(cos[:, sel], 0.0) + alb[:, sel]) + e[sel] * ir[:, sel])).sum(axis=1)
            got = np.array(archive.Q_env_W)[:, col]
            worst_t4 = max(worst_t4, float(np.max(np.abs(got - hand) / np.maximum(np.abs(hand), 1.0))))
        t4_ok = worst_t4 <= 1e-9
        all_ok &= t4_ok
        case_record.check(
            f"步骤3 {env['name']} earth_flux 经式 T4 进入温度导数",
            "耦合运行输出的 Q_env 与按 earth_flux 记录手算的式 T4 相对差不超过 1e-9",
            f"太阳能板与散热板最大相对差 {worst_t4:.2e}", t4_ok,
        )
        # independent references at the FE instants (analytic view factor, geocentric quadrature), to attribute
        # the differences between earth_flux and the FE loads of the solar array faces
        lam_back, lam_cells, alb_back_ref, alb_cells_ref = [], [], [], []
        for t in times:
            r = geo.position(float(t))
            nadir = -r / np.linalg.norm(r)
            lam_back.append(math.acos(max(-1.0, min(1.0, float((-geo.s) @ nadir)))))
            lam_cells.append(math.acos(max(-1.0, min(1.0, float(geo.s @ nadir)))))
            _, f_alb = quad.factors(r, np.array([-geo.s, geo.s]), geo.s)
            alb_back_ref.append(env["albedo"] * env["S"] * f_alb[0])
            alb_cells_ref.append(env["albedo"] * env["S"] * f_alb[1])
        exact_back = env["olr"] * ref.plate_sphere_view_factor(H, np.array(lam_back))
        exact_cells = env["olr"] * ref.plate_sphere_view_factor(H, np.array(lam_cells))
        alb_back_ref, alb_cells_ref = np.array(alb_back_ref), np.array(alb_cells_ref)
        dev_ir = max(_compare(mod["saw_back_infrared"], exact_back)[0], _compare(mod["saw_cells_infrared"], exact_cells)[0])
        dev_alb = max(_compare(mod["saw_back_albedo"], alb_back_ref)[0], _compare(mod["saw_cells_albedo"], alb_cells_ref)[0])
        an_ok = dev_ir <= 1e-3 and dev_alb <= STEP2_REL
        all_ok &= an_ok
        stats = {}
        for key, reference in (("saw_back_infrared", exact_back), ("saw_cells_infrared", exact_cells),
                               ("saw_back_albedo", alb_back_ref), ("saw_cells_albedo", alb_cells_ref)):
            m_ref = last_period(times, reference, run["t_end"], geo.period)[0]
            m_fe = last_period(times, fe[key], run["t_end"], geo.period)[0]
            m_mod = last_period(times, mod[key], run["t_end"], geo.period)[0]
            stats[key] = {"reference_mean_W_m2": m_ref, "fe_mean_W_m2": m_fe, "module_mean_W_m2": m_mod,
                          "fe_minus_reference_rel": (m_fe - m_ref) / m_ref if m_ref > 0 else None,
                          "module_minus_reference_rel": (m_mod - m_ref) / m_ref if m_ref > 0 else None}
        # spread among the 16 FE blankets: mutual obstruction between blankets would show up here
        t_all = np.array(fe_case["t_s"], dtype=float)
        row_of = {}
        for i, t in enumerate(t_all):
            row_of.setdefault(round(float(t), 6), i)
        rows = [row_of[round(float(t), 6)] for t in times]
        spread = {}
        for var, label in (("Gextu2", "back_infrared"), ("Gextu1", "back_albedo"), ("Gextd2", "cells_infrared")):
            ref_mean = last_period(times, np.array(fe_case["series"]["saw_all"][var])[rows], run["t_end"], geo.period)[0]
            rel = [last_period(times, np.array(v[var])[rows], run["t_end"], geo.period)[0] / ref_mean - 1.0
                   for k, v in fe_case["series"].items() if k.startswith("saw_") and k != "saw_all"]
            spread[label] = (min(rel), max(rel))
        stats["blanket_spread_rel"] = spread
        case_record.metric(f"fe_{case}_saw_faces_vs_references", stats)
        case_record.metric(f"fe_{case}_saw_back_ir_fe_minus_exact_mean_rel", stats["saw_back_infrared"]["fe_minus_reference_rel"])
        case_record.check(
            f"步骤3 {env['name']} 太阳翼正反面辐照与独立参照",
            "有限元输出时刻 earth_flux 红外与解析倾斜平板视角系数逐点相差不超过 0.1%，反照与地心面元积分逐点相差不超过 1%，"
            "参照接近数值零时使用 1e-12 W/m² 的绝对容限",
            f"红外最大 {dev_ir:.2e}，反照最大 {dev_alb:.2e}；整周期平均 有限元比参照 背面红外 "
            f"{pct(stats['saw_back_infrared']['fe_minus_reference_rel'])}、正面红外 "
            f"{pct(stats['saw_cells_infrared']['fe_minus_reference_rel'])}、背面反照 "
            f"{pct(stats['saw_back_albedo']['fe_minus_reference_rel'])}、正面反照 "
            f"{pct(stats['saw_cells_albedo']['fe_minus_reference_rel'])}；16 块毯面背面红外整周期平均相对全体平均 "
            f"{pct(spread['back_infrared'][0], 2)} 至 {pct(spread['back_infrared'][1], 2)}，背面反照 "
            f"{pct(spread['back_albedo'][0], 2)} 至 {pct(spread['back_albedo'][1], 2)}",
            an_ok,
        )
        # per-face irradiation statistics (diagnostic) and absorbed loads (acceptance)
        face_rows = []
        for key in mod:
            mm = last_period(times, mod[key], run["t_end"], geo.period)
            ff = last_period(times, fe[key], run["t_end"], geo.period)
            rel_mean = (mm[0] - ff[0]) / ff[0] if ff[0] > 0 else None
            rel_peak = (mm[1] - ff[1]) / ff[1] if ff[1] > 0 else None
            case_record.metric(f"fe_{case}_{key}_mean_W_m2", {"module": mm[0], "fe": ff[0], "rel": rel_mean})
            case_record.metric(f"fe_{case}_{key}_peak_W_m2", {"module": mm[1], "fe": ff[1], "rel": rel_peak})
            face_rows.append(f"{key} 平均 {mm[0]:.2f}/{ff[0]:.2f} 峰值 {mm[1]:.2f}/{ff[1]:.2f}")
        for key in ("radiator_inner_S1_down_infrared", "radiator_inner_P1_up_infrared"):
            base = "radiator_down_infrared" if "S1_down" in key else "radiator_up_infrared"
            mm = last_period(times, mod[base], run["t_end"], geo.period)
            ff = last_period(times, fe[key], run["t_end"], geo.period)
            case_record.metric(f"fe_{case}_{key}_mean_W_m2", {"module": mm[0], "fe": ff[0],
                                                             "rel": (mm[0] - ff[0]) / ff[0] if ff[0] > 0 else None})
        case_record.metric(f"fe_{case}_face_irradiance_module_over_fe", "；".join(face_rows))
        loads = {}
        for comp_name, faces in (("太阳翼", (("saw_cells", ic), ("saw_back", ib))),
                                 ("散热器", (("radiator_up", iu), ("radiator_down", idn)))):
            for band, key, coef in (("反照", "albedo", a), ("红外", "infrared", e)):
                m_load = sum(A[i] * coef[i] * mod[f"{f}_{key}"] for f, i in faces)
                f_load = sum(A[i] * coef[i] * fe[f"{f}_{key}"] for f, i in faces)
                mm = last_period(times, m_load, run["t_end"], geo.period)
                ff = last_period(times, f_load, run["t_end"], geo.period)
                rel_mean = (mm[0] - ff[0]) / ff[0]
                rel_peak = (mm[1] - ff[1]) / ff[1]
                in_window = (times >= run['t_end'] - geo.period - 1e-7) & (times <= run['t_end'] + 1e-7)
                big = in_window & (f_load >= 0.1 * ff[1])
                inst = float(np.max(np.abs(m_load[big] - f_load[big]) / f_load[big])) if big.any() else float("nan")
                nonzero = in_window & (f_load > 1e-10)
                pointwise = float(np.max(np.abs(m_load[nonzero] - f_load[nonzero]) / f_load[nonzero])) if nonzero.any() else 0.0
                zero_ref = in_window & (f_load <= 1e-10)
                zero_ok = bool(np.all(np.abs(m_load[zero_ref] - f_load[zero_ref]) <= 1e-12))
                worst_index = int(np.flatnonzero(nonzero)[np.argmax(np.abs(m_load[nonzero] - f_load[nonzero]) / f_load[nonzero])]) if nonzero.any() else None
                ok = (np.all(np.isfinite(m_load)) and np.all(np.isfinite(f_load))
                      and abs(rel_mean) <= FE_REL and abs(rel_peak) <= FE_REL and pointwise <= FE_REL and zero_ok)
                all_ok &= ok
                loads[(comp_name, band)] = dict(module=m_load, fe=f_load, mean=(mm[0], ff[0], rel_mean),
                                                peak=(mm[1], ff[1], rel_peak), inst=inst, ok=ok)
                case_record.metric(f"fe_{case}_{comp_name}_{band}_load", {
                    "module_mean_W": mm[0], "fe_mean_W": ff[0], "rel_mean": rel_mean, "module_peak_W": mm[1],
                    "fe_peak_W": ff[1], "rel_peak": rel_peak, "inst_max_rel_above_10pct_peak": inst,
                    "pointwise_max_rel": pointwise, "pointwise_max_abs_W": float(np.max(np.abs(m_load[in_window] - f_load[in_window]))),
                    "worst_relative_point": None if worst_index is None else {
                        "time_s": float(times[worst_index]), "module_W": float(m_load[worst_index]),
                        "fe_W": float(f_load[worst_index]), "abs_diff_W": float(abs(m_load[worst_index] - f_load[worst_index]))},
                    "pointwise_window_s": [run['t_end'] - geo.period, run['t_end']],
                    "zero_reference_abs_pass": zero_ok, "pass": bool(ok)})
                case_record.check(
                    f"步骤3 {env['name']} {comp_name}{band}热载荷与有限元",
                    "最后一个轨道周期同一时刻逐点比较、时间加权平均与峰值均相差不超过 3%，零参考值绝对差不超过 1e-12 W",
                    f"平均 earth_flux {mm[0] / 1e3:.3f} kW，有限元 {ff[0] / 1e3:.3f} kW，相差 {pct(rel_mean)}；"
                    f"峰值 {mm[1] / 1e3:.3f} kW 对 {ff[1] / 1e3:.3f} kW，相差 {pct(rel_peak)}；"
                    f"有限元值不低于峰值 10% 的时刻逐点最大相差 {inst * 100:.1f}%，全部非零参考值逐点最大相差 {pointwise * 100:.1f}%",
                    ok,
                )
        case_record.metric(f"fe_{case}_loads_summary", {f"{k[0]}{k[1]}": {"mean_rel": v["mean"][2], "peak_rel": v["peak"][2]}
                                                        for k, v in loads.items()})
        out_case["time_s"] = times.tolist()
        for key in mod:
            out_case[f"{key}_module_W_m2"] = np.asarray(mod[key]).tolist()
            out_case[f"{key}_fe_W_m2"] = np.asarray(fe[key]).tolist()
        for key in ("radiator_inner_S1_down_infrared", "radiator_inner_P1_up_infrared"):
            out_case[f"{key}_fe_W_m2"] = np.asarray(fe[key]).tolist()
        out_case["saw_back_infrared_analytic_W_m2"] = exact_back.tolist()
        out_case["saw_cells_infrared_analytic_W_m2"] = exact_cells.tolist()
        out_case["saw_back_albedo_reference_W_m2"] = alb_back_ref.tolist()
        out_case["saw_cells_albedo_reference_W_m2"] = alb_cells_ref.tolist()
        for (comp_name, band), v in loads.items():
            tag = {"太阳翼": "solar_array", "散热器": "radiator"}[comp_name] + {"反照": "_albedo", "红外": "_infrared"}[band]
            out_case[f"{tag}_load_module_W"] = np.asarray(v["module"]).tolist()
            out_case[f"{tag}_load_fe_W"] = np.asarray(v["fe"]).tolist()
        out_case["Q_env_S_module_W"] = np.array(saw_run["archive"].Q_env_W)[:, 0].tolist()
        out_case["Q_env_R_module_W"] = np.array(hrs_run["archive"].Q_env_W)[:, 1].tolist()
        out_case["G_W_m2"] = G_s.tolist()
        out_case["last_period_start_s"] = run["t_end"] - geo.period
        out_case["period_s"] = geo.period
        out_case["areas_m2"] = {"solar_array_each_face": run["area_saw"], "radiator_each_face": run["area_hrs"]}
        SERIES["fe"][case] = out_case
    assert all_ok


def _fe_faces_from_series(series: dict, S: float) -> dict:
    saw, s1, p1 = series["saw_all"], series["hrs_S1"], series["hrs_P1"]
    lit = np.array(saw["Gextd1"]) > 0.5 * S
    return {
        "saw_back_albedo": np.array(saw["Gextu1"]), "saw_back_infrared": np.array(saw["Gextu2"]),
        "saw_cells_albedo": np.where(lit, np.maximum(np.array(saw["Gextd1"]) - S, 0.0), np.array(saw["Gextd1"])),
        "saw_cells_infrared": np.array(saw["Gextd2"]),
        "radiator_up_albedo": np.array(s1["Gextu1"]), "radiator_up_infrared": np.array(s1["Gextu2"]),
        "radiator_down_albedo": np.array(p1["Gextd1"]), "radiator_down_infrared": np.array(p1["Gextd2"]),
    }


def _legacy_fe_refined_planet_diagnostic(case_record, fe_data, fe_runs):
    """Diagnostic only: loads-only re-solve of the same FE models with a finer planet discretisation (fe_refine.py).

    Module, production FE and refined FE are compared on the same first-orbit 120 s grid; no acceptance criterion of
    the case is evaluated here, the numbers are recorded as metrics.
    """

    path = DATA / "fe_loads_refined.json"
    if fe_runs is None or not path.exists():
        log = DATA / "fe_refine.log"
        status = "not run"
        if log.exists():
            last = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1:] or [""]
            status = f"attempted without a result file, last log line: {last[0][:200]}"
        case_record.metric("fe_refined_planet_diagnostic_status", status)
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    summary = {}
    SERIES["fe_refined_planet"] = {}
    for case, entry in data.get("cases", {}).items():
        if "series" not in entry:
            summary[case] = {"error": entry.get("error")}
            continue
        run = fe_runs[case]
        geo = run["geo"]
        env = ENV[case]
        t_ref = np.array(entry["t_s"], dtype=float)
        regular = np.isclose(np.mod(t_ref, 120.0), 0.0, atol=1e-6) & (t_ref < geo.period)
        times = t_ref[regular]
        refined = {k: v[regular] for k, v in _fe_faces_from_series(entry["series"], env["S"]).items()}
        prod_case = fe_data["cases"][case]
        t_prod = np.array(prod_case["t_s"], dtype=float)
        rows = [int(np.flatnonzero(np.isclose(t_prod, t, atol=1e-6))[0]) for t in times]
        production = {k: v[rows] for k, v in _fe_faces_from_series(prod_case["series"], env["S"]).items()}
        ids = [s.surface_id for s in run["params"].surfaces]
        surf = {s.surface_id: s for s in run["params"].surfaces}
        providers = {"太阳翼": run["runs"]["saw"]["provider"], "散热器": run["runs"]["hrs"]["provider"]}
        tt = np.append(times, geo.period)
        res = {}
        out = {"time_s": times.tolist(), "planet_rings_points": [entry.get("planet_nRings"), entry.get("planet_nPointsRing")]}
        for comp_name, tag, faces in (("太阳翼", "solar_array", (("saw_cells", "SAW_cells"), ("saw_back", "SAW_back"))),
                                      ("散热器", "radiator", (("radiator_up", "HRS_up"), ("radiator_down", "HRS_down")))):
            samples = [providers[comp_name].sample(float(t)) for t in times]
            for band, key in (("反照", "albedo"), ("红外", "infrared")):
                loads = {"module": np.zeros(times.size), "refined": np.zeros(times.size), "production": np.zeros(times.size)}
                for face, sid in faces:
                    coef = surf[sid].absorptivity if key == "albedo" else surf[sid].emissivity
                    idx = ids.index(sid)
                    vals = np.array([float(smp.earth_flux[f"{key}_W_m2"][idx]) for smp in samples])
                    loads["module"] += surf[sid].area_m2 * coef * vals
                    loads["refined"] += surf[sid].area_m2 * coef * refined[f"{face}_{key}"]
                    loads["production"] += surf[sid].area_m2 * coef * production[f"{face}_{key}"]
                means = {k: float(np.trapezoid(np.append(v, v[0]), tt) / geo.period) for k, v in loads.items()}
                peaks = {k: float(v.max()) for k, v in loads.items()}
                res[f"{comp_name}{band}"] = {
                    "module_mean_W": means["module"], "fe_refined_mean_W": means["refined"],
                    "fe_production_mean_W": means["production"],
                    "rel_mean": (means["module"] - means["refined"]) / means["refined"],
                    "rel_mean_vs_production": (means["module"] - means["production"]) / means["production"],
                    "rel_peak": (peaks["module"] - peaks["refined"]) / peaks["refined"],
                }
                for k, v in loads.items():
                    out[f"{tag}_{key}_load_{k}_W"] = v.tolist()
        summary[case] = {"planet": [entry.get("planet_nRings"), entry.get("planet_nPointsRing")],
                         "solve_wall_s": entry.get("solve_wall_s"), "loads": res}
        SERIES["fe_refined_planet"][case] = out
    case_record.metric("fe_refined_planet_diagnostic", summary)


# ------------------------------------------------------------------------------------------------------------ step 4
def test_step3_fe_ladder(case_record, fe_data, fe_runs):
    """Additional reference experiment; it does not replace the original FE acceptance."""
    spec = importlib.util.spec_from_file_location('en003_ladder', DATA / 'ladder_compare.py')
    ladder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ladder)
    detailed, table, missing, checks = {}, {}, [], []
    for case, env in ENV.items():
        levels = ladder.load_ladder(DATA, case)
        if levels is None:
            missing.append(case)
            continue
        result = ladder.compare_case(case, env, fe_runs[case], fe_data['cases'][case], levels,
                                     _fe_face_series, _fe_faces_from_series)
        detailed[case] = result
        table[case] = {}
        for name, row in result['loads'].items():
            table[case][name] = {'label_cn': name, 'label_en': row['label_en'],
                                'fe_mean_kW': {k: v / 1000 for k, v in row['fe_mean_W'].items()},
                                'module_mean_kW': row['module_mean_W'] / 1000,
                                'rel_vs_finest': row['module_vs_finest_mean_rel'],
                                'rel_vs_extrapolated': row['module_vs_converged_mean_rel'],
                                'extrapolation_monotone': row['fe_converged_mean_W']['monotone']}
        finite = all(np.isfinite(v) for row in result['loads'].values()
                     for values in row['series_W'].values() for v in values)
        checks.append(case_record.check(f"步骤3 {env['name']} 地球离散加密实验完成", '三个离散级别与模块使用相同时刻，全部热载荷有限',
                          f"{len(result['time_s'])} 个时刻，2x6 来源 {result['level_2x6_source']}，有限值 {finite}", finite))
        if result['level_2x6_source'] == 'ladder':
            worst = max(row['ladder_2x6_vs_production_max_rel'] for row in result['loads'].values())
            checks.append(case_record.check(f"步骤3 {env['name']} 原始离散热载荷重现",
                          '2x6 重算与原导出相同，按 max|参考值|, 1 W 缩放的差不超过 1e-8',
                          worst, np.isfinite(worst) and worst <= 1e-8))
    case_record.metric('fe_ladder_missing_cases', missing)
    case_record.metric('fe_ladder_diagnostic', detailed)
    if detailed:
        first = next(iter(detailed.values()))
        case_record.metric('fe_refined_comparison', {'levels': list(ladder.LEVELS), 'step_s': 360,
                           'instants': len(first['time_s']), 'sample_start_s': first['time_s'][0],
                           'sample_end_s': first['time_s'][-1], 'cases': table})
        SERIES['fe_ladder'] = detailed
    if missing:
        case_record.check('步骤3 地球离散加密覆盖三个工况', 'cold0、nom0、hot75 全部完成', missing, False)
    assert not missing and all(checks)


def _small_parameters():
    """Two surfaces on S and two on R, for the missing-record checks."""

    return _fe_parameters("nom0", 10.0, 5.0)


def _orbit_and_flux(params, run_id="en003-missing", t=600.0):
    r, v, s = orbit_state(2.0 * math.pi * t / FE_PERIOD_S, 0.0)
    xl, yl, zl = lvlh_axes(r, v)
    q = quat_from_axes(xl, yl, zl)
    orbit_input = {"run_id": run_id, "time_s": t, "epoch": EPOCH, "position_m": r, "sun_position_m": s * AU,
                   "frame": "GCRS", "quaternion_xyzw": q, "G_W_m2": 1371.0}
    flux = ef.earth_flux_record(run_id, t, r, s * AU, q, params, albedo=0.31, olr_W_m2=241.0, solar_constant_W_m2=1371.0)
    return orbit_input, dict(flux)


def test_step4_missing_records_reported(case_record):
    params = _small_parameters()
    ids = tuple(s.surface_id for s in params.surfaces)
    orbit_input, flux = _orbit_and_flux(params)
    baseline = prepare_surface_environment(orbit_input, flux, params)
    assert baseline["surface_ids"] == ids
    variants = []

    def attempt(label, mutated, must_name):
        try:
            result = prepare_surface_environment(orbit_input, mutated, params)
        except ThermalInputError as exc:
            msg = str(exc)
            named = all(token in msg for token in must_name)
            variants.append((label, True, named, msg))
            return
        except Exception as exc:  # noqa: BLE001  (a different error type is still reported, recorded as such)
            msg = f"{type(exc).__name__}: {exc}"
            variants.append((label, True, all(token in msg for token in must_name), msg))
            return
        variants.append((label, False, False, f"accepted, albedo {list(result['albedo_W_m2'])} infrared "
                                                f"{list(result['infrared_W_m2'])}"))

    for field in ("albedo_W_m2", "infrared_W_m2"):
        for idx, sid in enumerate(ids):
            mutated = dict(flux)
            values = [float(x) for x in flux[field]]
            values[idx] = None
            mutated[field] = values
            attempt(f"{field} {sid} 置为空值", mutated, (field, sid))
            mutated = dict(flux)
            values = [float(x) for x in flux[field]]
            del values[idx]
            mutated[field] = values
            attempt(f"{field} 删去 {sid} 一项", mutated, (field,))
            mutated = dict(flux)
            values = [float(x) for x in flux[field]]
            values[idx] = float("nan")
            mutated[field] = values
            attempt(f"{field} {sid} 为非数", mutated, (field, sid))
        mutated = dict(flux)
        del mutated[field]
        attempt(f"删去 {field} 字段", mutated, (field,))
    for idx, sid in enumerate(ids):
        mutated = dict(flux)
        mutated["surface_ids"] = tuple(x for x in ids if x != sid)
        mutated["albedo_W_m2"] = [float(x) for k, x in enumerate(flux["albedo_W_m2"]) if k != idx]
        mutated["infrared_W_m2"] = [float(x) for k, x in enumerate(flux["infrared_W_m2"]) if k != idx]
        attempt(f"删去 {sid} 整条记录", mutated, (sid,))
    mutated = dict(flux)
    keep = [k for k, x in enumerate(ids) if x not in (ids[0], ids[2])]
    mutated["surface_ids"] = tuple(ids[k] for k in keep)
    mutated["albedo_W_m2"] = [float(flux["albedo_W_m2"][k]) for k in keep]
    mutated["infrared_W_m2"] = [float(flux["infrared_W_m2"][k]) for k in keep]
    attempt(f"删去 {ids[0]} 与 {ids[2]} 两条记录", mutated, (ids[0], ids[2]))

    # calculate_surface_heat with an environment whose albedo or infrared entry is missing
    state = ThermalState("en003-missing", 600.0, np.array([290.0, 293.15, 293.15, 293.15, 293.15, 260.0]))
    for field in ("albedo_W_m2", "infrared_W_m2"):
        env = dict(baseline)
        values = [float(x) for x in baseline[field]]
        values[1] = None
        env[field] = values
        try:
            calculate_surface_heat(state, env, params)
            variants.append((f"calculate_surface_heat {field} 空值", False, False, "accepted"))
        except ThermalInputError as exc:
            variants.append((f"calculate_surface_heat {field} 空值", True, field in str(exc), str(exc)))

    # EarthFluxModel without one of its environment values
    for name in ("albedo", "olr_W_m2", "solar_constant_W_m2"):
        values = {"albedo": 0.31, "olr_W_m2": 241.0, "solar_constant_W_m2": 1371.0}
        values[name] = None
        try:
            cp.EarthFluxModel(**values)
            variants.append((f"EarthFluxModel 缺 {name}", False, False, "accepted"))
        except cp.EnvironmentProviderError as exc:
            variants.append((f"EarthFluxModel 缺 {name}", True, name in str(exc), str(exc)))

    # coupled run whose earth_flux provider loses the albedo record of one surface from t = 900 s
    def broken_flux(run_id, time_s, position_m, sun_position_m, quaternion_xyzw, parameters):
        rec = dict(ef.earth_flux_record(run_id, time_s, position_m, sun_position_m, quaternion_xyzw, parameters,
                                        albedo=0.31, olr_W_m2=241.0, solar_constant_W_m2=1371.0, resolution=(24, 48)))
        if time_s >= 900.0:
            values = [float(x) for x in rec["albedo_W_m2"]]
            values[1] = None
            rec["albedo_W_m2"] = values
        return rec

    geo = FEGeometry("nom0", None, {"orbit": {"R": R_ORB, "sun_ecs": [1.0, 0.0, 0.0]}})
    provider = cp.EnvironmentProvider.from_callables(
        run_id="en003-broken", epoch=EPOCH, parameters=params, position=geo.position, sun_position=geo.sun_position,
        quaternion=geo.q_saw, G=geo.G, earth_flux=broken_flux, eclipse_fraction=geo.lit)
    settings = cp.SolverSettings(method="RK45", rtol=1e-6, atol_T_K=1e-4, max_step_s=60.0, output_step_s=60.0,
                                 environment_step_s=10.0, event_time_tol_s=1e-3)
    state = ThermalState("en003-broken", 0.0, np.array([290.0, 293.15, 293.15, 293.15, 293.15, 260.0]))
    ports = lambda t: {"P_pv_W": 0.0, "P_load_W": 100.0, "Q_B_W": 0.0, "Q_D_W": 10.0}  # noqa: E731
    stopped = False
    message = ""
    last_accepted = float("nan")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cp.run_coupled(params, state, provider, 1800.0, settings=settings, prescribed_ports=ports)
    except cp.CoupledRunError as exc:
        stopped = exc.archive.status == "stopped"
        message = str(exc.archive.error.get("message", ""))
        last_accepted = float(exc.archive.error.get("last_accepted_time_s", float("nan")))
    named = "albedo_W_m2" in message and ids[1] in message
    run_ok = stopped and named and last_accepted < 900.0
    variants.append(("耦合运行中 900 s 起缺少一条反照记录", stopped, named,
                     f"停止 {stopped}，最后已接受时刻 {last_accepted:.1f} s，报错 {message[:200]}"))

    # an explicit teaching simplification is recorded, not hidden (design 9.4)
    disabled = cp.EarthFluxModel.disabled("EN-003 teaching case: albedo and infrared switched off on purpose")
    provider_off = cp.EnvironmentProvider.from_callables(
        run_id="en003-off", epoch=EPOCH, parameters=params, position=geo.position, sun_position=geo.sun_position,
        quaternion=geo.q_saw, G=geo.G, earth_flux=disabled, eclipse_fraction=geo.lit)
    state_off = ThermalState("en003-off", 0.0, np.array([290.0, 293.15, 293.15, 293.15, 293.15, 260.0]))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        arc_off = cp.run_coupled(params, state_off, provider_off, 300.0, settings=settings, prescribed_ports=ports)
    noted = any("switched off" in note and "teaching" in note for note in arc_off.notes)
    zero_flux = all(np.all(np.array(provider_off.sample(120.0).earth_flux[k]) == 0.0)
                    for k in ('albedo_W_m2', 'infrared_W_m2'))

    reported = [v for v in variants if v[1] and v[2]]
    ok = len(reported) == len(variants)
    case_record.metric("step4_variants", len(variants))
    case_record.metric("step4_reported", len(reported))
    for label, raised, named_ok, msg in variants:
        case_record.check(
            f"步骤4 缺失记录 {label}",
            "拒绝计算并在报错中指出未配置字段或缺失的表面，不按零处理",
            f"报错 {raised}，指出字段 {named_ok}：{msg[:300]}",
            bool(raised and named_ok),
        )
    case_record.check(
        "步骤4 显式关闭反照与红外的简化条件",
        "EarthFluxModel.disabled 给出零输入，并在归档 notes 中记录原因",
        f"零输入 {zero_flux}，notes 记录 {noted}",
        bool(noted and zero_flux),
    )
    assert ok and run_ok and noted and zero_flux


# ------------------------------------------------------------------------------------------------------------ summary
def test_summary(case_record):
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "EN-003_series.json").write_text(json.dumps(SERIES, ensure_ascii=False), encoding="utf-8")
    m = case_record.metrics
    explicit = [c for c in case_record.checks if not c["name"].startswith("test_")]
    failed = [c for c in explicit if not c["passed"]]
    crashed = [c for c in case_record.checks if c["name"].startswith("test_") and not c["passed"]]
    step_of = {"test_step1": "步骤1", "test_step2": "步骤2", "test_step3": "步骤3", "test_step4": "步骤4"}
    parts = []
    if "nadir_view_factor_module" in m:
        parts.append(
            f"按设计报告第 5.3 节与表 5 检验 earth_flux 为太阳能板与散热板表面提供的地球反照与红外辐照。"
            f"400 km 对地平板视角系数解析值 {m['nadir_view_factor_analytic']:.4f}，earth_flux 为 "
            f"{m['nadir_view_factor_module']:.4f}，最大相对误差 {pct_small(m['nadir_view_factor_max_rel_error'])}，门限 0.1%。"
        )
    if "step2_worst_criterion" in m:
        parts.append(
            f"β 0° 与 75° 两条 400 km 圆轨道每圈 {N_POS} 个位置，冷、平均、热三组环境值，对地、背地、垂直于当地竖直方向、"
            f"跟踪太阳及其背面共 8 个法向，与独立的地心面元积分和解析倾斜平板视角系数逐点比较，按判据折算的最大相差为 "
            f"{m['step2_worst_criterion'] * 100:.2f}%，门限 1%；参照面元积分与解析视角系数最大绝对差 "
            f"{m.get('reference_quadrature_vs_analytic_max_abs', float('nan')):.6f}，网格加密后参照变化不超过 "
            f"{pct_small(m.get('reference_grid_convergence_max', float('nan')))}，蒙特卡罗校核最大 "
            f"{m.get('reference_monte_carlo_max_sigma', float('nan')):.1f} 倍标准误差。"
        )
    fe_bits = []
    for case, env in ENV.items():
        rows = m.get(f"fe_{case}_loads_summary")
        if not rows:
            continue
        txt = "，".join(f"{k}平均相差 {pct(v['mean_rel'])}、峰值相差 {pct(v['peak_rel'])}" for k, v in rows.items())
        fe_bits.append(f"{env['name']}{txt}")
    if fe_bits:
        parts.append(
            "从已求解的国际空间站有限元模型导出美国太阳翼正面与背面、EATCS 散热器两翼外侧面的太阳波段与红外波段外部辐照；"
            "太阳能板按太阳翼正反两面配置，散热板按散热器两翼外侧面配置，在同一轨道、太阳方向与指向规律下经 run_coupled "
            "运行最后一个轨道周期，比较时间加权平均与峰值热载荷，门限 3%：" + "；".join(fe_bits) + "。"
        )
    diag = []
    for case, env in ENV.items():
        stats = m.get(f"fe_{case}_saw_faces_vs_references")
        if not stats:
            continue
        diag.append(
            f"{env['name']}背面红外 {pct(stats['saw_back_infrared']['fe_minus_reference_rel'])}、背面反照 "
            f"{pct(stats['saw_back_albedo']['fe_minus_reference_rel'])}、正面反照 "
            f"{pct(stats['saw_cells_albedo']['fe_minus_reference_rel'])}"
        )
    if diag:
        radius = m.get("fe_nom0_planet_radius") or {}
        radius_text = ""
        if radius.get("R_planet") and radius.get("nadir_view_factor_change_rel") is not None:
            r_km = str(radius["R_planet"]).split("[")[0]
            radius_text = (f"有限元行星半径 {r_km} km，由此引起的对地平板视角系数变化为 "
                           f"{abs(radius['nadir_view_factor_change_rel']) * 100:.4f}%，可以忽略。")
        spreads = [max(abs(v) for v in s["blanket_spread_rel"]["back_infrared"])
                   for s in (m.get(f"fe_{c}_saw_faces_vs_references") for c in ENV) if s and "blanket_spread_rel" in s]
        spread_text = (f"有限元 16 块毯面之间背面地球红外整周期平均与全体平均相差不超过 {max(spreads) * 100:.2f}%，"
                       "毯面之间的遮挡不能解释上述偏差；" if spreads else "")
        parts.append(
            "在有限元输出时刻，earth_flux 的太阳翼正反面红外与解析倾斜平板视角系数逐点相差不超过 0.1%，反照与地心面元积分逐点相差"
            "不超过 1%；同一时刻有限元整周期平均相对参照的偏差为" + "；".join(diag)
            + "。" + spread_text + "有限元把地球离散为 2 圈每圈 6 个点，太阳翼在掠射角下看到地球时偏差最大；" + radius_text
        )
    inner = []
    for case, env in ENV.items():
        for key, label in (("radiator_inner_P1_up_infrared", "左舷翼内侧面"),
                           ("radiator_inner_S1_down_infrared", "右舷翼内侧面")):
            v = m.get(f"fe_{case}_{key}_mean_W_m2")
            if v and v.get("rel") is not None and abs(v["rel"]) > FE_REL:
                inner.append(f"{env['name']}{label}地球红外 earth_flux 比有限元高 {pct(v['rel'])}")
    if inner:
        parts.append(
            "散热器两翼内侧面在部分姿态下被另一翼挡住地球，" + "，".join(inner)
            + "，设计报告第 4.4 节不计组件间遮挡，这些面只作记录，比较取两翼外侧面。"
        )
    refined = m.get("fe_refined_planet_diagnostic")
    if refined:
        bits = []
        planet = None
        for case, entry in refined.items():
            if "loads" not in entry:
                continue
            planet = entry.get("planet")
            txt = "，".join(f"{k}平均相差 {pct(v['rel_mean'])}" for k, v in entry["loads"].items())
            bits.append(f"{ENV[case]['name']}{txt}")
        if bits and planet:
            parts.append(
                f"诊断计算只把同一有限元模型的地球离散加密到 {planet[0]} 圈每圈 {planet[1]} 个点并重算一圈热载荷，"
                f"earth_flux 与加密后的有限元相比，" + "；".join(bits) + "。"
            )
    if "step4_variants" in m:
        parts.append(
            f"反照或红外记录缺失、空值与非有限值等 {m['step4_variants']} 种异常情形中 {m['step4_reported']} 种被拒绝并指出相应字段或表面，"
            "耦合运行在缺失记录的时刻之前停止，显式关闭反照与红外时归档记录了该简化条件。"
        )
    case_record.summary("".join(parts))
    lines = []
    for c in failed:
        name = c["name"].replace("步骤3 ", "").replace("步骤4 ", "")
        if c["name"].startswith("步骤3") and "热载荷与有限元" in c["name"]:
            lines.append(name + "：" + c["actual"].split("；有限元值")[0])
        else:
            lines.append(name + "未达到判据")
    for c in crashed:
        step = next((v for k, v in step_of.items() if c["name"].startswith(k)), None)
        if step is None or not any(f["name"].startswith(step) for f in failed):
            lines.append(f"测试函数 {c['name'].split(' ')[0]} 未正常完成")
    if lines:
        text = "；".join(lines) + "。"
        if failed and all(c["name"].startswith("步骤3") and "热载荷与有限元" in c["name"] for c in failed):
            text += (
                "另以解析倾斜平板视角系数、独立面元积分与有限元地球离散加密结果核对参照。"
                "离散误差的诊断不能替代原工况的验收结果，3% 门限保持不变。"
            )
        case_record.anomalies(clean_cn(text))
    else:
        case_record.anomalies("无")
    case_record.summary(clean_cn(case_record.summary_cn))
