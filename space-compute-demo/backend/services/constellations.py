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

from sgp4.api import Satrec

from . import geodyn
from . import timebase


# ---------------------------------------------------------------------------
# Demo time scale + epoch. Mission time is owned by services.timebase (one
# source of truth, shared with orbit_catalog so single-sat demos keep the same
# cadence); these names are re-exported because tools/stk_benchmark imports
# them from this module. 60× → an ISS LEO orbit (~93 min real) finishes in
# ~93 s of wall clock.
#
# They are the DEFAULT-mission values: propagation goes through
# timebase.jd_at / jd_after so a re-timed mission window is honoured, while
# the benchmark tooling keeps a fixed handle on the demo epoch.
# ---------------------------------------------------------------------------
TIME_SCALE = timebase.TIME_SCALE
DEMO_JD0, DEMO_FR0 = timebase.DEMO_JD0, timebase.DEMO_FR0


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

    # Monotonic design revision — bumped by make_custom_preset /
    # make_sso_preset so consumers keyed on the (constant) custom id still see
    # a change. 0 for built-ins.
    revision: int = 0

    # Constellation pattern this preset was generated from. "walker" spreads
    # ONE base TLE over `planes` RAAN steps; "sso" stacks `planes` independent
    # sun-synchronous shells (see `shell_tles`).
    mode: str = "walker"
    # SSO design parameters that produced this preset (None for Walker) — the
    # /orbit_design response echoes them back to the designer.
    sso: Optional[dict] = None
    # One (line1, line2) per shell, low->high. When set, `build_fleet` iterates
    # shells instead of spreading RAAN off the single base TLE. Element 0 is
    # always the same TLE as base_tle_line1/2, so inclination_deg /
    # altitude_km / period_s / ring_eci_km / preset_elements() keep describing
    # the LOWEST shell.
    shell_tles: Optional[list[tuple[str, str]]] = None

    # Cached fleet — populated lazily by `build_fleet`.
    _fleet: Optional[list[Satrec]] = field(default=None, init=False, repr=False)
    _ring_eci_km: Optional[list[tuple[float, float, float]]] = field(default=None, init=False, repr=False)
    # timebase.revision() the cached ring was sampled at — the ring starts at
    # mission start, so a re-timed window must resample it.
    _ring_rev: int = field(default=-1, init=False, repr=False)
    # One ring PER plane (walker) / PER shell (sso); same cache discipline.
    _rings_eci_km: Optional[list[list[tuple[float, float, float]]]] = field(default=None, init=False, repr=False)
    _rings_rev: int = field(default=-1, init=False, repr=False)

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
        """Build all `total_sats` sgp4.Satrec objects.

        Two layouts share the mean-anomaly spread:
          * `shell_tles` set (SSO) — each shell already carries its own
            inclination, altitude and RAAN, so only M is patched per sat.
          * otherwise (Walker) — one base TLE, RAAN stepped per plane."""
        if self._fleet is not None:
            return self._fleet
        if self.shell_tles:
            T = self.total_sats
            S = self.sats_per_plane
            shell_fleet: list[Satrec] = []
            for k, (l1, l2) in enumerate(self.shell_tles):
                shell_raan = _parse_field(l2, 17, 25)
                base_m = _parse_field(l2, 43, 51)
                for j in range(S):
                    m = base_m + j * (360.0 / S) + k * self.phasing * (360.0 / T)
                    shell_fleet.append(Satrec.twoline2rv(l1, _patch_line2(l2, shell_raan, m)))
            self._fleet = shell_fleet
            return shell_fleet
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
        rotation matrix.

        The ring starts at MISSION START, so the cache is keyed on
        timebase.revision() — re-timing the mission resamples it instead
        of drawing a stale ring."""
        rev = timebase.revision()
        if self._ring_eci_km is not None and self._ring_rev == rev:
            return self._ring_eci_km
        sat0 = self.build_fleet()[0]
        period = self.period_s
        pts: list[tuple[float, float, float]] = []
        for i in range(n_points):
            t = (i / n_points) * period          # real seconds, one revolution
            jd, fr = timebase.jd_after(t)
            _e, r, _v = sat0.sgp4(jd, fr)
            pts.append((float(r[0]), float(r[1]), float(r[2])))
        self._ring_eci_km = pts
        self._ring_rev = rev
        return pts

    def rings_eci_km(self, n_points: int = 128) -> list[list[tuple[float, float, float]]]:
        """One ring per plane (Walker) / per shell (SSO), low index first.

        `rings_eci_km()[0]` is the same sample set as `ring_eci_km()` — the
        legacy single-ring key stays valid — but consumers no longer have to
        reconstruct the other planes themselves. That reconstruction was the
        bug the Kit renderer shipped: it rotated the one ring by `k·360/planes`
        for EVERY pattern, which turns an SSO design (whose shells all share
        one dawn-dusk RAAN and differ only in altitude/inclination) into a fan
        of `layers` different planes. Walker still IS that rotation, so it is
        done here, once, where the pattern is known.

        Cached on timebase.revision() exactly like `ring_eci_km`."""
        rev = timebase.revision()
        if self._rings_eci_km is not None and self._rings_rev == rev:
            return self._rings_eci_km
        base = self.ring_eci_km(n_points)
        rings: list[list[tuple[float, float, float]]] = [list(base)]
        if self.shell_tles:
            # Each shell carries its own altitude AND its own sun-synchronous
            # inclination, so it has to be propagated, not rotated. Sat 0 of
            # shell k is fleet index k * sats_per_plane.
            fleet = self.build_fleet()
            for k in range(1, len(self.shell_tles)):
                sat_k = fleet[k * self.sats_per_plane]
                period = 86400.0 / _parse_field(self.shell_tles[k][1], 52, 63)
                pts: list[tuple[float, float, float]] = []
                for i in range(n_points):
                    jd, fr = timebase.jd_after((i / n_points) * period)
                    _e, r, _v = sat_k.sgp4(jd, fr)
                    pts.append((float(r[0]), float(r[1]), float(r[2])))
                rings.append(pts)
        else:
            # Walker: plane k is the base plane rotated by k·360/planes about
            # ECI +Z (exactly the RAAN step `build_fleet` patches into line 2).
            for k in range(1, self.planes):
                th = math.radians(k * 360.0 / self.planes)
                c, sn = math.cos(th), math.sin(th)
                rings.append([(c * x - sn * y, sn * x + c * y, z)
                              for (x, y, z) in base])
        self._rings_eci_km = rings
        self._rings_rev = rev
        return rings


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
# Dawn-dusk Sun-synchronous (terminator) orbit: 98.2° inc, RAAN at the 6 am/pm
# line, ~705 km (mean motion 14.57). A sat here never enters Earth's shadow.
_TLE_DAWNDUSK = (
    "1 39084U 13008A   24235.50000000  .00000100  00000-0  20000-3 0  9990",
    "2 39084  98.2000   6.0000 0001200  90.0000 270.0000 14.57000000123456",
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
    "dawn_dusk_sso": ConstellationPreset(
        id="dawn_dusk_sso",
        name="Dawn-Dusk Sun-Synchronous",
        description="Terminator SSO — never eclipsed, Sun stays normal to the "
                    "panels. 98.2° inc, ~705 km.",
        base_tle_line1=_TLE_DAWNDUSK[0],
        base_tle_line2=_TLE_DAWNDUSK[1],
        planes=2, sats_per_plane=6, phasing=1,
        online_rate=1.0, standby_rate=0.0,
        throughput_per_sat_mbps=200.0, duty_factor=0.7, isl_per_sat=2,
        gsl_total=8, coverage_pct=100.0,
    ),
}


# ---------------------------------------------------------------------------
# Custom constellation design — classical orbital elements → synthesized TLE.
#
# The designer UI edits the six Keplerian elements (a via altitude, e, i,
# Ω, ω, M) plus Walker parameters; we format them straight into a TLE
# line 2 (the demo convention skips checksums — sgp4 does not validate
# them) so the ENTIRE existing pipeline (fleet build, ring sampling,
# per-tick propagation, Kit rings, web fallback propagator) works on the
# designed constellation unchanged.
# ---------------------------------------------------------------------------
CUSTOM_ID = "custom_design"
EARTH_RADIUS_KM = 6378.137
_MU_EARTH = 3.986004418e14  # m^3/s^2

_CUSTOM_LINE1 = "1 99999U 26001A   24235.50000000  .00000100  00000-0  10000-3 0  9990"
# Last WALKER design the user applied. /orbit_design publishes `walker` and
# `sso` side by side so the designer can switch pattern without a round trip;
# reading the ACTIVE preset for the walker block made an SSO apply report
# `planes = layers` (an SSO reuses `planes` as its shell count) and poisoned
# the Walker draft. Mirrors `_last_sso` below.
_DEFAULT_WALKER = {"planes": 3, "sats_per_plane": 8, "phasing": 1}
_last_walker: Optional[dict] = None
# Bumped on every make_custom_preset / make_sso_preset so same-id redesigns
# are detectable.
_design_revision = 0


def _custom_line1() -> str:
    """The designer's reference line 1 with its epoch field (cols 19-32) set
    to the mission epoch. At the default epoch this rewrites
    `24235.50000000` with itself, so a default-mission design is byte-for-byte
    the historical TLE."""
    return (_CUSTOM_LINE1[:18]
            + timebase.tle_epoch_field(timebase.mission().epoch_utc)
            + _CUSTOM_LINE1[32:])


def make_custom_preset(
    altitude_km: float,
    eccentricity: float,
    inclination_deg: float,
    raan_deg: float,
    arg_perigee_deg: float,
    mean_anomaly_deg: float,
    planes: int,
    sats_per_plane: int,
    phasing: int,
) -> ConstellationPreset:
    """Build (and register) the designed constellation. Raises ValueError on
    out-of-range elements. Registered under CUSTOM_ID so every consumer
    (engine tick, /constellations/{id}, Kit, web propagator) resolves it
    like any other preset; re-designing replaces the previous one."""
    if not 200.0 <= altitude_km <= 40000.0:
        raise ValueError("altitude_km must be within 200..40000")
    if not 0.0 <= eccentricity <= 0.5:
        raise ValueError("eccentricity must be within 0..0.5")
    if not 0.0 <= inclination_deg <= 180.0:
        raise ValueError("inclination_deg must be within 0..180")
    for label, v in (("raan_deg", raan_deg), ("arg_perigee_deg", arg_perigee_deg),
                     ("mean_anomaly_deg", mean_anomaly_deg)):
        if not 0.0 <= v < 360.0:
            raise ValueError(f"{label} must be within 0..360")
    planes = int(planes)
    sats_per_plane = int(sats_per_plane)
    phasing = int(phasing)
    if not 1 <= planes <= 36:
        raise ValueError("planes must be within 1..36")
    if not 1 <= sats_per_plane <= 60:
        raise ValueError("sats_per_plane must be within 1..60")
    if not 0 <= phasing < max(1, planes):
        raise ValueError("phasing (Walker f) must be within 0..planes-1")
    # Perigee must stay above the atmosphere or SGP4 flags decay.
    a_km = EARTH_RADIUS_KM + altitude_km
    if a_km * (1.0 - eccentricity) < EARTH_RADIUS_KM + 160.0:
        raise ValueError("perigee below 160 km — reduce eccentricity or raise altitude")

    # Kepler: semi-major axis → mean motion (rev/day).
    a_m = a_km * 1000.0
    n_rad_s = math.sqrt(_MU_EARTH / (a_m ** 3))
    period_s = 2.0 * math.pi / n_rad_s
    mm_rev_day = 86400.0 / period_s

    ecc7 = f"{eccentricity:.7f}"[2:9]  # 7 digits, implied leading decimal
    line2 = (
        f"2 99999 {inclination_deg:8.4f} {raan_deg:8.4f} {ecc7} "
        f"{arg_perigee_deg:8.4f} {mean_anomaly_deg:8.4f} {mm_rev_day:11.8f}123456"
    )

    global _design_revision, _last_walker
    _design_revision += 1
    _last_walker = {"planes": planes, "sats_per_plane": sats_per_plane,
                    "phasing": phasing}
    total = planes * sats_per_plane
    preset = ConstellationPreset(
        id=CUSTOM_ID,
        name="Custom Design",
        description=(f"Designer orbit — {altitude_km:.0f} km, "
                     f"i={inclination_deg:.1f}°, Walker {planes}×{sats_per_plane} "
                     f"f={phasing}."),
        base_tle_line1=_custom_line1(),
        base_tle_line2=line2,
        planes=planes, sats_per_plane=sats_per_plane, phasing=phasing,
        mode="walker",
        # Formulaic KPI template, scaled by fleet size (demo numbers).
        online_rate=0.97, standby_rate=0.02,
        throughput_per_sat_mbps=150.0, duty_factor=0.5,
        isl_per_sat=2 if planes >= 2 else 0,
        gsl_total=min(12, total),
        coverage_pct=round(min(100.0, 100.0 * total / (total + 40.0)), 1),
        revision=_design_revision,
    )
    PRESETS[CUSTOM_ID] = preset
    return preset


def walker_config(preset: Optional[ConstellationPreset] = None) -> dict:
    """The `walker` block for /orbit_design: the ACTIVE preset's own Walker
    parameters when it is a Walker pattern (so the designer shows Starlink's
    72x22 while Starlink is flying), otherwise the last Walker design, else
    the defaults. Never an SSO preset's shell count."""
    if preset is not None and getattr(preset, "mode", "walker") != "sso":
        planes = int(preset.planes)
        spp = int(preset.sats_per_plane)
        phasing = int(preset.phasing)
    else:
        cfg = _last_walker or _DEFAULT_WALKER
        planes = int(cfg["planes"])
        spp = int(cfg["sats_per_plane"])
        phasing = int(cfg["phasing"])
    return {"planes": planes, "sats_per_plane": spp, "phasing": phasing,
            "total_sats": planes * spp}


