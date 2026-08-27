"""Offline what-if comparison — the Twin page's Compare panel.

Runs the SAME StateEngine physics for 2–4 variant loadouts side by side,
each from the live satellite's current state (same orbit phase, same SOC,
same structure temperature), and returns per-tick time series so the web
can plot e.g. three radiator coatings' cooling curves against each other.

Design rules:
  * ZERO physics duplication — each variant is a full StateEngine whose
    `_update_placeholder_physics` tick is called verbatim.  The only
    override (`_OfflineTwin._tick_fleet`) swaps whole-fleet propagation
    for a single private-Satrec propagate of the tracked sat: bit-identical
    orbit (Walker member 0 IS the base TLE — zero RAAN/M offsets), no
    shared Satrec with the live engine (thread-safe under asyncio.to_thread),
    and cheap even when the live constellation is a big Walker shell.
  * No USD is touched — comparison is pure physics; the viewport keeps
    showing the live design.
  * Fairness: every variant starts from the same initial conditions and
    flies with its array fully deployed (steady-state design comparison,
    not a deployment transient — a stowed redwire blanket would just
    flatline its solar trace).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sgp4.api import Satrec

import design_presets
from services import timebase as _timebase
from models import (
    CompareLiveState,
    CompareLiveVariant,
    SatelliteConfig,
    TwinGeometry,
)
from state_engine import (
    StateEngine,
    _BATT_MAT_TABLE,
    _BATT_SIZE_TABLE,
    _GPU_TABLE,
    _RAD_MAT_TABLE,
    _SOLAR_MAT_TABLE,
    _WORKLOAD_PROFILES,
)
from services import constellations as _consts


class CompareError(ValueError):
    """Invalid compare request (unknown dimension / bad values)."""


@dataclass(frozen=True)
class LiveSnapshot:
    """Tick-coherent freeze of the live loadout + integration state.

    MUST be captured on the event-loop thread (live_snapshot below) BEFORE
    run_compare is dispatched to a worker thread: the 1 Hz tick runs on that
    same loop, so a synchronous read there can never interleave with a tick,
    and every variant seeds from the exact same instant — the fairness
    invariant (same orbit phase → eclipses at the same sample index; SOC/temp
    deltas attributable only to the compared knob) depends on this."""
    constellation_id: str
    config: SatelliteConfig
    geometry: TwinGeometry
    workload_profile: str
    platform_power_w: float
    gpu_count: int
    sim_time_s: float
    orbit_type: str
    battery_capacity_wh: float
    battery_soc: float
    temperature_c: float


def live_snapshot(live: StateEngine) -> LiveSnapshot:
    """Freeze the live engine's compare-relevant state. Synchronous — call
    from the event loop (an async route handler), never from a worker thread.
    Reaching into the engine's private fields is deliberate: this module is
    the engine's offline twin, not an external consumer."""
    return LiveSnapshot(
        constellation_id=live.constellation_id,
        config=live.satellite_config.model_copy(deep=True),
        geometry=live.twin_geometry.model_copy(deep=True),
        workload_profile=live.workload_profile,
        platform_power_w=live._platform_power_w,
        gpu_count=live._gpu_count,
        sim_time_s=live._sim_time_s,
        orbit_type=live._sat.orbit_type,
        battery_capacity_wh=live._sat.battery_capacity_wh,
        battery_soc=live._sat.battery_soc,
        temperature_c=live._sat.temperature_c,
    )


