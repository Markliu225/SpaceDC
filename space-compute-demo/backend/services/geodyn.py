"""Earth/Sun geometry primitives shared by the orbit, power and thermal
models — the STK-benchmark-grade replacements for the earlier scene-light
approximations (fixed inertial sun, spherical Earth, GMST(0)=0).

Everything here is closed-form and dependency-free (math only), cheap enough
to run per satellite per 1 Hz tick for a 1500-sat Walker fleet.

Conventions
-----------
* Positions in km, TEME frame (sgp4 native). We treat the analytic Sun's
  mean-of-date frame as TEME — the nutation difference is ≲0.005°, far under
  the 0.5° accuracy envelope of the low-precision Sun model itself.
* Time is a single float Julian date (UTC ≈ UT1 ≈ TT for our purposes: the
  ~70 s TT−UTC offset moves the Sun by ≲0.003°, and UT1−UTC ≲0.9 s moves
  GMST by ≲0.004°).
* Validated against STK 11.6 (see tools/stk_benchmark): subpoint ≤0.006°,
  Sun direction ≤0.2°, umbra timing ≤ tens of seconds, access edges ≤ a few
  seconds at the masks we use.
"""

from __future__ import annotations

import math

# WGS-84 ellipsoid
WGS84_A_KM = 6378.137
WGS84_F = 1.0 / 298.257223563
_WGS84_E2 = WGS84_F * (2.0 - WGS84_F)

R_SUN_KM = 695_700.0
AU_KM = 149_597_870.7
SOLAR_CONSTANT_W_M2 = 1361.0          # at 1 AU
EARTH_IR_W_M2 = 237.0                 # mean outgoing longwave radiation
EARTH_ALBEDO = 0.30
R_EARTH_THERMAL_KM = 6371.0           # mean radius for the thermal Earth disc


# ---------------------------------------------------------------------------
# Time / rotation
# ---------------------------------------------------------------------------

def gmst_rad(jd_ut1: float) -> float:
    """Greenwich mean sidereal time (IAU-82, Vallado eq. 3-45), radians."""
    t = (jd_ut1 - 2451545.0) / 36525.0
    deg = (280.46061837
           + 360.98564736629 * (jd_ut1 - 2451545.0)
           + 0.000387933 * t * t
           - t * t * t / 38710000.0)
    return math.radians(deg % 360.0)


def teme_to_ecef(x: float, y: float, z: float, jd_ut1: float
                 ) -> tuple[float, float, float]:
    """Rotate a TEME vector into the Earth-fixed frame by GMST (polar motion
    neglected: ~15 m — invisible at our accuracy gates)."""
    g = gmst_rad(jd_ut1)
    cg, sg = math.cos(g), math.sin(g)
    return (cg * x + sg * y, -sg * x + cg * y, z)


# ---------------------------------------------------------------------------
# WGS-84 geodetic conversions
# ---------------------------------------------------------------------------

def ecef_to_geodetic(x_km: float, y_km: float, z_km: float
                     ) -> tuple[float, float, float]:
    """ECEF km → geodetic (lat°, lon°, alt km) by fixed-point iteration."""
    lon = math.atan2(y_km, x_km)
    p = math.hypot(x_km, y_km)
    if p < 1e-9:
        lat = math.copysign(math.pi / 2.0, z_km)
        alt = abs(z_km) - WGS84_A_KM * (1.0 - WGS84_F)
        return math.degrees(lat), math.degrees(lon), alt
    lat = math.atan2(z_km, p * (1.0 - _WGS84_E2))
    alt = 0.0
    for _ in range(6):
        s = math.sin(lat)
        n = WGS84_A_KM / math.sqrt(1.0 - _WGS84_E2 * s * s)
        alt = p / math.cos(lat) - n
        new_lat = math.atan2(z_km, p * (1.0 - _WGS84_E2 * n / (n + alt)))
        if abs(new_lat - lat) < 1e-12:
            lat = new_lat
            break
        lat = new_lat
    s = math.sin(lat)
    n = WGS84_A_KM / math.sqrt(1.0 - _WGS84_E2 * s * s)
    alt = p / math.cos(lat) - n
    return math.degrees(lat), math.degrees(lon), alt


def geodetic_to_ecef(lat_deg: float, lon_deg: float, alt_km: float
                     ) -> tuple[float, float, float]:
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    s, c = math.sin(lat), math.cos(lat)
    n = WGS84_A_KM / math.sqrt(1.0 - _WGS84_E2 * s * s)
    return ((n + alt_km) * c * math.cos(lon),
            (n + alt_km) * c * math.sin(lon),
            (n * (1.0 - _WGS84_E2) + alt_km) * s)


# ---------------------------------------------------------------------------
# Sun
# ---------------------------------------------------------------------------