# ---------------------------------------------------------------------------
# Sun-synchronous (SSO) design.
#
# An SSO precesses its ascending node at exactly the rate the mean Sun moves
# along the ecliptic, so the local solar time of the node is frozen. The
# secular J2 nodal drift is
#
#     Ω̇ = -3/2 · J2 · (Re/p)² · n · cos i
#
# and setting it equal to the Sun's apparent motion Ω̇_sun gives the
# sun-synchronous condition
#
#     cos i = -2 Ω̇_sun / (3 J2 (Re/p)² n),   n = √(μ/a³),  p = a(1 - e²)
#
# SANITY: a = 6878 km (500 km circular), e = 0 → i = 97.40°, the textbook
# 500 km sun-synchronous inclination. `_assert_sso_sanity()` below checks it
# at import time, so a mistyped constant can never ship silently.
#
# SSO fixes every element except altitude, so the designer only chooses an
# altitude range; e = 0 and ω = 0 fall out of the definition.
# ---------------------------------------------------------------------------
J2 = 1.08262668e-3
# 2π / 365.2422 mean solar days = 1.99106e-7 rad/s
OMEGA_DOT_SUN = 2.0 * math.pi / (365.2422 * 86400.0)
_MU_EARTH_KM3_S2 = _MU_EARTH / 1.0e9          # m³/s² → km³/s²

