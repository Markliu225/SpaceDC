"""
============================================================
  orbital_mechanics.py — Orbit angle, eclipse detection, RAAN
  Migrated from: js/canvas.js (getAngle, isEclipse) + js/orbit.js
============================================================
"""
import math
from .constants import ORBIT_PERIOD, ECLIPSE_FRAC, ECLIPSE_START


def get_angle(sim_time: float, orbit_period: float = 5742.0) -> float:
    """
    Current true-anomaly-like angle (radians) from simulation time.
    Uses configurable orbit_period.
    """
    return (sim_time / orbit_period) * math.pi * 2.0


def is_eclipse(angle: float, eclipse_frac: float = 0.36) -> bool:
    """
    Determine if the satellite is in Earth's shadow at the given angle.
    Uses configurable eclipse fraction.
    """
    n = angle % (math.pi * 2.0)
    if n < 0:
        n += math.pi * 2.0
    
    # Calculate shadow start/end symmetrically around π (midnight)
    # Total shadow arc = 2π * eclipse_frac
    # Start = π - (π * eclipse_frac), End = π + (π * eclipse_frac)
    shadow_half_arc = math.pi * eclipse_frac
    start = math.pi - shadow_half_arc
    end = math.pi + shadow_half_arc
    return n > start and n < end


def get_orbit_position(sim_time: float, orbit_radius: float = 3.4, tilt_deg: float = 97.6, orbit_period: float = 5742.0):
    """
    Satellite position in 3-D orbit space.
    Uses dynamic tilt and period.
    """
    angle = get_angle(sim_time, orbit_period)
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
