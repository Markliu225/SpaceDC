"""Constellation catalog (Architecture A — Walker delta pattern).

Each preset declares ONE reference TLE plus Walker parameters `i: t/p/f`:
  - i  : inclination (deg, taken straight from the base TLE)
  - t  : total satellites
  - p  : number of orbital planes
  - f  : phasing offset (relative phase between adjacent planes)

At preset load we DERIVE a full fleet of `t` sgp4.Satrec objects by patching
the base TLE's RAAN (per plane) and mean anomaly (per sat within plane).
All other elements (inclination, eccentricity, mean motion, BSTAR, …) are
shared with the reference. This is the standard Walker constellation
construction and a faithful idealisation of real systems like Starlink,
OneWeb, GPS Block IIR, and Iridium.

KPI synthesis is intentionally formulaic — the goal is a demo where the
numbers SHIFT visibly when you switch presets, not research-grade
modelling. Hard-coded per-preset coverage / throughput / link counts are
the cleanest way to get that.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from sgp4.api import Satrec, jday


# ---------------------------------------------------------------------------
# Demo time scale (shared with orbit_catalog so single-sat demos keep the
# same cadence). 60× → an ISS LEO orbit (~93 min real) finishes in ~93 s
# of wall clock.
# ---------------------------------------------------------------------------
TIME_SCALE = 60.0
DEMO_JD0, DEMO_FR0 = jday(2024, 8, 22, 12, 0, 0)


# ---------------------------------------------------------------------------
# TLE line-2 column layout (CCSDS / NORAD spec).
#
#   col 09-16  inclination     (deg, 8 chars,  format XXX.XXXX)
#   col 18-25  RAAN            (deg, 8 chars,  format XXX.XXXX)
#   col 27-33  eccentricity    (7 chars, no decimal point, e.g. 0006000 = .0006000)
#   col 35-42  arg of perigee  (deg, 8 chars,  format XXX.XXXX)
#   col 44-51  mean anomaly    (deg, 8 chars,  format XXX.XXXX)
#   col 53-63  mean motion     (rev/day, 11 chars, format XX.XXXXXXXX)
#
# Columns are 1-based per spec; Python slice indices below are 0-based.
# ---------------------------------------------------------------------------
def _parse_field(line2: str, start: int, end: int) -> float:
    return float(line2[start:end])


def _patch_line2(line2: str, raan_deg: float, m_deg: float) -> str:
    """Rewrite line2 with new RAAN (cols 18-25) and Mean Anomaly (cols 44-51).
    Preserves checksum-free convention for the demo — sgp4 does not validate it."""
    raan_field = f"{raan_deg % 360.0:8.4f}"
    m_field    = f"{m_deg    % 360.0:8.4f}"
    out = list(line2)
    out[17:25] = list(raan_field)
    out[43:51] = list(m_field)
    return "".join(out)


# ---------------------------------------------------------------------------
@dataclass
class ConstellationPreset:
    id: str
    name: str
    description: str
    base_tle_line1: str
    base_tle_line2: str
    planes: int
    sats_per_plane: int
    phasing: int             # Walker f
    # KPI template — all formulaic.
    online_rate: float       # nominal fraction online
    standby_rate: float      # nominal fraction standby (the rest split eclipse + offline)
    throughput_per_sat_mbps: float
    duty_factor: float       # fraction of online sats actively downlinking
    isl_per_sat: int         # full mesh = 4, in-plane only = 2, ground-only = 0
    gsl_total: int           # ground-station links (constellation-wide constant)
    coverage_pct: float      # demo-friendly hard-coded coverage

    # Cached fleet — populated lazily by `build_fleet`.
    _fleet: Optional[list[Satrec]] = field(default=None, init=False, repr=False)
    _ring_eci_km: Optional[list[tuple[float, float, float]]] = field(default=None, init=False, repr=False)

    @property
    def total_sats(self) -> int:
        return self.planes * self.sats_per_plane

    @property
    def inclination_deg(self) -> float:
        return _parse_field(self.base_tle_line2, 8, 16)

    @property
    def period_s(self) -> float:
        mean_motion = _parse_field(self.base_tle_line2, 52, 63)
        return 86400.0 / mean_motion

    @property
    def altitude_km(self) -> float:
        # Mean motion -> semi-major axis via Kepler (mu_earth).
        n = _parse_field(self.base_tle_line2, 52, 63) * 2 * math.pi / 86400.0  # rad/s
        mu = 3.986004418e14  # m^3/s^2
        a_m = (mu / (n * n)) ** (1.0 / 3.0)
        return a_m / 1000.0 - 6378.137

    # -- fleet construction ------------------------------------------------
    def build_fleet(self) -> list[Satrec]:
        """Build all `total_sats` sgp4.Satrec objects via Walker offsets."""
        if self._fleet is not None:
            return self._fleet
        base_raan = _parse_field(self.base_tle_line2, 17, 25)
        base_m    = _parse_field(self.base_tle_line2, 43, 51)
        T = self.total_sats
        S = self.sats_per_plane
        P = self.planes
        fleet: list[Satrec] = []
        for k in range(P):
            raan = base_raan + k * (360.0 / P)
            for j in range(S):
                m = base_m + j * (360.0 / S) + k * self.phasing * (360.0 / T)
                line2 = _patch_line2(self.base_tle_line2, raan, m)
                fleet.append(Satrec.twoline2rv(self.base_tle_line1, line2))
        self._fleet = fleet
        return fleet

    # -- precomputed ring (for the Kit-side renderer) ----------------------
    def ring_eci_km(self, n_points: int = 128) -> list[tuple[float, float, float]]:
        """Sample the BASE orbit (plane 0, sat 0) around one full revolution.
        All other planes are rotations of this ring about +Z; all other sats in
        a plane sit at fixed phase offsets along the same ring. Sampling once
        is enough — the Kit extension reuses the ring for every plane via a
        rotation matrix."""
        if self._ring_eci_km is not None:
            return self._ring_eci_km
        sat0 = self.build_fleet()[0]
        period = self.period_s
        pts: list[tuple[float, float, float]] = []
        for i in range(n_points):
            t = (i / n_points) * period
            _e, r, _v = sat0.sgp4(DEMO_JD0, DEMO_FR0 + t / 86400.0)
            pts.append((float(r[0]), float(r[1]), float(r[2])))
        self._ring_eci_km = pts
        return pts


# ---------------------------------------------------------------------------
# Reference TLEs — public CelesTrak snapshots (Aug 2024). RAAN and Mean
# Anomaly only matter as the BASE values; Walker offsets derive every other
# sat in the fleet.
# ---------------------------------------------------------------------------
_TLE_STARLINK = (
    "1 44713U 19074A   24235.50000000  .00012345  00000-0  60000-3 0  9990",
    "2 44713  53.0540  20.0000 0001500  90.0000 270.0000 15.06400000123456",
)
_TLE_ONEWEB = (
    "1 44056U 19010A   24235.50000000  .00000050  00000-0  10000-3 0  9990",
    "2 44056  87.4000 100.0000 0001000  90.0000 270.0000 13.18000000123456",
)
_TLE_GPS = (
    "1 24876U 97035A   24235.50000000 -.00000050  00000-0  00000-0 0  9994",
    "2 24876  55.0000  40.0000 0050000 250.0000 110.0000  2.00563107123456",
)
_TLE_IRIDIUM = (
    "1 43249U 18030A   24235.50000000  .00000050  00000-0  10000-3 0  9990",
    "2 43249  86.4000   0.0000 0002000 100.0000 260.0000 14.34000000123456",
)
_TLE_ISS = (
    "1 25544U 98067A   24235.50000000  .00012345  00000-0  22000-3 0  9990",
    "2 25544  51.6400 100.0000 0006000  90.0000 270.0000 15.50000000123456",
)


PRESETS: dict[str, ConstellationPreset] = {
    "starlink_shell1": ConstellationPreset(
        id="starlink_shell1",
        name="Starlink Shell 1",
        description="LEO broadband — 72 planes × 22 sats, 53° inclination, 550 km.",
        base_tle_line1=_TLE_STARLINK[0],
        base_tle_line2=_TLE_STARLINK[1],
        planes=72, sats_per_plane=22, phasing=13,
        online_rate=0.96, standby_rate=0.02,
        throughput_per_sat_mbps=280.0, duty_factor=0.55, isl_per_sat=4,
        gsl_total=60, coverage_pct=100.0,
    ),
    "oneweb": ConstellationPreset(
        id="oneweb",
        name="OneWeb",
        description="Polar LEO broadband — 18 planes × 36 sats, 87.4° inc, 1200 km.",
        base_tle_line1=_TLE_ONEWEB[0],
        base_tle_line2=_TLE_ONEWEB[1],
        planes=18, sats_per_plane=36, phasing=1,
        online_rate=0.93, standby_rate=0.03,
        throughput_per_sat_mbps=180.0, duty_factor=0.5, isl_per_sat=0,
        gsl_total=44, coverage_pct=99.0,
    ),
    "gps_iir": ConstellationPreset(
        id="gps_iir",
        name="GPS Block IIR",
        description="MEO PNT — 6 planes × 4 sats, 55° inc, 20,200 km.",
        base_tle_line1=_TLE_GPS[0],
        base_tle_line2=_TLE_GPS[1],
        planes=6, sats_per_plane=4, phasing=2,
        online_rate=0.95, standby_rate=0.04,
        throughput_per_sat_mbps=12.0, duty_factor=0.95, isl_per_sat=2,
        gsl_total=12, coverage_pct=100.0,
    ),
    "iridium_next": ConstellationPreset(
        id="iridium_next",
        name="Iridium NEXT",
        description="Polar LEO voice/data — 6 planes × 11 sats, 86.4° inc, 781 km.",
        base_tle_line1=_TLE_IRIDIUM[0],
        base_tle_line2=_TLE_IRIDIUM[1],
        planes=6, sats_per_plane=11, phasing=1,
        online_rate=0.94, standby_rate=0.03,
        throughput_per_sat_mbps=22.0, duty_factor=0.6, isl_per_sat=4,
        gsl_total=18, coverage_pct=100.0,
    ),
    "single_iss": ConstellationPreset(
        id="single_iss",
        name="ISS (single satellite)",
        description="Debug preset — one sat on the ISS orbit, 51.6° inc, 420 km.",
        base_tle_line1=_TLE_ISS[0],
        base_tle_line2=_TLE_ISS[1],
        planes=1, sats_per_plane=1, phasing=0,
        online_rate=1.0, standby_rate=0.0,
        throughput_per_sat_mbps=120.0, duty_factor=0.5, isl_per_sat=0,
        gsl_total=2, coverage_pct=9.0,
    ),
}


def list_presets() -> list[dict]:
    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "total_sats": p.total_sats,
            "planes": p.planes,
            "sats_per_plane": p.sats_per_plane,
            "phasing": p.phasing,
            "inclination_deg": p.inclination_deg,
            "altitude_km": p.altitude_km,
            "period_s": p.period_s,
        }
        for p in PRESETS.values()
    ]


def get_preset(preset_id: str) -> Optional[ConstellationPreset]:
    return PRESETS.get(preset_id)


# ---------------------------------------------------------------------------
# Per-tick fleet propagation + KPI synthesis.
# ---------------------------------------------------------------------------
# Sun direction in ECI used to flag eclipse-side sats. Matches the +X
# azimuth -45°, +23.5° elevation choice the USD overview stage uses for the
# directional light.
SUN_DIR_ECI = (0.648, -0.648, 0.398)


def propagate_fleet(preset: ConstellationPreset, sim_t_s: float) -> list[tuple[float, float, float]]:
    """Return ECI km positions for every sat in the preset at sim_t."""
    fleet = preset.build_fleet()
    scaled = sim_t_s * TIME_SCALE
    offset_days = scaled / 86400.0
    pts: list[tuple[float, float, float]] = []
    for sat in fleet:
        e, r, _v = sat.sgp4(DEMO_JD0, DEMO_FR0 + offset_days)
        if e:
            pts.append((0.0, 0.0, 0.0))
        else:
            pts.append((float(r[0]), float(r[1]), float(r[2])))
    return pts


def count_eclipse(positions_km: list[tuple[float, float, float]]) -> int:
    """Count sats currently on the night side (dot with sun_dir < 0)."""
    sx, sy, sz = SUN_DIR_ECI
    n = 0
    for x, y, z in positions_km:
        r = math.sqrt(x * x + y * y + z * z) or 1.0
        if (x * sx + y * sy + z * sz) / r < -0.05:
            n += 1
    return n


def synthesize_kpis(preset: ConstellationPreset, positions_km: list[tuple[float, float, float]]) -> dict:
    """Roll the preset template + live propagated positions into a flat KPI dict."""
    T = preset.total_sats
    online = int(round(T * preset.online_rate))
    standby = int(round(T * preset.standby_rate))
    eclipse = max(0, min(count_eclipse(positions_km), online))  # only online sats can be in eclipse
    online_visible = max(0, online - eclipse)
    offline = max(0, T - online - standby - eclipse)
    # Re-normalise rounding drift back into offline.
    drift = T - (online_visible + eclipse + standby + offline)
    if drift > 0:
        offline += drift
    elif drift < 0:
        offline = max(0, offline + drift)

    # Active links: ISL = each sat × isl_per_sat / 2 (each link counted twice).
    isl_links = (online_visible * preset.isl_per_sat) // 2
    gsl_links = min(preset.gsl_total, online_visible)
    links_total = isl_links + gsl_links

    agg_throughput = preset.throughput_per_sat_mbps * online_visible * preset.duty_factor

    return {
        "total": T,
        "online": online_visible,
        "eclipse": eclipse,
        "standby": standby,
        "offline": offline,
        "isl_links": isl_links,
        "gsl_links": gsl_links,
        "links_total": links_total,
        "coverage_pct": preset.coverage_pct,
        "agg_throughput_mbps": round(agg_throughput, 1),
    }