# Designer limits (mirrored by the /orbit_design validation table).
SSO_ALT_MIN_KM = 250.0
SSO_ALT_MAX_KM = 1600.0
SSO_MAX_LAYERS = 12

_DEFAULT_SSO = {
    "alt_min_km": 500.0,
    "alt_max_km": 700.0,
    "layers": 3,
    "sats_per_plane": 8,
    "phasing": 1,
    "ltan_hours": 18.0,          # dusk ascending node (see LTAN_CHOICES)
}
# Last SSO design the user applied — /orbit_design always publishes an `sso`
# block so the designer can pre-fill the form even while Walker is in force.
_last_sso: Optional[dict] = None


def sso_inclination_deg(altitude_km: float, eccentricity: float = 0.0) -> float:
    """Sun-synchronous inclination (deg) for a circular-ish orbit at
    `altitude_km`. Raises ValueError when |cos i| > 1, i.e. the altitude is
    too high for any inclination to keep the node sun-synchronous."""
    a_km = EARTH_RADIUS_KM + float(altitude_km)
    e = float(eccentricity)
    p_km = a_km * (1.0 - e * e)
    if a_km <= 0.0 or p_km <= 0.0:
        raise ValueError("altitude/eccentricity do not describe a valid orbit")
    n_rad_s = math.sqrt(_MU_EARTH_KM3_S2 / (a_km ** 3))
    cos_i = -2.0 * OMEGA_DOT_SUN / (
        3.0 * J2 * (EARTH_RADIUS_KM / p_km) ** 2 * n_rad_s)
    if abs(cos_i) > 1.0:
        raise ValueError(
            f"no sun-synchronous solution at {altitude_km:.0f} km "
            "— lower the altitude")
    return math.degrees(math.acos(cos_i))


