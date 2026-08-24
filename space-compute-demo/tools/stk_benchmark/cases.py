# -*- coding: utf-8 -*-
"""Shared benchmark case definitions — single source of truth for both sides.

Kept stdlib-only: imported by stk_ref.py (system Python + pywin32) and by
ours_ref.py / compare_report.py (backend .venv Python).

Scenario epoch equals the engine's DEMO epoch (services/orbit_catalog.py):
2024-08-22 12:00:00 UTC. All exported time columns are seconds from it.
"""

import os

# --- timeline ---------------------------------------------------------------
EPOCH_UTCG = "22 Aug 2024 12:00:00.000"          # STK Connect/scenario format
EPOCH_ISO = "2024-08-22T12:00:00Z"
EPOCH_JDAY = (2024, 8, 22, 12, 0, 0)             # args for sgp4.api.jday
DURATION_S = 86400.0
STOP_UTCG = "23 Aug 2024 12:00:00.000"
STEP_S = 60.0                                    # time-series cadence
EVENT_STEP_S = 1.0                               # our-side event root sampling

# --- TLE cases (verbatim from backend services/orbit_catalog.py CATALOG) ----
# STK validates checksums; fix them there via fix_checksum() without touching
# any orbital field. The python sgp4 package ignores checksums, so the engine
# side consumes these lines as-is.
TLE_CASES = {
    "leo_iss": {
        "line1": "1 25544U 98067A   24235.50000000  .00012345  00000-0  22000-3 0  9990",
        "line2": "2 25544  51.6400 100.0000 0006000  90.0000 270.0000 15.50000000123456",
        "access": True,
    },
    "sso_landsat": {
        "line1": "1 49260U 21088A   24235.50000000  .00000123  00000-0  37000-4 0  9999",
        "line2": "2 49260  98.2200 200.0000 0001234 100.0000 260.0000 14.57100000123456",
        "access": True,
    },
    "geo_goes": {
        "line1": "1 51850U 22021A   24235.50000000  .00000050  00000-0  00000+0 0  9998",
        "line2": "2 51850   0.0500  90.0000 0000500 180.0000 180.0000  1.00270000123456",
        "access": False,   # GOES slot not visible from Singapore; eclipse/thermal only
    },
}


def fix_checksum(line):
    """Recompute the TLE checksum column (STK rejects bad ones; sgp4 ignores)."""
    s = 0
    for ch in line[:68]:
        if ch.isdigit():
            s += int(ch)
        elif ch == "-":
            s += 1
    return line[:68] + str(s % 10)


# --- ground station (backend models.py GroundTarget defaults) ---------------
GS_NAME = "Singapore"
GS_LAT_DEG = 1.3521
GS_LON_DEG = 103.8198
GS_ALT_M = 0.0
ELEVATION_MASKS_DEG = [0.0, 5.0, 10.0, 20.0]

# --- power case (baseline design values from backend state_engine.py) -------
SOLAR_CONSTANT_W_M2 = 1361.0                     # engine _SOLAR_CONSTANT_W_M2
SOLAR_EFFICIENCY = 0.32                          # GaAs row of _SOLAR_MAT_TABLE
# baseline TwinGeometry: 4 clusters/side, cluster area from state_engine.py:294
_SOLAR_CLUSTER_M2 = (0.981 * 1.45 * 1.8) * (0.777 * 1.05 * 1.8)
SOLAR_AREA_M2 = 4 * 2 * _SOLAR_CLUSTER_M2        # ≈ 30.08 m²

BATTERY_CAPACITY_WH = 8000.0                     # LiIon × L pack
BATTERY_CHARGE_EFF = 0.95
LOAD_W = 3000.0                                  # 2400 W payload + 600 W platform

# --- thermal case (SEET-comparable isothermal sphere) ------------------------
THERM_SHAPE = "Sphere"
THERM_CROSS_SECTION_M2 = 10.0                    # SEET CrossSectionalArea (π r²)
THERM_RADIATING_AREA_M2 = 4.0 * THERM_CROSS_SECTION_M2   # sphere surface = 4πr²
THERM_ABSORPTIVITY = 0.25                        # white paint α
THERM_EMISSIVITY = 0.85                          # white paint ε (engine table)
THERM_EARTH_ALBEDO = 0.30
THERM_DISSIPATION_W = 2850.0                     # (2400+600)×0.95 — engine Q_in rule
THERM_C_TH_J_PER_K = 160_000.0                   # engine THERMAL_MASS_J_PER_K

# --- output layout -----------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
STK_OUT = os.path.join(OUT_DIR, "stk")
OURS_OUT = os.path.join(OUT_DIR, "ours")