def sun_teme(jd: float) -> tuple[tuple[float, float, float], float]:
    """Low-precision analytic Sun (Vallado 'SUN' algorithm, mean elements).

    Returns (geocentric vector km in TEME≈mean-of-date, distance in AU).
    Direction accurate to ~0.01–0.05° across decades around J2000.
    """
    t = (jd - 2451545.0) / 36525.0
    mean_lon = math.radians((280.460 + 36000.771 * t) % 360.0)
    mean_anom = math.radians((357.5291092 + 35999.05034 * t) % 360.0)
    ecl_lon = (mean_lon
               + math.radians(1.914666471) * math.sin(mean_anom)
               + math.radians(0.019994643) * math.sin(2.0 * mean_anom))
    r_au = (1.000140612
            - 0.016708617 * math.cos(mean_anom)
            - 0.000139589 * math.cos(2.0 * mean_anom))
    obliq = math.radians(23.439291 - 0.0130042 * t)
    r_km = r_au * AU_KM
    return ((r_km * math.cos(ecl_lon),
             r_km * math.cos(obliq) * math.sin(ecl_lon),
             r_km * math.sin(obliq) * math.sin(ecl_lon)), r_au)


def sun_unit_and_flux(jd: float
                      ) -> tuple[tuple[float, float, float], float]:
    """Unit Sun direction (TEME) + solar irradiance W/m² at the true Earth-Sun
    distance (inverse-square of the 1 AU constant)."""
    (sx, sy, sz), r_au = sun_teme(jd)
    n = math.sqrt(sx * sx + sy * sy + sz * sz) or 1.0
    return (sx / n, sy / n, sz / n), SOLAR_CONSTANT_W_M2 / (r_au * r_au)


# ---------------------------------------------------------------------------
# Eclipse (conical umbra/penumbra, apparent-disc overlap)
# ---------------------------------------------------------------------------

def _circle_overlap(r1: float, r2: float, d: float) -> float:
    if d <= 0.0:
        rm = min(r1, r2)
        return math.pi * rm * rm
    a1 = max(-1.0, min(1.0, (d * d + r1 * r1 - r2 * r2) / (2.0 * d * r1)))
    a2 = max(-1.0, min(1.0, (d * d + r2 * r2 - r1 * r1) / (2.0 * d * r2)))
    rad = max(0.0, (-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2)
              * (d + r1 + r2))
    return (r1 * r1 * math.acos(a1) + r2 * r2 * math.acos(a2)
            - 0.5 * math.sqrt(rad))


def sun_visible_fraction(sat_km: tuple[float, float, float],
                         sun_km: tuple[float, float, float]) -> float:
    """Visible fraction of the solar disc behind the Earth: 1 in full sun,
    0 in umbra, smooth 0..1 through the penumbra (same construction as the
    NTU reference model and STK's dual-cone shadow)."""
    sx = sun_km[0] - sat_km[0]
    sy = sun_km[1] - sat_km[1]
    sz = sun_km[2] - sat_km[2]
    ex, ey, ez = -sat_km[0], -sat_km[1], -sat_km[2]
    ds = math.sqrt(sx * sx + sy * sy + sz * sz)
    de = math.sqrt(ex * ex + ey * ey + ez * ez)
    if de <= WGS84_A_KM:
        return 0.0
    ang_sun = math.asin(min(1.0, R_SUN_KM / ds))
    ang_earth = math.asin(min(1.0, WGS84_A_KM / de))
    cos_sep = (sx * ex + sy * ey + sz * ez) / (ds * de)
    sep = math.acos(max(-1.0, min(1.0, cos_sep)))
    if sep >= ang_sun + ang_earth:
        return 1.0
    if ang_earth >= sep + ang_sun:
        return 0.0
    if ang_sun >= sep + ang_earth:
        return 1.0 - (ang_earth / ang_sun) ** 2
    overlap = _circle_overlap(ang_sun, ang_earth, sep)
    return max(0.0, min(1.0, 1.0 - overlap / (math.pi * ang_sun * ang_sun)))


# ---------------------------------------------------------------------------
# Ground-station geometry (WGS-84, ENU)
# ---------------------------------------------------------------------------

def elevation_from_ecef(sat_ecef_km: tuple[float, float, float],
                        gs_lat_deg: float, gs_lon_deg: float,
                        gs_alt_km: float = 0.0) -> float:
    """Geodetic elevation angle (deg) of a satellite seen from a site."""
    site = geodetic_to_ecef(gs_lat_deg, gs_lon_deg, gs_alt_km)
    dx = sat_ecef_km[0] - site[0]
    dy = sat_ecef_km[1] - site[1]
    dz = sat_ecef_km[2] - site[2]
    rng = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
    lat = math.radians(gs_lat_deg)
    lon = math.radians(gs_lon_deg)
    # geodetic up vector
    ux = math.cos(lat) * math.cos(lon)
    uy = math.cos(lat) * math.sin(lon)
    uz = math.sin(lat)
    return math.degrees(math.asin((dx * ux + dy * uy + dz * uz) / rng))


# ---------------------------------------------------------------------------
# Thermal environment
# ---------------------------------------------------------------------------

def earth_view_factor(r_km: float) -> float:
    """View factor from a small convex body at geocentric distance r to the
    Earth disc: F = (1 − √(1 − (R/r)²)) / 2. Multiplied by the TOTAL surface
    area it gives the effective Earth-IR collecting area (matches STK SEET's
    isothermal sphere to <0.2 K in the benchmark)."""
    rho = R_EARTH_THERMAL_KM / max(r_km, R_EARTH_THERMAL_KM)
    return 0.5 * (1.0 - math.sqrt(max(0.0, 1.0 - rho * rho)))