def _assert_sso_sanity() -> None:
    """Import-time guard on the textbook 500 km case (see the block comment)."""
    i500 = sso_inclination_deg(500.0)
    assert abs(i500 - 97.40) < 0.02, f"SSO formula drifted: i(500 km) = {i500}"


_assert_sso_sanity()


# ---------------------------------------------------------------------------
# Dawn-dusk geometry -- what makes an SSO a TERMINATOR orbit.
#
# A sun-synchronous inclination only freezes the LOCAL SOLAR TIME of the node;
# WHICH local time is set by the RAAN. The plane stands on the day/night
# terminator when its normal points along the Earth->Sun line, i.e.
#
#     LTAN (hours) = 12 + (RAAN - alpha_sun) / 15 deg
#         =>  RAAN = alpha_sun + 15 * (LTAN - 12)
#
# so LTAN 18:00 (dusk ascending node) is alpha_sun + 90 deg and LTAN 06:00
# (dawn) is alpha_sun - 90 deg. alpha_sun is read from `geodyn.sun_teme` AT THE
# MISSION EPOCH, in TEME -- the same frame the TLE's RAAN lives in, so SGP4
# reads the number we meant.
#
# EVERY shell of a design shares that one RAAN; only the altitude (and the
# sun-synchronous inclination that goes with it) changes shell to shell. That
# is what renders as concentric rings on ONE plane. The previous
# `RAAN_k = k * 360 / layers` spread put every layer on a DIFFERENT plane,
# none of them the terminator -- the bug this replaces.
#
# HONESTY NOTE -- beta, the Sun's elevation above the orbit plane:
#
#     sin beta = sin i * cos dec * sin(RAAN - alpha_sun) + cos i * sin dec
#              = sin(i + dec)                            when LTAN = 18:00
#
# beta = 90 deg means the plane contains the terminator exactly. RAAN =
# alpha_sun + 90 deg is the RAAN that MAXIMISES beta -- but at the demo epoch
# (2024-08-22, dec = +11.5 deg) with i ~ 98.2 deg that maximum is only
# beta ~ 70.3 deg: the plane genuinely sits ~20 deg off the terminator because
# of the Sun's declination. beta reaches 90 deg when dec = -(i - 90) ~ -8.2
# deg, i.e. around 5 Oct and 8 Mar, which the user can dial in via `epoch_utc`.
# We PUBLISH beta so the UI can say so. We do NOT bend i or RAAN to force
# beta = 90 -- that would stop the orbit being sun-synchronous.
# ---------------------------------------------------------------------------
LTAN_DAWN_H = 6.0
LTAN_DUSK_H = 18.0
LTAN_CHOICES = (LTAN_DAWN_H, LTAN_DUSK_H)


def sun_ra_dec_deg(jd_utc: float) -> tuple[float, float]:
    """(right ascension, declination) of the Sun in TEME, degrees. RA is
    wrapped into 0..360; declination is signed."""
    (sx, sy, sz), _r_au = geodyn.sun_teme(jd_utc)
    return (math.degrees(math.atan2(sy, sx)) % 360.0,
            math.degrees(math.atan2(sz, math.hypot(sx, sy))))


def epoch_sun_ra_dec_deg() -> tuple[float, float]:
    """The Sun's RA/dec at the MISSION EPOCH, not at "now" -- a TLE's RAAN is
    an epoch quantity, so the Sun it is measured against must be too."""
    return sun_ra_dec_deg(timebase.jd_utc_at_epoch())


def dawn_dusk_raan_deg(ltan_hours: float = LTAN_DUSK_H,
                       sun_ra_deg: Optional[float] = None) -> float:
    """The shared dawn-dusk RAAN (deg) for a local time of ascending node.
    Pass `sun_ra_deg` to reuse an alpha_sun already computed for this epoch."""
    ra = epoch_sun_ra_dec_deg()[0] if sun_ra_deg is None else float(sun_ra_deg)
    return (ra + 15.0 * (float(ltan_hours) - 12.0)) % 360.0


def beta_angle_deg(inclination_deg: float, raan_deg: float,
                   sun_ra_deg: float, sun_dec_deg: float) -> float:
    """Sun elevation above the orbit plane, degrees: beta = asin(h_hat . s_hat)
    with the orbit normal h_hat = (sin i sin RAAN, -sin i cos RAAN, cos i).
    |beta| = 90 means the plane contains the terminator."""
    i = math.radians(float(inclination_deg))
    d_ra = math.radians(float(raan_deg) - float(sun_ra_deg))
    dec = math.radians(float(sun_dec_deg))
    sin_b = (math.sin(i) * math.cos(dec) * math.sin(d_ra)
             + math.cos(i) * math.sin(dec))
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_b))))


def validate_ltan(ltan_hours: float) -> float:
    """Only the two terminator local times are offered: 06:00 (dawn node) and
    18:00 (dusk node). Any other LTAN is a perfectly good SSO but not a
    dawn-dusk one, and this designer only builds dawn-dusk."""
    v = float(ltan_hours)
    if v not in LTAN_CHOICES:
        raise ValueError("ltan_hours must be 6.0 (dawn) or 18.0 (dusk)")
    return v