# ---------------------------------------------------------------------------
# Offline engine — the live tick with fleet propagation swapped for a
# private single-sat Satrec.
# ---------------------------------------------------------------------------
class _OfflineTwin(StateEngine):
    def __init__(self, snap: LiveSnapshot):
        super().__init__(on_state=lambda _p: None)
        # Seed from the frozen snapshot — every variant starts from the
        # identical instant regardless of live ticks during the worker's
        # compute (see LiveSnapshot).
        self._constellation_id = snap.constellation_id
        self._config = snap.config.model_copy(deep=True)
        self._twin_geometry = snap.geometry.model_copy(deep=True)
        self._workload_profile = snap.workload_profile
        self._platform_power_w = snap.platform_power_w
        self._gpu_count = snap.gpu_count
        self._sim_time_s = snap.sim_time_s
        self._sat.orbit_type = snap.orbit_type
        self._sat.battery_capacity_wh = snap.battery_capacity_wh
        self._sat.battery_soc = snap.battery_soc
        self._sat.temperature_c = snap.temperature_c
        # Private Satrec — identical orbit to the tracked sat (fleet member
        # 0 carries zero Walker offsets, so the base TLE IS its elements).
        preset = (_consts.get_preset(self._constellation_id)
                  or _consts.get_preset("single_iss"))
        self._satrec = Satrec.twoline2rv(preset.base_tle_line1,
                                         preset.base_tle_line2)

    def _tick_fleet(self, t: float) -> tuple[float, float, float]:
        jd, fr = _timebase.jd_at(t)
        e, r, v = self._satrec.sgp4(jd, fr)
        if e:
            self._tracked_vel_km_s = (0.0, 0.0, 0.0)
            return (0.0, 0.0, 0.0)
        # Mirror the base engine: capture velocity too so an offline twin flown
        # in a velocity/inertial attitude (if compare ever seeds one) projects
        # its panels correctly instead of reading the (0,0,0) init default.
        self._tracked_vel_km_s = (float(v[0]), float(v[1]), float(v[2]))
        return (float(r[0]), float(r[1]), float(r[2]))

    def settle_deployables(self) -> None:
        """Steady-state comparison: fly fully deployed regardless of what the
        applied variant (e.g. the stowed-on-apply redwire design) commanded."""
        self._solar_deploy_target = 1.0
        self._sat.solar_deploy_frac = 1.0


# ---------------------------------------------------------------------------
# Comparable dimensions — every Configurator-editable knob.
# `values` lists the choices offered by the UI; `apply` stamps one choice
# onto an offline engine.  Values are JSON scalars (str / int / float).
# ---------------------------------------------------------------------------
def _apply_config(key: str):
    def apply(eng: StateEngine, value: Any) -> None:
        eng.set_config({key: str(value)}, mark_custom=False)
    return apply


def _apply_geometry(key: str, cast=float):
    def apply(eng: StateEngine, value: Any) -> None:
        eng.set_twin_geometry({key: cast(value)}, mark_custom=False)
    return apply


def _apply_workload(eng: StateEngine, value: Any) -> None:
    eng.set_workload_profile(str(value), mark_custom=False)


def _apply_design(eng: StateEngine, value: Any) -> None:
    preset = design_presets.get_preset(str(value))
    if preset is None:
        raise CompareError(f"unknown design {value!r}")
    eng.apply_design(preset)


