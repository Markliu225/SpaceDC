"""validate_elements.py — audit the OE<->RV layer (services/elements.py).

Offline (no server): imports the backend modules directly. Gates follow the
NTU SDCTwin test report CV-001/CV-002 acceptance criteria:
  - valid nonsingular round-trip: |dr| <= 1e-8 km, |dv| <= 1e-10 km/s
  - nonsingular element recovery: dimensionless <= 1e-10, angles <= 1e-8 rad
  - singular cases (circular / equatorial / retrograde / both) reconstruct
    the SAME Cartesian state to the SAME tolerance, with the documented
    deterministic conventions (never NaN)
  - invalid inputs raise explicit errors (no plausible-but-wrong states)
Plus an engine-in-the-loop check: one tick produces broadcast osculating
elements consistent with the active TLE.

Run: backend/.venv/Scripts/python tools/validate_elements.py
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "backend"))

from services import elements as el  # noqa: E402
from services import orbit_catalog as oc  # noqa: E402

_results: list[tuple[bool, str]] = []


def check(ok: bool, msg: str) -> None:
    _results.append((ok, msg))
    print(f"  {'PASS' if ok else 'FAIL'}  {msg}")


def d3(a, b):
    return math.dist(a, b)


CASES = [
    # name, a_km, e, i_deg, raan_deg, argp_deg, nu_deg, singular?
    ("nominal LEO (NTU OD-001 state)", 7000.0, 0.001, 98.0, 40.0, 30.0, 10.0, False),
    ("high-eccentricity (Molniya-ish)", 26562.0, 0.72, 63.4, 245.0, 270.0, 40.0, False),
    ("polar", 7378.0, 0.01, 90.0, 10.0, 80.0, 300.0, False),
    ("near-wrap angles", 7000.0, 0.05, 45.0, 359.9999, 0.0001, 359.9999, False),
    ("circular inclined", 6928.0, 0.0, 51.6, 100.0, 0.0, 200.0, True),
    ("elliptic equatorial", 8000.0, 0.3, 0.0, 0.0, 75.0, 120.0, True),
    ("elliptic equatorial retrograde", 8000.0, 0.2, 180.0, 0.0, 75.0, 120.0, True),
    ("circular equatorial", 42164.0, 0.0, 0.0, 0.0, 0.0, 123.0, True),
    ("circular equatorial retrograde", 42164.0, 0.0, 180.0, 0.0, 0.0, 123.0, True),
]


def main() -> int:
    print("== validate_elements: OE<->RV round-trips, conventions, errors ==")

    # ---- A. round-trips at the CV-001/CV-002 gates -----------------------
    for name, a, e, i, O, w, nu in [(c[0], *c[1:7]) for c in CASES]:
        singular = dict((c[0], c[7]) for c in CASES)[name]
        r, v = el.oe_to_rv(a, e, math.radians(i), math.radians(O),
                           math.radians(w), math.radians(nu))
        oe = el.rv_to_oe(r, v)
        r2, v2 = el.oe_to_rv(oe["a_km"], oe["e"], oe["inc_rad"],
                             oe["raan_rad"], oe["argp_rad"], oe["nu_rad"])
        dr, dv = d3(r, r2), d3(v, v2)
        check(dr <= 1e-8 and dv <= 1e-10,
              f"round-trip [{name}]: |dr| {dr:.2e} km <= 1e-8, |dv| {dv:.2e} <= 1e-10")
        if not singular:
            da = abs(oe["a_km"] - a) / a
            de = abs(oe["e"] - e)
            dang = max(abs(oe["inc_rad"] - math.radians(i)),
                       abs(oe["raan_rad"] - math.radians(O)) % (2 * math.pi),
                       abs(oe["argp_rad"] - math.radians(w)) % (2 * math.pi),
                       abs(oe["nu_rad"] - math.radians(nu)) % (2 * math.pi))
            dang = min(dang, 2 * math.pi - dang)
            check(da <= 1e-10 and de <= 1e-10 and dang <= 1e-8,
                  f"element recovery [{name}]: da/a {da:.1e}, de {de:.1e}, "
                  f"worst angle {dang:.1e} rad")

    # ---- B. two-body invariants ------------------------------------------
    r, v = el.oe_to_rv(7000.0, 0.001, math.radians(98), math.radians(40),
                       math.radians(30), math.radians(10))
    mu = el.MU_EARTH_KM3_S2
    energy = 0.5 * d3(v, (0, 0, 0)) ** 2 - mu / d3(r, (0, 0, 0))
    check(abs(energy - (-mu / (2 * 7000.0))) / (mu / (2 * 7000.0)) <= 1e-12,
          "vis-viva: specific energy == -mu/2a to 1e-12 relative")
    h = (r[1] * v[2] - r[2] * v[1], r[2] * v[0] - r[0] * v[2],
         r[0] * v[1] - r[1] * v[0])
    h_expect = math.sqrt(mu * 7000.0 * (1 - 0.001 ** 2))
    check(abs(d3(h, (0, 0, 0)) - h_expect) / h_expect <= 1e-12,
          "angular momentum |h| == sqrt(mu*p) to 1e-12 relative")

    # ---- C. singular-case conventions ------------------------------------
    r, v = el.oe_to_rv(6928.0, 0.0, math.radians(51.6), math.radians(100.0),
                       0.0, math.radians(200.0))
    oe = el.rv_to_oe(r, v)
    check(oe["argp_rad"] == 0.0 and abs(math.degrees(oe["nu_rad"]) - 200.0) < 1e-6,
          "circular: argp := 0, anomaly = argument of latitude")
    r, v = el.oe_to_rv(8000.0, 0.3, 0.0, 0.0, math.radians(75.0),
                       math.radians(120.0))
    oe = el.rv_to_oe(r, v)
    check(oe["raan_rad"] == 0.0 and abs(math.degrees(oe["argp_rad"]) - 75.0) < 1e-6,
          "equatorial: raan := 0, argp = longitude of periapsis")
    r, v = el.oe_to_rv(42164.0, 0.0, math.radians(180.0), 0.0, 0.0,
                       math.radians(123.0))
    oe = el.rv_to_oe(r, v)
    check(abs(math.degrees(oe["nu_rad"]) - 123.0) < 1e-6
          and abs(math.degrees(oe["inc_rad"]) - 180.0) < 1e-9,
          "retrograde circular equatorial: true longitude keeps its sign convention")

    # ---- D. explicit rejection of invalid input --------------------------
    for label, fn in [
        ("oe_to_rv rejects e >= 1", lambda: el.oe_to_rv(8000.0, 1.0, 0, 0, 0, 0)),
        ("oe_to_rv rejects a <= 0", lambda: el.oe_to_rv(-7000.0, 0.1, 0, 0, 0, 0)),
        ("rv_to_oe rejects hyperbolic",
         lambda: el.rv_to_oe((7000.0, 0.0, 0.0), (0.0, 12.0, 0.0))),
        ("rv_to_oe rejects radial",
         lambda: el.rv_to_oe((7000.0, 0.0, 0.0), (1.0, 0.0, 0.0))),
        ("rv_to_oe rejects zero position",
         lambda: el.rv_to_oe((0.0, 0.0, 0.0), (1.0, 2.0, 3.0))),
    ]:
        try:
            fn()
            check(False, label + " (no exception raised)")
        except ValueError:
            check(True, label)

    # ---- E. against the live SGP4 catalog state --------------------------
    from sgp4.api import Satrec
    entry = oc.CATALOG["LEO"]
    sat = Satrec.twoline2rv(entry.line1, entry.line2)
    err, r, v = sat.sgp4(oc.DEMO_JD0, oc.DEMO_FR0)
    oe = el.rv_to_oe(r, v)
    di = abs(math.degrees(oe["inc_rad"]) - entry.inclination_deg)
    check(err == 0 and di <= 0.05,
          f"osculating inclination within 0.05 deg of the TLE ({di:.4f})")
    p_osc = el.period_s(oe["a_km"])
    check(abs(p_osc - entry.period_s) / entry.period_s <= 0.01,
          f"osculating period within 1% of the TLE mean period "
          f"({p_osc:.0f}s vs {entry.period_s:.0f}s — mean vs osculating)")

    # ---- F. engine in the loop -------------------------------------------
    import state_engine
    eng = state_engine.StateEngine(lambda s: None)
    eng._sim_time_s = 0.0
    eng._update_placeholder_physics(1.0)
    oe_b = eng._sat.orbital_elements
    check(oe_b is not None, "engine broadcasts orbital_elements after one tick")
    if oe_b is not None:
        check(abs(oe_b.inclination_deg - entry.inclination_deg) <= 0.1
              and 0.0 <= oe_b.eccentricity < 0.01
              and oe_b.perigee_alt_km > 300.0,
              f"broadcast elements match the active TLE (i={oe_b.inclination_deg:.2f}, "
              f"e={oe_b.eccentricity:.5f}, hp={oe_b.perigee_alt_km:.0f} km)")

    fails = [m for ok, m in _results if not ok]
    print()
    print(f"{len(fails)} FAILED" if fails else f"ALL {len(_results)} ELEMENT CHECKS PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
