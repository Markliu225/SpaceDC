"""
============================================================
  constellation.py - Multi-satellite TLE/OMM-style orbit helpers
============================================================

  Provides a lightweight constellation layer that can ingest multiple
  TLE records and propagate each satellite either with the optional
  ``sgp4`` package or with a compact Keplerian fallback.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    from sgp4.api import Satrec, jday
    HAS_SGP4 = True
except ImportError:
    HAS_SGP4 = False


MU_EARTH_KM3_S2 = 398600.4418
EARTH_RADIUS_KM = 6371.0
DEFAULT_DAWN_DUSK_RAAN_DEG = 152.0


@dataclass
class TleSatellite:
    name: str
    line1: str
    line2: str
    catalog_number: str
    international_designator: str
    epoch_utc: datetime
    inclination_deg: float
    raan_deg: float
    eccentricity: float
    arg_perigee_deg: float
    mean_anomaly_deg: float
    mean_motion_rev_per_day: float
    satrec: object = field(default=None, repr=False)

    @property
    def safe_id(self) -> str:
        return f"Sat_{self.catalog_number or self.name.replace(' ', '_')}"

    @property
    def label(self) -> str:
        if self.catalog_number:
            return f"{self.name} ({self.catalog_number})"
        return self.name

    @property
    def period_seconds(self) -> float:
        if self.mean_motion_rev_per_day <= 0.0:
            return 0.0
        return 86400.0 / self.mean_motion_rev_per_day

    @property
    def semi_major_axis_km(self) -> float:
        mean_motion_rad_s = self.mean_motion_rev_per_day * 2.0 * math.pi / 86400.0
        if mean_motion_rad_s <= 0.0:
            return EARTH_RADIUS_KM
        return (MU_EARTH_KM3_S2 / (mean_motion_rad_s ** 2.0)) ** (1.0 / 3.0)

    @property
    def mean_altitude_km(self) -> float:
        return max(0.0, self.semi_major_axis_km - EARTH_RADIUS_KM)


@dataclass
class ConstellationData:
    source_path: str
    satellites: list[TleSatellite]
    loaded_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    by_catalog_number: dict[str, TleSatellite] = field(init=False, default_factory=dict)

    def __post_init__(self):
        self.by_catalog_number = {
            sat.catalog_number: sat for sat in self.satellites if sat.catalog_number
        }

    def get(self, sat_id: str) -> Optional[TleSatellite]:
        return self.by_catalog_number.get(str(sat_id))


def _parse_tle_epoch(line1: str) -> datetime:
    year_2 = int(line1[18:20])
    day_of_year = float(line1[20:32])
    full_year = 1900 + year_2 if year_2 >= 57 else 2000 + year_2
    year_start = datetime(full_year, 1, 1, tzinfo=timezone.utc)
    return year_start + timedelta(days=day_of_year - 1.0)


def _make_satrec(line1: str, line2: str):
    if not HAS_SGP4:
        return None
    try:
        return Satrec.twoline2rv(line1, line2)
    except Exception:
        return None


def _parse_tle_triplets(lines: list[str]) -> list[tuple[str, str, str]]:
    triplets: list[tuple[str, str, str]] = []
    i = 0
    while i < len(lines):
        current = lines[i].strip()
        if not current:
            i += 1
            continue

        if current.startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
            name = f"SAT-{current[2:7].strip()}"
            triplets.append((name, current, lines[i + 1].strip()))
            i += 2
            continue

        if i + 2 < len(lines) and lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            name = current[2:].strip() if current.startswith("0 ") else current
            triplets.append((name, lines[i + 1].strip(), lines[i + 2].strip()))
            i += 3
            continue

        i += 1
    return triplets


def parse_tle_text(text: str) -> list[TleSatellite]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    satellites: list[TleSatellite] = []

    for name, line1, line2 in _parse_tle_triplets(lines):
        try:
            catalog_number = line1[2:7].strip()
            intl_des = line1[9:17].strip()
            inclination_deg = float(line2[8:16])
            raan_deg = float(line2[17:25])
            eccentricity = float(f"0.{line2[26:33].strip()}")
            arg_perigee_deg = float(line2[34:42])
            mean_anomaly_deg = float(line2[43:51])
            mean_motion_rev_per_day = float(line2[52:63])
            epoch_utc = _parse_tle_epoch(line1)
        except Exception:
            continue

        satellites.append(
            TleSatellite(
                name=name,
                line1=line1,
                line2=line2,
                catalog_number=catalog_number,
                international_designator=intl_des,
                epoch_utc=epoch_utc,
                inclination_deg=inclination_deg,
                raan_deg=raan_deg,
                eccentricity=eccentricity,
                arg_perigee_deg=arg_perigee_deg,
                mean_anomaly_deg=mean_anomaly_deg,
                mean_motion_rev_per_day=mean_motion_rev_per_day,
                satrec=_make_satrec(line1, line2),
            )
        )

    return satellites


def load_tle_file(path: str) -> ConstellationData:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    satellites = parse_tle_text(text)
    return ConstellationData(source_path=path, satellites=satellites)


def build_dawn_dusk_constellation(
    count: int = 6,
    altitude_km: float = 550.0,
    inclination_deg: float = 97.6,
    raan_deg: float = DEFAULT_DAWN_DUSK_RAAN_DEG,
    epoch_utc: Optional[datetime] = None,
    name_prefix: str = "SDC",
) -> ConstellationData:
    """
    Build a synthetic dawn-dusk sun-synchronous-style formation for demo use.

    All satellites share one orbital plane and are evenly phased so they keep
    a visually synchronized ring around Earth.
    """
    epoch = epoch_utc or datetime.now(timezone.utc)
    semi_major_axis = EARTH_RADIUS_KM + altitude_km
    mean_motion_rad_s = math.sqrt(MU_EARTH_KM3_S2 / (semi_major_axis ** 3.0))
    mean_motion_rev_per_day = mean_motion_rad_s * 86400.0 / (2.0 * math.pi)

    satellites: list[TleSatellite] = []
    total = max(1, count)
    for index in range(total):
        phase_deg = (360.0 * index / total) % 360.0
        catalog_number = f"97{index + 1:03d}"
        satellites.append(
            TleSatellite(
                name=f"{name_prefix}-{index + 1:02d}",
                line1="",
                line2="",
                catalog_number=catalog_number,
                international_designator=f"SDC{index + 1:02d}",
                epoch_utc=epoch,
                inclination_deg=inclination_deg,
                raan_deg=raan_deg,
                eccentricity=0.0,
                arg_perigee_deg=0.0,
                mean_anomaly_deg=phase_deg,
                mean_motion_rev_per_day=mean_motion_rev_per_day,
                satrec=None,
            )
        )

    return ConstellationData(
        source_path="builtin:dawn_dusk_sdc",
        satellites=satellites,
    )


def _solve_kepler(mean_anomaly_rad: float, eccentricity: float, iterations: int = 10) -> float:
    e_anomaly = mean_anomaly_rad
    for _ in range(iterations):
        f = e_anomaly - eccentricity * math.sin(e_anomaly) - mean_anomaly_rad
        f_prime = 1.0 - eccentricity * math.cos(e_anomaly)
        if abs(f_prime) < 1e-8:
            break
        e_anomaly -= f / f_prime
    return e_anomaly


def _propagate_kepler_km(sat: TleSatellite, when_utc: datetime) -> tuple[float, float, float]:
    delta_t = (when_utc - sat.epoch_utc).total_seconds()
    mean_motion_rad_s = sat.mean_motion_rev_per_day * 2.0 * math.pi / 86400.0
    semi_major_axis = sat.semi_major_axis_km

    mean_anomaly = math.radians(sat.mean_anomaly_deg) + mean_motion_rad_s * delta_t
    mean_anomaly = math.fmod(mean_anomaly, 2.0 * math.pi)
    if mean_anomaly < 0.0:
        mean_anomaly += 2.0 * math.pi

    ecc = max(0.0, min(0.99, sat.eccentricity))
    e_anomaly = _solve_kepler(mean_anomaly, ecc)

    cos_e = math.cos(e_anomaly)
    sin_e = math.sin(e_anomaly)
    radius = semi_major_axis * (1.0 - ecc * cos_e)

    sqrt_1me2 = math.sqrt(max(1.0 - ecc * ecc, 1e-8))
    x_orb = semi_major_axis * (cos_e - ecc)
    y_orb = semi_major_axis * sqrt_1me2 * sin_e

    raan = math.radians(sat.raan_deg)
    inc = math.radians(sat.inclination_deg)
    argp = math.radians(sat.arg_perigee_deg)

    cos_o = math.cos(raan)
    sin_o = math.sin(raan)
    cos_i = math.cos(inc)
    sin_i = math.sin(inc)
    cos_w = math.cos(argp)
    sin_w = math.sin(argp)

    x = (cos_o * cos_w - sin_o * sin_w * cos_i) * x_orb + (-cos_o * sin_w - sin_o * cos_w * cos_i) * y_orb
    y = (sin_o * cos_w + cos_o * sin_w * cos_i) * x_orb + (-sin_o * sin_w + cos_o * cos_w * cos_i) * y_orb
    z = (sin_w * sin_i) * x_orb + (cos_w * sin_i) * y_orb

    scale = radius / max(math.sqrt(x * x + y * y + z * z), 1e-8)
    return (x * scale, y * scale, z * scale)


def propagate_tle_km(sat: TleSatellite, when_utc: datetime) -> tuple[float, float, float]:
    if sat.satrec is not None and HAS_SGP4:
        try:
            jd, fr = jday(
                when_utc.year,
                when_utc.month,
                when_utc.day,
                when_utc.hour,
                when_utc.minute,
                when_utc.second + when_utc.microsecond / 1_000_000.0,
            )
            error, position, _velocity = sat.satrec.sgp4(jd, fr)
            if error == 0:
                return tuple(float(v) for v in position)
        except Exception:
            pass
    return _propagate_kepler_km(sat, when_utc)


def scene_position_for_satellite(
    sat: TleSatellite,
    when_utc: datetime,
    earth_radius_scene_units: float,
) -> tuple[float, float, float]:
    x_km, y_km, z_km = propagate_tle_km(sat, when_utc)
    scale = earth_radius_scene_units / EARTH_RADIUS_KM
    # Convert from classical orbital coordinates (Z=north) into the scene's
    # coordinate frame where Y is north and XZ is the equatorial plane.
    return (x_km * scale, z_km * scale, y_km * scale)


def sample_orbit_scene_points(
    sat: TleSatellite,
    earth_radius_scene_units: float,
    samples: int = 181,
) -> list[tuple[float, float, float]]:
    period = max(sat.period_seconds, 1.0)
    start_time = sat.epoch_utc
    points: list[tuple[float, float, float]] = []

    for index in range(samples):
        weight = index / max(samples - 1, 1)
        when_utc = start_time + timedelta(seconds=period * weight)
        points.append(scene_position_for_satellite(sat, when_utc, earth_radius_scene_units))
    return points