def sso_shell_plan(alt_min_km: float, alt_max_km: float, layers: int,
                   sats_per_plane: int,
                   ltan_hours: float = LTAN_DUSK_H) -> list[dict]:
    """The `layers` dawn-dusk shells of an SSO design, low -> high.

    Altitude steps linearly from `alt_min_km` to `alt_max_km` (a single layer
    sits at `alt_min_km`) and inclination is that altitude's sun-synchronous
    solution -- so the ~0.8 deg inclination spread across 500-700 km is REAL
    and must not be flattened; it is what keeps each shell individually
    sun-synchronous. RAAN is the SHARED dawn-dusk node, identical on every
    shell -- that is what makes the shells concentric rings on one plane."""
    L = max(1, int(layers))
    lo = float(alt_min_km)
    hi = float(alt_max_km)
    sun_ra, sun_dec = epoch_sun_ra_dec_deg()
    raan = round(dawn_dusk_raan_deg(ltan_hours, sun_ra), 4)
    shells: list[dict] = []
    for k in range(L):
        frac = 0.0 if L == 1 else k / (L - 1)
        alt = lo + (hi - lo) * frac
        inc = sso_inclination_deg(alt)
        shells.append({
            "altitude_km": round(alt, 3),
            "inclination_deg": round(inc, 4),
            "raan_deg": raan,
            "beta_deg": round(beta_angle_deg(inc, raan, sun_ra, sun_dec), 3),
            "sats": int(sats_per_plane),
        })
    # The whole point of the pattern: one plane, many altitudes.
    assert len({sh["raan_deg"] for sh in shells}) == 1, (
        "dawn-dusk shells must share one RAAN")
    return shells


def _mean_motion_rev_day(altitude_km: float) -> float:
    a_m = (EARTH_RADIUS_KM + float(altitude_km)) * 1000.0
    n_rad_s = math.sqrt(_MU_EARTH / (a_m ** 3))
    return 86400.0 / (2.0 * math.pi / n_rad_s)


def _validate_sso(alt_min_km: float, alt_max_km: float, layers: int,
                  sats_per_plane: int, phasing: int,
                  ltan_hours: float = LTAN_DUSK_H) -> tuple:
    if not SSO_ALT_MIN_KM <= alt_min_km <= SSO_ALT_MAX_KM:
        raise ValueError(
            f"alt_min_km must be within {SSO_ALT_MIN_KM:.0f}..{SSO_ALT_MAX_KM:.0f}")
    if not SSO_ALT_MIN_KM <= alt_max_km <= SSO_ALT_MAX_KM:
        raise ValueError(
            f"alt_max_km must be within {SSO_ALT_MIN_KM:.0f}..{SSO_ALT_MAX_KM:.0f}")
    if alt_min_km > alt_max_km:
        raise ValueError("alt_min_km must be <= alt_max_km")
    layers = int(layers)
    sats_per_plane = int(sats_per_plane)
    phasing = int(phasing)
    if not 1 <= layers <= SSO_MAX_LAYERS:
        raise ValueError(f"layers must be within 1..{SSO_MAX_LAYERS}")
    if not 1 <= sats_per_plane <= 60:
        raise ValueError("sats_per_plane must be within 1..60")
    if not 0 <= phasing < max(1, layers):
        raise ValueError("phasing (Walker f) must be within 0..layers-1")
    ltan_hours = validate_ltan(ltan_hours)
    # No explicit perigee guard here: SSO orbits are circular by definition and
    # SSO_ALT_MIN_KM (250 km) already sits above the Walker designer's 160 km
    # perigee floor, so SGP4 can never be handed a decaying element set.
    return (float(alt_min_km), float(alt_max_km), layers, sats_per_plane,
            phasing, ltan_hours)


def sso_config(shells_from: Optional[dict] = None) -> dict:
    """The `sso` block for /orbit_design: the last applied SSO design (or the
    defaults), with its shell table, total and dawn-dusk geometry recomputed
    at the CURRENT mission epoch -- so switching the pattern radio previews
    the RAAN/beta the design would actually get if applied now.

    `raan_deg` is the shared dawn-dusk node (identical on every shell) and
    `beta_deg` is the Sun's elevation above that plane for the LOWEST shell;
    per-shell beta rides in `shells[*].beta_deg` (it moves ~0.8 deg across a
    500-700 km stack, because each shell has its own SSO inclination)."""
    cfg = dict(shells_from or _last_sso or _DEFAULT_SSO)
    layers = int(cfg["layers"])
    spp = int(cfg["sats_per_plane"])
    ltan = float(cfg.get("ltan_hours", LTAN_DUSK_H))
    sun_ra, _sun_dec = epoch_sun_ra_dec_deg()
    shells = sso_shell_plan(cfg["alt_min_km"], cfg["alt_max_km"],
                            layers, spp, ltan)
    return {
        "alt_min_km": float(cfg["alt_min_km"]),
        "alt_max_km": float(cfg["alt_max_km"]),
        "layers": layers,
        "sats_per_plane": spp,
        "phasing": int(cfg["phasing"]),
        "total_sats": layers * spp,
        "ltan_hours": ltan,
        "raan_deg": shells[0]["raan_deg"],
        "sun_ra_deg": round(sun_ra, 4),
        "beta_deg": shells[0]["beta_deg"],
        "shells": shells,
    }


