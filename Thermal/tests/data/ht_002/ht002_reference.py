"""Independent reference calculations of test case HT-002.

Written from the thermal design report alone: T1 of section 4.1, T2 of 4.2, T3 of 4.3, T4 and table 5 of 4.4 and
T5 of 4.5, with the surface environment of 5.3 (satellite-to-Sun direction from the Earth-to-Sun vector minus the
satellite position, normals turned by the active body-to-GCRS quaternion in scalar-last order). It imports nothing
from the ``thermal`` package or from ``sdtwin_sim`` and works on plain Python floats, so its values can serve as
references for ``thermal_derivative``. Sums use ``math.fsum``.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

SIGMA_W_M2_K4 = 5.670374419e-8  # Stefan-Boltzmann constant of design table 5
NODES = ("S", "J", "C", "B", "D", "R")
EXPOSED = ("S", "R")
# Path name, first node, second node; a positive flow goes from the first node to the second (T2).
PATHS = (("SR", "S", "R"), ("JC", "J", "C"), ("CR", "C", "R"), ("BR", "B", "R"), ("DR", "D", "R"))
PORTS = ("P_pv_W", "P_load_W", "Q_B_W", "Q_D_W")

DATA_FILE = Path(__file__).resolve().parent / "ht002_parameters.json"


def load_parameter_sets(path: Path = DATA_FILE) -> dict[str, dict]:
    """Read the parameter sets; a set with ``base`` copies that set and replaces the listed records."""

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    sets: dict[str, dict] = {}
    for name, entry in raw["sets"].items():
        if "base" in entry:
            result = copy.deepcopy(sets[entry["base"]])
            for instance_id, fields in entry.get("replace_components", {}).items():
                matches = [c for c in result["components"] if c["instance_id"] == instance_id]
                if len(matches) != 1:
                    raise ValueError(f"set {name}: component {instance_id} not found once in the base set")
                matches[0].update(copy.deepcopy(fields))
            for path, record in entry.get("replace_connections", {}).items():
                index = [i for i, c in enumerate(result["connections"]) if c["path"] == path]
                if len(index) != 1:
                    raise ValueError(f"set {name}: connection {path} not found once in the base set")
                result["connections"][index[0]] = copy.deepcopy(record)
        else:
            result = {"components": copy.deepcopy(entry["components"]), "connections": copy.deepcopy(entry["connections"])}
        sets[name] = result
    return sets


def path_resistance(record: dict) -> float:
    """Second line of T5, or a supplied equivalent total that already holds the contact part (design 4.5)."""

    if "equivalent_total_resistance_K_W" in record:
        total = float(record["equivalent_total_resistance_K_W"])
        if record["includes_contact"]:
            return total
        return total + float(record["contact_resistance_K_W"])
    conduction = float(record["length_m"]) / (float(record["conductivity_W_mK"]) * float(record["area_m2"]))
    return conduction + float(record["contact_resistance_K_W"])


def rotate_active_xyzw(quaternion, vector) -> tuple[float, float, float]:
    """Active rotation of ``vector`` by the unit quaternion (x, y, z, w): v' = v + w t + u x t with t = 2 u x v."""

    x, y, z, w = (float(c) for c in quaternion)
    vx, vy, vz = (float(c) for c in vector)
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def sun_direction(position_m, sun_position_m) -> tuple[float, float, float]:
    """Unit satellite-to-Sun direction from the Earth-to-Sun vector minus the satellite position (design 5.3)."""

    d = [float(s) - float(p) for s, p in zip(sun_position_m, position_m)]
    norm = math.sqrt(math.fsum(c * c for c in d))
    return (d[0] / norm, d[1] / norm, d[2] / norm)


