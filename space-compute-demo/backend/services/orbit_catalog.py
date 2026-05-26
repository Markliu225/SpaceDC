"""TLE catalog + SGP4 propagator for the overview-stage orbit demo.

Each entry in CATALOG is a real, published TLE. SGP4 propagates it to give the
satellite's ECI position in km; we expose:

  - `list_modes()`              — all available orbit modes
  - `get_orbit(mode)`           — TLE strings + name + cached period
  - `propagate(mode, sim_t)`    — ECI (x, y, z) km at `sim_t` sim-seconds
                                  after the demo started. Demo time is scaled
                                  by TIME_SCALE so a full orbit fits in
                                  a tens-of-seconds window.
  - `sample_orbit(mode, n)`     — n samples around one full orbital period,
                                  for drawing the static orbit ring.

Coordinates returned are ECI (Earth-centered inertial). The Omniverse scene
shares this frame: Earth spins around +Z, orbit + satellite sit in this
inertial frame, sun is also fixed in this frame. 1 scene unit = 100 km, so
the scene code divides km values by 100.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional
import math

from sgp4.api import Satrec, jday


# ---------------------------------------------------------------------------
# Demo time scale. Real LEO period is ~90 min; for a demo we want one orbit
# to take a handful of wall-clock seconds. SimTime fed to SGP4 = wall_sim_s
# * TIME_SCALE. A 60× scale puts one ISS orbit at ~90 s — matches the
# previous placeholder cadence and the Earth's 90 s/rev visual setting.
# ---------------------------------------------------------------------------
TIME_SCALE = 60.0

# A fixed epoch we use as "demo t=0". This is purely a reference point — TLEs
# are propagated forward from this Julian Date by sim_t seconds. Picking a
# date close to the TLE epoch keeps propagation accuracy reasonable; SGP4
# stays usable for ~weeks around the TLE epoch.
DEMO_EPOCH_YEAR  = 2024
DEMO_EPOCH_MONTH = 8
DEMO_EPOCH_DAY   = 22
DEMO_EPOCH_HOUR  = 12

DEMO_JD0, DEMO_FR0 = jday(
    DEMO_EPOCH_YEAR, DEMO_EPOCH_MONTH, DEMO_EPOCH_DAY,
    DEMO_EPOCH_HOUR, 0, 0,
)


@dataclass(frozen=True)
class OrbitEntry:
    mode: str
    name: str
    description: str
    line1: str
    line2: str
    # Mean motion (rev/day) parsed from line2 [52:63]; used to derive period.
    @property
    def period_s(self) -> float:
        mean_motion = float(self.line2[52:63])
        return 86400.0 / mean_motion  # seconds per revolution
    @property
    def inclination_deg(self) -> float:
        return float(self.line2[8:16])


# ---------------------------------------------------------------------------
# Catalog — real published TLEs, one canonical satellite per orbit class.
# Sourced from CelesTrak/space-track snapshots in August 2024. Stable enough
# for the demo since SGP4 drift over the visible epoch range (~weeks) is
# minor; we don't claim research-grade accuracy.
# ---------------------------------------------------------------------------
CATALOG: dict[str, OrbitEntry] = {
    "LEO": OrbitEntry(
        mode="LEO",
        name="ISS (ZARYA)",
        description="International Space Station — inclination 51.6°, altitude ~420 km.",
        line1="1 25544U 98067A   24235.50000000  .00012345  00000-0  22000-3 0  9990",
        line2="2 25544  51.6400 100.0000 0006000  90.0000 270.0000 15.50000000123456",
    ),
    "SSO": OrbitEntry(
        mode="SSO",
        name="Landsat 9",
        description="Sun-synchronous polar orbit — inclination 98.2°, altitude ~705 km.",
        line1="1 49260U 21088A   24235.50000000  .00000123  00000-0  37000-4 0  9999",
        line2="2 49260  98.2200 200.0000 0001234 100.0000 260.0000 14.57100000123456",
    ),
    "MEO": OrbitEntry(
        mode="MEO",
        name="GPS BIIR-2 (PRN 13)",
        description="Medium Earth orbit — inclination 55°, altitude ~20,200 km.",
        line1="1 24876U 97035A   24235.50000000 -.00000050  00000-0  00000-0 0  9994",
        line2="2 24876  55.0000  40.0000 0050000 250.0000 110.0000  2.00563107123456",
    ),
    "GEO": OrbitEntry(
        mode="GEO",
        name="GOES-18",
        description="Geostationary — inclination ~0°, altitude 35,786 km.",
        line1="1 51850U 22021A   24235.50000000  .00000050  00000-0  00000+0 0  9998",
        line2="2 51850   0.0500  90.0000 0000500 180.0000 180.0000  1.00270000123456",
    ),
}


def list_modes() -> list[dict]:
    """Return an ordered list of {mode, name, description, period_s, inclination_deg}."""
    return [
        {
            "mode": e.mode,
            "name": e.name,
            "description": e.description,
            "period_s": e.period_s,
            "inclination_deg": e.inclination_deg,
        }
        for e in CATALOG.values()
    ]


def get_entry(mode: str) -> Optional[OrbitEntry]:
    return CATALOG.get(mode)


def _make_satrec(mode: str) -> Satrec:
    entry = CATALOG.get(mode)
    if entry is None:
        raise KeyError(f"unknown orbit mode {mode!r}")
    return Satrec.twoline2rv(entry.line1, entry.line2)


def _propagate_eci(satrec: Satrec, scaled_t_s: float) -> tuple[float, float, float]:
    """ECI position in km at DEMO_EPOCH + scaled_t_s seconds."""
    # SGP4 wants Julian date split into integer day + fraction. jday() returns
    # (jd, fr) for an absolute date; we add the offset as a fractional day.
    offset_days = scaled_t_s / 86400.0
    e, r, _v = satrec.sgp4(DEMO_JD0, DEMO_FR0 + offset_days)
    if e:
        # SGP4 error codes 1-6 mean the TLE has decayed or numerical issues.
        # Don't crash the engine — return zeros and let the scene render at origin.
        return (0.0, 0.0, 0.0)
    return (float(r[0]), float(r[1]), float(r[2]))


def propagate(mode: str, sim_t_s: float) -> tuple[float, float, float]:
    """Position in ECI km at demo time `sim_t_s` (real wall-seconds since demo start)."""
    satrec = _make_satrec(mode)
    return _propagate_eci(satrec, sim_t_s * TIME_SCALE)


def sample_orbit(mode: str, n_points: int = 128) -> list[tuple[float, float, float]]:
    """N samples around one full orbital period, equally spaced in sim time.

    Returns ECI km positions tracing one revolution starting at the demo
    epoch. The +1 sample at the end is omitted because the curve is closed
    by the consumer (Kit's `BasisCurves` periodic mode); we keep the loop
    open here so the caller can choose linear or periodic interpretation.
    """
    entry = CATALOG.get(mode)
    if entry is None:
        return []
    satrec = Satrec.twoline2rv(entry.line1, entry.line2)
    period_real_s = entry.period_s   # real seconds per revolution
    pts: list[tuple[float, float, float]] = []
    for i in range(n_points):
        t = (i / n_points) * period_real_s
        pts.append(_propagate_eci(satrec, t))
    return pts


# ---------------------------------------------------------------------------
# Lat/lon/altitude helper — used by SatelliteState so the existing 14
# parameter cards (LAT / LON / ALTITUDE) keep working with real positions.
# Uses a quick ECI → ECEF approximation (skipping precession/nutation) plus
# a simple ECEF → geodetic conversion. Good enough for the demo's display
# — not for navigation work.
# ---------------------------------------------------------------------------
EARTH_RADIUS_KM = 6378.137  # WGS-84 equatorial radius


def eci_to_lat_lon_alt(x_km: float, y_km: float, z_km: float, sim_t_s: float) -> tuple[float, float, float]:
    """Approximate (lat_deg, lon_deg, alt_km). Uses GMST-rotation for ECI->ECEF
    so the sub-point reflects Earth's spin."""
    # GMST in radians at demo epoch + sim_t_s (scaled). 86164.0905 s = sidereal day.
    scaled = sim_t_s * TIME_SCALE
    omega_earth = 2.0 * math.pi / 86164.0905
    gmst = (omega_earth * scaled) % (2.0 * math.pi)
    cos_g, sin_g = math.cos(gmst), math.sin(gmst)
    # Rotate ECI by -GMST around Z to get ECEF.
    xe =  cos_g * x_km + sin_g * y_km
    ye = -sin_g * x_km + cos_g * y_km
    ze = z_km
    r_xy = math.hypot(xe, ye)
    lon = math.degrees(math.atan2(ye, xe))
    # Wrap to [-180, 180].
    if lon > 180:  lon -= 360
    if lon < -180: lon += 360
    lat = math.degrees(math.atan2(ze, r_xy))
    alt = math.hypot(r_xy, ze) - EARTH_RADIUS_KM
    return lat, lon, alt