def make_sso_preset(
    alt_min_km: float = 500.0,
    alt_max_km: float = 700.0,
    layers: int = 3,
    sats_per_plane: int = 8,
    phasing: int = 1,
    ltan_hours: float = LTAN_DUSK_H,
) -> ConstellationPreset:
    """Build (and register) a DAWN-DUSK sun-synchronous constellation:
    `layers` shells stacked low -> high on ONE terminator plane, one orbital
    plane each, every shell at its own SSO inclination and all of them at the
    same dawn-dusk RAAN. Registered under CUSTOM_ID exactly like the Walker
    designer, so the whole pipeline (engine tick, Kit rings, coverage map)
    follows. Raises ValueError on out-of-range parameters."""
    global _design_revision, _last_sso
    (alt_min_km, alt_max_km, layers,
     sats_per_plane, phasing, ltan_hours) = _validate_sso(
        alt_min_km, alt_max_km, layers, sats_per_plane, phasing, ltan_hours)

    shells = sso_shell_plan(alt_min_km, alt_max_km, layers, sats_per_plane,
                            ltan_hours)
    line1 = _custom_line1()
    ecc7 = f"{0.0:.7f}"[2:9]            # circular by definition -> "0000000"
    shell_tles: list[tuple[str, str]] = []
    for sh in shells:
        mm = _mean_motion_rev_day(sh["altitude_km"])
        line2 = (
            f"2 99999 {sh['inclination_deg']:8.4f} {sh['raan_deg']:8.4f} {ecc7} "
            f"{0.0:8.4f} {0.0:8.4f} {mm:11.8f}123456"
        )
        shell_tles.append((line1, line2))

    total = layers * sats_per_plane
    _last_sso = {"alt_min_km": alt_min_km, "alt_max_km": alt_max_km,
                 "layers": layers, "sats_per_plane": sats_per_plane,
                 "phasing": phasing, "ltan_hours": ltan_hours}
    _design_revision += 1
    preset = ConstellationPreset(
        id=CUSTOM_ID,
        name="Custom Design",
        description=(f"Dawn-dusk sun-synchronous — {layers} shell(s) on one "
                     f"terminator plane, {alt_min_km:.0f}–{alt_max_km:.0f} km, "
                     f"i={shells[0]['inclination_deg']:.2f}–"
                     f"{shells[-1]['inclination_deg']:.2f}°, "
                     f"LTAN {int(ltan_hours):02d}:00, "
                     f"Ω={shells[0]['raan_deg']:.2f}°, "
                     f"β={shells[0]['beta_deg']:.1f}°, "
                     f"{sats_per_plane} sats/plane, f={phasing}."),
        # Shell 0 doubles as the reference TLE: inclination_deg, altitude_km,
        # period_s, ring_eci_km and preset_elements() all describe the LOWEST
        # shell (documented in the /orbit_design contract).
        base_tle_line1=shell_tles[0][0],
        base_tle_line2=shell_tles[0][1],
        planes=layers, sats_per_plane=sats_per_plane, phasing=phasing,
        # Same formulaic KPI template as the Walker designer (demo numbers).
        online_rate=0.97, standby_rate=0.02,
        throughput_per_sat_mbps=150.0, duty_factor=0.5,
        isl_per_sat=2 if layers >= 2 else 0,
        gsl_total=min(12, total),
        coverage_pct=round(min(100.0, 100.0 * total / (total + 40.0)), 1),
        revision=_design_revision,
        mode="sso",
        sso=sso_config(_last_sso),
        shell_tles=shell_tles,
    )
    PRESETS[CUSTOM_ID] = preset
    return preset


# ---------------------------------------------------------------------------
# Propagator catalog. SGP4 is the only implemented model; the other three are
# published so the designer can show the real menu (and say why they are off)
# instead of pretending the choice does not exist.
# ---------------------------------------------------------------------------
PROPAGATORS: list[dict] = [
    {"id": "sgp4", "label": "SGP4", "implemented": True,
     "note": "NORAD mean elements, SGP4/SDP4 perturbations"},
    {"id": "twobody", "label": "Two-body", "implemented": False,
     "note": "Keplerian point mass, no perturbations"},
    {"id": "j2", "label": "J2", "implemented": False,
     "note": "Secular J2 nodal + apsidal drift"},
    {"id": "hpop", "label": "HPOP", "implemented": False,
     "note": "Numerical integration, full force model"},
]
DEFAULT_PROPAGATOR = "sgp4"


def get_propagator(propagator_id: str) -> dict:
    """Look up a propagator by id. Raises ValueError for unknown ids and for
    the three catalogued-but-unimplemented models."""
    pid = str(propagator_id)
    entry = next((p for p in PROPAGATORS if p["id"] == pid), None)
    if entry is None or not entry["implemented"]:
        avail = ", ".join(p["id"] for p in PROPAGATORS if p["implemented"])
        raise ValueError(
            f"propagator {pid!r} is not implemented (available: {avail})")
    return entry


def preset_elements(preset: ConstellationPreset) -> dict:
    """The six classical orbital elements (+ derived period/altitude) parsed
    back out of the preset's reference TLE — the designer displays these
    for ANY active constellation, not just the custom one."""
    line2 = preset.base_tle_line2
    ecc = float("0." + line2[26:33].strip())
    return {
        "altitude_km": round(preset.altitude_km, 1),
        "semi_major_axis_km": round(preset.altitude_km + EARTH_RADIUS_KM, 1),
        "eccentricity": round(ecc, 7),
        "inclination_deg": round(_parse_field(line2, 8, 16), 4),
        "raan_deg": round(_parse_field(line2, 17, 25), 4),
        "arg_perigee_deg": round(_parse_field(line2, 34, 42), 4),
        "mean_anomaly_deg": round(_parse_field(line2, 43, 51), 4),
        "period_s": round(preset.period_s, 1),
        "period_min": round(preset.period_s / 60.0, 2),
    }


