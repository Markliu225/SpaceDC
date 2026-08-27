"""Mission time — the single source of truth for "what absolute instant is
sim second t?".

Before this module `TIME_SCALE` and the demo epoch were duplicated in
`services/constellations.py` and `services/orbit_catalog.py`, and every
propagation call site open-coded
`Satrec.sgp4(DEMO_JD0, DEMO_FR0 + t * TIME_SCALE / 86400)`. Both modules now
re-export the constants from here (`tools/stk_benchmark` and
`tools/validate_elements.py` import them by their old names) and every call
site goes through `jd_at` / `jd_after` / `jd_utc_at`.

The mission window has three parts:

  epoch_utc  the instant the design's reference TLE is anchored at
             (TLE line 1 cols 19-32, see `tle_epoch_field`)
  start_utc  the absolute instant sim second 0 maps to
  end_utc    the end of the analysis window (start + 24 h by default)

Sim time is *scaled*: one sim second advances the mission by `TIME_SCALE`
real seconds, so a 60x scale flies a ~93 min LEO orbit in ~93 s of wall
clock. Absolute UTC of sim second t is therefore
`start_utc + t * TIME_SCALE` seconds.

DEFAULT-MISSION INVARIANT (load-bearing — the STK 11.6 benchmark suite in
`tools/stk_benchmark` validates the physics against truth data at this
epoch): with the default window, `jd_at(t)` returns *exactly*
`(DEMO_JD0, DEMO_FR0 + t * TIME_SCALE / 86400.0)` and `jd_utc_at(t)` returns
*exactly* `DEMO_JD0 + DEMO_FR0 + t * TIME_SCALE / 86400.0` — same operations
in the same order, so propagation stays bit-for-bit identical to the
pre-refactor code.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sgp4.api import jday

# ---------------------------------------------------------------------------
# Constants (re-exported by constellations / orbit_catalog under their
# historical names — do not rename, external tools import them).
# ---------------------------------------------------------------------------
TIME_SCALE = 60.0                       # sim seconds -> real seconds

DEMO_EPOCH_YEAR = 2024
DEMO_EPOCH_MONTH = 8
DEMO_EPOCH_DAY = 22
DEMO_EPOCH_HOUR = 12

DEMO_EPOCH_UTC = datetime(DEMO_EPOCH_YEAR, DEMO_EPOCH_MONTH, DEMO_EPOCH_DAY,
                          DEMO_EPOCH_HOUR, 0, 0, tzinfo=timezone.utc)

# Julian date of the DEFAULT mission start, split the way SGP4 wants it.
DEMO_JD0, DEMO_FR0 = jday(DEMO_EPOCH_YEAR, DEMO_EPOCH_MONTH, DEMO_EPOCH_DAY,
                          DEMO_EPOCH_HOUR, 0, 0)

DEFAULT_WINDOW_S = 86400.0              # 24 h
MAX_WINDOW_S = 30.0 * 86400.0           # 30 days — the analysis cap


# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MissionWindow:
    """Epoch + analysis window. Immutable; `set_mission` swaps the whole
    object so nothing can observe a half-updated window."""
    epoch_utc: datetime
    start_utc: datetime
    end_utc: datetime

    @property
    def window_s(self) -> float:
        """Analysis window length in REAL seconds (end - start).

        ADVISORY, not a fence: nothing stops the sim clock at `end_utc`. The
        window sizes the analysis products (coverage/solar sampling, the
        designer's readout) and is validated (end > start, <= 30 days), but a
        demo left running past it keeps propagating — deliberately, because a
        clock that freezes mid-presentation is worse than one that runs on.
        See the /orbit_design docstrings, which say the same thing to API
        consumers."""
        return (self.end_utc - self.start_utc).total_seconds()

    @property
    def window_sim_s(self) -> float:
        """The same window expressed in SIM seconds (window / TIME_SCALE)."""
        return self.window_s / TIME_SCALE

    def to_dict(self) -> dict:
        return {
            "epoch_utc": iso_z(self.epoch_utc),
            "start_utc": iso_z(self.start_utc),
            "end_utc": iso_z(self.end_utc),
            "window_s": self.window_s,
            "time_scale": TIME_SCALE,
        }


_DEFAULT_MISSION = MissionWindow(
    epoch_utc=DEMO_EPOCH_UTC,
    start_utc=DEMO_EPOCH_UTC,
    end_utc=DEMO_EPOCH_UTC + timedelta(seconds=DEFAULT_WINDOW_S),
)

_mission: MissionWindow = _DEFAULT_MISSION
# (jd, fr) of _mission.start_utc — recomputed only when the window changes.
_start_jd: tuple[float, float] = (DEMO_JD0, DEMO_FR0)
# Bumped on every window change so caches keyed on mission time (e.g.
# ConstellationPreset._ring_eci_km) can detect staleness cheaply.
_revision: int = 0


# ---------------------------------------------------------------------------
# UTC helpers
# ---------------------------------------------------------------------------
def as_utc(dt: datetime) -> datetime:
    """Coerce to a timezone-aware UTC datetime (naive input is read as UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_utc(value: str | datetime) -> datetime:
    """Parse an ISO-8601 instant into aware UTC. Accepts the trailing 'Z'
    form the web sends and bare `YYYY-MM-DDTHH:MM` (read as UTC).
    Raises ValueError on anything unparseable."""
    if isinstance(value, datetime):
        return as_utc(value)
    s = str(value).strip()
    if not s:
        raise ValueError("empty datetime")
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    return as_utc(datetime.fromisoformat(s))


def iso_z(dt: datetime) -> str:
    """Render as `YYYY-MM-DDTHH:MM:SSZ` (what the API contract publishes)."""
    return as_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def tle_epoch_field(dt: datetime) -> str:
    """`YYDDD.DDDDDDDD` for TLE line 1 columns 19-32 (14 chars).

    YY = two-digit year, DDD = day of year (1-based, zero padded), then the
    fraction of that day. The demo epoch renders as `24235.50000000`, which
    is exactly the epoch already baked into the designer's reference line 1 —
    so patching a default-epoch design is a no-op."""
    d = as_utc(dt)
    frac = (d.hour * 3600.0 + d.minute * 60.0 + d.second
            + d.microsecond * 1e-6) / 86400.0
    return f"{d.year % 100:02d}{d.timetuple().tm_yday + frac:012.8f}"


# ---------------------------------------------------------------------------
# Mission window
# ---------------------------------------------------------------------------
def mission() -> MissionWindow:
    """The mission window currently in force."""
    return _mission


def revision() -> int:
    """Monotonic counter bumped on every mission-window change."""
    return _revision


def set_mission(epoch_utc: str | datetime | None = None,
                start_utc: str | datetime | None = None,
                end_utc: str | datetime | None = None) -> MissionWindow:
    """Install a mission window. `None` means "the default" (NOT "keep the
    current value"), so a request that omits the time keys always lands back
    on the demo mission and behaves exactly like the pre-mission-window code.

    Raises ValueError if a value is unparseable, if end <= start, or if the
    window exceeds MAX_WINDOW_S."""
    global _mission, _start_jd, _revision
    epoch = DEMO_EPOCH_UTC if epoch_utc is None else parse_utc(epoch_utc)
    start = DEMO_EPOCH_UTC if start_utc is None else parse_utc(start_utc)
    if end_utc is None:
        end = start + timedelta(seconds=DEFAULT_WINDOW_S)
    else:
        end = parse_utc(end_utc)
    span = (end - start).total_seconds()
    if span <= 0.0:
        raise ValueError("end_utc must be after start_utc")
    if span > MAX_WINDOW_S:
        raise ValueError("mission window must be 30 days or shorter")
    _mission = MissionWindow(epoch_utc=epoch, start_utc=start, end_utc=end)
    _start_jd = _jd_of(start)
    _revision += 1
    return _mission


def reset_mission() -> MissionWindow:
    """Back to the demo mission (used by tests / engine reset)."""
    global _mission, _start_jd, _revision
    _mission = _DEFAULT_MISSION
    _start_jd = (DEMO_JD0, DEMO_FR0)
    _revision += 1
    return _mission


def _jd_of(dt: datetime) -> tuple[float, float]:
    """(jd, fr) of an absolute UTC instant, via the same `jday` the module
    constants use — with the demo epoch this returns (DEMO_JD0, DEMO_FR0)
    identically, which is what keeps the default mission bit-for-bit."""
    d = as_utc(dt)
    return jday(d.year, d.month, d.day, d.hour, d.minute,
                d.second + d.microsecond * 1e-6)


# ---------------------------------------------------------------------------
# Sim time -> Julian date
# ---------------------------------------------------------------------------
def jd_after(real_offset_s: float) -> tuple[float, float]:
    """(jd, fr) at mission start + `real_offset_s` REAL seconds — no sim
    scaling. Callers that already work in real seconds (orbit-ring sampling
    over one orbital period) use this."""
    jd0, fr0 = _start_jd
    return jd0, fr0 + real_offset_s / 86400.0


def jd_at(sim_t_s: float) -> tuple[float, float]:
    """(jd, fr) of the absolute UTC instant that sim second `sim_t_s` maps
    to, i.e. mission start + `sim_t_s * TIME_SCALE` real seconds. This is the
    pair SGP4 wants (`Satrec.sgp4(jd, fr)`)."""
    return jd_after(sim_t_s * TIME_SCALE)


def jd_utc_at(sim_t_s: float) -> float:
    """The same instant as a SINGLE summed Julian date — what the analytic
    Sun / GMST helpers in `services.geodyn` take. Kept separate from `jd_at`
    because summing (jd0 + fr0) before adding the offset is what the
    pre-refactor call sites did, and float addition is not associative."""
    jd0, fr0 = _start_jd
    return jd0 + fr0 + (sim_t_s * TIME_SCALE) / 86400.0


def jd_utc_after(real_offset_s: float) -> float:
    """Single summed Julian date at mission start + `real_offset_s` REAL
    seconds. Same operand order as `jd_utc_at`, so the two agree bit-for-bit
    when `real_offset_s == sim_t_s * TIME_SCALE`; the STK benchmark exporter
    drives its timeline in real seconds and uses this."""
    jd0, fr0 = _start_jd
    return jd0 + fr0 + real_offset_s / 86400.0


def jd_at_epoch() -> tuple[float, float]:
    """(jd, fr) of the mission EPOCH — the instant the design's reference TLE
    is anchored at. NOT the same as sim second 0 unless epoch == start."""
    return _jd_of(_mission.epoch_utc)


def jd_utc_at_epoch() -> float:
    """The mission EPOCH as a single summed Julian date — what the analytic
    Sun helper wants. This is the instant the dawn-dusk RAAN is solved at:
    the TLE's RAAN is an epoch quantity, so the Sun direction it is measured
    against has to be read at the epoch too, not at "now"."""
    jd, fr = _jd_of(_mission.epoch_utc)
    return jd + fr


def utc_at(sim_t_s: float) -> datetime:
    """Absolute UTC datetime of sim second `sim_t_s`."""
    return _mission.start_utc + timedelta(seconds=sim_t_s * TIME_SCALE)
