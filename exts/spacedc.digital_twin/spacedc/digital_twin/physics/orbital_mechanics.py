"""
============================================================
  orbital_mechanics.py — Orbit angle, eclipse detection, RAAN
  Migrated from: js/canvas.js (getAngle, isEclipse) + js/orbit.js
============================================================
"""
import math
from .constants import ORBIT_PERIOD, ECLIPSE_FRAC, ECLIPSE_START


def get_angle(sim_time: float) -> float:
    """
    Current true-anomaly-like angle (radians) from simulation time.
    Equivalent to JS ``getAngle(t)``.
    """
    return (sim_time / ORBIT_PERIOD) * math.pi * 2.0


def is_eclipse(angle: float) -> bool:
    """
    Determine if the satellite is in Earth's shadow at the given angle.
    Equivalent to JS ``isEclipse(a)``.
    """
    n = angle % (math.pi * 2.0)
    if n < 0:
        n += math.pi * 2.0
    return n > ECLIPSE_START and n < (ECLIPSE_START + ECLIPSE_FRAC * math.pi * 2.0)


def get_orbit_position(sim_time: float, orbit_radius: float = 3.4, tilt_deg: float = 7.6):
    """
    Satellite position in 3-D orbit space (matches orbit3d.js).

    Returns:
        (x, y, z) tuple in scene units.
    """
    angle = get_angle(sim_time)
    tilt = math.radians(tilt_deg)
    sx = math.cos(angle) * orbit_radius
    rz = math.sin(angle) * orbit_radius
    return (sx, rz * math.sin(tilt), rz * math.cos(tilt))


def get_raan(met_seconds: float) -> float:
    """Right Ascension of Ascending Node (degrees), drifting ~0.9856°/day."""
    return (156.3 + (met_seconds / 86400.0) * 0.9856) % 360.0


def get_true_anomaly_deg(sim_time: float) -> float:
    """Current angle in degrees (0-360)."""
    return (math.degrees(get_angle(sim_time))) % 360.0


def get_sun_beta_angle(sim_time: float) -> float:
    """Approximate beta angle oscillation (degrees)."""
    return 2.3 + math.sin(sim_time * 0.0001) * 0.5