# ---------------------------------------------------------------------------
# Ground-station visibility (elevation-angle model).
#
# For a ground point G and a satellite with sub-satellite point S at
# altitude h: with ψ the central angle G→S and ρ = Re/(Re+h),
#     elevation = atan2(cos ψ − ρ, sin ψ)
# The satellite is visible when elevation ≥ the mask angle (default 10°).
# Pure geometry on top of the same eci→lat/lon conversion the engine's
# display path uses, so "visible" here matches what the map shows.
# ---------------------------------------------------------------------------
def elevation_deg(sat_lat: float, sat_lon: float, sat_alt_km: float,
                  gs_lat: float, gs_lon: float) -> float:
    """Geodetic elevation via WGS-84 ECEF vectors (replaces the earlier
    spherical-Earth central-angle formula; STK-benchmarked to seconds-level
    access-window agreement)."""
    sat_ecef = geodyn.geodetic_to_ecef(sat_lat, sat_lon, sat_alt_km)
    return geodyn.elevation_from_ecef(sat_ecef, gs_lat, gs_lon, 0.0)


# ---------------------------------------------------------------------------
# Communication bands. Higher frequency → more per-satellite throughput but
# a higher elevation-mask requirement (low passes suffer rain/atmospheric
# attenuation), so a band trades bandwidth against how many sats are usable.
# ---------------------------------------------------------------------------
COMMS_BANDS: dict[str, dict] = {
    "UHF": {"label": "UHF",     "per_sat_mbps": 2.0,   "min_elevation_deg": 5.0},
    "S":   {"label": "S-band",  "per_sat_mbps": 20.0,  "min_elevation_deg": 5.0},
    "X":   {"label": "X-band",  "per_sat_mbps": 150.0, "min_elevation_deg": 10.0},
    "Ka":  {"label": "Ka-band", "per_sat_mbps": 800.0, "min_elevation_deg": 20.0},
}
DEFAULT_BAND = "X"

# Elevation thresholds sampled for the band-comparison curves (throughput at
# each mask = sats-above-mask × band rate).
_CDF_MASKS = [0, 5, 10, 15, 20, 25, 30, 35, 40]


def get_band(band_id: str) -> dict:
    return COMMS_BANDS.get(str(band_id), COMMS_BANDS[DEFAULT_BAND])


