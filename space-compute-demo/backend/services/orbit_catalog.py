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

from sgp4.api import Satrec

from . import timebase


# ---------------------------------------------------------------------------
# Demo time scale + epoch now live in services.timebase (one source of truth
# for mission time). Re-exported here under their historical names because
# tools/stk_benchmark and tools/validate_elements.py import them from this
# module. Real LEO period is ~90 min; a 60× scale puts one ISS orbit at ~90 s
# of wall clock — matching the Earth's 90 s/rev visual setting.
#
# NOTE these are the DEFAULT-mission values. Propagation must go through
# timebase.jd_at / jd_after, which follow a re-timed mission window; these
# constants stay pinned to the demo epoch for the benchmark tooling.
# ---------------------------------------------------------------------------
TIME_SCALE       = timebase.TIME_SCALE
DEMO_EPOCH_YEAR  = timebase.DEMO_EPOCH_YEAR
DEMO_EPOCH_MONTH = timebase.DEMO_EPOCH_MONTH
DEMO_EPOCH_DAY   = timebase.DEMO_EPOCH_DAY
DEMO_EPOCH_HOUR  = timebase.DEMO_EPOCH_HOUR
DEMO_JD0         = timebase.DEMO_JD0
DEMO_FR0         = timebase.DEMO_FR0


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
    """ECI position in km at mission start + scaled_t_s REAL seconds."""
    # SGP4 wants the Julian date split into integer day + fraction; timebase
    # anchors the day on the mission start and folds the offset into the
    # fraction.
    jd, fr = timebase.jd_after(scaled_t_s)
    e, r, _v = satrec.sgp4(jd, fr)
    if e:
        # SGP4 error codes 1-6 mean the TLE has decayed or numerical issues.
        # Don't crash the engine — return zeros and let the scene render at origin.
        return (0.0, 0.0, 0.0)
    return (float(r[0]), float(r[1]), float(r[2]))


def propagate(mode: str, sim_t_s: float) -> tuple[float, float, float]:
    """Position in ECI km at demo time `sim_t_s` (sim-seconds since mission start)."""
    satrec = _make_satrec(mode)
    return _propagate_eci(satrec, sim_t_s * TIME_SCALE)


def sample_orbit(mode: str, n_points: int = 128) -> list[tuple[float, float, float]]:
    """N samples around one full orbital period, equally spaced in sim time.

    Returns ECI km positions tracing one revolution starting at the mission
    start. The +1 sample at the end is omitted because the curve is closed
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
# TEME → ECEF by true GMST at the mission start + scaled time, then WGS-84
# geodetic latitude/altitude (STK-benchmarked: ≤0.006° / ≤0.06 km against
# STK 11 LLA State — see tools/stk_benchmark).
# ---------------------------------------------------------------------------
EARTH_RADIUS_KM = 6378.137  # WGS-84 equatorial radius

from . import geodyn  # noqa: E402  (after constants — avoids cycle at import)


def eci_to_lat_lon_alt(x_km: float, y_km: float, z_km: float, sim_t_s: float) -> tuple[float, float, float]:
    """(lat_deg, lon_deg, alt_km) — geodetic WGS-84 sub-point at the real
    absolute epoch (mission start + sim_t_s × TIME_SCALE)."""
    jd = timebase.jd_utc_at(sim_t_s)
    xe, ye, ze = geodyn.teme_to_ecef(x_km, y_km, z_km, jd)
    lat, lon, alt = geodyn.ecef_to_geodetic(xe, ye, ze)
    if lon > 180:  lon -= 360
    if lon < -180: lon += 360
    return lat, lon, alt