DIMENSIONS: dict[str, dict[str, Any]] = {
    "radiator_material": {
        "label": "Radiator coating",
        "group": "Thermal",
        "values": lambda: [
            {"id": k, "label": f"{k} · ε {v['emissivity']:.2f}"}
            for k, v in _RAD_MAT_TABLE.items()
        ],
        "current": lambda eng: eng.satellite_config.radiator_material,
        "apply": _apply_config("radiator_material"),
        "default_metric": "temperature_c",
    },
    "solar_material": {
        "label": "Solar cell material",
        "group": "Power",
        "values": lambda: [
            {"id": k, "label": f"{k} · η {v['efficiency']:.2f}"}
            for k, v in _SOLAR_MAT_TABLE.items()
        ],
        "current": lambda eng: eng.satellite_config.solar_material,
        "apply": _apply_config("solar_material"),
        "default_metric": "battery_soc",
    },
    "gpu": {
        "label": "GPU model",
        "group": "Compute",
        "values": lambda: [
            {"id": k, "label": f"{k} · {v['tdp_w']:.0f} W TDP"}
            for k, v in _GPU_TABLE.items()
        ],
        "current": lambda eng: eng.satellite_config.gpu,
        "apply": _apply_config("gpu"),
        "default_metric": "tokens_per_s",
    },
    "solar_clusters_per_side": {
        "label": "Solar wing span",
        "group": "Power",
        "values": lambda: [
            {"id": n, "label": f"{n} cluster{'s' if n > 1 else ''}/side"}
            for n in (1, 2, 3, 4, 6, 8)
        ],
        "current": lambda eng: eng.twin_geometry.solar_clusters_per_side,
        "apply": _apply_geometry("solar_clusters_per_side", int),
        "default_metric": "battery_soc",
    },
    "radiator_long": {
        "label": "Radiator size",
        "group": "Thermal",
        "values": lambda: [
            {"id": v, "label": f"{v:.1f} u long edge"}
            for v in (0.6, 1.0, 1.4, 2.0, 2.6)
        ],
        "current": lambda eng: eng.twin_geometry.radiator_long,
        "apply": _apply_geometry("radiator_long", float),
        "default_metric": "temperature_c",
    },
    "battery_material": {
        "label": "Battery chemistry",
        "group": "Power",
        "values": lambda: [
            {"id": k, "label": f"{k} · {v['density_wh_kg']:.0f} Wh/kg · η {v['efficiency']:.2f}"}
            for k, v in _BATT_MAT_TABLE.items()
        ],
        "current": lambda eng: eng.satellite_config.battery_material,
        "apply": _apply_config("battery_material"),
        "default_metric": "battery_soc",
    },
    "battery_size": {
        "label": "Battery pack size",
        "group": "Power",
        "values": lambda: [
            {"id": k, "label": f"{k} · {v['mass_kg']:.0f} kg"}
            for k, v in _BATT_SIZE_TABLE.items()
        ],
        "current": lambda eng: eng.satellite_config.battery_size,
        "apply": _apply_config("battery_size"),
        "default_metric": "battery_soc",
    },
    "workload_profile": {
        "label": "Workload profile",
        "group": "Compute",
        "values": lambda: [
            {"id": k, "label": v["label"]}
            for k, v in _WORKLOAD_PROFILES.items()
        ],
        "current": lambda eng: eng.workload_profile,
        "apply": _apply_workload,
        "default_metric": "payload_power_w",
    },
    "design": {
        "label": "Whole design",
        "group": "Design",
        "values": lambda: [
            {"id": s["id"], "label": s["name"]}
            for s in design_presets.list_summaries()
        ],
        "current": lambda eng: eng.design_id,
        "apply": _apply_design,
        "default_metric": "battery_soc",
    },
}


METRICS: list[dict[str, Any]] = [
    {"key": "temperature_c",   "label": "Structure Temp", "unit": "°C",    "digits": 1},
    {"key": "battery_soc",     "label": "Battery SOC",    "unit": "%",     "digits": 0, "factor": 100},
    {"key": "solar_input_w",   "label": "Solar Input",    "unit": "W",     "digits": 0},
    {"key": "payload_power_w", "label": "Payload Power",  "unit": "W",     "digits": 0},
    {"key": "radiator_power_w","label": "Radiator Emit",  "unit": "W",     "digits": 0},
    {"key": "battery_charge_w","label": "Net Power",      "unit": "W",     "digits": 0},
    {"key": "tokens_per_s",    "label": "LLM Throughput", "unit": "tok/s", "digits": 0},
    {"key": "gpu_die_temp_c",  "label": "GPU Die Temp",   "unit": "°C",    "digits": 1},
]


def _canon(v: Any) -> str:
    """Canonical string key for a choice id / request value. Numeric ids
    survive the JSON round-trip with changed types (Python 1.0 → JS 1 →
    Python int 1), so label lookups and dedupe must compare through one
    normal form: format(float, 'g') gives '1' for 1.0 and '0.6' for 0.6."""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return format(float(v), "g")
    return str(v)


def options(live: StateEngine) -> dict[str, Any]:
    """GET /compare/options payload — dimensions with their choices and the
    live loadout's current value, plus the metric catalog.

    When the live value is not one of the curated choices (custom
    radiator_long 1.9, a preset's 7000 Wh pack…) it is prepended as a
    first-class 'Current' choice so the panel can anchor 'current vs …'
    comparisons on it. Exception: the design dimension — a 'custom' loadout
    is not an applicable design preset, so it gets no synthetic choice (the
    panel simply starts with nothing picked)."""
    dims = []
    for dim_id, dim in DIMENSIONS.items():
        values = dim["values"]()
        current = dim["current"](live)
        if (dim_id != "design"
                and not any(_canon(o["id"]) == _canon(current) for o in values)):
            values = [{"id": current, "label": f"Current · {_canon(current)}"},
                      *values]
        dims.append({
            "id": dim_id,
            "label": dim["label"],
            "group": dim["group"],
            "values": values,
            "current": current,
            "default_metric": dim["default_metric"],
        })
    return {
        "dimensions": dims,
        "metrics": METRICS,
        "default_duration_s": 240,
    }