def ground_analytics(
    fleet_pos_km: list[tuple[float, float, float]],
    fleet_lla: list[tuple[float, float, float]],
    gs_lat: float, gs_lon: float,
    effective_mask_deg: float,
    per_sat_mbps: float,
    solar_peak_w: float,
    solar_bin: int,
    sun_unit: tuple[float, float, float] | None = None,
) -> dict:
    """Per-tick ground-station analytics over the whole fleet (positions +
    sub-points already computed by the caller). Returns visibility, aggregate
    bandwidth for the active band, an elevation CDF (for the band-comparison
    curves) and a solar-intensity histogram (per-bin sat count + collection).

    Solar intensity is the illumination geometry factor 0..100 =
    100·max(0, r̂·ŝ) — a satellite at the subsolar point reads 100, at the
    terminator/night 0 — a visualization metric independent of the physics
    array model. Binned by `solar_bin` (5 or 10). `sun_unit` should be the
    real Sun direction for the current tick (sun_unit_at); the fixed scene
    light remains only as a fallback."""
    sx, sy, sz = sun_unit if sun_unit is not None else SUN_DIR_ECI
    cdf = [0] * len(_CDF_MASKS)
    visible: list[int] = []
    best = -90.0
    solar_bin = 10 if int(solar_bin) not in (5, 10) else int(solar_bin)
    nbins = 100 // solar_bin
    bin_count = [0] * nbins
    bin_coll = [0.0] * nbins

    for i, ((x, y, z), (la, lo, al)) in enumerate(zip(fleet_pos_km, fleet_lla)):
        if al <= 0.0:  # (0,0,0) sgp4-error sentinel — skip dead sats
            continue
        e = elevation_deg(la, lo, al, gs_lat, gs_lon)
        if e > best:
            best = e
        for mi, m in enumerate(_CDF_MASKS):
            if e >= m:
                cdf[mi] += 1
        if e >= effective_mask_deg:
            visible.append(i)
        r = math.sqrt(x * x + y * y + z * z) or 1.0
        intensity = max(0.0, (x * sx + y * sy + z * sz) / r) * 100.0
        bi = min(nbins - 1, int(intensity // solar_bin))
        bin_count[bi] += 1
        bin_coll[bi] += (intensity / 100.0) * solar_peak_w

    solar_hist = [
        {"lo": b * solar_bin, "hi": (b + 1) * solar_bin,
         "sat_count": bin_count[b], "collection_w": round(bin_coll[b], 1)}
        for b in range(nbins)
    ]
    return {
        "visible_sats": len(visible),
        "best_elevation_deg": round(best, 2),
        "visible_indices": visible[:64],
        "aggregate_mbps": round(len(visible) * per_sat_mbps, 1),
        "elevation_cdf": [{"mask_deg": m, "count": cdf[mi]}
                          for mi, m in enumerate(_CDF_MASKS)],
        "solar_hist": solar_hist,
    }


def ground_visibility_series(
    preset: ConstellationPreset,
    gs_lat: float, gs_lon: float,
    t0_sim_s: float, duration_sim_s: float, step_sim_s: float,
    min_elevation_deg: float,
    eci_to_lla,
) -> dict:
    """Sample fleet↔ground visibility over [t0, t0+duration] sim-seconds.
    `eci_to_lla` is orbit_catalog.eci_to_lat_lon_alt (injected to avoid an
    import cycle). Returns per-sample series + merged any-sat-visible pass
    windows. Blocking for big fleets — call via asyncio.to_thread."""
    samples = []
    n_steps = max(2, int(duration_sim_s / max(0.25, step_sim_s)))
    for i in range(n_steps + 1):
        t = t0_sim_s + i * duration_sim_s / n_steps
        best = -90.0
        visible = 0
        for (x, y, z) in propagate_fleet(preset, t):
            lat, lon, alt = eci_to_lla(x, y, z, t)
            # Skip the (0,0,0) sgp4-error sentinel (alt = -Re).
            if alt <= 0.0:
                continue
            e = elevation_deg(lat, lon, alt, gs_lat, gs_lon)
            if e > best:
                best = e
            if e >= min_elevation_deg:
                visible += 1
        samples.append({
            "t_s": round(t - t0_sim_s, 2),
            "visible_sats": visible,
            "best_elevation_deg": round(best, 2),
        })

    # Merge consecutive visible samples into pass windows.
    windows = []
    cur = None
    for s in samples:
        if s["visible_sats"] > 0:
            if cur is None:
                cur = {"start_s": s["t_s"], "end_s": s["t_s"],
                       "max_elevation_deg": s["best_elevation_deg"]}
            else:
                cur["end_s"] = s["t_s"]
                cur["max_elevation_deg"] = max(cur["max_elevation_deg"],
                                               s["best_elevation_deg"])
        elif cur is not None:
            windows.append(cur)
            cur = None
    if cur is not None:
        windows.append(cur)

    visible_samples = sum(1 for s in samples if s["visible_sats"] > 0)
    nxt = next((s["t_s"] for s in samples if s["visible_sats"] > 0), None)
    return {
        "samples": samples,
        "windows": windows,
        "coverage_fraction": round(visible_samples / len(samples), 3),
        "next_pass_in_s": nxt,
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
# Legacy fixed sun direction. NOT a sun — at the demo epoch it points 141°
# away from the real one. It survives only as the last-resort branch of the
# two functions below for callers that hand in no time at all; every path
# that knows its instant uses the analytic Sun (geodyn.sun_unit_and_flux via
# `sun_unit_at`), and the renderers now take the Sun from the broadcast
# FleetSnapshot.sun_unit_teme rather than from any constant. Do not reach for
# this in new code: pass a time.
SUN_DIR_ECI = (0.648, -0.648, 0.398)


def sun_unit_at(sim_t_s: float) -> tuple[float, float, float]:
    """Real unit Sun direction (TEME) at mission start + sim_t_s × TIME_SCALE."""
    unit, _flux = geodyn.sun_unit_and_flux(timebase.jd_utc_at(sim_t_s))
    return unit


def propagate_tracked(preset: ConstellationPreset, sim_t_s: float) -> tuple[float, float, float]:
    """ECI km position of the TRACKED satellite (plane 0, slot 0) only — a
    single cached-Satrec sgp4 call, cheap enough to refresh the display
    kinematics on every /state read (Kit polls at 5 Hz) instead of once per
    1 Hz physics tick."""
    sat = preset.build_fleet()[0]
    jd, fr = timebase.jd_at(sim_t_s)
    e, r, _v = sat.sgp4(jd, fr)
    if e:
        return (0.0, 0.0, 0.0)
    return (float(r[0]), float(r[1]), float(r[2]))


def propagate_tracked_rv(
    preset: ConstellationPreset, sim_t_s: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """ECI position (km) AND velocity (km/s) of the tracked satellite —
    velocity is needed for the attitude/solar geometry (ram + orbit-normal
    panel pointing). Single cached-Satrec sgp4 call."""
    sat = preset.build_fleet()[0]
    jd, fr = timebase.jd_at(sim_t_s)
    e, r, v = sat.sgp4(jd, fr)
    if e:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    return (float(r[0]), float(r[1]), float(r[2])), (float(v[0]), float(v[1]), float(v[2]))


def propagate_fleet(preset: ConstellationPreset, sim_t_s: float) -> list[tuple[float, float, float]]:
    """Return ECI km positions for every sat in the preset at sim_t."""
    fleet = preset.build_fleet()
    jd, fr = timebase.jd_at(sim_t_s)
    pts: list[tuple[float, float, float]] = []
    for sat in fleet:
        e, r, _v = sat.sgp4(jd, fr)
        if e:
            pts.append((0.0, 0.0, 0.0))
        else:
            pts.append((float(r[0]), float(r[1]), float(r[2])))
    return pts


def count_eclipse(positions_km: list[tuple[float, float, float]],
                  sim_t_s: float | None = None) -> int:
    """Count sats currently in the Earth's shadow. With a time, uses the real
    Sun + conical umbra/penumbra test (< half the solar disc visible); the
    legacy fixed-sun hemisphere test remains only for time-less callers."""
    if sim_t_s is not None:
        sun_km, _r_au = geodyn.sun_teme(timebase.jd_utc_at(sim_t_s))
        n = 0
        for pos in positions_km:
            if pos == (0.0, 0.0, 0.0):
                continue
            if geodyn.sun_visible_fraction(pos, sun_km) < 0.5:
                n += 1
        return n
    sx, sy, sz = SUN_DIR_ECI
    n = 0
    for x, y, z in positions_km:
        r = math.sqrt(x * x + y * y + z * z) or 1.0
        if (x * sx + y * sy + z * sz) / r < -0.05:
            n += 1
    return n


def synthesize_kpis(preset: ConstellationPreset, positions_km: list[tuple[float, float, float]],
                    sim_t_s: float | None = None) -> dict:
    """Roll the preset template + live propagated positions into a flat KPI dict."""
    T = preset.total_sats
    online = int(round(T * preset.online_rate))
    standby = int(round(T * preset.standby_rate))
    eclipse = max(0, min(count_eclipse(positions_km, sim_t_s), online))  # only online sats can be in eclipse
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