class ReferenceModel:
    """Capacitances, resistances and surfaces of one parameter set, evaluated with T1 to T5 by hand."""

    def __init__(self, parameter_set: dict) -> None:
        components = parameter_set["components"]
        portions: dict[str, list[float]] = {node: [] for node in NODES}
        ranges: dict[str, list[tuple[float, float]]] = {node: [] for node in NODES}
        self.surfaces: list[dict] = []
        for component in components:
            node = component["node_id"]
            for material in component["materials"]:
                portions[node].append(float(material["mass_kg"]) * float(material["cp_J_kgK"]))
            low, high = (float(v) for v in component["temperature_range_K"])
            ranges[node].append((low, high))
            for surface in component.get("surfaces", []):
                self.surfaces.append(
                    {
                        "surface_id": surface["surface_id"],
                        "node_id": node,
                        "area_m2": float(surface["area_m2"]),
                        "normal_body": tuple(float(v) for v in surface["normal_body"]),
                        "absorptivity": float(surface["absorptivity"]),
                        "emissivity": float(surface["emissivity"]),
                    }
                )
        # First line of T5: C_i = sum over the material portions of m c_p.
        self.C = {node: math.fsum(portions[node]) for node in NODES}
        self.R = {path: path_resistance(next(c for c in parameter_set["connections"] if c["path"] == path))
                  for path, _, _ in PATHS}
        # Range in which the constants of a node apply: common interval of its instances.
        self.ranges = {node: (max(r[0] for r in ranges[node]), min(r[1] for r in ranges[node])) for node in NODES}
        self.surface_ids = tuple(surface["surface_id"] for surface in self.surfaces)

    def with_resistance(self, path: str, value: float) -> "ReferenceModel":
        other = copy.copy(self)
        other.R = dict(self.R)
        other.R[path] = float(value)
        return other

    # ------------------------------------------------------------------ environment and T4
    def cos_incidence(self, position_m, sun_position_m, quaternion_xyzw) -> list[float]:
        s = sun_direction(position_m, sun_position_m)
        result = []
        for surface in self.surfaces:
            n = rotate_active_xyzw(quaternion_xyzw, surface["normal_body"])
            result.append(n[0] * s[0] + n[1] * s[1] + n[2] * s[2])
        return result

    def absorbed_solar_S(self, G_W_m2: float, cosines) -> float:
        """Direct sunlight absorbed by the S surfaces: sum of A alpha G max(0, cos) (design 4.4, 5.4)."""

        values = []
        for surface, cos_f in zip(self.surfaces, cosines):
            if surface["node_id"] == "S":
                g_sun = float(G_W_m2) * max(0.0, float(cos_f))
                values.append(surface["area_m2"] * surface["absorptivity"] * g_sun)
        return math.fsum(values)

    def surface_heat(self, temperature: dict, G_W_m2: float, cosines, albedo, infrared) -> tuple[dict, dict]:
        """T4: Q_env,i = sum A [alpha (g_sun + g_alb) + eps g_IR], Q_emit,i = sum eps sigma A T_i^4, i in S, R."""

        absorbed = {node: [] for node in EXPOSED}
        emitted = {node: [] for node in EXPOSED}
        for surface, cos_f, g_alb, g_ir in zip(self.surfaces, cosines, albedo, infrared, strict=True):
            node = surface["node_id"]
            area = surface["area_m2"]
            alpha = surface["absorptivity"]
            eps = surface["emissivity"]
            g_sun = float(G_W_m2) * max(0.0, float(cos_f))
            absorbed[node].append(area * (alpha * (g_sun + float(g_alb)) + eps * float(g_ir)))
            emitted[node].append(eps * SIGMA_W_M2_K4 * area * float(temperature[node]) ** 4)
        return ({node: math.fsum(absorbed[node]) for node in EXPOSED},
                {node: math.fsum(emitted[node]) for node in EXPOSED})

    # ------------------------------------------------------------------ T2, T3 and T1
    def heat_flows(self, temperature: dict) -> dict:
        """T2: q_ij = (T_i - T_j) / R_ij for every path."""

        return {path: (float(temperature[i]) - float(temperature[j])) / self.R[path] for path, i, j in PATHS}

    @staticmethod
    def node_terms(q: dict, Q_env: dict, Q_emit: dict, ports: dict) -> dict:
        """Signed terms of the right side of each line of T3."""

        return {
            "S": [Q_env["S"], -ports["P_pv_W"], -q["SR"], -Q_emit["S"]],
            "J": [ports["P_load_W"], -q["JC"]],
            "C": [q["JC"], -q["CR"]],
            "B": [ports["Q_B_W"], -q["BR"]],
            "D": [ports["Q_D_W"], -q["DR"]],
            "R": [q["SR"], q["CR"], q["BR"], q["DR"], Q_env["R"], -Q_emit["R"]],
        }

    @staticmethod
    def t1_terms(Q_env: dict, Q_emit: dict, ports: dict) -> list[float]:
        """Right side of T1: Q_env,S + Q_env,R - P_pv + P_load + Q_B + Q_D - Q_emit,S - Q_emit,R."""

        return [Q_env["S"], Q_env["R"], -ports["P_pv_W"], ports["P_load_W"], ports["Q_B_W"], ports["Q_D_W"],
                -Q_emit["S"], -Q_emit["R"]]

    def evaluate(self, temperature: dict, position_m, sun_position_m, quaternion_xyzw, G_W_m2, albedo, infrared,
                 ports: dict) -> dict:
        """All reference quantities of one evaluation; derivatives are the T3 rows divided by C_i."""

        cosines = self.cos_incidence(position_m, sun_position_m, quaternion_xyzw)
        Q_env, Q_emit = self.surface_heat(temperature, G_W_m2, cosines, albedo, infrared)
        q = self.heat_flows(temperature)
        terms = self.node_terms(q, Q_env, Q_emit, ports)
        rows = {node: math.fsum(terms[node]) for node in NODES}
        gross = {node: math.fsum(abs(t) for t in terms[node]) for node in NODES}
        t1 = self.t1_terms(Q_env, Q_emit, ports)
        return {
            "cos_incidence": cosines,
            "Q_env": Q_env,
            "Q_emit": Q_emit,
            "q": q,
            "terms": terms,
            "rows_W": rows,
            "gross_W": gross,
            "dT_dt_K_s": {node: rows[node] / self.C[node] for node in NODES},
            "t1_terms": t1,
            "t1_rhs_W": math.fsum(t1),
        }