class LiveCompareSession:
    """Live what-if comparison — variants tick in LOCKSTEP with the engine.

    2-4 variant engines are seeded from one event-loop-consistent
    LiveSnapshot at start; StateEngine._run then calls step() once per
    1 Hz physics tick, so every variant advances exactly when the live
    satellite does (pausing the sim pauses the comparison too). The
    variants' CURRENT samples ride StatePacket.compare_live on every
    broadcast/poll; the web accumulates them into the telemetry strip's
    rolling window, so the curves grow and diverge in real time.

    Construction validates the request (raises CompareError -> 422).
    step() and payload() run on the event-loop thread only."""

    def __init__(self, snap: LiveSnapshot, dimension: str, values: list[Any]):
        dim = DIMENSIONS.get(str(dimension))
        if dim is None:
            raise CompareError(f"unknown compare dimension {dimension!r}")
        if not isinstance(values, list):
            raise CompareError("values must be a list")
        # Bound BEFORE the O(n^2) dedupe -- an unbounded client list would
        # burn event-loop CPU just to be rejected afterwards.
        if len(values) > 16:
            raise CompareError("pick between 2 and 4 distinct values to compare")
        # Dedupe preserving order through the canonical key (2 == "2" == 2.0).
        seen: list[Any] = []
        seen_keys: set[str] = set()
        for v in values:
            k = _canon(v)
            if k not in seen_keys:
                seen_keys.add(k)
                seen.append(v)
        if not 2 <= len(seen) <= 4:
            raise CompareError("pick between 2 and 4 distinct values to compare")

        self.dimension = str(dimension)
        self.dimension_label = str(dim["label"])
        self.start_sim_time_s = snap.sim_time_s
        self.elapsed_s = 0.0
        value_labels = {_canon(o["id"]): o["label"] for o in dim["values"]()}
        self._variants: list[tuple[Any, str, _OfflineTwin]] = []
        for value in seen:
            eng = _OfflineTwin(snap)
            try:
                dim["apply"](eng, value)
            except CompareError:
                raise
            except Exception as e:  # bad enum value etc. -> 422, not 500
                raise CompareError(f"cannot apply {dimension}={value!r}: {e}") from e
            eng.settle_deployables()
            eng._reset_workload_totals()
            self._variants.append(
                (value, value_labels.get(_canon(value), _canon(value)), eng))

    def step(self, dt: float = 1.0) -> None:
        """Advance every variant one physics step. Called by the engine tick
        right after the live physics update -- lockstep by construction."""
        self.elapsed_s += dt
        for _value, _label, eng in self._variants:
            eng._sim_time_s += dt
            eng._update_placeholder_physics(dt)

    def payload(self) -> CompareLiveState:
        """Wire model for StatePacket.compare_live -- each variant's CURRENT
        sample (the web appends these into its rolling strip window)."""
        variants: list[CompareLiveVariant] = []
        for value, label, eng in self._variants:
            sat = eng._sat
            det = sat.workload_detail
            variants.append(CompareLiveVariant(
                value=value,
                label=label,
                solar_input_w=round(sat.solar_input_w, 1),
                payload_power_w=round(sat.payload_power_w, 1),
                battery_soc=round(sat.battery_soc, 4),
                temperature_c=round(sat.temperature_c, 2),
                gpu_utilization=round(sat.gpu_utilization, 3),
                tokens_per_s=(round(det.throughput_total, 1)
                              if det is not None
                              and det.throughput_unit == "tok/s" else 0.0),
            ))
        return CompareLiveState(
            active=True,
            dimension=self.dimension,
            dimension_label=self.dimension_label,
            start_sim_time_s=self.start_sim_time_s,
            elapsed_s=self.elapsed_s,
            variants=variants,
        )
